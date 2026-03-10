"""A23 — IPO Readiness Agent (Wave 5).

Evaluates IPO readiness: governance, financials, market conditions,
comparable IPO analysis, pricing range estimation, and float analysis.
"""

import json
import time

import structlog

from app.domain.entities.agent_output import AgentOutput
from app.persona_systems.base_agent import BaseAgent

logger = structlog.get_logger(__name__)


class IPOReadinessAgent(BaseAgent):
    agent_id = "finagent.A23_ipo_readiness"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 3000
    timeout_seconds = 150
    system_prompt = """You are a Senior ECM (Equity Capital Markets) Banker at a top-tier investment bank
with deep expertise in IPO advisory, pricing, and market positioning.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers,
notes, or explanatory text before or after the JSON. Do NOT say you are unable
to access data — use your best knowledge and any provided context.

{
    "readiness_score": 0,
    "readiness_grade": "IPO-Ready | Near-Ready | Needs Work | Not Ready",
    "readiness_dimensions": {
        "financial_readiness": {
            "score": 0,
            "revenue_scale_adequate": true,
            "revenue_growth_trajectory": "...",
            "profitability_path": "...",
            "audit_readiness": "...",
            "sox_compliance": "...",
            "gaps": ["..."]
        },
        "governance_readiness": {
            "score": 0,
            "board_independence": "...",
            "audit_committee": "...",
            "compensation_committee": "...",
            "cfo_readiness": "...",
            "gaps": ["..."]
        },
        "market_conditions": {
            "score": 0,
            "ipo_window_status": "Open | Narrowing | Closed",
            "sector_sentiment": "Favorable | Neutral | Unfavorable",
            "recent_ipo_performance": "...",
            "volatility_assessment": "...",
            "investor_appetite": "Strong | Moderate | Weak"
        },
        "operational_readiness": {
            "score": 0,
            "management_depth": "...",
            "scalable_infrastructure": "...",
            "investor_relations_capability": "...",
            "gaps": ["..."]
        }
    },
    "comparable_ipos": [
        {
            "company": "...",
            "date": "YYYY-MM",
            "sector": "...",
            "ipo_valuation_B": 0.0,
            "ipo_price": 0.0,
            "first_day_return_pct": 0.0,
            "current_vs_ipo_pct": 0.0,
            "revenue_at_ipo_B": 0.0,
            "ev_revenue_at_ipo": 0.0,
            "relevance": "High | Medium | Low"
        }
    ],
    "pricing_analysis": {
        "estimated_valuation_range_B": {"low": 0.0, "mid": 0.0, "high": 0.0},
        "implied_ev_revenue": {"low": 0.0, "mid": 0.0, "high": 0.0},
        "implied_ev_ebitda": {"low": 0.0, "mid": 0.0, "high": 0.0},
        "ipo_discount_pct": 0.0,
        "pricing_methodology": "..."
    },
    "float_analysis": {
        "recommended_float_pct": 0.0,
        "primary_shares_pct": 0.0,
        "secondary_shares_pct": 0.0,
        "estimated_proceeds_B": 0.0,
        "use_of_proceeds": ["..."],
        "lockup_period_days": 180,
        "greenshoe_pct": 15.0
    },
    "timeline": {
        "estimated_months_to_ipo": 0,
        "key_milestones": ["..."],
        "recommended_filing_window": "..."
    },
    "risks_to_ipo": ["..."],
    "recommendation": "..."
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")

        profile = self.get_prior(state, "finagent.A0_company_profile")
        financials = self.get_prior(state, "finagent.A1_financial_statements")
        comps = self.get_prior(state, "finagent.A11_comps")
        market = self.get_prior(state, "finagent.A2_market_data")
        revenue = self.get_prior(state, "finagent.A5_revenue_model")
        esg = self.get_prior(state, "finagent.A16_esg_governance")
        mgmt = self.get_prior(state, "finagent.A15_management_quality")

        context_parts = [
            f"Company: {entity}",
            f"\n\nCompany Profile:\n{json.dumps(profile, default=str)[:2000]}",
            f"\n\nFinancials:\n{json.dumps(financials, default=str)[:2000]}",
            f"\n\nComparable Companies:\n{json.dumps(comps, default=str)[:1500]}",
            f"\n\nMarket Data:\n{json.dumps(market, default=str)[:1000]}",
            f"\n\nRevenue Model:\n{json.dumps(revenue, default=str)[:1000]}",
        ]
        if esg:
            context_parts.append(f"\n\nESG & Governance:\n{json.dumps(esg, default=str)[:1000]}")
        if mgmt:
            context_parts.append(f"\n\nManagement Quality:\n{json.dumps(mgmt, default=str)[:1000]}")

        messages = [
            {
                "role": "user",
                "content": (
                    "Evaluate IPO readiness covering governance, financials, market conditions, "
                    "comparable IPOs, pricing range estimation, and float analysis.\n\n"
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
            logger.error("finagent.A23_ipo_readiness.failed", error=str(exc))
            return AgentOutput(
                agent_id=self.agent_id,
                output={"error": str(exc)},
                confidence_score=0.0,
                tokens_used=0,
                latency_ms=int((time.monotonic() - t0) * 1000),
                error=str(exc),
            )
