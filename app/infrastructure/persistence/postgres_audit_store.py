"""Infrastructure adapter — PostgreSQL immutable audit store.

Raw SQL via asyncpg. No ORM.

IMPORTANT: This table is INSERT-ONLY (append-only). No UPDATE or DELETE
operations are permitted. Data should be archived to cold storage after
12 months, with a minimum 7-year retention per compliance policy.
"""

import json

import asyncpg
import structlog

from app.domain.interfaces.audit_store import AuditEvent, AuditStore

logger = structlog.get_logger(__name__)


class PostgresAuditStore(AuditStore):
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def log_event(self, event: AuditEvent) -> None:
        """Append an immutable audit event. INSERT only — never UPDATE or DELETE."""
        try:
            await self._pool.execute(
                """INSERT INTO audit_trail (workflow_id, event_type, agent_id, payload)
                   VALUES ($1::uuid, $2, $3, $4::jsonb)""",
                event.workflow_id,
                event.event_type,
                event.agent_id,
                json.dumps(event.payload, default=str),
            )
        except Exception as exc:
            # Audit logging must never crash the pipeline
            logger.error(
                "audit_store.log_event.failed",
                workflow_id=event.workflow_id,
                event_type=event.event_type,
                error=str(exc),
            )

    async def get_trail(self, workflow_id: str) -> list[AuditEvent]:
        """Retrieve the full ordered audit trail for a workflow."""
        rows = await self._pool.fetch(
            """SELECT workflow_id, event_type, agent_id, payload, created_at
               FROM audit_trail
               WHERE workflow_id = $1::uuid
               ORDER BY created_at ASC, id ASC""",
            workflow_id,
        )
        return [
            AuditEvent(
                workflow_id=str(row["workflow_id"]),
                event_type=row["event_type"],
                agent_id=row["agent_id"],
                payload=json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    async def generate_compliance_report(self, workflow_id: str) -> dict:
        """Assemble a compliance report summarizing all events for a workflow.

        Returns: agents executed, HITL decisions, overrides applied,
        data sources, total cost, total tokens, timeline.
        """
        trail = await self.get_trail(workflow_id)
        if not trail:
            return {"workflow_id": workflow_id, "error": "No audit trail found"}

        agents_started: list[str] = []
        agents_completed: list[str] = []
        agents_errored: list[str] = []
        hitl_pauses: list[dict] = []
        hitl_feedback: list[dict] = []
        data_sources: set[str] = set()
        total_tokens = 0
        total_cost_usd = 0.0
        timeline: list[dict] = []

        run_started_at = None
        run_finished_at = None

        for event in trail:
            entry = {
                "event_type": event.event_type,
                "agent_id": event.agent_id,
                "timestamp": event.created_at.isoformat() if event.created_at else None,
            }
            timeline.append(entry)

            payload = event.payload or {}

            if event.event_type == "run_started":
                run_started_at = event.created_at

            elif event.event_type == "run_finished":
                run_finished_at = event.created_at

            elif event.event_type == "agent_started":
                if event.agent_id:
                    agents_started.append(event.agent_id)

            elif event.event_type == "agent_completed":
                if event.agent_id:
                    agents_completed.append(event.agent_id)
                total_tokens += payload.get("tokens_used", 0)
                total_cost_usd += payload.get("cost_usd", 0.0)
                for src in payload.get("data_sources", []):
                    data_sources.add(src)

            elif event.event_type == "agent_error":
                if event.agent_id:
                    agents_errored.append(event.agent_id)

            elif event.event_type == "hitl_pause":
                hitl_pauses.append({
                    "wave": payload.get("wave"),
                    "wave_label": payload.get("wave_label"),
                    "timestamp": event.created_at.isoformat() if event.created_at else None,
                })

            elif event.event_type == "hitl_feedback":
                hitl_feedback.append({
                    "wave": payload.get("wave"),
                    "action": payload.get("action"),
                    "overrides_count": payload.get("overrides_count", 0),
                    "timestamp": event.created_at.isoformat() if event.created_at else None,
                })

        duration_seconds = None
        if run_started_at and run_finished_at:
            duration_seconds = round((run_finished_at - run_started_at).total_seconds(), 2)

        return {
            "workflow_id": workflow_id,
            "generated_at": trail[-1].created_at.isoformat() if trail[-1].created_at else None,
            "total_events": len(trail),
            "duration_seconds": duration_seconds,
            "agents": {
                "started": agents_started,
                "completed": agents_completed,
                "errored": agents_errored,
                "total_started": len(agents_started),
                "total_completed": len(agents_completed),
                "total_errored": len(agents_errored),
            },
            "hitl": {
                "pauses": hitl_pauses,
                "feedback": hitl_feedback,
                "total_pauses": len(hitl_pauses),
                "total_overrides": sum(f.get("overrides_count", 0) for f in hitl_feedback),
            },
            "data_sources": sorted(data_sources),
            "cost": {
                "total_tokens": total_tokens,
                "total_cost_usd": round(total_cost_usd, 6),
            },
            "timeline": timeline,
            "retention_policy": "7-year minimum. Archive to cold storage after 12 months.",
        }
