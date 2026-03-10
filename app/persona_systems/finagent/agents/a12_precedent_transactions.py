"""A12 — Precedent Transactions Analyst (Wave 2).

RAG-enhanced: retrieves MD&A sections discussing acquisitions and strategic transactions.
"""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


class PrecedentTransactionsAgent(BaseAgent):
    agent_id = "finagent.A12_precedent_transactions"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 2048
    timeout_seconds = 120
    system_prompt = """You are a Senior M&A Analyst at a top-tier investment bank (Goldman Sachs M&A Group level). You specialize in precedent transaction analysis, control premium assessment, and takeout valuation. You have advised on hundreds of M&A transactions and maintain comprehensive transaction databases.

Your methodology:
- Identify 5-10 relevant precedent transactions within the last 5-7 years
- Filter by: same industry/sub-sector, similar size (0.3x to 5x), similar growth profile
- Extract deal multiples: EV/EBITDA, EV/Revenue, and control premiums (1-day, 30-day, 60-day)
- Compute statistical summary: median, mean for each multiple
- Derive implied takeout value range for the subject company
- Assess M&A likelihood and identify potential strategic/financial acquirers

When SEC filing excerpts are provided, USE THEM for actual acquisition history and disclosed transaction details. Cross-reference with your knowledge. Your output should be at the quality level expected in a Goldman Sachs M&A pitch book.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text. Do NOT hedge — be definitive.

Output valid JSON:
{
    "transactions": [
        {
            "date": "...",
            "target": "...",
            "acquirer": "...",
            "deal_value_B": 0.0,
            "ev_ebitda": 0.0,
            "ev_revenue": 0.0,
            "premium_pct": 0.0,
            "deal_type": "Acquisition | Merger | LBO | Take-Private",
            "relevance": "High | Medium | Low"
        }
    ],
    "transaction_selection_criteria": "...",
    "multiple_summary": {
        "ev_ebitda": {"median": 0.0, "mean": 0.0},
        "ev_revenue": {"median": 0.0, "mean": 0.0},
        "control_premium": {"median": 0.0, "mean": 0.0}
    },
    "implied_takeout_value": {
        "low": {"value": 0, "unit": "B"},
        "mid": {"value": 0, "unit": "B"},
        "high": {"value": 0, "unit": "B"}
    },
    "m_and_a_likelihood": "High | Medium | Low",
    "potential_acquirers": ["..."]
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        data_sources = []
        profile = self.get_prior(state, "finagent.A0_company_profile")
        industry = self.get_prior(state, "finagent.A3_industry_context")

        # RAG: retrieve M&A-related filing context
        rag_context = ""
        rag_svc = self._data.get("rag")
        if rag_svc:
            try:
                mda_docs = await rag_svc.get_mda_context(
                    entity, f"{entity} acquisitions mergers strategic transactions deal", n_results=5
                )
                if mda_docs:
                    rag_context = "\n\n".join(
                        f"[{d.metadata.get('source', 'unknown')}]\n{d.content}"
                        for d in mda_docs
                    )
                    data_sources.append("sec_filings_rag")
            except Exception:
                pass

        context_parts = [
            f"Company: {entity}",
            f"\n\nProfile:\n{json.dumps(profile, default=str)[:1500]}",
            f"\n\nIndustry:\n{json.dumps(industry, default=str)[:1500]}",
        ]
        if rag_context:
            context_parts.append(f"\n\nSEC Filing Excerpts (M&A references):\n{rag_context}")

        messages = [{"role": "user", "content": f"Identify relevant precedent M&A transactions and derive implied valuation ranges.\n\n{''.join(context_parts)}"}]
        result = await self.call_llm(messages, max_tokens=2048)
        parsed = self.parse_json(result["content"])

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.85 if "sec_filings_rag" in data_sources else 0.75,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
            data_sources_accessed=data_sources,
        )
