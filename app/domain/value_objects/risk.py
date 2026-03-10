"""Value objects for risk scoring."""

from enum import Enum


class RiskTier(Enum):
    STABLE = "STABLE"       # 0-25
    WATCH = "WATCH"         # 25-50
    ELEVATED = "ELEVATED"   # 50-75
    CRITICAL = "CRITICAL"   # 75-100

    @classmethod
    def from_score(cls, score: float) -> "RiskTier":
        if score < 25:
            return cls.STABLE
        if score < 50:
            return cls.WATCH
        if score < 75:
            return cls.ELEVATED
        return cls.CRITICAL
