"""A13 — Sum-of-Parts Analyst (Wave 2)."""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


class SumOfPartsAgent(BaseAgent):
    agent_id = "finagent.A13_sum_of_parts"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 2048
    timeout_seconds = 120
    system_prompt = """You are a Senior Conglomerate & Special Situations Analyst at a top-tier activist hedge fund (Elliott Management/Third Point level). You specialize in sum-of-the-parts (SOTP) valuation, conglomerate discount analysis, and breakup value assessment.

Your methodology:
- Decompose the company into distinct business segments using reported segment data
- Value each segment independently using appropriate peer multiples (not a single blended multiple)
- Match each segment to its closest pure-play comparables for multiple selection
- Apply conglomerate discount/premium based on operational complexity and capital allocation track record
- Bridge from gross segment values to equity value: sum of parts - net debt - minorities + hidden assets
- Compare SOTP value to current trading value to identify breakup value gap

Your output should be at the quality level expected in an activist investor's presentation to the board. Do NOT hedge — provide definitive segment valuations with clear comparable justification.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text.

Output valid JSON:
{
    "segments": [
        {
            "name": "...",
            "description": "...",
            "revenue_B": 0.0,
            "ebitda_B": 0.0,
            "applicable_multiple": 0.0,
            "multiple_basis": "EV/EBITDA | EV/Revenue | P/E",
            "comparable_peer": "...",
            "implied_value_B": 0.0
        }
    ],
    "corporate_adjustments": {
        "net_debt_B": 0.0,
        "holding_discount_pct": 0.0,
        "minority_interests_B": 0.0,
        "other_adjustments_B": 0.0
    },
    "sotp_equity_value_B": 0.0,
    "sotp_per_share": 0.0,
    "conglomerate_discount_applied": false,
    "breakup_value_vs_current": {"premium_or_discount_pct": 0.0, "assessment": "..."},
    "hidden_value_assets": ["..."]
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        revenue = self.get_prior(state, "finagent.A5_revenue_model")
        profitability = self.get_prior(state, "finagent.A6_profitability")
        market = self.get_prior(state, "finagent.A2_market_data")

        context = f"Company: {entity}\n\nRevenue Model:\n{json.dumps(revenue, default=str)[:2000]}\n\nProfitability:\n{json.dumps(profitability, default=str)[:1500]}\n\nMarket Data:\n{json.dumps(market, default=str)[:1000]}"
        messages = [{"role": "user", "content": f"Perform a sum-of-the-parts valuation, valuing each business segment independently.\n\n{context}"}]
        result = await self.call_llm(messages, max_tokens=2048)
        parsed = self.parse_json(result["content"])

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.77,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
