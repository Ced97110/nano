"""A11 — Comparable Companies Analyst (Wave 2)."""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


class CompsAgent(BaseAgent):
    agent_id = "finagent.A11_comps"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 3000
    timeout_seconds = 120
    system_prompt = """You are a Senior Comparable Companies Analyst at a top-tier investment bank (Evercore/Centerview level). You specialize in peer group selection, trading multiples analysis, and relative valuation. You build the comps tables that drive pricing for IPOs, M&A transactions, and equity research coverage.

Your methodology:
1. PEER SELECTION (5-8 companies): Select true peers based on:
   - Same GICS sub-industry or adjacent
   - Similar revenue scale (0.5x to 3x of subject)
   - Similar growth profile and business model
   - Same geographic exposure
   - Score each peer 0-1.0 on relevance
2. VALUATION MULTIPLES for each peer:
   - EV/EBITDA (primary for most sectors)
   - EV/Revenue (for high-growth or unprofitable companies)
   - P/E (for mature, profitable companies)
   - P/B (for financials/asset-heavy sectors)
   - PEG ratio (growth-adjusted P/E)
3. STATISTICAL SUMMARY: median, mean, 25th/75th percentiles for each multiple
4. IMPLIED VALUATION: Apply peer multiples to subject's financials for low/mid/high ranges
5. PREMIUM/DISCOUNT ANALYSIS: Justify why subject should trade at premium or discount to peers
6. FOOTBALL FIELD: Provide data points for a valuation football field chart

Your output should be at the quality level expected in an Evercore fairness opinion. Do NOT hedge — provide definitive peer selections with clear rationale.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text.

Output valid JSON:
{
    "peer_group": [
        {
            "ticker": "...",
            "name": "...",
            "market_cap_B": 0.0,
            "ev_ebitda": 0.0,
            "pe_ratio": 0.0,
            "ev_revenue": 0.0,
            "price_to_book": 0.0,
            "peg_ratio": 0.0,
            "revenue_growth": 0.0,
            "ebitda_margin": 0.0,
            "relevance_score": 0.0,
            "selection_reason": "..."
        }
    ],
    "peer_selection_rationale": "...",
    "selection_criteria": {
        "industry_match": "...",
        "size_range": "...",
        "growth_profile": "...",
        "excluded_companies": [{"name": "...", "reason": "..."}]
    },
    "multiple_summary": {
        "ev_ebitda": {"median": 0.0, "mean": 0.0, "p25": 0.0, "p75": 0.0, "range": [0.0, 0.0]},
        "pe_ratio": {"median": 0.0, "mean": 0.0, "p25": 0.0, "p75": 0.0, "range": [0.0, 0.0]},
        "ev_revenue": {"median": 0.0, "mean": 0.0, "p25": 0.0, "p75": 0.0, "range": [0.0, 0.0]},
        "peg_ratio": {"median": 0.0, "mean": 0.0, "range": [0.0, 0.0]}
    },
    "implied_valuation": {
        "ev_ebitda_range": {"low": 0.0, "mid": 0.0, "high": 0.0, "unit": "B"},
        "pe_range": {"low": 0.0, "mid": 0.0, "high": 0.0, "unit": "B"},
        "ev_revenue_range": {"low": 0.0, "mid": 0.0, "high": 0.0, "unit": "B"}
    },
    "football_field": {
        "ev_ebitda": {"low": 0.0, "high": 0.0},
        "pe": {"low": 0.0, "high": 0.0},
        "ev_revenue": {"low": 0.0, "high": 0.0},
        "current_price": 0.0
    },
    "premium_discount_assessment": "...",
    "premium_discount_pct": 0.0,
    "comps_confidence": "High | Medium | Low"
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        profile = self.get_prior(state, "finagent.A0_company_profile")
        financials = self.get_prior(state, "finagent.A1_financial_statements")
        market = self.get_prior(state, "finagent.A2_market_data")
        industry = self.get_prior(state, "finagent.A3_industry_context")
        revenue = self.get_prior(state, "finagent.A5_revenue_model")
        profitability = self.get_prior(state, "finagent.A6_profitability")

        context = (
            f"Company: {entity}\n\n"
            f"Profile (sector, industry, sub_industry for peer matching):\n{json.dumps(profile, default=str)[:1500]}\n\n"
            f"Financial Statements (revenue, EBITDA, net income for multiple calculation):\n{json.dumps(financials, default=str)[:1500]}\n\n"
            f"Market Data (current multiples, market cap, share price):\n{json.dumps(market, default=str)[:1500]}\n\n"
            f"Industry (top competitors, market dynamics):\n{json.dumps(industry, default=str)[:1500]}\n\n"
            f"Revenue Model (segments, growth rate):\n{json.dumps(revenue, default=str)[:1000]}\n\n"
            f"Profitability (margins for peer benchmarking):\n{json.dumps(profitability, default=str)[:1000]}"
        )
        messages = [{"role": "user", "content": f"Build a comparable companies analysis. Select 5-8 true peer companies with explicit selection criteria. Calculate EV/EBITDA, EV/Revenue, P/E, P/B, and PEG multiples. Derive implied valuation ranges and assess premium/discount vs. peer median.\n\n{context}"}]
        result = await self.call_llm(messages)
        parsed = self.parse_json(result["content"])

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.80,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
