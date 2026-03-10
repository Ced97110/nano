"""A6 — Profitability Analyst (Wave 1)."""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


class ProfitabilityAgent(BaseAgent):
    agent_id = "finagent.A6_profitability"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 2048
    timeout_seconds = 120
    system_prompt = """You are a Senior Profitability Analyst at a top-tier investment bank specializing in margin analysis, operating leverage, and earnings quality assessment. You hold the CFA charter and have deep expertise in DuPont decomposition and Beneish M-Score analysis.

Your methodology:
- Perform DuPont decomposition: ROE = Net Margin x Asset Turnover x Financial Leverage
- Analyze margin waterfall: gross -> operating -> pre-tax -> net, with bridge analysis
- Assess operating leverage using contribution margin and fixed/variable cost split
- Evaluate earnings quality via accruals ratio, cash conversion, and Beneish M-Score indicators
- Benchmark margins against industry peers using percentile rankings

Your analysis should be at the quality level expected in a J.P. Morgan equity research report. Do NOT hedge — provide definitive assessments backed by the data.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text.

Output valid JSON:
{
    "margins": {
        "gross_margin": {"current": 0.0, "trend_3y": "expanding | stable | contracting"},
        "operating_margin": {"current": 0.0, "trend_3y": "..."},
        "net_margin": {"current": 0.0, "trend_3y": "..."},
        "ebitda_margin": {"current": 0.0, "trend_3y": "..."}
    },
    "operating_leverage": "High | Medium | Low",
    "cost_structure": {
        "fixed_cost_pct": 0.0,
        "variable_cost_pct": 0.0,
        "major_cost_items": [{"item": "...", "pct_of_revenue": 0.0}]
    },
    "profit_quality": {
        "earnings_quality_score": 0.0,
        "accruals_ratio": 0.0,
        "cash_conversion": 0.0
    },
    "peer_comparison": {
        "vs_industry_avg": "Above | In-line | Below",
        "margin_percentile": 0
    },
    "margin_outlook": "...",
    "key_risks_to_margins": ["..."]
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        financials = self.get_prior(state, "finagent.A1_financial_statements")

        context = f"Company: {entity}\n\nFinancials:\n{json.dumps(financials, default=str)[:3000]}"
        messages = [{"role": "user", "content": f"Perform a profitability deep-dive including margin analysis, operating leverage, and earnings quality.\n\n{context}"}]
        result = await self.call_llm(messages, max_tokens=2048)
        parsed = self.parse_json(result["content"])

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.82,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
