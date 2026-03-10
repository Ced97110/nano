"""A26 — Sensitivity Analysis Agent (Wave 6).

Multi-variable sensitivity tables, scenario analysis with probability weights,
break-even analysis on key assumptions, and tornado chart data.
Depends on: A10 (DCF), A22 (LBO), A25 (Operating Model).
"""

import json
import time

import structlog

from app.domain.entities.agent_output import AgentOutput
from app.persona_systems.base_agent import BaseAgent

logger = structlog.get_logger(__name__)


class SensitivityAnalysisAgent(BaseAgent):
    agent_id = "finagent.A26_sensitivity"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 3000
    timeout_seconds = 150
    system_prompt = """You are a Senior Quantitative Analyst at a top-tier investment bank with deep expertise
in sensitivity analysis, scenario modeling, and risk quantification.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers,
notes, or explanatory text before or after the JSON. Do NOT say you are unable
to access data — use your best knowledge and any provided context.

{
    "dcf_sensitivity": {
        "wacc_vs_terminal_growth": {
            "wacc_range_pct": [0.0, 0.0, 0.0, 0.0, 0.0],
            "terminal_growth_range_pct": [0.0, 0.0, 0.0, 0.0, 0.0],
            "implied_price_matrix": [
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0]
            ],
            "base_case_price": 0.0
        },
        "revenue_vs_margin": {
            "revenue_growth_range_pct": [0.0, 0.0, 0.0, 0.0, 0.0],
            "ebitda_margin_range_pct": [0.0, 0.0, 0.0, 0.0, 0.0],
            "implied_ev_matrix_B": [
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0]
            ]
        }
    },
    "lbo_sensitivity": {
        "entry_multiple_vs_exit_multiple": {
            "entry_range": [0.0, 0.0, 0.0, 0.0, 0.0],
            "exit_range": [0.0, 0.0, 0.0, 0.0, 0.0],
            "irr_matrix_pct": [
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0]
            ]
        },
        "leverage_vs_ebitda_growth": {
            "leverage_range_x": [0.0, 0.0, 0.0, 0.0, 0.0],
            "ebitda_cagr_range_pct": [0.0, 0.0, 0.0],
            "irr_matrix_pct": [
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 0.0, 0.0]
            ]
        }
    },
    "scenario_analysis": {
        "bull_case": {
            "probability_pct": 25,
            "implied_value_B": 0.0,
            "implied_price_per_share": 0.0,
            "upside_pct": 0.0,
            "key_assumptions": ["..."],
            "catalysts": ["..."]
        },
        "base_case": {
            "probability_pct": 50,
            "implied_value_B": 0.0,
            "implied_price_per_share": 0.0,
            "upside_pct": 0.0,
            "key_assumptions": ["..."]
        },
        "bear_case": {
            "probability_pct": 25,
            "implied_value_B": 0.0,
            "implied_price_per_share": 0.0,
            "downside_pct": 0.0,
            "key_assumptions": ["..."],
            "risk_triggers": ["..."]
        },
        "probability_weighted_value_B": 0.0,
        "probability_weighted_price": 0.0
    },
    "breakeven_analysis": {
        "revenue_breakeven_growth_pct": 0.0,
        "margin_breakeven_pct": 0.0,
        "wacc_breakeven_pct": 0.0,
        "multiple_breakeven": 0.0,
        "commentary": "..."
    },
    "tornado_chart": {
        "variables_ranked": [
            {
                "variable": "...",
                "low_assumption": 0.0,
                "high_assumption": 0.0,
                "low_value_impact_B": 0.0,
                "high_value_impact_B": 0.0,
                "range_B": 0.0
            }
        ],
        "most_sensitive_variable": "...",
        "least_sensitive_variable": "..."
    },
    "monte_carlo_summary": {
        "simulations_run": 0,
        "mean_value_B": 0.0,
        "median_value_B": 0.0,
        "std_dev_B": 0.0,
        "percentile_10_B": 0.0,
        "percentile_90_B": 0.0,
        "probability_above_current_pct": 0.0,
        "methodology_note": "..."
    },
    "key_insights": ["..."],
    "highest_impact_risks": ["..."]
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")

        dcf = self.get_prior(state, "finagent.A10_dcf")
        lbo = self.get_prior(state, "finagent.A22_lbo_model")
        operating_model = self.get_prior(state, "finagent.A25_operating_model")
        market = self.get_prior(state, "finagent.A2_market_data")
        comps = self.get_prior(state, "finagent.A11_comps")
        financials = self.get_prior(state, "finagent.A1_financial_statements")

        context_parts = [
            f"Company: {entity}",
            f"\n\nDCF Analysis:\n{json.dumps(dcf, default=str)[:2500]}",
            f"\n\nOperating Model:\n{json.dumps(operating_model, default=str)[:2500]}",
            f"\n\nMarket Data:\n{json.dumps(market, default=str)[:1000]}",
            f"\n\nFinancials:\n{json.dumps(financials, default=str)[:1000]}",
        ]
        if lbo:
            context_parts.append(f"\n\nLBO Model:\n{json.dumps(lbo, default=str)[:2000]}")
        if comps:
            context_parts.append(f"\n\nComparable Companies:\n{json.dumps(comps, default=str)[:1000]}")

        messages = [
            {
                "role": "user",
                "content": (
                    "Build comprehensive sensitivity analysis with multi-variable tables "
                    "(WACC vs terminal growth, revenue vs margin, entry vs exit multiples), "
                    "bull/base/bear scenario analysis with probability weights, break-even analysis, "
                    "and tornado chart data ranking variable impacts.\n\n"
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
                confidence_score=0.82,
                tokens_used=result.get("tokens_used", 0),
                cost_usd=result.get("cost_usd", 0.0),
                latency_ms=int((time.monotonic() - t0) * 1000),
                data_sources_accessed=[],
            )
        except Exception as exc:
            logger.error("finagent.A26_sensitivity.failed", error=str(exc))
            return AgentOutput(
                agent_id=self.agent_id,
                output={"error": str(exc)},
                confidence_score=0.0,
                tokens_used=0,
                latency_ms=int((time.monotonic() - t0) * 1000),
                error=str(exc),
            )
