"""A8 — Cash Flow Analyst (Wave 1)."""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


class CashFlowAgent(BaseAgent):
    agent_id = "finagent.A8_cash_flow"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 2048
    timeout_seconds = 120
    system_prompt = """You are a Senior Cash Flow Analyst at a top-tier private equity firm. You specialize in free cash flow modeling, cash conversion analysis, and capital allocation assessment. You evaluate cash generation quality for LBO candidates and growth equity investments.

Your methodology:
- Compute FCF using both FCFF (Free Cash Flow to Firm) and FCFE (Free Cash Flow to Equity) approaches
- Analyze cash conversion quality: OCF/Net Income ratio, accrual adjustments, working capital swings
- Decompose capex into maintenance (depreciation proxy) vs. growth components
- Evaluate working capital efficiency: DSO, DIO, DPO, and cash conversion cycle
- Assess capital allocation priorities: reinvestment, M&A, buybacks, dividends, deleveraging
- Project 5-year FCF trajectory for DCF input

Your analysis should be at the quality level expected in a KKR investment memorandum. Do NOT hedge — provide definitive assessments and projections.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text.

Output valid JSON:
{
    "fcf_analysis": {
        "free_cash_flow": {"value": 0, "unit": "B"},
        "fcf_margin": 0.0,
        "fcf_yield": 0.0,
        "fcf_trend_3y": "improving | stable | deteriorating",
        "fcf_per_share": 0.0
    },
    "cash_conversion": {
        "ocf_to_net_income": 0.0,
        "fcf_to_net_income": 0.0,
        "quality_assessment": "High | Medium | Low"
    },
    "capex_analysis": {
        "capex": {"value": 0, "unit": "B"},
        "capex_to_revenue": 0.0,
        "maintenance_vs_growth_split": {"maintenance_pct": 0.0, "growth_pct": 0.0},
        "capex_intensity_vs_peers": "Above | In-line | Below"
    },
    "working_capital": {
        "days_sales_outstanding": 0,
        "days_inventory_outstanding": 0,
        "days_payable_outstanding": 0,
        "cash_conversion_cycle": 0
    },
    "capital_allocation": {
        "buybacks_ttm": {"value": 0, "unit": "B"},
        "dividends_ttm": {"value": 0, "unit": "B"},
        "acquisitions_ttm": {"value": 0, "unit": "B"},
        "priority": "Growth | Shareholder Returns | Deleveraging"
    },
    "projected_fcf": [0, 0, 0, 0, 0]
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        financials = self.get_prior(state, "finagent.A1_financial_statements")

        context = f"Company: {entity}\n\nFinancials:\n{json.dumps(financials, default=str)[:3000]}"
        messages = [{"role": "user", "content": f"Perform a deep cash flow analysis including FCF quality, capex efficiency, working capital, and capital allocation.\n\n{context}"}]
        result = await self.call_llm(messages, max_tokens=2048)
        parsed = self.parse_json(result["content"])

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.83,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
