"""A22 — LBO Model Agent (Wave 5).

Leveraged buyout analysis: entry multiple, debt structure, exit assumptions,
5-year hold period model, IRR sensitivity, and sources of value creation.
"""

import json
import time

import structlog

from app.domain.entities.agent_output import AgentOutput
from app.persona_systems.base_agent import BaseAgent

logger = structlog.get_logger(__name__)


class LBOModelAgent(BaseAgent):
    agent_id = "finagent.A22_lbo_model"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 3000
    timeout_seconds = 150
    system_prompt = """You are a Senior Private Equity Associate at a top-tier buyout firm with deep
expertise in LBO modeling, capital structure optimization, and value creation planning.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers,
notes, or explanatory text before or after the JSON. Do NOT say you are unable
to access data — use your best knowledge and any provided context.

{
    "entry_assumptions": {
        "entry_ev_B": 0.0,
        "entry_ev_ebitda": 0.0,
        "entry_equity_B": 0.0,
        "ltm_ebitda_B": 0.0,
        "ltm_revenue_B": 0.0,
        "transaction_fees_pct": 0.0,
        "premium_to_current_pct": 0.0
    },
    "debt_structure": {
        "total_leverage_x": 0.0,
        "senior_secured": {
            "amount_B": 0.0,
            "leverage_x": 0.0,
            "interest_rate_pct": 0.0,
            "maturity_years": 0,
            "amortization_pct": 0.0
        },
        "second_lien": {
            "amount_B": 0.0,
            "leverage_x": 0.0,
            "interest_rate_pct": 0.0,
            "maturity_years": 0
        },
        "mezzanine": {
            "amount_B": 0.0,
            "leverage_x": 0.0,
            "interest_rate_pct": 0.0,
            "pik_rate_pct": 0.0
        },
        "equity_contribution_B": 0.0,
        "equity_pct_of_total": 0.0
    },
    "operating_projections": {
        "year_0": {"revenue_B": 0.0, "ebitda_B": 0.0, "ebitda_margin_pct": 0.0, "capex_B": 0.0, "fcf_B": 0.0},
        "year_1": {"revenue_B": 0.0, "ebitda_B": 0.0, "ebitda_margin_pct": 0.0, "capex_B": 0.0, "fcf_B": 0.0},
        "year_2": {"revenue_B": 0.0, "ebitda_B": 0.0, "ebitda_margin_pct": 0.0, "capex_B": 0.0, "fcf_B": 0.0},
        "year_3": {"revenue_B": 0.0, "ebitda_B": 0.0, "ebitda_margin_pct": 0.0, "capex_B": 0.0, "fcf_B": 0.0},
        "year_4": {"revenue_B": 0.0, "ebitda_B": 0.0, "ebitda_margin_pct": 0.0, "capex_B": 0.0, "fcf_B": 0.0},
        "year_5": {"revenue_B": 0.0, "ebitda_B": 0.0, "ebitda_margin_pct": 0.0, "capex_B": 0.0, "fcf_B": 0.0}
    },
    "exit_assumptions": {
        "exit_year": 5,
        "exit_ev_ebitda": 0.0,
        "exit_ev_B": 0.0,
        "net_debt_at_exit_B": 0.0,
        "exit_equity_B": 0.0
    },
    "returns": {
        "moic": 0.0,
        "irr_pct": 0.0,
        "equity_invested_B": 0.0,
        "equity_returned_B": 0.0,
        "holding_period_years": 5
    },
    "value_creation_bridge": {
        "ebitda_growth_pct_of_total": 0.0,
        "multiple_expansion_pct_of_total": 0.0,
        "debt_paydown_pct_of_total": 0.0,
        "total_value_created_B": 0.0
    },
    "irr_sensitivity": {
        "exit_multiple_range": [0.0, 0.0, 0.0, 0.0, 0.0],
        "ebitda_growth_range": [0.0, 0.0, 0.0],
        "irr_matrix": [
            [0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 0.0]
        ]
    },
    "key_risks": ["..."],
    "lbo_feasibility": "Attractive | Feasible | Marginal | Not Feasible",
    "lbo_thesis": "..."
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")

        financials = self.get_prior(state, "finagent.A1_financial_statements")
        dcf = self.get_prior(state, "finagent.A10_dcf")
        comps = self.get_prior(state, "finagent.A11_comps")
        cash_flow = self.get_prior(state, "finagent.A8_cash_flow")
        balance = self.get_prior(state, "finagent.A7_balance_sheet")
        market = self.get_prior(state, "finagent.A2_market_data")

        context_parts = [
            f"Company: {entity}",
            f"\n\nFinancials:\n{json.dumps(financials, default=str)[:2000]}",
            f"\n\nDCF Analysis:\n{json.dumps(dcf, default=str)[:2000]}",
            f"\n\nComparable Companies:\n{json.dumps(comps, default=str)[:1500]}",
            f"\n\nCash Flow:\n{json.dumps(cash_flow, default=str)[:1500]}",
            f"\n\nBalance Sheet:\n{json.dumps(balance, default=str)[:1000]}",
            f"\n\nMarket Data:\n{json.dumps(market, default=str)[:1000]}",
        ]

        messages = [
            {
                "role": "user",
                "content": (
                    "Build a comprehensive LBO model with 5-year projections, debt structure, "
                    "exit assumptions, IRR sensitivity, and value creation bridge.\n\n"
                    + "".join(context_parts)
                ),
            }
        ]

        try:
            result = await self.call_llm(messages, max_tokens=3000, temperature=0.3)
            parsed = self.parse_json(result["content"])
            return AgentOutput(
                agent_id=self.agent_id,
                output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
                confidence_score=0.78,
                tokens_used=result.get("tokens_used", 0),
                cost_usd=result.get("cost_usd", 0.0),
                latency_ms=int((time.monotonic() - t0) * 1000),
                data_sources_accessed=[],
            )
        except Exception as exc:
            logger.error("finagent.A22_lbo_model.failed", error=str(exc))
            return AgentOutput(
                agent_id=self.agent_id,
                output={"error": str(exc)},
                confidence_score=0.0,
                tokens_used=0,
                latency_ms=int((time.monotonic() - t0) * 1000),
                error=str(exc),
            )
