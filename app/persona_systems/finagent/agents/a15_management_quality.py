"""A15 — Management Quality Analyst (Wave 3).

RAG-enhanced: retrieves proxy statement (DEF 14A) for compensation,
board composition, and governance data.
"""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


class ManagementQualityAgent(BaseAgent):
    agent_id = "finagent.A15_management_quality"
    persona_system = "finagent"
    temperature = 0.3
    max_tokens = 2048
    timeout_seconds = 120
    system_prompt = """You are a Senior Governance & Leadership Analyst at a top-tier proxy advisory firm (ISS/Glass Lewis level). You specialize in management quality assessment, executive compensation analysis, and corporate governance evaluation. You advise institutional investors on proxy voting and activism campaigns.

Your methodology:
- Assess CEO track record: TSR vs. peers during tenure, strategic pivots, capital allocation decisions
- Evaluate board quality: independence ratio, diversity, expertise coverage, overboarding, refreshment rate
- Analyze compensation structure: pay-for-performance alignment, STI/LTI mix, clawback provisions, peer benchmarking
- Score capital allocation: ROIC vs. WACC spread, acquisition track record (IRR analysis), buyback timing
- Assess succession planning depth and key person risk

When proxy statement (DEF 14A) excerpts are provided, USE THEM for actual compensation data, board composition, and insider ownership figures. These are legally filed numbers — prioritize them over estimates.

Your output should be at the quality level expected in an ISS governance report. Do NOT hedge — provide definitive scores and assessments.

IMPORTANT: Output ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text. Respond with nothing but valid JSON:
{
    "overall_management_score": 0.0,
    "ceo_assessment": {
        "name": "...",
        "tenure_years": 0,
        "track_record": "...",
        "compensation_alignment": "Well-aligned | Adequate | Misaligned",
        "insider_ownership_pct": 0.0
    },
    "board_quality": {
        "independence_pct": 0.0,
        "avg_tenure_years": 0.0,
        "diversity_score": "High | Medium | Low",
        "notable_members": ["..."]
    },
    "capital_allocation_track_record": {
        "roic_vs_wacc": "Above | At | Below",
        "acquisition_success_rate": "...",
        "shareholder_value_creation": "Strong | Mixed | Poor"
    },
    "compensation_structure": {
        "ceo_total_comp_M": 0.0,
        "pay_for_performance_alignment": "Strong | Moderate | Weak",
        "stock_based_comp_pct": 0.0
    },
    "management_risks": ["..."],
    "succession_planning": "Strong | Adequate | Weak | Unknown"
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        data_sources = []
        profile = self.get_prior(state, "finagent.A0_company_profile")

        # RAG: retrieve proxy statement context
        rag_context = ""
        rag_svc = self._data.get("rag")
        if rag_svc:
            try:
                proxy_docs = await rag_svc.get_proxy_context(
                    entity, f"{entity} CEO compensation board directors insider ownership governance", n_results=8
                )
                if proxy_docs:
                    rag_context = "\n\n".join(
                        f"[DEF 14A Proxy]\n{d.content}" for d in proxy_docs
                    )
                    data_sources.append("sec_proxy_statement")
            except Exception:
                pass

        context_parts = [
            f"Company: {entity}",
            f"\n\nProfile:\n{json.dumps(profile, default=str)[:2000]}",
        ]
        if rag_context:
            context_parts.append(f"\n\nPROXY STATEMENT (DEF 14A) EXCERPTS:\n{rag_context}")

        messages = [{"role": "user", "content": f"Assess management quality including CEO track record, board governance, capital allocation history, and compensation alignment.\n\n{''.join(context_parts)}"}]
        result = await self.call_llm(messages, max_tokens=2048)
        parsed = self.parse_json(result["content"])

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.88 if "sec_proxy_statement" in data_sources else 0.75,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
            data_sources_accessed=data_sources,
        )
