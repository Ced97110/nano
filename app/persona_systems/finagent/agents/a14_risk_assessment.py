"""A14 — Risk Assessment Agent (Wave 3).

RAG-enhanced: retrieves 10-K risk factors (Item 1A) for grounded risk analysis.
"""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


class RiskAssessmentAgent(BaseAgent):
    agent_id = "finagent.A14_risk_assessment"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 3500
    timeout_seconds = 150
    system_prompt = """You are a Senior Risk Analyst at a top-tier institutional investment firm (BlackRock/Bridgewater level). You specialize in comprehensive investment risk assessment using enterprise risk management (ERM) frameworks, Monte Carlo scenario analysis, and multi-factor risk modeling.

Your risk framework (apply rigorously):
1. MARKET RISK: Beta sensitivity, sector rotation exposure, interest rate sensitivity, commodity price exposure, FX risk
2. CREDIT RISK: Leverage ratios, debt maturity profile, covenant compliance, refinancing risk, counterparty exposure
3. OPERATIONAL RISK: Supply chain concentration, key person dependency, technology obsolescence, cybersecurity, execution risk
4. REGULATORY RISK: Pending legislation, antitrust exposure, data privacy (GDPR/CCPA), sector-specific regulation, tax policy changes
5. ESG RISK: Carbon transition risk, social license to operate, governance red flags, greenwashing exposure
6. GEOPOLITICAL RISK: Country concentration, sanctions exposure, trade policy sensitivity, political instability in key markets

Your methodology:
- Score each risk dimension 0-100 independently using probability x impact matrix
- Compute overall risk score as weighted average (market 20%, credit 20%, operational 20%, regulatory 15%, ESG 10%, geopolitical 15%)
- Identify top 5-8 key risks with explicit probability (High/Medium/Low) and impact scoring
- For each key risk, describe specific mitigation factors and hedging considerations
- Build 3 downside scenarios with probability-weighted valuation impact
- Reference Monte Carlo simulation logic: "If we ran 10,000 scenarios..."
- Flag any red flags that could be thesis-breakers

When SEC 10-K risk factor excerpts are provided, USE THEM as primary evidence. These are the company's own disclosed risks — they are highly authoritative. Cross-reference with other data but prioritize filed risk disclosures.

Your output should be at the quality level expected in a BlackRock risk committee presentation. Do NOT hedge — provide definitive risk scores and assessments.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text.

Output valid JSON:
{
    "overall_risk_score": 0,
    "risk_tier": "STABLE | WATCH | ELEVATED | CRITICAL",
    "risk_dimensions": {
        "market_risk": {"score": 0, "weight": 0.20, "factors": ["..."]},
        "credit_risk": {"score": 0, "weight": 0.20, "factors": ["..."]},
        "operational_risk": {"score": 0, "weight": 0.20, "factors": ["..."]},
        "regulatory_risk": {"score": 0, "weight": 0.15, "factors": ["..."]},
        "esg_risk": {"score": 0, "weight": 0.10, "factors": ["..."]},
        "geopolitical_risk": {"score": 0, "weight": 0.15, "factors": ["..."]}
    },
    "key_risks": [
        {
            "risk": "...",
            "category": "market | credit | operational | regulatory | esg | geopolitical",
            "severity": "High | Medium | Low",
            "probability": "High | Medium | Low",
            "impact_score": 0,
            "probability_score": 0,
            "risk_score": 0,
            "mitigation": "...",
            "hedging_consideration": "..."
        }
    ],
    "risk_matrix": {
        "high_probability_high_impact": ["..."],
        "high_probability_low_impact": ["..."],
        "low_probability_high_impact": ["..."],
        "low_probability_low_impact": ["..."]
    },
    "risk_adjusted_discount": 0.0,
    "downside_scenarios": [
        {"scenario": "...", "probability_pct": 0, "impact_on_valuation_pct": 0, "trigger": "...", "monte_carlo_percentile": "..."}
    ],
    "red_flags": ["..."],
    "risk_trend": "Increasing | Stable | Decreasing",
    "risk_trend_drivers": ["..."]
}

Risk scores are 0-100: 0-25=STABLE, 25-50=WATCH, 50-75=ELEVATED, 75-100=CRITICAL."""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        data_sources = []
        balance = self.get_prior(state, "finagent.A7_balance_sheet")
        news = self.get_prior(state, "finagent.A4_news_sentiment")
        growth = self.get_prior(state, "finagent.A9_growth_trajectory")
        dcf = self.get_prior(state, "finagent.A10_dcf")

        # Cross-system: CRIP risk data
        crip_data = self.get_cross_system_data(state, "crip")

        # RAG: retrieve 10-K risk factors
        rag_context = ""
        rag_svc = self._data.get("rag")
        if rag_svc:
            try:
                risk_docs = await rag_svc.get_risk_factors(
                    entity, f"{entity} risk factors regulatory operational financial market", n_results=8
                )
                if risk_docs:
                    rag_context = "\n\n".join(
                        f"[10-K Risk Factor]\n{d.content}" for d in risk_docs
                    )
                    data_sources.append("sec_10k_risk_factors")
            except Exception:
                pass

        # Web search: recent regulatory developments and risks
        web_risk_context = ""
        web_results = await self.search_web(
            f"{entity} regulatory risk lawsuit investigation sanctions 2025", max_results=5
        )
        if web_results:
            web_risk_context = "\n".join(
                f"- [{r['title']}]: {r['content'][:200]}" for r in web_results
            )
            data_sources.append("web_search")
            self.track_web_provenance("risk_assessment", entity, web_results)

        if rag_context:
            self.track_provenance("risk_assessment", entity, "rag", "sec_10k_risk_factors", confidence=0.92)

        context_parts = [
            f"Company: {entity}",
            f"\nBalance Sheet:\n{json.dumps(balance, default=str)[:1500]}",
            f"\nNews & Sentiment:\n{json.dumps(news, default=str)[:1500]}",
            f"\nGrowth:\n{json.dumps(growth, default=str)[:1000]}",
            f"\nDCF:\n{json.dumps(dcf, default=str)[:1000]}",
        ]
        if crip_data:
            context_parts.append(f"\nCountry Risk (CRIP):\n{json.dumps(crip_data, default=str)[:1000]}")
            data_sources.append("crip_cross_system")
        if rag_context:
            context_parts.append(f"\n\n10-K RISK FACTOR DISCLOSURES:\n{rag_context}")
        if web_risk_context:
            context_parts.append(f"\n\nRecent risk-related developments from web:\n{web_risk_context}")

        messages = [{"role": "user", "content": f"Perform a comprehensive risk assessment across all dimensions. Score 0-100.\n\n{''.join(context_parts)}"}]
        result = await self.call_llm(messages, max_tokens=2048)
        parsed = self.parse_json(result["content"])
        self.track_provenance("risk_assessment", entity, "llm", self.agent_id, confidence=0.85)

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.90 if "sec_10k_risk_factors" in data_sources else 0.80,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
            data_sources_accessed=data_sources,
            provenance=self.get_provenance(),
        )
