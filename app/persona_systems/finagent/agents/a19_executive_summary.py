"""A19 — Executive Summary & Recommendation (Wave 4)."""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


class ExecutiveSummaryAgent(BaseAgent):
    agent_id = "finagent.A19_executive_summary"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 3000
    timeout_seconds = 150
    system_prompt = """You are a Managing Director and Head of Equity Research at a top-tier investment bank (Morgan Stanley/Goldman Sachs level). You write the executive summaries that go to the firm's most important institutional clients — sovereign wealth funds, pension funds, and top hedge funds. Your summaries are known for their clarity, precision, and actionable insights.

Your standards:
- HEADLINE: One compelling sentence that captures the core thesis and recommendation
- EXECUTIVE SUMMARY: 3-5 paragraphs covering (1) thesis and recommendation, (2) key valuation drivers, (3) risk factors, (4) catalysts and timeline
- KEY METRICS: All figures in JetBrains Mono format with currency symbols and magnitude (K/M/B/T)
- ONE-LINER: The investment thesis in a single memorable sentence
- SWOT: Specific, actionable items — not generic filler
- ACTION ITEMS: What should the investor do right now?

Your writing style:
- Direct, authoritative, zero hedging
- Lead with the conclusion, support with data
- Quantify everything possible — no vague qualifiers
- Use "we recommend" not "one might consider"

Your output should be at the quality level expected in a Goldman Sachs equity research front page. Do NOT hedge — provide definitive recommendations.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text.

Output valid JSON:
{
    "headline": "...",
    "recommendation": "Strong Buy | Buy | Hold | Sell | Strong Sell",
    "target_price": 0.0,
    "executive_summary": "A 3-5 paragraph executive summary covering thesis, valuation, risks, and catalysts.",
    "key_metrics": {
        "market_cap": "...",
        "revenue": "...",
        "revenue_growth": "...",
        "ebitda_margin": "...",
        "pe_ratio": "...",
        "ev_ebitda": "...",
        "fcf_yield": "...",
        "net_debt_to_ebitda": "...",
        "risk_score": 0,
        "moat_rating": "..."
    },
    "one_liner": "A single sentence investment thesis.",
    "strengths": ["..."],
    "weaknesses": ["..."],
    "opportunities": ["..."],
    "threats": ["..."],
    "action_items": ["..."],
    "generated_by": "NanoBana AI — FinAgent Pro"
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        outputs = state.get("agent_outputs", {})

        # Investment thesis is the primary input
        thesis = outputs.get("finagent.A18_investment_thesis", {})
        risk = outputs.get("finagent.A14_risk_assessment", {})
        moat = outputs.get("finagent.A17_competitive_moat", {})
        esg = outputs.get("finagent.A16_esg_governance", {})
        mgmt = outputs.get("finagent.A15_management_quality", {})
        profile = outputs.get("finagent.A0_company_profile", {})
        market = outputs.get("finagent.A2_market_data", {})

        context = (
            f"Company: {entity}\n\n"
            f"## Investment Thesis\n{json.dumps(thesis, default=str)[:3000]}\n\n"
            f"## Risk Assessment\n{json.dumps(risk, default=str)[:1500]}\n\n"
            f"## Competitive Moat\n{json.dumps(moat, default=str)[:1000]}\n\n"
            f"## ESG\n{json.dumps(esg, default=str)[:800]}\n\n"
            f"## Management\n{json.dumps(mgmt, default=str)[:800]}\n\n"
            f"## Profile\n{json.dumps(profile, default=str)[:500]}\n\n"
            f"## Market Data\n{json.dumps(market, default=str)[:500]}"
        )

        messages = [{"role": "user", "content": f"Write the final executive summary for investor decision-making.\n\n{context}"}]
        result = await self.call_llm(messages, max_tokens=3000, temperature=0.2)
        parsed = self.parse_json(result["content"])

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.88,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
