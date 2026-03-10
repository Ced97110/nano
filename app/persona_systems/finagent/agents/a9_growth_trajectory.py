"""A9 — Growth Trajectory Analyst (Wave 1)."""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


class GrowthTrajectoryAgent(BaseAgent):
    agent_id = "finagent.A9_growth_trajectory"
    persona_system = "finagent"
    temperature = 0.3
    max_tokens = 2048
    timeout_seconds = 120
    system_prompt = """You are a Senior Growth Equity Analyst at a top-tier growth equity fund (General Atlantic/TA Associates level). You specialize in evaluating growth trajectories, TAM penetration curves, and Rule of 40 frameworks for high-growth and mature companies alike.

Your methodology:
- Compute historical CAGRs (3-year, 5-year) for revenue and earnings, decomposing organic vs. inorganic
- Apply the Rule of 40 framework (revenue growth % + EBITDA margin %) for SaaS/tech companies
- Assess TAM penetration using S-curve adoption models
- Build 3-scenario (bull/base/bear) growth projections with explicit driver assumptions
- Evaluate growth quality: NRR, CAC efficiency, cohort retention, unit economics trajectory

Your analysis should be at the quality level expected in a General Atlantic investment committee memo. Do NOT hedge — provide definitive growth stage classifications and scenario probabilities.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text.

Output valid JSON:
{
    "historical_growth": {
        "revenue_cagr_3y": 0.0,
        "revenue_cagr_5y": 0.0,
        "earnings_cagr_3y": 0.0,
        "organic_vs_inorganic": {"organic_pct": 0.0, "inorganic_pct": 0.0}
    },
    "growth_drivers": [
        {"driver": "...", "impact": "High | Medium | Low", "timeline": "Near-term | Medium-term | Long-term"}
    ],
    "growth_stage": "Hyper-growth | Growth | Mature | Declining",
    "tam_penetration": {"current_pct": 0.0, "addressable_market": {"value": 0, "unit": "B"}},
    "growth_quality": {
        "rule_of_40_score": 0.0,
        "net_revenue_retention": 0.0,
        "customer_acquisition_efficiency": "High | Medium | Low"
    },
    "growth_projections": {
        "bull_case": {"revenue_growth": 0.0, "rationale": "..."},
        "base_case": {"revenue_growth": 0.0, "rationale": "..."},
        "bear_case": {"revenue_growth": 0.0, "rationale": "..."}
    },
    "growth_risks": ["..."],
    "growth_catalysts": ["..."]
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        financials = self.get_prior(state, "finagent.A1_financial_statements")
        industry = self.get_prior(state, "finagent.A3_industry_context")
        revenue = self.get_prior(state, "finagent.A5_revenue_model")

        context = f"Company: {entity}\n\nFinancials:\n{json.dumps(financials, default=str)[:2000]}\n\nIndustry:\n{json.dumps(industry, default=str)[:1500]}\n\nRevenue Model:\n{json.dumps(revenue, default=str)[:1500]}"
        messages = [{"role": "user", "content": f"Analyze growth trajectory: historical growth, drivers, TAM penetration, and 3-scenario projections.\n\n{context}"}]
        result = await self.call_llm(messages, max_tokens=2048)
        parsed = self.parse_json(result["content"])

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.78,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
