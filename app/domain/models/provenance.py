"""Domain model -- per-data-point provenance tracking.

Every data point in agent output can be traced to its source:
LLM inference, web search, RAG retrieval, yfinance, SEC EDGAR,
user-uploaded documents, or computed from other fields.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class DataSource:
    source_type: str  # "llm", "web_search", "rag", "yfinance", "edgar", "user_upload", "computed"
    source_id: str  # URL, document_id, API endpoint, agent_id
    retrieved_at: str = ""
    confidence: float = 1.0
    snippet: str = ""  # relevant excerpt from source

    def __post_init__(self) -> None:
        if not self.retrieved_at:
            self.retrieved_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "retrieved_at": self.retrieved_at,
            "confidence": self.confidence,
            "snippet": self.snippet,
        }


@dataclass
class ProvenanceRecord:
    field_path: str  # e.g., "revenue_growth_rate", "dcf.wacc"
    value: str  # the actual value
    sources: list[DataSource] = field(default_factory=list)
    derived_from: list[str] = field(default_factory=list)  # other field_paths this was computed from

    def to_dict(self) -> dict:
        return {
            "field_path": self.field_path,
            "value": self.value,
            "sources": [s.to_dict() for s in self.sources],
            "derived_from": self.derived_from,
        }
