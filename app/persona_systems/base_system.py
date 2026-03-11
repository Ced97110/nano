"""Base persona system — LangGraph-powered DAG execution engine.

Depends on domain interfaces only. Infrastructure is injected via constructor.
Barrier nodes now run audit layers 1-3 instead of being passthrough.
Supports Human-in-the-Loop (HITL) pause/resume at wave boundaries.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

import structlog
from langgraph.graph import END, START, StateGraph

from app.domain.interfaces.audit_store import AuditEvent, AuditStore
from app.domain.interfaces.cache_repository import CacheRepository
from app.domain.interfaces.event_publisher import EventPublisher
from app.domain.interfaces.llm_gateway import LLMGateway
from app.domain.interfaces.web_search import WebSearchGateway
from app.persona_systems.audit.cost_monitor import (
    BudgetExceededError,
    CostMonitor,
)
from app.persona_systems.audit.schemas import validate_schema
from app.persona_systems.audit.consistency import check_wave_consistency
from app.persona_systems.audit.llm_audit import audit_agent_output, CRITICAL_AGENTS
from app.persona_systems.base_agent import BaseAgent

logger = structlog.get_logger(__name__)


class WorkflowCancelledException(Exception):
    """Raised when an analyst cancels the workflow at a HITL gate."""


# Which waves pause for human review in each mode
HITL_GATES: dict[str, set[int]] = {
    "express": set(),        # No pauses — fully autonomous
    "analyst": {0, 2},       # Pause after data gathering & valuation
    "review": {0, 1, 2, 3}, # Pause after every wave (except final)
}

WAVE_LABELS = {
    0: "Data Gathering",
    1: "Analysis",
    2: "Valuation",
    3: "Risk & Quality",
    4: "Synthesis",
    5: "IC Decision",
    6: "Specialized",
    7: "Sensitivity",
}

HITL_TIMEOUT = 300  # 5 minutes — auto-continue if analyst doesn't respond


def _merge_dicts(left: dict, right: dict) -> dict:
    merged = left.copy()
    merged.update(right)
    return merged


class PipelineState(TypedDict):
    intent: dict
    request: dict
    cross_system_context: dict
    agent_outputs: Annotated[dict, _merge_dicts]
    request_id: str
    entity: str
    audit_log: Annotated[dict, _merge_dicts]
    cost_log: Annotated[dict, _merge_dicts]
    hitl_mode: str  # "express" | "analyst" | "review"
    cost_monitor: CostMonitor | None  # budget enforcement (not merged)


class BasePersonaSystem:
    """Abstract base for all persona systems.

    Receives infrastructure via constructor injection (Dependency Inversion).
    Subclasses override _build_agents(), get_agent_dependency_graph(), run_pipeline().
    """

    system_id: str = ""
    PIPELINE_CACHE_TTL: int = 3600

    def __init__(
        self,
        llm: LLMGateway,
        cache: CacheRepository,
        events: EventPublisher,
        data_repos: dict | None = None,
        audit_store: AuditStore | None = None,
        web_search: WebSearchGateway | None = None,
    ) -> None:
        self._llm = llm
        self._cache = cache
        self._events = events
        self._data = data_repos or {}
        self._audit_store = audit_store
        self._web_search = web_search
        self.agents = self._build_agents()
        self._graph_cache: dict[str, object] = {}  # analysis_type → CompiledGraph
        self._compiled_graph = None  # lazily compiled on first use

    # ── Override in subclass ──

    def _build_agents(self) -> dict[str, BaseAgent]:
        raise NotImplementedError

    def get_agent_dependency_graph(self) -> dict[str, list[str]]:
        raise NotImplementedError

    async def run_pipeline(
        self,
        request: dict,
        intent: dict,
        cross_system_context: dict | None = None,
    ) -> dict:
        raise NotImplementedError

    # ── LangGraph compilation ──

    def _compile_graph(self):
        builder = StateGraph(PipelineState)

        for agent_id, agent in self.agents.items():
            builder.add_node(agent_id, agent)

        waves = self._compute_waves()

        # Create validator nodes for each wave boundary (replaces _passthrough)
        for wave_idx in range(len(waves)):
            if wave_idx < len(waves) - 1:
                validator = self._make_validator(wave_idx, waves[wave_idx])
                builder.add_node(f"_barrier_{wave_idx}", validator)

        for wave_idx, wave_agents in enumerate(waves):
            if wave_idx == 0:
                for aid in wave_agents:
                    builder.add_edge(START, aid)
            else:
                prev_barrier = f"_barrier_{wave_idx - 1}"
                for aid in wave_agents:
                    builder.add_edge(prev_barrier, aid)

            if wave_idx < len(waves) - 1:
                barrier_name = f"_barrier_{wave_idx}"
                for aid in wave_agents:
                    builder.add_edge(aid, barrier_name)
            else:
                for aid in wave_agents:
                    builder.add_edge(aid, END)

        return builder.compile()

    def _make_validator(self, wave_idx: int, wave_agent_ids: list[str]):
        """Create a validator node for a wave boundary.

        Runs:
          Layer 1: Schema validation on each agent that just completed
          Layer 2: Cross-agent consistency checks
          Layer 3: LLM audit on critical-path agents (if any in this wave)
          HITL:    If mode requires it, pause and wait for analyst feedback
        """
        llm = self._llm
        events = self._events
        system_id = self.system_id
        audit_store = self._audit_store

        async def validator_node(state: dict) -> dict:
            outputs = state.get("agent_outputs", {})
            entity = state.get("entity", "")
            request_id = state.get("request_id", "")
            hitl_mode = state.get("hitl_mode", "express")

            all_violations = []
            audit_results = {}

            # ── Layer 1: Schema validation ──
            for agent_id in wave_agent_ids:
                agent_output = outputs.get(agent_id, {})
                violations = validate_schema(agent_id, agent_output)
                if violations:
                    all_violations.extend(violations)
                    logger.warning(
                        "audit.schema.violations",
                        agent_id=agent_id,
                        violations=violations,
                    )

            # ── Layer 2: Cross-agent consistency ──
            consistency_warnings = check_wave_consistency(wave_idx, outputs)
            if consistency_warnings:
                all_violations.extend(consistency_warnings)
                logger.warning(
                    "audit.consistency.warnings",
                    wave=wave_idx,
                    warnings=consistency_warnings,
                )

            # ── Layer 3: LLM audit on critical agents ──
            critical_in_wave = [
                aid for aid in wave_agent_ids if aid in CRITICAL_AGENTS
            ]
            for agent_id in critical_in_wave:
                agent_output = outputs.get(agent_id, {})
                if isinstance(agent_output, dict) and "error" not in agent_output:
                    audit = await audit_agent_output(llm, agent_id, entity, agent_output)
                    audit_results[agent_id] = audit
                    if not audit.get("passed", True):
                        logger.warning(
                            "audit.llm.failed_check",
                            agent_id=agent_id,
                            severity=audit.get("severity"),
                            issues=audit.get("issues", []),
                        )

            # Store audit results in state
            wave_key = f"wave_{wave_idx}"
            audit_entry = {
                wave_key: {
                    "schema_violations": all_violations,
                    "llm_audits": {
                        aid: {
                            "passed": a.get("passed"),
                            "severity": a.get("severity"),
                            "issues_count": len(a.get("issues", [])),
                            "confidence_adjustment": a.get("confidence_adjustment", 0.0),
                        }
                        for aid, a in audit_results.items()
                    },
                }
            }

            # Accumulate audit LLM costs
            audit_costs = {}
            for aid, a in audit_results.items():
                tokens = a.get("_tokens_used", 0)
                cost = a.get("_cost_usd", 0.0)
                if tokens or cost:
                    audit_costs[f"audit_{aid}"] = {
                        "tokens_used": tokens,
                        "cost_usd": round(cost, 6),
                        "type": "llm_audit",
                    }

            logger.info(
                "audit.wave.completed",
                system=system_id,
                wave=wave_idx,
                violations=len(all_violations),
                llm_audits=len(audit_results),
                audit_cost_usd=round(sum(c.get("cost_usd", 0) for c in audit_costs.values()), 6),
            )

            result = {"audit_log": audit_entry}
            if audit_costs:
                result["cost_log"] = audit_costs

            # ── Budget enforcement via CostMonitor ──
            monitor = state.get("cost_monitor")
            if monitor:
                cost_log = state.get("cost_log", {})
                # Ingest cost data from agents that just completed
                new_costs = {
                    aid: cost_log[aid]
                    for aid in wave_agent_ids
                    if aid in cost_log
                }
                if new_costs:
                    monitor.ingest_cost_log(new_costs)
                monitor.check_budget()  # raises BudgetExceededError if over limit

            # ── HITL: Pause for analyst review if this wave is gated ──
            # OVERRIDE PROPAGATION (PRD §FR-03): Overrides merge into
            # agent_outputs via the _merge_dicts Annotated reducer. All
            # downstream agents call get_prior() which reads from agent_outputs,
            # so overrides at Wave N are automatically visible to Waves N+1..end.
            # No re-execution of completed agents is needed because the DAG
            # executes sequentially by wave — overrides happen at barriers
            # BEFORE downstream waves run.
            hitl_gates = HITL_GATES.get(hitl_mode, set())
            if wave_idx in hitl_gates and request_id:
                # Extract key outputs from this wave for analyst review
                wave_outputs = {
                    aid: outputs.get(aid, {}) for aid in wave_agent_ids
                }

                # Publish WAVE_REVIEW event to SSE stream
                await events.publish(request_id, {
                    "type": "WAVE_REVIEW",
                    "runId": request_id,
                    "wave": wave_idx,
                    "wave_label": WAVE_LABELS.get(wave_idx, f"Wave {wave_idx}"),
                    "agent_outputs": wave_outputs,
                    "audit_findings": {
                        "schema_violations": all_violations,
                        "consistency_warnings": [
                            w for w in all_violations if w.startswith("CONSISTENCY:")
                        ],
                        "llm_audit_issues": [
                            {
                                "agent_id": aid,
                                "passed": a.get("passed"),
                                "severity": a.get("severity"),
                                "issues": a.get("issues", []),
                            }
                            for aid, a in audit_results.items()
                            if not a.get("passed", True)
                        ],
                    },
                    "total_agents_in_wave": len(wave_agent_ids),
                })

                logger.info(
                    "hitl.waiting_for_input",
                    system=system_id,
                    wave=wave_idx,
                    request_id=request_id,
                )

                # ── Audit: hitl_pause ──
                if audit_store and request_id:
                    try:
                        await audit_store.log_event(AuditEvent(
                            workflow_id=request_id,
                            event_type="hitl_pause",
                            payload={
                                "wave": wave_idx,
                                "wave_label": WAVE_LABELS.get(wave_idx, f"Wave {wave_idx}"),
                                "hitl_mode": hitl_mode,
                                "agents_in_wave": wave_agent_ids,
                                "violations_count": len(all_violations),
                            },
                        ))
                    except Exception:
                        pass

                # Block until analyst responds or timeout
                hitl_channel = f"{request_id}:{wave_idx}"
                feedback = await events.wait_for_input(hitl_channel, HITL_TIMEOUT)

                if feedback:
                    action = feedback.get("action", "approve")
                    overrides = feedback.get("overrides", {})
                    notes = feedback.get("notes", "")

                    logger.info(
                        "hitl.feedback_received",
                        system=system_id,
                        wave=wave_idx,
                        action=action,
                        overrides_count=len(overrides),
                    )

                    # ── Audit: hitl_feedback ──
                    if audit_store and request_id:
                        try:
                            await audit_store.log_event(AuditEvent(
                                workflow_id=request_id,
                                event_type="hitl_feedback",
                                payload={
                                    "wave": wave_idx,
                                    "action": action,
                                    "overrides_count": len(overrides),
                                    "has_notes": bool(notes),
                                },
                            ))
                        except Exception:
                            pass

                    # ── Handle cancel: abort the entire pipeline ──
                    if action == "cancel":
                        await events.publish(request_id, {
                            "type": "RUN_CANCELLED",
                            "runId": request_id,
                            "wave": wave_idx,
                            "reason": notes or "Analyst cancelled the workflow",
                        })
                        raise WorkflowCancelledException(
                            f"Workflow cancelled by analyst at wave {wave_idx}"
                        )

                    # ── Handle reject: re-run this wave's agents ──
                    if action == "reject":
                        logger.info(
                            "hitl.reject_rerun",
                            system=system_id,
                            wave=wave_idx,
                            notes=notes,
                        )
                        await events.publish(request_id, {
                            "type": "HUMAN_INPUT_RECEIVED",
                            "runId": request_id,
                            "wave": wave_idx,
                            "action": "reject",
                        })
                        # Re-run each agent in this wave with analyst notes
                        rerun_state = dict(state)
                        if notes:
                            rerun_state["analyst_notes"] = notes
                        for aid in wave_agent_ids:
                            agent = self.agents.get(aid)
                            if agent:
                                try:
                                    rerun_output = await agent(rerun_state)
                                    new_outputs = rerun_output.get("agent_outputs", {})
                                    result.setdefault("agent_outputs", {})
                                    result["agent_outputs"].update(new_outputs)
                                except Exception as exc:
                                    logger.error("hitl.rerun_failed", agent=aid, error=str(exc))
                        return result

                    # Publish confirmation event
                    await events.publish(request_id, {
                        "type": "HUMAN_INPUT_RECEIVED",
                        "runId": request_id,
                        "wave": wave_idx,
                        "action": action,
                        "overrides_count": len(overrides),
                    })

                    # Merge analyst overrides into agent_outputs
                    if action == "override" and overrides:
                        result["agent_outputs"] = overrides
                else:
                    logger.info(
                        "hitl.timeout_auto_continue",
                        system=system_id,
                        wave=wave_idx,
                    )
                    await events.publish(request_id, {
                        "type": "HUMAN_INPUT_RECEIVED",
                        "runId": request_id,
                        "wave": wave_idx,
                        "action": "auto_continue",
                        "overrides_count": 0,
                    })

                    # ── Audit: hitl_feedback (timeout) ──
                    if audit_store and request_id:
                        try:
                            await audit_store.log_event(AuditEvent(
                                workflow_id=request_id,
                                event_type="hitl_feedback",
                                payload={
                                    "wave": wave_idx,
                                    "action": "auto_continue",
                                    "overrides_count": 0,
                                    "timeout": True,
                                },
                            ))
                        except Exception:
                            pass

            return result

        return validator_node

    def _compute_waves(self) -> list[list[str]]:
        dag = self.get_agent_dependency_graph()
        completed: set[str] = set()
        remaining = set(dag.keys())
        waves: list[list[str]] = []
        while remaining:
            ready = {
                a for a in remaining
                if all(d in completed for d in dag.get(a, []))
            }
            if not ready:
                raise RuntimeError(
                    f"DAG deadlock in {self.system_id}: "
                    f"remaining={remaining}, completed={completed}"
                )
            waves.append(sorted(ready))
            completed |= ready
            remaining -= ready
        return waves

    async def execute_dag(self, initial_state: dict) -> dict:
        initial_state.setdefault("audit_log", {})
        initial_state.setdefault("cost_log", {})
        initial_state.setdefault("hitl_mode", "express")
        initial_state.setdefault("cost_monitor", None)

        if self._compiled_graph is None:
            self._compiled_graph = self._compile_graph()
        result = await self._compiled_graph.ainvoke(initial_state)
        return result.get("agent_outputs", {})

    async def execute_dag_with_audit(self, initial_state: dict) -> tuple[dict, dict, dict]:
        """Execute DAG and return agent outputs, audit log, and cost log."""
        initial_state.setdefault("audit_log", {})
        initial_state.setdefault("cost_log", {})
        initial_state.setdefault("hitl_mode", "express")
        initial_state.setdefault("cost_monitor", None)

        if self._compiled_graph is None:
            self._compiled_graph = self._compile_graph()
        result = await self._compiled_graph.ainvoke(initial_state)
        return (
            result.get("agent_outputs", {}),
            result.get("audit_log", {}),
            result.get("cost_log", {}),
        )
