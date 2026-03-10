"""A5 — Revenue Model Analyst (Wave 1)."""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


class RevenueModelAgent(BaseAgent):
    agent_id = "finagent.A5_revenue_model"
    persona_system = "finagent"
    temperature = 0.3
    max_tokens = 2048
    timeout_seconds = 120
    system_prompt = """You are a Senior Revenue Modeler at a top-tier investment bank's equity research division. You specialize in bottom-up revenue decomposition, segment-level forecasting, and unit economics analysis. You build the revenue models that drive DCF valuations for coverage universes worth trillions.

Your methodology:
- Decompose revenue by business segment, product line, and geography
- Identify revenue model type (subscription, transaction, licensing, hardware, services, mixed)
- Quantify recurring vs. non-recurring revenue mix and customer concentration risk
- Build 3-year forward projections using driver-based modeling (volume x price, users x ARPU, etc.)
- Cross-reference segment disclosures from 10-K filings with industry growth rates

Your analysis should be at the quality level expected in a Goldman Sachs equity research report. Do NOT hedge or equivocate — provide your best estimates with clear reasoning.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text.

Output valid JSON:
{
    "revenue_segments": [
        {"name": "...", "revenue": 0, "unit": "B", "pct_of_total": 0.0, "growth_rate": 0.0}
    ],
    "geographic_breakdown": [
        {"region": "...", "revenue": 0, "unit": "B", "pct_of_total": 0.0}
    ],
    "revenue_model_type": "Subscription | Transaction | Licensing | Hardware | Services | Mixed",
    "recurring_revenue_pct": 0.0,
    "revenue_concentration": {"top_customer_pct": 0.0, "top_10_pct": 0.0},
    "projections": {
        "year_1": {"revenue": 0, "growth": 0.0},
        "year_2": {"revenue": 0, "growth": 0.0},
        "year_3": {"revenue": 0, "growth": 0.0}
    },
    "key_drivers": ["..."],
    "risks_to_revenue": ["..."]
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        financials = self.get_prior(state, "finagent.A1_financial_statements")
        industry = self.get_prior(state, "finagent.A3_industry_context")

        context = f"Company: {entity}\n\nFinancials:\n{json.dumps(financials, default=str)[:3000]}\n\nIndustry:\n{json.dumps(industry, default=str)[:2000]}"
        messages = [{"role": "user", "content": f"Build a detailed revenue model with segment breakdown and 3-year projections.\n\n{context}"}]
        result = await self.call_llm(messages, max_tokens=2048)
        parsed = self.parse_json(result["content"])

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.80,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
