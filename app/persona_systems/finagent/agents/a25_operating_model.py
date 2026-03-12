"""A25 — Operating Model Agent (Wave 5).

Granular revenue build: segment-level drivers (volume x price x mix),
cost structure decomposition, working capital model, capex requirements,
and 5-year projections with base/bull/bear scenarios.
"""

import json
import time

import structlog

from app.domain.entities.agent_output import AgentOutput
from app.persona_systems.base_agent import BaseAgent

logger = structlog.get_logger(__name__)


class OperatingModelAgent(BaseAgent):
    agent_id = "finagent.A25_operating_model"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 3500
    timeout_seconds = 240
    system_prompt = """You are a Senior Financial Modeler at a top-tier investment bank with deep expertise
in building granular operating models, scenario analysis, and unit economics.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers,
notes, or explanatory text before or after the JSON. Do NOT say you are unable
to access data — use your best knowledge and any provided context.

{
    "revenue_build": {
        "segments": [
            {
                "name": "...",
                "driver_type": "Volume x Price | Users x ARPU | Units x ASP | Subscriptions x MRR",
                "current_year": {
                    "volume": 0,
                    "price": 0.0,
                    "revenue_B": 0.0,
                    "mix_pct": 0.0
                },
                "projections": {
                    "year_1": {"volume_growth_pct": 0.0, "price_change_pct": 0.0, "revenue_B": 0.0},
                    "year_2": {"volume_growth_pct": 0.0, "price_change_pct": 0.0, "revenue_B": 0.0},
                    "year_3": {"volume_growth_pct": 0.0, "price_change_pct": 0.0, "revenue_B": 0.0},
                    "year_4": {"volume_growth_pct": 0.0, "price_change_pct": 0.0, "revenue_B": 0.0},
                    "year_5": {"volume_growth_pct": 0.0, "price_change_pct": 0.0, "revenue_B": 0.0}
                }
            }
        ],
        "total_revenue_projections_B": [0.0, 0.0, 0.0, 0.0, 0.0],
        "total_revenue_growth_pct": [0.0, 0.0, 0.0, 0.0, 0.0]
    },
    "cost_structure": {
        "cogs": {
            "pct_of_revenue": 0.0,
            "fixed_component_B": 0.0,
            "variable_component_pct": 0.0,
            "projected_margins_pct": [0.0, 0.0, 0.0, 0.0, 0.0]
        },
        "opex_breakdown": {
            "rnd": {"current_B": 0.0, "pct_of_revenue": 0.0, "projected_pct": [0.0, 0.0, 0.0, 0.0, 0.0]},
            "sales_marketing": {"current_B": 0.0, "pct_of_revenue": 0.0, "projected_pct": [0.0, 0.0, 0.0, 0.0, 0.0]},
            "general_admin": {"current_B": 0.0, "pct_of_revenue": 0.0, "projected_pct": [0.0, 0.0, 0.0, 0.0, 0.0]}
        },
        "operating_leverage": {
            "incremental_margin_pct": 0.0,
            "fixed_cost_base_B": 0.0,
            "breakeven_revenue_B": 0.0,
            "leverage_sensitivity": "High | Medium | Low"
        }
    },
    "working_capital": {
        "days_sales_outstanding": 0,
        "days_inventory_outstanding": 0,
        "days_payables_outstanding": 0,
        "cash_conversion_cycle_days": 0,
        "nwc_as_pct_revenue": 0.0,
        "projected_nwc_change_B": [0.0, 0.0, 0.0, 0.0, 0.0]
    },
    "capex_model": {
        "maintenance_capex_B": 0.0,
        "growth_capex_B": 0.0,
        "total_capex_B": 0.0,
        "capex_as_pct_revenue": 0.0,
        "projected_capex_B": [0.0, 0.0, 0.0, 0.0, 0.0],
        "depreciation_B": 0.0,
        "capex_intensity_trend": "Increasing | Stable | Decreasing"
    },
    "scenario_projections": {
        "base_case": {
            "probability_pct": 50,
            "revenue_cagr_pct": 0.0,
            "ebitda_margin_year5_pct": 0.0,
            "fcf_year5_B": 0.0,
            "key_assumptions": ["..."]
        },
        "bull_case": {
            "probability_pct": 25,
            "revenue_cagr_pct": 0.0,
            "ebitda_margin_year5_pct": 0.0,
            "fcf_year5_B": 0.0,
            "key_assumptions": ["..."]
        },
        "bear_case": {
            "probability_pct": 25,
            "revenue_cagr_pct": 0.0,
            "ebitda_margin_year5_pct": 0.0,
            "fcf_year5_B": 0.0,
            "key_assumptions": ["..."]
        }
    },
    "unit_economics": {
        "ltv": 0.0,
        "cac": 0.0,
        "ltv_to_cac": 0.0,
        "payback_period_months": 0,
        "gross_margin_per_unit": 0.0,
        "applicability": "High | Medium | Low | N/A"
    },
    "model_confidence": "High | Medium | Low",
    "key_model_risks": ["..."]
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")

        profile = self.get_prior(state, "finagent.A0_company_profile")
        financials = self.get_prior(state, "finagent.A1_financial_statements")
        industry = self.get_prior(state, "finagent.A3_industry_context")
        revenue = self.get_prior(state, "finagent.A5_revenue_model")
        profitability = self.get_prior(state, "finagent.A6_profitability")
        cash_flow = self.get_prior(state, "finagent.A8_cash_flow")
        growth = self.get_prior(state, "finagent.A9_growth_trajectory")

        context_parts = [
            f"Company: {entity}",
            f"\n\nCompany Profile:\n{json.dumps(profile, default=str)[:1500]}",
            f"\n\nFinancials:\n{json.dumps(financials, default=str)[:2000]}",
            f"\n\nIndustry Context:\n{json.dumps(industry, default=str)[:1500]}",
            f"\n\nRevenue Model:\n{json.dumps(revenue, default=str)[:1500]}",
            f"\n\nProfitability:\n{json.dumps(profitability, default=str)[:1000]}",
            f"\n\nCash Flow:\n{json.dumps(cash_flow, default=str)[:1000]}",
            f"\n\nGrowth Trajectory:\n{json.dumps(growth, default=str)[:1000]}",
        ]

        messages = [
            {
                "role": "user",
                "content": (
                    "Build a granular operating model with segment-level revenue drivers, "
                    "cost structure decomposition, working capital model, capex requirements, "
                    "and 5-year projections under base/bull/bear scenarios.\n\n"
                    + "".join(context_parts)
                ),
            }
        ]

        try:
            result = await self.call_llm(messages, max_tokens=3500, temperature=0.3)
            parsed = self.parse_json(result["content"])
            return AgentOutput(
                agent_id=self.agent_id,
                output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
                confidence_score=0.80,
                tokens_used=result.get("tokens_used", 0),
                cost_usd=result.get("cost_usd", 0.0),
                latency_ms=int((time.monotonic() - t0) * 1000),
                data_sources_accessed=[],
            )
        except Exception as exc:
            logger.error("finagent.A25_operating_model.failed", error=str(exc))
            return AgentOutput(
                agent_id=self.agent_id,
                output={"error": str(exc)},
                confidence_score=0.0,
                tokens_used=0,
                latency_ms=int((time.monotonic() - t0) * 1000),
                error=str(exc),
            )
