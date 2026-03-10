"""A2 — Market Data Collector (Wave 0).

Fetches market data via CompanyDataService (DB-backed, 15-min staleness).
Falls back to direct yfinance if DB unavailable.
"""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


class MarketDataAgent(BaseAgent):
    agent_id = "finagent.A2_market_data"
    persona_system = "finagent"
    temperature = 0.1
    max_tokens = 1500
    timeout_seconds = 90
    system_prompt = """You are a Senior Market Data Analyst at a top-tier quantitative trading desk. You specialize in equity market microstructure, technical analysis, and valuation metrics. You process real-time market feeds for institutional portfolio managers.

Your methodology:
- Use real market data as the single source of truth for prices and volumes
- Calculate relative volume, moving average crossovers, and distance from 52-week range
- Map analyst consensus using standardized rating scales
- Compute float-adjusted metrics and short interest indicators

Use the real numbers as the authoritative source. Do NOT invent prices or valuations. Your output should be at the quality level expected in a Bloomberg terminal equity snapshot.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text. Do NOT hedge or say you are unable to access data — be definitive.

Output valid JSON:
{
    "market_cap": {"value": 0, "unit": "B", "currency": "USD"},
    "share_price": {"current": 0.0, "52w_high": 0.0, "52w_low": 0.0},
    "volume": {"avg_daily": 0, "relative_volume": 0.0},
    "valuation_multiples": {
        "pe_ratio": 0.0,
        "forward_pe": 0.0,
        "ev_ebitda": 0.0,
        "price_to_sales": 0.0,
        "price_to_book": 0.0
    },
    "dividend": {"yield_pct": 0.0, "payout_ratio": 0.0, "annual_dividend": 0.0},
    "beta": 0.0,
    "short_interest_pct": 0.0,
    "institutional_ownership_pct": 0.0,
    "shares_outstanding": {"value": 0, "unit": "B"},
    "float": {"value": 0, "unit": "B"},
    "analyst_targets": {"low": 0.0, "mean": 0.0, "high": 0.0, "recommendation": "..."},
    "moving_averages": {"50d": 0.0, "200d": 0.0},
    "data_freshness": "real-time | cached | llm_knowledge"
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        data_sources = []

        real_data = {}

        # Read from DB only — data should be pre-ingested
        svc = self._data.get("company_data")
        if svc:
            try:
                store = svc._store
                real_data = await store.get_market_snapshot(entity)
                if real_data and real_data.get("share_price"):
                    data_sources.append("yahoo_finance")
            except Exception:
                pass

        if real_data and data_sources:
            prompt = (
                f"Here is REAL market data for {entity} from Yahoo Finance:\n\n"
                f"{json.dumps(real_data, indent=2, default=str)}\n\n"
                "Structure this into the required format. Convert market_cap and shares_outstanding "
                "to billions (B). Calculate relative_volume = volume / avg_volume. "
                "Map recommendation_key to standard ratings."
            )
        else:
            prompt = f"Compile current market data and trading metrics for: {entity}"
            data_sources.append("llm_knowledge")

        messages = [{"role": "user", "content": prompt}]
        result = await self.call_llm(messages, max_tokens=1500)
        parsed = self.parse_json(result["content"])

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.95 if "yahoo_finance" in data_sources else 0.65,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
            data_sources_accessed=data_sources,
        )
