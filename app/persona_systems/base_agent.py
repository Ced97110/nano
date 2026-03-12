"""Base agent class — depends ONLY on domain interfaces (ports), never on infrastructure.

Dependencies (LLMGateway, CacheRepository, EventPublisher, WebSearchGateway)
are injected via constructor by the persona system that owns this agent.
"""

import asyncio
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel

from app.domain.entities.agent_output import AgentOutput
from app.domain.interfaces.audit_store import AuditEvent, AuditStore
from app.domain.interfaces.cache_repository import CacheRepository
from app.domain.interfaces.event_publisher import EventPublisher
from app.domain.interfaces.llm_gateway import LLMGateway
from app.domain.interfaces.web_search import WebSearchGateway
from app.domain.models.provenance import DataSource

logger = structlog.get_logger(__name__)


class BaseAgent:
    """Base class for all LangGraph-powered agents.

    Subclasses set ``agent_id``, ``system_prompt``, and override ``execute()``.
    The ``__call__`` method is the LangGraph node entry-point.

    Per-agent LLM configuration:
        model_override: str | None — use a different model for this agent
        temperature: float — LLM temperature (default 0.3)
        max_tokens: int — max response tokens (default 2048)
        timeout_seconds: int — per-agent execution timeout (default 120)
    """

    agent_id: str = ""
    persona_system: str = ""
    system_prompt: str = ""
    cache_ttl: int = 1800

    # Per-agent LLM configuration — override in subclass
    model_override: str | None = None
    temperature: float = 0.3
    max_tokens: int = 2048
    timeout_seconds: int = 120
    json_mode: bool = False  # Set True for models that support response_format (not glm-4.7)

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
        self._web_search: WebSearchGateway | None = web_search
        self._provenance: dict[str, list[dict]] = {}  # field_path -> list of DataSource dicts

    # ── LangGraph node callable ──

    async def __call__(self, state: dict) -> dict:
        request_id = state.get("request_id", "")
        t0 = time.monotonic()

        if request_id:
            await self._safe_publish(request_id, {
                "type": "AGENT_STATE_STARTED",
                "agentId": self.agent_id,
                "runId": request_id,
            })

        # ── Audit: agent_started ──
        await self._safe_audit(request_id, "agent_started", {
            "entity": state.get("entity", ""),
            "intent_keys": list(state.get("intent", {}).keys()),
        })

        try:
            input_hash = self._compute_input_hash(state)
            cached = await self._safe_cache_get(input_hash)
            if cached is not None:
                latency = int((time.monotonic() - t0) * 1000)
                logger.info("agent.cache.hit", agent=self.agent_id)
                if request_id:
                    await self._safe_publish(request_id, {
                        "type": "AGENT_STATE_COMPLETED",
                        "agentId": self.agent_id,
                        "runId": request_id,
                        "cached": True,
                        "latency_ms": latency,
                        "tokens_used": 0,
                        "cost_usd": 0.0,
                    })
                # ── Audit: agent_completed (cache hit) ──
                await self._safe_audit(request_id, "agent_completed", {
                    "cached": True,
                    "latency_ms": latency,
                    "tokens_used": 0,
                    "cost_usd": 0.0,
                })
                return {
                    "agent_outputs": {self.agent_id: cached},
                    "cost_log": {self.agent_id: {
                        "tokens_used": 0, "cost_usd": 0.0,
                        "cached": True, "latency_ms": latency,
                    }},
                }

            # Reset provenance tracking for this execution
            self.reset_provenance()

            # Execute with timeout enforcement
            try:
                result = await asyncio.wait_for(
                    self.execute(state),
                    timeout=self.timeout_seconds,
                )
            except asyncio.TimeoutError:
                latency = int((time.monotonic() - t0) * 1000)
                error_msg = f"Agent {self.agent_id} timed out after {self.timeout_seconds}s"
                logger.error("agent.timeout", agent=self.agent_id, timeout=self.timeout_seconds)
                if request_id:
                    await self._safe_publish(request_id, {
                        "type": "AGENT_STATE_COMPLETED",
                        "agentId": self.agent_id,
                        "runId": request_id,
                        "error": error_msg,
                        "tokens_used": 0,
                        "cost_usd": 0.0,
                    })
                await self._safe_audit(request_id, "agent_timeout", {
                    "timeout_seconds": self.timeout_seconds,
                    "latency_ms": latency,
                })
                return {
                    "agent_outputs": {self.agent_id: {"error": error_msg}},
                    "cost_log": {self.agent_id: {
                        "tokens_used": 0, "cost_usd": 0.0,
                        "cached": False, "error": error_msg,
                        "latency_ms": latency,
                    }},
                }

            # Attach provenance to result if any was tracked
            if self._provenance and result.provenance is None:
                result.provenance = self.get_provenance()

            await self._safe_cache_set(input_hash, result.output)

            logger.info(
                "agent.completed",
                agent=self.agent_id,
                tokens=result.tokens_used,
                cost_usd=round(result.cost_usd, 6),
                latency_ms=result.latency_ms,
            )

            if request_id:
                await self._safe_publish(request_id, {
                    "type": "AGENT_STATE_COMPLETED",
                    "agentId": self.agent_id,
                    "runId": request_id,
                    "cached": False,
                    "confidence": result.confidence_score,
                    "latency_ms": result.latency_ms,
                    "tokens_used": result.tokens_used,
                    "cost_usd": round(result.cost_usd, 6),
                })

            # ── Audit: agent_completed ──
            output_summary = self._truncate_output(result.output)
            await self._safe_audit(request_id, "agent_completed", {
                "cached": False,
                "confidence": result.confidence_score,
                "latency_ms": result.latency_ms,
                "tokens_used": result.tokens_used,
                "cost_usd": round(result.cost_usd, 6),
                "data_sources": result.data_sources_accessed,
                "output_summary": output_summary,
                "has_provenance": result.provenance is not None,
            })

            # Include provenance in agent output if tracked
            agent_output = result.output
            if result.provenance:
                agent_output = {**agent_output, "_provenance": result.provenance}

            return {
                "agent_outputs": {self.agent_id: agent_output},
                "cost_log": {self.agent_id: {
                    "tokens_used": result.tokens_used,
                    "cost_usd": round(result.cost_usd, 6),
                    "cached": False, "latency_ms": result.latency_ms,
                }},
            }

        except Exception as exc:
            logger.error("agent.failed", agent=self.agent_id, error=str(exc))
            if request_id:
                await self._safe_publish(request_id, {
                    "type": "AGENT_STATE_COMPLETED",
                    "agentId": self.agent_id,
                    "runId": request_id,
                    "error": str(exc),
                    "tokens_used": 0,
                    "cost_usd": 0.0,
                })
            # ── Audit: agent_error ──
            await self._safe_audit(request_id, "agent_error", {
                "error": str(exc)[:2000],
            })
            return {
                "agent_outputs": {self.agent_id: {"error": str(exc)}},
                "cost_log": {self.agent_id: {
                    "tokens_used": 0, "cost_usd": 0.0,
                    "cached": False, "error": str(exc),
                }},
            }

    # ── Override in subclass ──

    async def execute(self, state: dict) -> AgentOutput:
        raise NotImplementedError

    # ── Utilities (delegate to injected ports) ──

    async def call_llm(
        self,
        messages: list[dict],
        max_tokens: int | None = None,
        temperature: float | None = None,
        json_mode: bool | None = None,
    ) -> dict:
        """Call LLM using per-agent defaults for model, max_tokens, and temperature.

        Explicit arguments override the agent-level defaults.
        """
        return await self._llm.chat(
            messages=messages,
            system=self.system_prompt,
            max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
            temperature=temperature if temperature is not None else self.temperature,
            model=self.model_override,
            json_mode=json_mode if json_mode is not None else self.json_mode,
        )

    T = TypeVar("T", bound=BaseModel)

    async def call_llm_structured(
        self,
        messages: list[dict],
        response_model: type[T],
        max_tokens: int | None = None,
        temperature: float | None = None,
        max_retries: int = 2,
    ) -> tuple[T, dict]:
        """Call LLM and return a validated Pydantic model via instructor.

        Returns (parsed_model, metadata_dict) so callers get both
        the structured output and token/cost metadata.
        Uses per-agent defaults for model, max_tokens, and temperature.
        """
        return await self._llm.chat_structured(
            messages=messages,
            response_model=response_model,
            system=self.system_prompt,
            max_tokens=max_tokens if max_tokens is not None else self.max_tokens,
            temperature=temperature if temperature is not None else self.temperature,
            model=self.model_override,
            max_retries=max_retries,
        )

    @staticmethod
    def _repair_json(text: str) -> str:
        """Fix common LLM JSON mistakes: trailing commas, single quotes, comments."""
        # Remove single-line comments (// ...)
        text = re.sub(r'//[^\n]*', '', text)
        # Remove trailing commas before } or ]
        text = re.sub(r',\s*([}\]])', r'\1', text)
        # Replace single-quoted strings with double-quoted (simple heuristic)
        # Only outside of already double-quoted strings
        result = []
        in_double = False
        escape_next = False
        for c in text:
            if escape_next:
                result.append(c)
                escape_next = False
                continue
            if c == '\\':
                escape_next = True
                result.append(c)
                continue
            if c == '"':
                in_double = not in_double
                result.append(c)
            elif c == "'" and not in_double:
                result.append('"')
            else:
                result.append(c)
        return ''.join(result)

    @staticmethod
    def parse_json(text: str) -> dict | list | Any:
        # Strip markdown code fences
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # LLM may wrap JSON in surrounding prose — extract first { ... } or [ ... ]
        # Find the first top-level JSON object
        for start_char, end_char in [("{", "}"), ("[", "]")]:
            start = cleaned.find(start_char)
            if start == -1:
                continue
            # Walk from the end to find the matching closing brace/bracket
            depth = 0
            end = -1
            in_string = False
            escape_next = False
            for i in range(start, len(cleaned)):
                c = cleaned[i]
                if escape_next:
                    escape_next = False
                    continue
                if c == "\\":
                    escape_next = True
                    continue
                if c == '"' and not escape_next:
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if c == start_char:
                    depth += 1
                elif c == end_char:
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end > start:
                candidate = cleaned[start : end + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    # Try repairing common LLM JSON mistakes
                    try:
                        repaired = BaseAgent._repair_json(candidate)
                        return json.loads(repaired)
                    except json.JSONDecodeError:
                        pass

        # Last resort: try repairing the entire cleaned text
        try:
            repaired = BaseAgent._repair_json(cleaned)
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

        return {"raw": text}

    def get_prior(self, state: dict, agent_id: str) -> dict:
        return state.get("agent_outputs", {}).get(agent_id, {})

    def get_cross_system_data(self, state: dict, source_system: str) -> dict:
        return state.get("cross_system_context", {}).get(source_system, {})

    # ── Web search convenience methods ──

    async def search_web(self, query: str, max_results: int = 5) -> list[dict]:
        """Search the web via the injected gateway. Returns empty list if unavailable."""
        if not self._web_search:
            return []
        try:
            results = await self._web_search.search(query, max_results=max_results)
            return results
        except Exception as exc:
            logger.warning("agent.search_web.error", agent=self.agent_id, error=str(exc))
            return []

    async def search_news(self, query: str, days: int = 7, max_results: int = 5) -> list[dict]:
        """Search recent news via the injected gateway. Returns empty list if unavailable."""
        if not self._web_search:
            return []
        try:
            results = await self._web_search.search_news(query, days=days, max_results=max_results)
            return results
        except Exception as exc:
            logger.warning("agent.search_news.error", agent=self.agent_id, error=str(exc))
            return []

    # ── Provenance tracking helpers ──

    def track_provenance(
        self,
        field_path: str,
        value: str,
        source_type: str,
        source_id: str,
        confidence: float = 1.0,
        snippet: str = "",
    ) -> None:
        """Record provenance for a specific output field."""
        ds = DataSource(
            source_type=source_type,
            source_id=source_id,
            confidence=confidence,
            snippet=snippet[:500],
        )
        self._provenance.setdefault(field_path, []).append(ds.to_dict())

    def track_web_provenance(self, field_path: str, value: str, web_results: list[dict]) -> None:
        """Record web search results as provenance for a field."""
        for r in web_results:
            self.track_provenance(
                field_path=field_path,
                value=value,
                source_type="web_search",
                source_id=r.get("url", ""),
                confidence=r.get("score", 0.5),
                snippet=r.get("content", "")[:300],
            )

    def get_provenance(self) -> dict[str, list[dict]] | None:
        """Return collected provenance or None if empty."""
        return self._provenance if self._provenance else None

    def reset_provenance(self) -> None:
        """Clear provenance tracking for a new execution."""
        self._provenance = {}

    def _compute_input_hash(self, state: dict) -> str:
        entity = state.get("entity", "")
        intent_str = json.dumps(state.get("intent", {}), sort_keys=True, default=str)
        raw = f"{self.agent_id}:{entity}:{intent_str}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    # ── Safe wrappers (never crash the agent) ──

    async def _safe_audit(self, workflow_id: str, event_type: str, payload: dict) -> None:
        """Log an audit event. Never crashes the agent."""
        if not self._audit_store or not workflow_id:
            return
        try:
            await self._audit_store.log_event(AuditEvent(
                workflow_id=workflow_id,
                event_type=event_type,
                agent_id=self.agent_id,
                payload=payload,
            ))
        except Exception:
            pass

    @staticmethod
    def _truncate_output(output: dict, max_chars: int = 2000) -> str:
        """Truncate output dict to a reasonable summary for audit payload."""
        raw = json.dumps(output, default=str)
        if len(raw) <= max_chars:
            return raw
        return raw[:max_chars] + "...[truncated]"

    async def _safe_publish(self, request_id: str, event: dict) -> None:
        try:
            await self._events.publish(request_id, event)
        except Exception:
            pass

    async def _safe_cache_get(self, input_hash: str) -> dict | None:
        try:
            return await self._cache.get_agent(self.agent_id, input_hash)
        except Exception:
            return None

    async def _safe_cache_set(self, input_hash: str, data: dict) -> None:
        try:
            await self._cache.set_agent(self.agent_id, input_hash, data, self.cache_ttl)
        except Exception:
            pass
