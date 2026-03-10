"""A21 — M&A Analysis Agent (Wave 5).

Analyzes M&A activity: recent deals in sector, potential acquirers/targets,
accretive/dilutive analysis framework, and synergy estimation methodology.
"""

import json
import time

import structlog

from app.domain.entities.agent_output import AgentOutput
from app.persona_systems.base_agent import BaseAgent

logger = structlog.get_logger(__name__)


class MAAnalysisAgent(BaseAgent):
    agent_id = "finagent.A21_ma_analysis"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 3000
    timeout_seconds = 150
    system_prompt = """You are a Senior M&A Advisor at a top-tier investment bank with deep expertise
in deal structuring, synergy analysis, and strategic rationale evaluation.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers,
notes, or explanatory text before or after the JSON. Do NOT say you are unable
to access data — use your best knowledge and any provided context.

{
    "ma_landscape": {
        "recent_sector_deals": [
            {
                "date": "YYYY-MM",
                "target": "...",
                "acquirer": "...",
                "deal_value_B": 0.0,
                "ev_ebitda_multiple": 0.0,
                "ev_revenue_multiple": 0.0,
                "deal_type": "Acquisition | Merger | Take-Private | JV | Spin-Off",
                "strategic_rationale": "...",
                "status": "Completed | Pending | Rumored"
            }
        ],
        "deal_activity_trend": "Accelerating | Stable | Declining",
        "average_premium_pct": 0.0,
        "dominant_deal_type": "..."
    },
    "target_assessment": {
        "attractiveness_score": 0,
        "key_attractions": ["..."],
        "potential_acquirers": [
            {
                "name": "...",
                "rationale": "...",
                "estimated_synergies_B": 0.0,
                "likelihood": "High | Medium | Low",
                "deal_type": "Strategic | Financial | Consortium"
            }
        ],
        "defensive_measures": ["..."]
    },
    "acquirer_assessment": {
        "acquisition_capacity_B": 0.0,
        "max_leverage_capacity_B": 0.0,
        "potential_targets": [
            {
                "name": "...",
                "rationale": "...",
                "estimated_value_B": 0.0,
                "strategic_fit": "High | Medium | Low"
            }
        ],
        "acquisition_track_record": "..."
    },
    "accretion_dilution": {
        "framework": "...",
        "key_assumptions": {
            "financing_mix": {"cash_pct": 0.0, "debt_pct": 0.0, "equity_pct": 0.0},
            "cost_of_debt": 0.0,
            "tax_rate": 0.0,
            "shares_issued_M": 0
        },
        "eps_impact_year1": "Accretive | Dilutive | Neutral",
        "eps_impact_pct": 0.0,
        "breakeven_synergies_B": 0.0
    },
    "synergy_analysis": {
        "revenue_synergies": {
            "estimated_B": 0.0,
            "timeline_years": 0,
            "sources": ["..."],
            "confidence": "High | Medium | Low"
        },
        "cost_synergies": {
            "estimated_B": 0.0,
            "timeline_years": 0,
            "sources": ["..."],
            "confidence": "High | Medium | Low"
        },
        "total_synergy_npv_B": 0.0,
        "integration_risks": ["..."]
    },
    "ma_recommendation": "...",
    "key_risks": ["..."]
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")

        profile = self.get_prior(state, "finagent.A0_company_profile")
        industry = self.get_prior(state, "finagent.A3_industry_context")
        comps = self.get_prior(state, "finagent.A11_comps")
        financials = self.get_prior(state, "finagent.A1_financial_statements")
        precedent = self.get_prior(state, "finagent.A12_precedent_transactions")

        context_parts = [
            f"Company: {entity}",
            f"\n\nCompany Profile:\n{json.dumps(profile, default=str)[:2000]}",
            f"\n\nIndustry Context:\n{json.dumps(industry, default=str)[:2000]}",
            f"\n\nComparable Companies:\n{json.dumps(comps, default=str)[:2000]}",
            f"\n\nFinancials:\n{json.dumps(financials, default=str)[:1500]}",
        ]
        if precedent:
            context_parts.append(
                f"\n\nPrecedent Transactions:\n{json.dumps(precedent, default=str)[:1500]}"
            )

        messages = [
            {
                "role": "user",
                "content": (
                    "Conduct a comprehensive M&A analysis covering sector deal activity, "
                    "target/acquirer assessment, accretion/dilution framework, and synergy estimation.\n\n"
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
                confidence_score=0.80,
                tokens_used=result.get("tokens_used", 0),
                cost_usd=result.get("cost_usd", 0.0),
                latency_ms=int((time.monotonic() - t0) * 1000),
                data_sources_accessed=[],
            )
        except Exception as exc:
            logger.error("finagent.A21_ma_analysis.failed", error=str(exc))
            return AgentOutput(
                agent_id=self.agent_id,
                output={"error": str(exc)},
                confidence_score=0.0,
                tokens_used=0,
                latency_ms=int((time.monotonic() - t0) * 1000),
                error=str(exc),
            )
