"""A24 — Credit Analysis Agent (Wave 5).

Credit profile: rating assessment, debt capacity, covenant analysis,
interest coverage, leverage ratios, free cash flow coverage,
Altman Z-score, and Merton model concepts.
"""

import json
import time

import structlog

from app.domain.entities.agent_output import AgentOutput
from app.persona_systems.base_agent import BaseAgent

logger = structlog.get_logger(__name__)


class CreditAnalysisAgent(BaseAgent):
    agent_id = "finagent.A24_credit_analysis"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 3000
    timeout_seconds = 150
    system_prompt = """You are a Senior Credit Analyst at a top-tier rating agency with deep expertise
in credit risk assessment, debt capacity analysis, and covenant structuring.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers,
notes, or explanatory text before or after the JSON. Do NOT say you are unable
to access data — use your best knowledge and any provided context.

{
    "credit_rating_assessment": {
        "implied_rating": "AAA | AA+ | AA | AA- | A+ | A | A- | BBB+ | BBB | BBB- | BB+ | BB | BB- | B+ | B | B- | CCC+ | CCC | CCC-",
        "rating_outlook": "Positive | Stable | Negative | Watch",
        "current_agency_ratings": {
            "sp": "...",
            "moodys": "...",
            "fitch": "..."
        },
        "rating_drivers": ["..."],
        "rating_headwinds": ["..."]
    },
    "leverage_analysis": {
        "total_debt_B": 0.0,
        "net_debt_B": 0.0,
        "total_debt_to_ebitda": 0.0,
        "net_debt_to_ebitda": 0.0,
        "debt_to_equity": 0.0,
        "debt_to_total_capital": 0.0,
        "secured_vs_unsecured_pct": {"secured": 0.0, "unsecured": 0.0},
        "maturity_profile": {
            "weighted_avg_maturity_years": 0.0,
            "near_term_maturities_B": 0.0,
            "maturity_wall_year": 0
        }
    },
    "coverage_ratios": {
        "interest_coverage_ebitda": 0.0,
        "interest_coverage_ebit": 0.0,
        "fcf_to_debt": 0.0,
        "fcf_to_interest": 0.0,
        "fixed_charge_coverage": 0.0,
        "debt_service_coverage": 0.0
    },
    "debt_capacity": {
        "max_incremental_debt_B": 0.0,
        "target_leverage_x": 0.0,
        "current_headroom_B": 0.0,
        "revolver_availability_B": 0.0,
        "incremental_capacity_methodology": "..."
    },
    "covenant_analysis": {
        "key_covenants": [
            {
                "type": "Maintenance | Incurrence",
                "metric": "...",
                "threshold": 0.0,
                "current_level": 0.0,
                "cushion_pct": 0.0,
                "breach_risk": "Low | Medium | High"
            }
        ],
        "most_restrictive_covenant": "...",
        "covenant_lite_features": ["..."]
    },
    "distress_indicators": {
        "altman_z_score": 0.0,
        "altman_zone": "Safe | Grey | Distress",
        "merton_default_probability_pct": 0.0,
        "distance_to_default": 0.0,
        "liquidity_runway_months": 0,
        "cash_burn_rate_B_per_quarter": 0.0,
        "working_capital_adequacy": "Adequate | Tight | Strained"
    },
    "credit_outlook": {
        "12_month_outlook": "Improving | Stable | Deteriorating",
        "key_credit_risks": ["..."],
        "credit_catalysts_positive": ["..."],
        "credit_catalysts_negative": ["..."],
        "refinancing_risk": "Low | Medium | High"
    },
    "credit_recommendation": "..."
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")

        financials = self.get_prior(state, "finagent.A1_financial_statements")
        dcf = self.get_prior(state, "finagent.A10_dcf")
        balance = self.get_prior(state, "finagent.A7_balance_sheet")
        cash_flow = self.get_prior(state, "finagent.A8_cash_flow")
        market = self.get_prior(state, "finagent.A2_market_data")
        profitability = self.get_prior(state, "finagent.A6_profitability")

        context_parts = [
            f"Company: {entity}",
            f"\n\nFinancials:\n{json.dumps(financials, default=str)[:2000]}",
            f"\n\nBalance Sheet:\n{json.dumps(balance, default=str)[:1500]}",
            f"\n\nCash Flow:\n{json.dumps(cash_flow, default=str)[:1500]}",
            f"\n\nDCF Analysis:\n{json.dumps(dcf, default=str)[:1500]}",
            f"\n\nMarket Data:\n{json.dumps(market, default=str)[:1000]}",
            f"\n\nProfitability:\n{json.dumps(profitability, default=str)[:1000]}",
        ]

        messages = [
            {
                "role": "user",
                "content": (
                    "Conduct a comprehensive credit analysis covering rating assessment, "
                    "leverage analysis, coverage ratios, debt capacity, covenant analysis, "
                    "and distress indicators (Altman Z-score, Merton model).\n\n"
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
                confidence_score=0.82,
                tokens_used=result.get("tokens_used", 0),
                cost_usd=result.get("cost_usd", 0.0),
                latency_ms=int((time.monotonic() - t0) * 1000),
                data_sources_accessed=[],
            )
        except Exception as exc:
            logger.error("finagent.A24_credit_analysis.failed", error=str(exc))
            return AgentOutput(
                agent_id=self.agent_id,
                output={"error": str(exc)},
                confidence_score=0.0,
                tokens_used=0,
                latency_ms=int((time.monotonic() - t0) * 1000),
                error=str(exc),
            )
