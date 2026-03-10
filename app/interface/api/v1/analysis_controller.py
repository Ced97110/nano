"""Interface layer — FastAPI controller for analysis endpoints.

Thin adapter: validates HTTP input, delegates to use cases, formats HTTP output.
No business logic here.
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.interface.auth import AuthUser, Role, get_current_user, require_role

from app.application.dto.analysis_dto import AnalysisRequestDTO
from app.application.use_cases.run_analysis import RunAnalysisUseCase
from app.application.use_cases.stream_analysis import StreamAnalysisUseCase
from app.domain.interfaces.audit_store import AuditStore
from app.domain.interfaces.cache_repository import CacheRepository
from app.domain.interfaces.event_publisher import EventPublisher
from app.domain.interfaces.llm_gateway import LLMGateway
from app.interface.api.v1.schemas import (
    VALID_ANALYSIS_TYPES,
    AnalysisCreateSchema,
    AnalysisOutputSchema,
    HITLFeedbackSchema,
    SharingApprovalSchema,
    SharingStatusSchema,
)

router = APIRouter(prefix="/api/v1/analysis", tags=["analysis"])

VALID_PERSONA_SYSTEMS = {"finagent"}

# Injected by the composition root (main.py)
_run_use_case: RunAnalysisUseCase | None = None
_stream_use_case: StreamAnalysisUseCase | None = None
_events: EventPublisher | None = None
_llm: LLMGateway | None = None
_cache: CacheRepository | None = None
_audit_store: AuditStore | None = None

SHARING_TTL = 86400  # 24 hours


def configure(
    run_uc: RunAnalysisUseCase,
    stream_uc: StreamAnalysisUseCase,
    events: EventPublisher | None = None,
    llm: LLMGateway | None = None,
    cache: CacheRepository | None = None,
    audit_store: AuditStore | None = None,
) -> None:
    """Called once at startup to inject use cases."""
    global _run_use_case, _stream_use_case, _events, _llm, _cache, _audit_store
    _run_use_case = run_uc
    _stream_use_case = stream_uc
    _events = events
    _llm = llm
    _cache = cache
    _audit_store = audit_store


def _validate_system(system_id: str) -> None:
    if system_id not in VALID_PERSONA_SYSTEMS:
        raise HTTPException(400, f"Unknown system: {system_id}. Valid: {VALID_PERSONA_SYSTEMS}")


@router.post("/run", response_model=AnalysisOutputSchema)
async def run_analysis(
    body: AnalysisCreateSchema,
    user: Annotated[AuthUser, Depends(require_role(Role.analyst))],
):
    _validate_system(body.persona_system)
    if body.analysis_type not in VALID_ANALYSIS_TYPES:
        raise HTTPException(400, f"Invalid analysis_type: {body.analysis_type}. Valid: {VALID_ANALYSIS_TYPES}")
    dto = AnalysisRequestDTO(
        persona_system=body.persona_system,
        ticker=body.ticker,
        query=body.query,
        country=body.country,
        analysis_type=body.analysis_type,
    )
    result = await _run_use_case.execute(dto)
    return AnalysisOutputSchema(
        request_id=result.request_id,
        system_id=result.system_id,
        result=result.result,
        cached=result.cached,
    )


@router.post("/run/stream")
async def run_analysis_stream(
    body: AnalysisCreateSchema,
    user: Annotated[AuthUser, Depends(require_role(Role.analyst))],
):
    _validate_system(body.persona_system)
    if body.mode not in ("express", "analyst", "review"):
        raise HTTPException(400, f"Invalid mode: {body.mode}. Valid: express, analyst, review")
    if body.analysis_type not in VALID_ANALYSIS_TYPES:
        raise HTTPException(400, f"Invalid analysis_type: {body.analysis_type}. Valid: {VALID_ANALYSIS_TYPES}")
    dto = AnalysisRequestDTO(
        persona_system=body.persona_system,
        ticker=body.ticker,
        query=body.query,
        country=body.country,
        mode=body.mode,
        analysis_type=body.analysis_type,
    )
    request_id, stream = await _stream_use_case.execute(dto)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Request-ID": request_id,
        },
    )


@router.post("/{request_id}/feedback")
async def submit_hitl_feedback(
    request_id: str,
    body: HITLFeedbackSchema,
    user: Annotated[AuthUser, Depends(require_role(Role.analyst))],
):
    """Submit analyst feedback for a paused HITL wave.

    The pipeline barrier node is blocking on BLPOP — this endpoint
    delivers the feedback via RPUSH, unblocking the pipeline.
    """
    if not _events:
        raise HTTPException(500, "Event publisher not configured")

    hitl_channel = f"{request_id}:{body.wave}"
    await _events.send_input(hitl_channel, {
        "action": body.action,
        "overrides": body.overrides,
        "notes": body.notes,
    })
    return {"status": "accepted", "wave": body.wave, "action": body.action}


@router.get("/systems")
async def list_systems(
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    return {"systems": sorted(VALID_PERSONA_SYSTEMS)}


@router.get("/stats")
async def get_stats(
    user: Annotated[AuthUser, Depends(require_role(Role.admin))],
):
    """Return session-level LLM usage stats from the gateway."""
    if not _llm:
        return {"total_tokens": 0, "total_cost_usd": 0.0}
    return {
        "total_tokens": getattr(_llm, "total_tokens_used", 0),
        "total_cost_usd": round(getattr(_llm, "total_cost_usd", 0.0), 6),
    }


@router.get("/{workflow_id}/audit")
async def get_audit_trail(
    workflow_id: str,
    user: Annotated[AuthUser, Depends(require_role(Role.analyst))],
):
    """Return the full immutable audit trail for a workflow."""
    if not _audit_store:
        raise HTTPException(500, "Audit store not configured")

    trail = await _audit_store.get_trail(workflow_id)
    return {
        "workflow_id": workflow_id,
        "total_events": len(trail),
        "events": [
            {
                "event_type": e.event_type,
                "agent_id": e.agent_id,
                "payload": e.payload,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in trail
        ],
    }


@router.get("/{workflow_id}/compliance-report")
async def get_compliance_report(
    workflow_id: str,
    user: Annotated[AuthUser, Depends(require_role(Role.admin))],
):
    """Generate a compliance report for a workflow.

    Summarizes all agents executed, HITL decisions, overrides applied,
    data sources, total cost, total tokens, and full timeline.
    """
    if not _audit_store:
        raise HTTPException(500, "Audit store not configured")

    report = await _audit_store.generate_compliance_report(workflow_id)
    return report


@router.post("/{request_id}/approve-sharing", response_model=SharingStatusSchema)
async def approve_sharing(
    request_id: str,
    user: Annotated[AuthUser, Depends(require_role(Role.analyst))],
    body: SharingApprovalSchema | None = None,
):
    """Mark a completed analysis as approved for external sharing.

    PRD requirement: No externally-shareable output without explicit user
    approval after final Human Review Gate.  Stores approval in Redis
    with 24h TTL.
    """
    if not _cache:
        raise HTTPException(500, "Cache not configured — cannot store sharing approval")

    approved_by = body.approved_by if body else "analyst"
    now = datetime.now(timezone.utc).isoformat()
    approval = {"approved": True, "approved_at": now, "approved_by": approved_by}

    await _cache.set_pipeline(
        system_id="sharing_approved",
        entity=request_id,
        data=approval,
        ttl=SHARING_TTL,
    )

    return SharingStatusSchema(**approval)


@router.get("/{request_id}/sharing-status", response_model=SharingStatusSchema)
async def get_sharing_status(
    request_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Check whether an analysis has been approved for external sharing."""
    if not _cache:
        return SharingStatusSchema(approved=False)

    data = await _cache.get_pipeline(
        system_id="sharing_approved",
        entity=request_id,
    )

    if data and data.get("approved"):
        return SharingStatusSchema(**data)

    return SharingStatusSchema(approved=False)
