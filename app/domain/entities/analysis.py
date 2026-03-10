"""Domain entities for analysis requests and results."""

from dataclasses import dataclass, field


@dataclass
class AnalysisRequest:
    """Represents a request to run a persona system pipeline."""
    request_id: str
    persona_system: str
    ticker: str = ""
    query: str = ""
    country: str = ""
    mode: str = "express"  # "express" | "analyst" | "review"
    analysis_type: str = "full"  # "full" | "quick" | "ma_focused" | "credit_focused" | "valuation_deep"

    @property
    def intent(self) -> dict:
        return {
            "ticker": self.ticker,
            "query": self.query,
            "entities_detected": {
                "companies": [self.ticker] if self.ticker else [],
                "countries": [self.country] if self.country else [],
            },
        }

    @property
    def entity(self) -> str:
        if self.ticker:
            return self.ticker.upper()
        if self.country:
            return self.country.upper()
        return "UNKNOWN"


@dataclass
class AnalysisResult:
    """The final output of a persona system pipeline."""
    request_id: str
    system_id: str
    result: dict = field(default_factory=dict)
    cached: bool = False
