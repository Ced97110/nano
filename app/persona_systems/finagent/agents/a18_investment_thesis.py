"""A18 — Investment Thesis Synthesizer (Wave 4)."""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


class InvestmentThesisAgent(BaseAgent):
    agent_id = "finagent.A18_investment_thesis"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 3500
    timeout_seconds = 180
    system_prompt = """You are a Senior Portfolio Manager at a top-tier fundamental equity fund (Fidelity/Capital Group/T. Rowe Price level) with 20+ years of experience managing $10B+ portfolios. You are the final decision-maker who synthesizes all research into a clear, actionable investment thesis.

Your methodology:
- VALUATION SYNTHESIS: Blend DCF, comps, precedent transactions, and SOTP using methodology-appropriate weights
- BULL/BASE/BEAR FRAMEWORK: Assign explicit probabilities (must sum to 100%) with specific triggers for each scenario
- RECOMMENDATION FRAMEWORK: Strong Buy (>30% upside, high conviction), Buy (15-30% upside), Hold (0-15% upside), Sell (0 to -15%), Strong Sell (>15% downside)
- CATALYST MAPPING: Identify specific events with timeline and directional impact
- POSITION SIZING: Full/Half/Quarter based on conviction and risk/reward asymmetry
- TIME HORIZON: Specific (e.g., "12-18 months") with milestone checkpoints

Critical standards:
- Target price must be derivable from your valuation summary (show the weighted blend)
- Bull and bear cases must be genuinely balanced — not token opposition
- Each case must reference specific upstream agent data points (not generic statements)
- Position sizing must reflect the risk/reward skew, not just the upside

Your output should be at the quality level expected in a Fidelity investment committee presentation. Do NOT hedge or equivocate — take a clear stance with conviction.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text.

Output valid JSON:
{
    "recommendation": "Strong Buy | Buy | Hold | Sell | Strong Sell",
    "conviction_level": "High | Medium | Low",
    "target_price": 0.0,
    "current_price": 0.0,
    "upside_pct": 0.0,
    "investment_thesis": "...",
    "bull_case": {
        "target_price": 0.0,
        "probability_pct": 0,
        "key_drivers": ["..."],
        "narrative": "..."
    },
    "base_case": {
        "target_price": 0.0,
        "probability_pct": 0,
        "key_drivers": ["..."],
        "narrative": "..."
    },
    "bear_case": {
        "target_price": 0.0,
        "probability_pct": 0,
        "key_drivers": ["..."],
        "narrative": "..."
    },
    "valuation_summary": {
        "dcf_implied": 0.0,
        "comps_implied": 0.0,
        "precedent_implied": 0.0,
        "sotp_implied": 0.0,
        "blended_fair_value": 0.0
    },
    "key_metrics_to_watch": ["..."],
    "catalysts": [
        {"event": "...", "timeline": "...", "impact": "Positive | Negative"}
    ],
    "position_sizing": "Full | Half | Quarter",
    "time_horizon": "..."
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        outputs = state.get("agent_outputs", {})
        data_sources = []

        # Gather key outputs from all prior waves
        summary_parts = [f"Company: {entity}\n"]
        key_agents = [
            "finagent.A0_company_profile", "finagent.A2_market_data",
            "finagent.A5_revenue_model", "finagent.A6_profitability",
            "finagent.A8_cash_flow", "finagent.A9_growth_trajectory",
            "finagent.A10_dcf", "finagent.A11_comps",
            "finagent.A12_precedent_transactions", "finagent.A13_sum_of_parts",
            "finagent.A14_risk_assessment", "finagent.A17_competitive_moat",
        ]
        for aid in key_agents:
            data = outputs.get(aid, {})
            if data:
                summary_parts.append(f"## {aid}\n{json.dumps(data, default=str)[:1200]}\n")
                self.track_provenance("investment_thesis", entity, "computed", aid, confidence=0.90)

        # Web search: latest market developments and analyst opinions
        web_results = await self.search_web(
            f"{entity} investment thesis analyst rating target price 2025", max_results=5
        )
        if web_results:
            web_context = "\n".join(
                f"- [{r['title']}]: {r['content'][:200]}" for r in web_results
            )
            summary_parts.append(f"\n## Recent analyst and market intelligence (web)\n{web_context}\n")
            data_sources.append("web_search")
            self.track_web_provenance("investment_thesis", entity, web_results)

        messages = [{"role": "user", "content": f"Synthesize a complete investment thesis with bull/base/bear cases and a clear recommendation.\n\n{''.join(summary_parts)}"}]
        result = await self.call_llm(messages, max_tokens=3000, temperature=0.2)
        parsed = self.parse_json(result["content"])
        self.track_provenance("investment_thesis", entity, "llm", self.agent_id, confidence=0.85)

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.85,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
            data_sources_accessed=data_sources,
            provenance=self.get_provenance(),
        )
