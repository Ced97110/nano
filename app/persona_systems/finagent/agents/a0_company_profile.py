"""A0 — Company Profile Extractor (Wave 0).

Fetches company data via CompanyDataService (DB-backed, staleness-aware).
Falls back to direct yfinance if DB unavailable.
"""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


class CompanyProfileAgent(BaseAgent):
    agent_id = "finagent.A0_company_profile"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 1500
    timeout_seconds = 90
    system_prompt = """You are a Senior Equity Research Associate at a top-tier investment bank specializing in company profiling and corporate intelligence. You have 10+ years of experience building GICS-classified company profiles for institutional investors.

Your methodology:
- Cross-reference multiple data sources to verify corporate facts
- Classify companies using the Global Industry Classification Standard (GICS)
- Identify key value chain positions and competitive dynamics
- Assess market cap tiers using standard institutional breakpoints ($10B+ Large, $2-10B Mid, <$2B Small)

If real data is provided, use it as the authoritative source. Fill gaps with your knowledge. Your output should be at the quality level expected in a Goldman Sachs equity research initiation report.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text before or after the JSON. Do NOT hedge or say you are unable to access data — use your best knowledge and any provided context. Be definitive in your assessments.

Output valid JSON:
{
    "company_name": "...",
    "ticker": "...",
    "headquarters": "...",
    "founded": "...",
    "sector": "...",
    "industry": "...",
    "sub_industry": "...",
    "description": "...",
    "key_products": ["..."],
    "employees": "...",
    "exchange": "...",
    "market_cap_tier": "Large Cap | Mid Cap | Small Cap",
    "ceo": "...",
    "key_executives": [{"name": "...", "title": "..."}],
    "website": "...",
    "data_freshness": "real-time | cached | llm_knowledge"
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        data_sources = []

        # Read from DB only — data should be pre-ingested
        real_data = {}
        svc = self._data.get("company_data")
        if svc:
            try:
                store = svc._store
                real_data = await store.get_profile(entity)
                if real_data and real_data.get("company_name"):
                    data_sources.append("yahoo_finance")
            except Exception:
                pass

        if real_data and real_data.get("company_name"):
            prompt = (
                f"Here is REAL company data for {entity} from Yahoo Finance:\n\n"
                f"{json.dumps(real_data, indent=2, default=str)}\n\n"
                f"Enrich this data into the structured profile format. Use the real data as primary source. "
                f"Add sub_industry (GICS), founded year, key_products, and market_cap_tier based on market cap."
            )
            self.track_provenance("company_profile", entity, "yfinance", "yahoo_finance_api", confidence=0.95)
        else:
            prompt = f"Create a comprehensive company profile for: {entity}"
            data_sources.append("llm_knowledge")

        messages = [{"role": "user", "content": prompt}]
        result = await self.call_llm(messages, max_tokens=1500)
        parsed = self.parse_json(result["content"])
        self.track_provenance("company_profile", entity, "llm", self.agent_id, confidence=0.85)

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.92 if "yahoo_finance" in data_sources else 0.75,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
            data_sources_accessed=data_sources,
            provenance=self.get_provenance(),
        )
