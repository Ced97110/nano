"""Domain entity — the output of a single agent execution."""

from dataclasses import dataclass, field


@dataclass
class AgentOutput:
    agent_id: str
    output: dict = field(default_factory=dict)
    confidence_score: float = 0.0
    tokens_used: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    data_sources_accessed: list[str] = field(default_factory=list)
    error: str | None = None
    provenance: dict[str, list[dict]] | None = None  # field_path -> list of DataSource dicts
