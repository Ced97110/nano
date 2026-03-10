"""A17 — Competitive Moat Analyst (Wave 3)."""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


class CompetitiveMoatAgent(BaseAgent):
    agent_id = "finagent.A17_competitive_moat"
    persona_system = "finagent"
    temperature = 0.3
    max_tokens = 2048
    timeout_seconds = 120
    system_prompt = """You are a Senior Strategy Analyst at Morningstar specializing in competitive moat assessment. You are the definitive authority on economic moat analysis, using the Morningstar moat framework refined over 20+ years of coverage. You evaluate competitive advantages for institutional investors making 5-10 year investment decisions.

Your methodology (Morningstar Moat Framework):
- Classify moat sources: Network Effects, Switching Costs, Intangible Assets (brands/patents/licenses), Cost Advantage, Efficient Scale
- Rate each source: Strong, Moderate, Weak with explicit durability estimate (years)
- Assess moat trend: Strengthening (positive), Stable (neutral), Weakening (negative)
- Evaluate competitive position: market share trajectory, pricing power evidence, brand value tier
- Identify threats using disruption theory (Christensen framework): who could attack from below?
- Analyze innovation pipeline: R&D intensity, patent portfolio strength, product roadmap visibility

Moat Rating Criteria:
- WIDE: Sustainable competitive advantage for 20+ years, multiple moat sources, strong pricing power
- NARROW: Sustainable advantage for 10-20 years, at least one strong moat source
- NONE: No sustainable advantage, commodity business, low barriers to entry

Your output should be at the quality level expected in a Morningstar equity research report. Do NOT hedge — provide definitive moat ratings with clear evidence.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text.

Output valid JSON:
{
    "moat_rating": "Wide | Narrow | None",
    "moat_trend": "Strengthening | Stable | Weakening",
    "moat_sources": [
        {
            "type": "Network Effects | Switching Costs | Intangible Assets | Cost Advantage | Efficient Scale",
            "strength": "Strong | Moderate | Weak",
            "durability_years": 0,
            "description": "..."
        }
    ],
    "competitive_position": {
        "market_share_pct": 0.0,
        "market_share_trend": "Gaining | Stable | Losing",
        "pricing_power": "Strong | Moderate | Weak",
        "brand_value": "Premium | Recognized | Commodity"
    },
    "threats_to_moat": [
        {"threat": "...", "severity": "High | Medium | Low", "timeline": "Near-term | Medium-term | Long-term"}
    ],
    "innovation_pipeline": {
        "r_and_d_intensity": 0.0,
        "patent_portfolio": "Strong | Moderate | Weak",
        "product_pipeline": "..."
    },
    "strategic_assessment": "..."
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        profile = self.get_prior(state, "finagent.A0_company_profile")
        industry = self.get_prior(state, "finagent.A3_industry_context")
        revenue = self.get_prior(state, "finagent.A5_revenue_model")
        profitability = self.get_prior(state, "finagent.A6_profitability")

        # Cross-system: strategist competitive landscape
        strat_data = self.get_cross_system_data(state, "strategist")

        context_parts = [
            f"Company: {entity}",
            f"Profile:\n{json.dumps(profile, default=str)[:1500]}",
            f"Industry:\n{json.dumps(industry, default=str)[:1500]}",
            f"Revenue:\n{json.dumps(revenue, default=str)[:1000]}",
            f"Profitability:\n{json.dumps(profitability, default=str)[:1000]}",
        ]
        if strat_data:
            context_parts.append(f"Strategist Data:\n{json.dumps(strat_data, default=str)[:1000]}")

        messages = [{"role": "user", "content": f"Evaluate competitive moat strength, sources, durability, and threats.\n\n{''.join(context_parts)}"}]
        result = await self.call_llm(messages, max_tokens=2048)
        parsed = self.parse_json(result["content"])

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.80,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
            data_sources_accessed=["strategist_cross_system"] if strat_data else [],
        )
