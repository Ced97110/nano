"""Application-layer data transfer objects for analysis use cases."""

from dataclasses import dataclass, field


@dataclass
class AnalysisRequestDTO:
    persona_system: str
    ticker: str = ""
    query: str = ""
    country: str = ""
    mode: str = "express"  # "express" | "analyst" | "review"
    analysis_type: str = "full"  # "full" | "quick" | "ma_focused" | "credit_focused" | "valuation_deep"


@dataclass
class AnalysisResultDTO:
    request_id: str
    system_id: str
    result: dict = field(default_factory=dict)
    cached: bool = False
