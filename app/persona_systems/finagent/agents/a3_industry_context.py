"""A3 — Industry Context Analyzer (Wave 0).

RAG-enhanced: retrieves MD&A and industry report chunks for grounded analysis.
"""

import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


class IndustryContextAgent(BaseAgent):
    agent_id = "finagent.A3_industry_context"
    persona_system = "finagent"
    temperature = 0.3
    max_tokens = 2048
    timeout_seconds = 120
    system_prompt = """You are a Senior Industry Analyst at a top-tier strategy consulting firm (McKinsey/BCG level). You specialize in industry structure analysis using Porter's Five Forces, market sizing (TAM/SAM/SOM), and competitive dynamics mapping.

Your methodology:
- Apply Porter's Five Forces framework to assess industry attractiveness
- Size markets using top-down and bottom-up approaches with CAGR projections
- Map competitive landscape including market share distribution and concentration (HHI)
- Identify secular trends, disruption vectors, and regulatory catalysts
- Assess industry lifecycle stage and margin structure

When SEC filing excerpts are provided, USE THEM as primary evidence. Cross-reference with your knowledge but prioritize filed data. Your output should be at the quality level expected in a McKinsey industry landscape report.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text. Do NOT hedge or say you are unable to access data — be definitive.

Output valid JSON:
{
    "industry": "...",
    "tam": {"value": 0, "unit": "B", "currency": "USD", "cagr": 0.0},
    "industry_growth_rate": 0.0,
    "industry_stage": "Growth | Mature | Declining | Emerging",
    "key_trends": ["..."],
    "regulatory_environment": "...",
    "barriers_to_entry": ["..."],
    "top_competitors": [{"name": "...", "market_share_pct": 0.0}],
    "supply_chain_dynamics": "...",
    "macro_sensitivity": "High | Medium | Low",
    "disruption_risk": "High | Medium | Low"
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        data_sources = []

        # RAG: retrieve MD&A context about industry positioning
        rag_context = ""
        rag_svc = self._data.get("rag")
        if rag_svc:
            try:
                mda_docs = await rag_svc.get_mda_context(
                    entity, f"{entity} industry market size competition trends", n_results=5
                )
                industry_docs = await rag_svc.get_industry_context(
                    f"{entity} industry analysis market dynamics", n_results=3
                )
                all_docs = mda_docs + industry_docs
                if all_docs:
                    rag_context = "\n\n".join(
                        f"[{d.metadata.get('source', 'unknown')} — {d.metadata.get('section', '')}]\n{d.content}"
                        for d in all_docs
                    )
                    data_sources.append("sec_filings_rag")
            except Exception:
                pass

        # Web search: industry trends and recent reports
        web_context = ""
        web_results = await self.search_web(
            f"{entity} industry trends market size analysis report 2025", max_results=5
        )
        if web_results:
            web_context = "\n".join(
                f"- [{r['title']}]: {r['content'][:200]}" for r in web_results
            )
            data_sources.append("web_search")
            self.track_web_provenance("industry_context", entity, web_results)

        if rag_context:
            self.track_provenance("industry_context", entity, "rag", "sec_filings", confidence=0.90)

        prompt_parts = [f"Analyze the industry context for: {entity}. Cover market size, growth, competition, and key trends."]
        if rag_context:
            prompt_parts.append(f"\n\nRelevant SEC filing excerpts:\n{rag_context}")
        else:
            data_sources.append("llm_knowledge")
        if web_context:
            prompt_parts.append(f"\n\nRecent industry research from web:\n{web_context}")

        messages = [{"role": "user", "content": "".join(prompt_parts)}]
        result = await self.call_llm(messages, max_tokens=2048)
        parsed = self.parse_json(result["content"])
        self.track_provenance("industry_context", entity, "llm", self.agent_id, confidence=0.85)

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.90 if "sec_filings_rag" in data_sources else 0.82,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
            data_sources_accessed=data_sources,
            provenance=self.get_provenance(),
        )
