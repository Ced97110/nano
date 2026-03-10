"""
LangGraph Agent Cost Monitor — per-agent and per-pipeline cost tracking,
budget enforcement, and loop detection for the Nano Bana Pro platform.

Tracks every LLM call across the FinAgentPro 27-agent pipeline, enforces
configurable budget limits, detects runaway agent loops, and generates
detailed cost reports for logging and SSE streaming.

Architecture notes (do NOT modify these files — these are observations):
------------------------------------------------------------------------
- base_system.py: ``builder.compile()`` is called with no ``recursion_limit``
  config.  Since the DAG is wave-based with no conditional/cyclic edges,
  LangGraph's built-in recursion limit (default 25) is not a concern for
  the current topology.  However, if conditional edges are ever added,
  ``builder.compile(checkpointer=..., recursion_limit=50)`` should be
  passed explicitly.

- base_agent.py: ``call_llm_structured`` passes ``max_retries=2`` which
  is bounded.  Per-agent ``timeout_seconds`` (default 120) is enforced
  via ``asyncio.wait_for``.  These are adequate per-agent safeguards.

- base_system.py ``_make_validator`` HITL reject path (lines 380-393):
  Re-runs all agents in a wave once per reject action.  There is no
  counter limiting how many times an analyst can reject the same wave
  via external API calls within the 5-minute HITL window.  A
  ``max_agent_calls`` guard in CostMonitor would catch this.

- finagent/system.py ``run_pipeline``: Computes a cost summary at the
  end but performs NO budget enforcement during execution.  Integrating
  ``CostMonitor.check_budget()`` calls into barrier validators would
  enable mid-pipeline budget enforcement.

Integration guide:
------------------
1. Instantiate ``CostMonitor`` at pipeline start in ``run_pipeline()``.
2. Call ``monitor.on_agent_start()`` before each agent runs.
3. Call ``monitor.on_agent_complete()`` after each agent returns with
   cost data from ``cost_log``.
4. Call ``monitor.check_budget()`` at each barrier/validator to enforce
   limits mid-pipeline.
5. Call ``monitor.generate_report()`` at pipeline end and include in
   the ``cost`` section of the result dict.
6. Catch ``BudgetExceededError`` and ``AgentLoopDetectedError`` in the
   DAG executor to gracefully abort the pipeline.

Usage example:
    monitor = CostMonitor(max_pipeline_cost_usd=2.0, max_agent_calls=3)
    monitor.on_agent_start("finagent.A0_company_profile", wave=0)
    monitor.on_agent_complete(
        agent_id="finagent.A0_company_profile",
        tokens_in=1234, tokens_out=567,
        model="gpt-4o", latency_ms=2100, cached=False,
    )
    monitor.check_budget()  # raises BudgetExceededError if over limit
    report = monitor.generate_report()
    print(report.to_summary_table())
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Safeguard defaults — recommended limits for pipeline execution
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SAFEGUARD_DEFAULTS: dict[str, int | float] = {
    "max_pipeline_cost_usd": 2.0,        # Hard cap on total pipeline spend
    "max_agent_calls": 3,                 # Per agent per pipeline run
    "max_agent_latency_ms": 60_000,       # Flag agents exceeding 60s
    "max_pipeline_duration_ms": 300_000,  # 5 min total pipeline timeout
    "max_total_tokens": 500_000,          # Hard cap on total token consumption
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Model pricing — cost per 1M tokens (input, output) as of Mar 2025
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

MODEL_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o":             (2.50,  10.00),
    "gpt-4o-mini":        (0.15,   0.60),
    "gpt-4-turbo":       (10.00,  30.00),
    "gpt-4":             (30.00,  60.00),
    "gpt-3.5-turbo":      (0.50,   1.50),
    "o1":                (15.00,  60.00),
    "o1-mini":            (3.00,  12.00),
    "o3-mini":            (1.10,   4.40),

    # Anthropic
    "claude-3-opus":     (15.00,  75.00),
    "claude-3-sonnet":    (3.00,  15.00),
    "claude-3-haiku":     (0.25,   1.25),
    "claude-3.5-sonnet":  (3.00,  15.00),
    "claude-3.5-haiku":   (0.80,   4.00),
    "claude-opus-4":     (15.00,  75.00),
    "claude-sonnet-4":    (3.00,  15.00),

    # Google
    "gemini-1.5-pro":     (1.25,   5.00),
    "gemini-1.5-flash":   (0.075,  0.30),
    "gemini-2.0-flash":   (0.10,   0.40),

    # Local / self-hosted — zero cost
    "glm-4.7":            (0.0,    0.0),
    "glm-4.7:cloud":      (0.0,    0.0),
    "ollama":             (0.0,    0.0),
    "local":              (0.0,    0.0),
}

# Fallback pricing for unknown models (assumes a mid-range model)
_FALLBACK_PRICING: tuple[float, float] = (2.50, 10.00)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Exceptions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class BudgetExceededError(Exception):
    """Raised when the pipeline's total cost exceeds the configured limit.

    Attributes:
        current_cost_usd:  The accumulated cost so far.
        limit_usd:         The configured maximum.
        agent_id:          The agent that triggered the breach (if applicable).
    """

    def __init__(
        self,
        current_cost_usd: float,
        limit_usd: float,
        agent_id: str = "",
        resource: str = "cost_usd",
    ) -> None:
        self.current_cost_usd = current_cost_usd
        self.limit_usd = limit_usd
        self.agent_id = agent_id
        self.resource = resource
        detail = f"${current_cost_usd:.4f} exceeds limit ${limit_usd:.4f}"
        if resource == "tokens":
            detail = f"{int(current_cost_usd)} tokens exceeds limit {int(limit_usd)}"
        agent_info = f" (triggered by {agent_id})" if agent_id else ""
        super().__init__(
            f"Pipeline budget exceeded: {detail}{agent_info}"
        )


class AgentLoopDetectedError(Exception):
    """Raised when a single agent is called more times than allowed.

    Attributes:
        agent_id:   The agent that looped.
        call_count: How many times it has been called.
        max_calls:  The configured maximum.
    """

    def __init__(self, agent_id: str, call_count: int, max_calls: int) -> None:
        self.agent_id = agent_id
        self.call_count = call_count
        self.max_calls = max_calls
        super().__init__(
            f"Agent loop detected: {agent_id} called {call_count} times "
            f"(max allowed: {max_calls})"
        )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Data classes
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@dataclass
class AgentCostRecord:
    """Cost and performance record for a single agent execution."""

    agent_id: str
    wave: int = -1
    tokens_in: int = 0
    tokens_out: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    cached: bool = False
    status: str = "pending"  # "pending" | "running" | "completed" | "error" | "timeout"
    call_count: int = 0
    model: str = ""
    error: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for JSON / SSE."""
        return {
            "agent_id": self.agent_id,
            "wave": self.wave,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "latency_ms": self.latency_ms,
            "cached": self.cached,
            "status": self.status,
            "call_count": self.call_count,
            "model": self.model,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class PipelineCostReport:
    """Aggregated cost report for an entire pipeline run."""

    pipeline_id: str = ""
    ticker: str = ""
    analysis_type: str = "full"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_ms: float = 0.0
    agent_records: list[AgentCostRecord] = field(default_factory=list)
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    cache_hit_rate: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for JSON / SSE / API response."""
        return {
            "pipeline_id": self.pipeline_id,
            "ticker": self.ticker,
            "analysis_type": self.analysis_type,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "duration_ms": round(self.duration_ms, 1),
            "agent_records": [r.to_dict() for r in self.agent_records],
            "total_tokens_in": self.total_tokens_in,
            "total_tokens_out": self.total_tokens_out,
            "total_tokens": self.total_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "cache_hit_rate": round(self.cache_hit_rate, 4),
            "warnings": self.warnings,
            "agents_completed": sum(
                1 for r in self.agent_records if r.status == "completed"
            ),
            "agents_total": len(self.agent_records),
        }

    def to_summary_table(self) -> str:
        """Format a clean ASCII table for structured logging output.

        Produces a box-drawing table with per-agent rows sorted by wave
        then agent_id, plus a totals footer row.
        """
        title = f"Pipeline Cost Report: {self.ticker} ({self.analysis_type})"

        # Column widths
        w_agent = 20
        w_wave = 6
        w_tin = 11
        w_tout = 12
        w_cost = 9
        w_lat = 9
        w_status = 8
        inner_width = w_agent + w_wave + w_tin + w_tout + w_cost + w_lat + w_status + 6  # 6 separators

        lines: list[str] = []

        # Top border
        lines.append(f"+{'=' * inner_width}+")
        # Title (centered)
        lines.append(f"|{title:^{inner_width}}|")
        # Header separator
        lines.append(f"+{'=' * inner_width}+")
        # Column headers
        hdr = (
            f"| {'Agent':<{w_agent}}"
            f"| {'Wave':^{w_wave}}"
            f"| {'Tokens In':>{w_tin}}"
            f"| {'Tokens Out':>{w_tout}}"
            f"| {'Cost':>{w_cost}}"
            f"| {'Latency':>{w_lat}}"
            f"| {'Status':^{w_status}}"
            f"|"
        )
        lines.append(hdr)
        lines.append(f"+{'-' * inner_width}+")

        # Sort records by wave, then agent_id
        sorted_records = sorted(
            self.agent_records, key=lambda r: (r.wave, r.agent_id)
        )

        for rec in sorted_records:
            # Shorten agent_id for display: "finagent.A0_company_profile" -> "A0 company prof"
            short_name = _shorten_agent_id(rec.agent_id, w_agent)
            wave_str = str(rec.wave) if rec.wave >= 0 else "-"
            cost_str = f"${rec.cost_usd:.4f}"
            latency_str = _format_latency(rec.latency_ms)
            status_char = _status_symbol(rec.status)

            row = (
                f"| {short_name:<{w_agent}}"
                f"| {wave_str:^{w_wave}}"
                f"| {rec.tokens_in:>{w_tin},}"
                f"| {rec.tokens_out:>{w_tout},}"
                f"| {cost_str:>{w_cost}}"
                f"| {latency_str:>{w_lat}}"
                f"| {status_char:^{w_status}}"
                f"|"
            )
            lines.append(row)

        # Totals separator
        lines.append(f"+{'-' * inner_width}+")

        completed = sum(1 for r in self.agent_records if r.status == "completed")
        total = len(self.agent_records)
        total_cost_str = f"${self.total_cost_usd:.4f}"
        total_latency_str = _format_latency(int(self.duration_ms))
        status_str = f"{completed}/{total}"

        totals_row = (
            f"| {'TOTAL':<{w_agent}}"
            f"| {'':^{w_wave}}"
            f"| {self.total_tokens_in:>{w_tin},}"
            f"| {self.total_tokens_out:>{w_tout},}"
            f"| {total_cost_str:>{w_cost}}"
            f"| {total_latency_str:>{w_lat}}"
            f"| {status_str:^{w_status}}"
            f"|"
        )
        lines.append(totals_row)

        # Bottom border
        lines.append(f"+{'=' * inner_width}+")

        # Warnings section (if any)
        if self.warnings:
            lines.append("")
            lines.append("Warnings:")
            for w in self.warnings:
                lines.append(f"  - {w}")

        # Cache info
        lines.append("")
        lines.append(
            f"Cache hit rate: {self.cache_hit_rate:.1%}  |  "
            f"Duration: {self.duration_ms / 1000:.1f}s  |  "
            f"Pipeline: {self.pipeline_id[:12]}..."
        )

        return "\n".join(lines)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Pricing helper
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimate USD cost for a single LLM call.

    Looks up the model in ``MODEL_PRICING``.  For Ollama / local models
    the cost is $0.00.  Unknown models fall back to gpt-4o pricing to
    err on the side of overestimation.

    Args:
        model:      Model identifier string (e.g. "gpt-4o", "claude-3-sonnet").
        tokens_in:  Number of input (prompt) tokens.
        tokens_out: Number of output (completion) tokens.

    Returns:
        Estimated cost in USD, rounded to 6 decimal places.
    """
    # Normalize model name: strip provider prefixes and version suffixes
    normalized = _normalize_model_name(model)
    pricing = MODEL_PRICING.get(normalized, _FALLBACK_PRICING)

    input_cost = (tokens_in / 1_000_000) * pricing[0]
    output_cost = (tokens_out / 1_000_000) * pricing[1]
    return round(input_cost + output_cost, 6)


def _normalize_model_name(model: str) -> str:
    """Best-effort normalization of model identifiers.

    Handles patterns like "openai/gpt-4o", "anthropic/claude-3-sonnet",
    "ollama/llama3", etc.
    """
    if not model:
        return ""

    # Strip known provider prefixes
    lower = model.lower()
    for prefix in ("openai/", "anthropic/", "google/", "ollama/"):
        if lower.startswith(prefix):
            stripped = model[len(prefix):]
            # ollama/* models are free
            if prefix == "ollama/":
                return "ollama"
            return stripped

    # Direct match
    if lower in MODEL_PRICING:
        return lower

    # Partial match: find the longest key that is a prefix of the model
    for key in sorted(MODEL_PRICING.keys(), key=len, reverse=True):
        if lower.startswith(key):
            return key

    return model


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CostMonitor
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class CostMonitor:
    """Tracks per-agent and per-pipeline costs with budget enforcement.

    Create one instance per pipeline run.  Thread-safe for use within a
    single asyncio event loop (no locks needed since all calls are from
    the same coroutine chain).

    Args:
        pipeline_id:           Unique identifier for this pipeline run.
        ticker:                The entity/ticker being analyzed.
        analysis_type:         The analysis type (e.g. "full", "quick").
        max_pipeline_cost_usd: Hard cap on total pipeline spend in USD.
        max_agent_calls:       Max times any single agent_id may be called.
        max_agent_latency_ms:  Latency threshold to flag slow agents.
        max_pipeline_duration_ms: Overall pipeline timeout in ms.
        max_total_tokens:      Hard cap on total token consumption.
    """

    def __init__(
        self,
        pipeline_id: str = "",
        ticker: str = "",
        analysis_type: str = "full",
        max_pipeline_cost_usd: float = SAFEGUARD_DEFAULTS["max_pipeline_cost_usd"],
        max_agent_calls: int = int(SAFEGUARD_DEFAULTS["max_agent_calls"]),
        max_agent_latency_ms: int = int(SAFEGUARD_DEFAULTS["max_agent_latency_ms"]),
        max_pipeline_duration_ms: int = int(SAFEGUARD_DEFAULTS["max_pipeline_duration_ms"]),
        max_total_tokens: int = int(SAFEGUARD_DEFAULTS["max_total_tokens"]),
    ) -> None:
        self.pipeline_id = pipeline_id
        self.ticker = ticker
        self.analysis_type = analysis_type

        # Limits
        self.max_pipeline_cost_usd = max_pipeline_cost_usd
        self.max_agent_calls = max_agent_calls
        self.max_agent_latency_ms = max_agent_latency_ms
        self.max_pipeline_duration_ms = max_pipeline_duration_ms
        self.max_total_tokens = max_total_tokens

        # State
        self._records: dict[str, AgentCostRecord] = {}  # agent_id -> latest record
        self._call_counts: dict[str, int] = {}  # agent_id -> total call count
        self._all_records: list[AgentCostRecord] = []  # every execution (including re-runs)
        self._warnings: list[str] = []
        self._started_at: datetime = datetime.now(timezone.utc)
        self._started_mono: float = time.monotonic()
        self._completed_at: datetime | None = None

        # Running totals
        self._total_tokens_in: int = 0
        self._total_tokens_out: int = 0
        self._total_cost_usd: float = 0.0
        self._cache_hits: int = 0
        self._total_agents: int = 0

    # ── Lifecycle hooks ──

    def on_agent_start(self, agent_id: str, wave: int = -1) -> None:
        """Record that an agent has begun execution.

        Must be called before ``on_agent_complete`` or ``on_agent_error``.
        Raises ``AgentLoopDetectedError`` if the agent has already been
        called ``max_agent_calls`` times.
        """
        self._call_counts.setdefault(agent_id, 0)
        self._call_counts[agent_id] += 1

        count = self._call_counts[agent_id]
        if count > self.max_agent_calls:
            error = AgentLoopDetectedError(agent_id, count, self.max_agent_calls)
            logger.error(
                "cost_monitor.loop_detected",
                agent_id=agent_id,
                call_count=count,
                max_calls=self.max_agent_calls,
            )
            raise error

        record = AgentCostRecord(
            agent_id=agent_id,
            wave=wave,
            status="running",
            call_count=count,
            started_at=datetime.now(timezone.utc),
        )
        self._records[agent_id] = record

        logger.debug(
            "cost_monitor.agent_start",
            agent_id=agent_id,
            wave=wave,
            call_count=count,
        )

    def on_agent_complete(
        self,
        agent_id: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        model: str = "",
        latency_ms: int = 0,
        cached: bool = False,
        cost_usd: float | None = None,
    ) -> None:
        """Record successful agent completion with cost data.

        If ``cost_usd`` is not provided, it is estimated from the model
        and token counts using ``estimate_cost()``.

        Args:
            agent_id:   The agent that completed.
            tokens_in:  Input (prompt) tokens consumed.
            tokens_out: Output (completion) tokens consumed.
            model:      The LLM model used.
            latency_ms: Wall-clock execution time in milliseconds.
            cached:     Whether the result came from cache.
            cost_usd:   Explicit cost (if already calculated by gateway).
        """
        record = self._records.get(agent_id)
        if record is None:
            # Agent completed without a prior on_agent_start call.
            # Create a record retroactively.
            record = AgentCostRecord(
                agent_id=agent_id,
                call_count=self._call_counts.get(agent_id, 1),
            )
            self._records[agent_id] = record

        total_tokens = tokens_in + tokens_out
        computed_cost = (
            cost_usd
            if cost_usd is not None
            else estimate_cost(model, tokens_in, tokens_out)
        )

        record.tokens_in = tokens_in
        record.tokens_out = tokens_out
        record.total_tokens = total_tokens
        record.cost_usd = computed_cost
        record.latency_ms = latency_ms
        record.cached = cached
        record.model = model
        record.status = "completed"
        record.completed_at = datetime.now(timezone.utc)

        # Accumulate totals
        self._total_tokens_in += tokens_in
        self._total_tokens_out += tokens_out
        self._total_cost_usd += computed_cost
        self._total_agents += 1
        if cached:
            self._cache_hits += 1

        # Snapshot into the full history
        self._all_records.append(AgentCostRecord(
            agent_id=record.agent_id,
            wave=record.wave,
            tokens_in=record.tokens_in,
            tokens_out=record.tokens_out,
            total_tokens=record.total_tokens,
            cost_usd=record.cost_usd,
            latency_ms=record.latency_ms,
            cached=record.cached,
            status=record.status,
            call_count=record.call_count,
            model=record.model,
            started_at=record.started_at,
            completed_at=record.completed_at,
        ))

        # Check for slow agents
        if latency_ms > self.max_agent_latency_ms and not cached:
            warning = (
                f"Slow agent: {agent_id} took {latency_ms / 1000:.1f}s "
                f"(threshold: {self.max_agent_latency_ms / 1000:.1f}s)"
            )
            self._warnings.append(warning)
            logger.warning(
                "cost_monitor.slow_agent",
                agent_id=agent_id,
                latency_ms=latency_ms,
                threshold_ms=self.max_agent_latency_ms,
            )

        logger.debug(
            "cost_monitor.agent_complete",
            agent_id=agent_id,
            tokens=total_tokens,
            cost_usd=round(computed_cost, 6),
            latency_ms=latency_ms,
            cached=cached,
            pipeline_total_cost=round(self._total_cost_usd, 6),
        )

    def on_agent_error(self, agent_id: str, error: str) -> None:
        """Record an agent execution failure.

        Args:
            agent_id: The agent that failed.
            error:    Error message string.
        """
        record = self._records.get(agent_id)
        if record is None:
            record = AgentCostRecord(
                agent_id=agent_id,
                call_count=self._call_counts.get(agent_id, 1),
            )
            self._records[agent_id] = record

        record.status = "error"
        record.error = error[:500]
        record.completed_at = datetime.now(timezone.utc)
        self._total_agents += 1

        self._all_records.append(AgentCostRecord(
            agent_id=record.agent_id,
            wave=record.wave,
            status="error",
            error=record.error,
            call_count=record.call_count,
            started_at=record.started_at,
            completed_at=record.completed_at,
        ))

        logger.warning(
            "cost_monitor.agent_error",
            agent_id=agent_id,
            error=error[:200],
        )

    def on_agent_timeout(self, agent_id: str, timeout_seconds: int) -> None:
        """Record an agent timeout.

        Args:
            agent_id:        The agent that timed out.
            timeout_seconds: The configured timeout that was exceeded.
        """
        record = self._records.get(agent_id)
        if record is None:
            record = AgentCostRecord(
                agent_id=agent_id,
                call_count=self._call_counts.get(agent_id, 1),
            )
            self._records[agent_id] = record

        record.status = "timeout"
        record.error = f"Timed out after {timeout_seconds}s"
        record.latency_ms = timeout_seconds * 1000
        record.completed_at = datetime.now(timezone.utc)
        self._total_agents += 1

        self._all_records.append(AgentCostRecord(
            agent_id=record.agent_id,
            wave=record.wave,
            status="timeout",
            error=record.error,
            latency_ms=record.latency_ms,
            call_count=record.call_count,
            started_at=record.started_at,
            completed_at=record.completed_at,
        ))

        warning = f"Agent timeout: {agent_id} exceeded {timeout_seconds}s"
        self._warnings.append(warning)
        logger.warning(
            "cost_monitor.agent_timeout",
            agent_id=agent_id,
            timeout_seconds=timeout_seconds,
        )

    # ── Budget enforcement ──

    def check_budget(self) -> None:
        """Check all budget limits and raise if any are exceeded.

        Checks performed:
        1. Total pipeline cost vs ``max_pipeline_cost_usd``
        2. Total tokens vs ``max_total_tokens``
        3. Pipeline duration vs ``max_pipeline_duration_ms``

        Raises:
            BudgetExceededError: If any limit is exceeded.

        Note:
            Agent loop detection is performed in ``on_agent_start()``
            rather than here, to fail as early as possible.
        """
        # 1. Cost budget
        if self._total_cost_usd > self.max_pipeline_cost_usd:
            logger.error(
                "cost_monitor.budget_exceeded",
                total_cost_usd=round(self._total_cost_usd, 6),
                limit_usd=self.max_pipeline_cost_usd,
            )
            raise BudgetExceededError(
                current_cost_usd=self._total_cost_usd,
                limit_usd=self.max_pipeline_cost_usd,
            )

        # 2. Token budget
        total_tokens = self._total_tokens_in + self._total_tokens_out
        if total_tokens > self.max_total_tokens:
            logger.error(
                "cost_monitor.token_budget_exceeded",
                total_tokens=total_tokens,
                limit=self.max_total_tokens,
            )
            raise BudgetExceededError(
                current_cost_usd=float(total_tokens),
                limit_usd=float(self.max_total_tokens),
                resource="tokens",
            )

        # 3. Duration budget
        elapsed_ms = (time.monotonic() - self._started_mono) * 1000
        if elapsed_ms > self.max_pipeline_duration_ms:
            warning = (
                f"Pipeline duration {elapsed_ms / 1000:.1f}s exceeds "
                f"limit {self.max_pipeline_duration_ms / 1000:.1f}s"
            )
            self._warnings.append(warning)
            logger.warning("cost_monitor.duration_exceeded", elapsed_ms=elapsed_ms)
            # Duration is a warning, not a hard stop — the pipeline may be
            # in a valid long-running state (e.g. waiting for HITL input).
            # Callers can choose to abort based on the warning.

        # Emit budget utilization for observability
        cost_pct = (
            (self._total_cost_usd / self.max_pipeline_cost_usd * 100)
            if self.max_pipeline_cost_usd > 0
            else 0
        )
        if cost_pct > 75 and cost_pct <= 100:
            warning = (
                f"Budget warning: {cost_pct:.0f}% of ${self.max_pipeline_cost_usd:.2f} "
                f"limit used (${self._total_cost_usd:.4f})"
            )
            if warning not in self._warnings:
                self._warnings.append(warning)
                logger.warning(
                    "cost_monitor.budget_warning",
                    pct_used=round(cost_pct, 1),
                    cost_usd=round(self._total_cost_usd, 6),
                    limit_usd=self.max_pipeline_cost_usd,
                )

    # ── Report generation ──

    def generate_report(self) -> PipelineCostReport:
        """Generate the final cost report for this pipeline run.

        Should be called once at the end of the pipeline.  Populates
        all aggregate fields and returns a ``PipelineCostReport``.
        """
        now = datetime.now(timezone.utc)
        self._completed_at = now
        elapsed_ms = (time.monotonic() - self._started_mono) * 1000

        total_tokens = self._total_tokens_in + self._total_tokens_out
        cache_hit_rate = (
            self._cache_hits / self._total_agents
            if self._total_agents > 0
            else 0.0
        )

        # Use the latest record per agent for the summary
        # (if an agent was re-run, we show the most recent execution)
        records_list = list(self._records.values())

        return PipelineCostReport(
            pipeline_id=self.pipeline_id,
            ticker=self.ticker,
            analysis_type=self.analysis_type,
            started_at=self._started_at,
            completed_at=now,
            duration_ms=elapsed_ms,
            agent_records=records_list,
            total_tokens_in=self._total_tokens_in,
            total_tokens_out=self._total_tokens_out,
            total_tokens=total_tokens,
            total_cost_usd=self._total_cost_usd,
            cache_hit_rate=cache_hit_rate,
            warnings=list(self._warnings),
        )

    # ── Convenience accessors ──

    @property
    def total_cost_usd(self) -> float:
        """Current accumulated pipeline cost."""
        return self._total_cost_usd

    @property
    def total_tokens(self) -> int:
        """Current accumulated total tokens (in + out)."""
        return self._total_tokens_in + self._total_tokens_out

    @property
    def elapsed_ms(self) -> float:
        """Milliseconds since pipeline start."""
        return (time.monotonic() - self._started_mono) * 1000

    @property
    def agent_call_counts(self) -> dict[str, int]:
        """Current call counts per agent (for diagnostics)."""
        return dict(self._call_counts)

    def get_agent_record(self, agent_id: str) -> AgentCostRecord | None:
        """Retrieve the latest cost record for a specific agent."""
        return self._records.get(agent_id)

    def get_all_executions(self) -> list[AgentCostRecord]:
        """Return every execution record including re-runs (chronological)."""
        return list(self._all_records)

    def ingest_cost_log(self, cost_log: dict[str, dict], wave_map: dict[str, int] | None = None) -> None:
        """Bulk-import cost data from a ``PipelineState.cost_log`` dict.

        This allows retroactive import of cost data that was tracked by
        ``BaseAgent.__call__`` into the existing ``cost_log`` state field,
        without requiring changes to ``BaseAgent``.

        Args:
            cost_log:  The ``cost_log`` dict from PipelineState.  Keys are
                       agent IDs, values are dicts with ``tokens_used``,
                       ``cost_usd``, ``cached``, ``latency_ms``.
            wave_map:  Optional mapping of agent_id -> wave index.
        """
        wave_map = wave_map or {}
        for agent_id, entry in cost_log.items():
            if not isinstance(entry, dict):
                continue

            tokens_used = entry.get("tokens_used", 0)
            cost_usd = entry.get("cost_usd", 0.0)
            cached = entry.get("cached", False)
            latency_ms = entry.get("latency_ms", 0)
            error = entry.get("error", "")
            wave = wave_map.get(agent_id, -1)

            # Approximate token split (we don't have prompt vs completion
            # in the existing cost_log format, so estimate 70/30 split)
            tokens_in = int(tokens_used * 0.7)
            tokens_out = tokens_used - tokens_in

            self._call_counts.setdefault(agent_id, 0)
            self._call_counts[agent_id] += 1

            status = "completed"
            if error:
                status = "error"

            record = AgentCostRecord(
                agent_id=agent_id,
                wave=wave,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                total_tokens=tokens_used,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                cached=cached,
                status=status,
                call_count=self._call_counts[agent_id],
                error=error[:500] if error else "",
            )
            self._records[agent_id] = record
            self._all_records.append(record)

            self._total_tokens_in += tokens_in
            self._total_tokens_out += tokens_out
            self._total_cost_usd += cost_usd
            self._total_agents += 1
            if cached:
                self._cache_hits += 1


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Internal formatting helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _shorten_agent_id(agent_id: str, max_len: int) -> str:
    """Shorten 'finagent.A0_company_profile' to 'A0 company prof' for tables."""
    # Remove system prefix
    short = agent_id
    if "." in short:
        short = short.split(".", 1)[1]

    # Replace underscores with spaces
    short = short.replace("_", " ")

    if len(short) <= max_len:
        return short

    return short[: max_len - 1] + "~"


def _format_latency(ms: int) -> str:
    """Format latency for display: ms < 1000 -> '234ms', else '2.1s'."""
    if ms < 1000:
        return f"{ms}ms"
    return f"{ms / 1000:.1f}s"


def _status_symbol(status: str) -> str:
    """Map status to a compact display character."""
    return {
        "completed": "OK",
        "error": "ERR",
        "timeout": "T/O",
        "running": "...",
        "pending": "-",
    }.get(status, "?")
