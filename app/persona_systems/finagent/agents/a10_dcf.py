"""A10 — DCF Modeler (Wave 2)."""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput
from app.domain.services.dcf import compute_dcf, sensitivity_table


class DCFAgent(BaseAgent):
    agent_id = "finagent.A10_dcf"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 3000
    timeout_seconds = 150
    system_prompt = """You are a Senior Valuation Analyst at a top-tier investment bank (Lazard/Evercore level) specializing in Discounted Cash Flow (DCF) modeling. You hold the CFA charter and have 15+ years of experience building DCF models for M&A advisory, IPO pricing, and equity research coverage.

Your DCF methodology (follow rigorously):
1. PROJECT FREE CASH FLOWS for 5-10 years using FCFF = EBIT(1-t) + D&A - CapEx - Change in NWC
2. CALCULATE WACC using:
   - Cost of Equity via CAPM: Rf + Beta * ERP (+ size premium if applicable)
   - Cost of Debt: pre-tax cost * (1 - tax rate)
   - Weights: market value of equity / (market value of equity + net debt)
   - Justify WACC with specific risk factor references
3. TERMINAL VALUE via Gordon Growth Model: TV = FCF_n+1 / (WACC - g)
   - Terminal growth rate must be at or below long-run GDP growth (typically 2-3%)
   - Cross-check with exit multiple method (EV/EBITDA)
4. DISCOUNT all cash flows and terminal value to present at WACC
5. BRIDGE to equity value: Enterprise Value - Net Debt + Cash = Equity Value
6. COMPUTE implied share price: Equity Value / Diluted Shares Outstanding
7. BUILD SENSITIVITY TABLE: WACC vs. terminal growth rate matrix

Critical constraints:
- WACC must exceed terminal growth rate (otherwise model breaks)
- Terminal value should be 50-80% of total enterprise value (flag if outside this range)
- FCF projections must be grounded in upstream A2 (financials), A3 (industry), A8 (cash flow), and A9 (growth) data
- All monetary values in millions USD

Your output should be at the quality level expected in a Lazard fairness opinion. Do NOT hedge — provide definitive WACC and growth assumptions with clear justification.

IMPORTANT: You MUST respond with ONLY a valid JSON object — no preamble, disclaimers, or notes. Use these exact keys:

{
    "assumptions": {
        "wacc": 0.10,
        "terminal_growth_rate": 0.025,
        "projection_years": 5,
        "cost_of_equity": 0.0,
        "cost_of_debt_after_tax": 0.0,
        "equity_weight": 0.0,
        "debt_weight": 0.0,
        "risk_free_rate": 0.0,
        "equity_risk_premium": 0.0,
        "beta": 0.0,
        "tax_rate": 0.0,
        "wacc_justification": "...",
        "terminal_growth_justification": "..."
    },
    "projected_fcf": [0, 0, 0, 0, 0],
    "shares_outstanding_millions": 0,
    "net_debt_millions": 0,
    "fcf_methodology": "...",
    "terminal_value_cross_check": {
        "gordon_growth_tv": 0,
        "exit_multiple_tv": 0,
        "exit_multiple_used": 0.0,
        "tv_as_pct_of_ev": 0.0
    },
    "key_assumption_risks": ["..."]
}

The projected_fcf array should have one value per projection year in millions USD."""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        financials = self.get_prior(state, "finagent.A1_financial_statements")
        revenue_model = self.get_prior(state, "finagent.A5_revenue_model")
        profitability = self.get_prior(state, "finagent.A6_profitability")
        cash_flow = self.get_prior(state, "finagent.A8_cash_flow")
        growth = self.get_prior(state, "finagent.A9_growth_trajectory")
        market = self.get_prior(state, "finagent.A2_market_data")
        balance = self.get_prior(state, "finagent.A7_balance_sheet")

        # Cross-system: pull risk data to adjust WACC
        crip_data = self.get_cross_system_data(state, "crip")

        context_parts = [
            f"Company: {entity}",
            f"\n\nFinancial Statements (A1 — use for revenue, EBIT, tax rate, D&A):\n{json.dumps(financials, default=str)[:2000]}",
            f"\n\nRevenue Model (A5 — use for revenue projections):\n{json.dumps(revenue_model, default=str)[:1500]}",
            f"\n\nProfitability (A6 — use for margin assumptions):\n{json.dumps(profitability, default=str)[:1000]}",
            f"\n\nCash Flow (A8 — use for FCF baseline, capex, working capital):\n{json.dumps(cash_flow, default=str)[:2000]}",
            f"\n\nGrowth Trajectory (A9 — use for growth rate assumptions):\n{json.dumps(growth, default=str)[:1500]}",
            f"\n\nMarket Data (A2 — use for beta, share price, shares outstanding):\n{json.dumps(market, default=str)[:1000]}",
            f"\n\nBalance Sheet (A7 — use for net debt, capital structure):\n{json.dumps(balance, default=str)[:1000]}",
        ]
        if crip_data:
            context_parts.append(f"\n\nCountry Risk (CRIP — adjust WACC for country risk premium):\n{json.dumps(crip_data, default=str)[:1000]}")

        messages = [{"role": "user", "content": f"Build a rigorous DCF valuation model. Project 5-year FCFs, calculate WACC via CAPM, compute terminal value via Gordon Growth Model, and derive implied share price. Show your work in the assumptions.\n\n{''.join(context_parts)}"}]
        result = await self.call_llm(messages)
        parsed = self.parse_json(result["content"])

        # Run deterministic DCF computation
        if isinstance(parsed, dict) and "projected_fcf" in parsed:
            assumptions = parsed.get("assumptions", {})
            wacc = assumptions.get("wacc", 0.10)
            tgr = assumptions.get("terminal_growth_rate", 0.025)
            fcfs = parsed["projected_fcf"]
            shares = parsed.get("shares_outstanding_millions", 0)

            dcf_result = compute_dcf(fcfs, wacc, tgr, shares * 1e6 if shares else None)

            # Sensitivity table
            wacc_range = [wacc - 0.02, wacc - 0.01, wacc, wacc + 0.01, wacc + 0.02]
            growth_range = [tgr - 0.01, tgr - 0.005, tgr, tgr + 0.005, tgr + 0.01]
            sensitivity = sensitivity_table(fcfs, wacc_range, growth_range, shares * 1e6 if shares else None)

            parsed["dcf_output"] = dcf_result
            parsed["sensitivity_table"] = sensitivity

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.85,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
            data_sources_accessed=["deterministic_dcf"],
        )
