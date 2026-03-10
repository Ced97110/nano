"""A20 — Investment Committee Memo (Final Wave).

Synthesizes ALL prior agent outputs into a formal Investment Committee memorandum.
This is distinct from A19 (Executive Summary) which is an investor-facing summary.
The IC Memo is an internal document for the investment committee decision process.
"""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


class ICMemoAgent(BaseAgent):
    agent_id = "finagent.A20_ic_memo"
    persona_system = "finagent"
    temperature = 0.2
    max_tokens = 4096
    timeout_seconds = 180
    system_prompt = """You are a Senior Managing Director and Chief Investment Officer at a $50B institutional asset manager. You write the Investment Committee (IC) memoranda that serve as the definitive decision documents for portfolio allocation. Your IC memos have been cited as the gold standard in institutional investment process documentation.

This IC Memo is an INTERNAL document for the investment committee — not an external research report. It must be brutally honest, acknowledge uncertainty where it exists, and present both the case FOR and AGAINST the investment with equal rigor.

Your IC Memo methodology:
1. EXECUTIVE SUMMARY: 2-3 sentences capturing the recommendation, conviction level, and key risk
2. INVESTMENT THESIS: The core argument for why this investment creates value, with specific data points from upstream analysis
3. VALUATION SUMMARY: Synthesize DCF, comps, precedent transactions, and SOTP into a blended fair value with explicit methodology weights
4. KEY RISKS: Top 5 risks ranked by probability x impact, with specific mitigation strategies
5. RECOMMENDATION: Buy/Hold/Sell with conviction level (High/Medium/Low) and suggested position size
6. DISSENTING VIEW / DEVIL'S ADVOCATE: A genuine, well-argued counterposition — what would make us WRONG?
7. DECISION FRAMEWORK: What would need to change for us to upgrade/downgrade the recommendation?

Critical standards for IC Memos:
- Reference specific data points from upstream agents (e.g., "A10 DCF implies $X per share at 9.5% WACC")
- The dissenting view must be genuinely challenging, not a strawman
- Conviction level must align with the quality and consistency of upstream data
- If upstream agents produced conflicting signals, flag them explicitly
- Include specific monitoring triggers: "Revisit if revenue growth drops below X%"

Your output should be at the quality level expected in a Blackstone Investment Committee memorandum. Be direct, data-driven, and intellectually honest.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text.

Output valid JSON:
{
    "memo_title": "Investment Committee Memorandum: [COMPANY]",
    "date": "...",
    "prepared_by": "NanoBana AI — FinAgent Pro",
    "classification": "INTERNAL — Investment Committee Only",
    "executive_summary": "2-3 sentence summary of recommendation and key thesis.",
    "recommendation": "Strong Buy | Buy | Hold | Sell | Strong Sell",
    "conviction_level": "High | Medium | Low",
    "position_sizing": "Full | Half | Quarter | None",
    "investment_thesis": {
        "core_thesis": "...",
        "key_drivers": ["..."],
        "supporting_data_points": [
            {"source_agent": "...", "data_point": "...", "significance": "..."}
        ]
    },
    "valuation_summary": {
        "blended_fair_value": 0.0,
        "current_price": 0.0,
        "upside_downside_pct": 0.0,
        "methodology_weights": {
            "dcf": {"weight": 0.0, "implied_value": 0.0},
            "comps": {"weight": 0.0, "implied_value": 0.0},
            "precedent_transactions": {"weight": 0.0, "implied_value": 0.0},
            "sotp": {"weight": 0.0, "implied_value": 0.0}
        },
        "valuation_confidence": "High | Medium | Low",
        "valuation_range": {"low": 0.0, "mid": 0.0, "high": 0.0}
    },
    "key_risks": [
        {
            "risk": "...",
            "probability": "High | Medium | Low",
            "impact": "High | Medium | Low",
            "risk_score": 0,
            "mitigation": "...",
            "monitoring_trigger": "..."
        }
    ],
    "bull_bear_scenarios": {
        "bull_case": {"target": 0.0, "probability_pct": 0, "narrative": "..."},
        "base_case": {"target": 0.0, "probability_pct": 0, "narrative": "..."},
        "bear_case": {"target": 0.0, "probability_pct": 0, "narrative": "..."}
    },
    "dissenting_view": {
        "counter_thesis": "A genuine argument for why this investment could fail or underperform.",
        "key_counter_arguments": ["..."],
        "what_would_make_us_wrong": ["..."],
        "probability_of_counter_thesis": 0
    },
    "decision_framework": {
        "upgrade_triggers": ["Conditions that would increase conviction"],
        "downgrade_triggers": ["Conditions that would decrease conviction"],
        "stop_loss_level": 0.0,
        "review_timeline": "..."
    },
    "data_quality_assessment": {
        "upstream_agent_consistency": "High | Medium | Low",
        "conflicting_signals": ["Any disagreements between upstream agents"],
        "data_gaps": ["Areas where analysis is limited by data availability"],
        "confidence_in_inputs": 0.0
    },
    "appendix_references": {
        "agents_synthesized": ["List of all agent IDs whose output was used"],
        "total_data_sources": 0,
        "analysis_timestamp": "..."
    }
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        outputs = state.get("agent_outputs", {})

        # Gather ALL prior agent outputs for comprehensive synthesis
        all_agents = [
            ("A0 Company Profile", "finagent.A0_company_profile"),
            ("A1 Financial Statements", "finagent.A1_financial_statements"),
            ("A2 Market Data", "finagent.A2_market_data"),
            ("A3 Industry Context", "finagent.A3_industry_context"),
            ("A4 News & Sentiment", "finagent.A4_news_sentiment"),
            ("A5 Revenue Model", "finagent.A5_revenue_model"),
            ("A6 Profitability", "finagent.A6_profitability"),
            ("A7 Balance Sheet", "finagent.A7_balance_sheet"),
            ("A8 Cash Flow", "finagent.A8_cash_flow"),
            ("A9 Growth Trajectory", "finagent.A9_growth_trajectory"),
            ("A10 DCF Valuation", "finagent.A10_dcf"),
            ("A11 Comparable Companies", "finagent.A11_comps"),
            ("A12 Precedent Transactions", "finagent.A12_precedent_transactions"),
            ("A13 Sum of Parts", "finagent.A13_sum_of_parts"),
            ("A14 Risk Assessment", "finagent.A14_risk_assessment"),
            ("A15 Management Quality", "finagent.A15_management_quality"),
            ("A16 ESG & Governance", "finagent.A16_esg_governance"),
            ("A17 Competitive Moat", "finagent.A17_competitive_moat"),
            ("A18 Investment Thesis", "finagent.A18_investment_thesis"),
            ("A19 Executive Summary", "finagent.A19_executive_summary"),
        ]

        agents_used = []
        summary_parts = [f"Entity: {entity}\n"]

        for label, agent_id in all_agents:
            data = outputs.get(agent_id, {})
            if data and isinstance(data, dict) and "error" not in data:
                agents_used.append(agent_id)
                # Give more space to critical agents
                if agent_id in (
                    "finagent.A18_investment_thesis",
                    "finagent.A19_executive_summary",
                    "finagent.A14_risk_assessment",
                    "finagent.A10_dcf",
                ):
                    max_chars = 2000
                elif agent_id in (
                    "finagent.A11_comps",
                    "finagent.A12_precedent_transactions",
                    "finagent.A13_sum_of_parts",
                    "finagent.A17_competitive_moat",
                ):
                    max_chars = 1500
                else:
                    max_chars = 1000
                summary_parts.append(
                    f"\n## {label} ({agent_id})\n"
                    f"{json.dumps(data, default=str)[:max_chars]}\n"
                )

        # Check for conflicting signals
        thesis = outputs.get("finagent.A18_investment_thesis", {})
        risk = outputs.get("finagent.A14_risk_assessment", {})
        summary = outputs.get("finagent.A19_executive_summary", {})

        conflict_notes = []
        if thesis.get("recommendation") and summary.get("recommendation"):
            if thesis["recommendation"] != summary["recommendation"]:
                conflict_notes.append(
                    f"CONFLICT: A18 recommends '{thesis['recommendation']}' "
                    f"but A19 recommends '{summary['recommendation']}'"
                )

        risk_score = risk.get("overall_risk_score", 0)
        rec = thesis.get("recommendation", "")
        if isinstance(risk_score, (int, float)):
            if risk_score > 75 and rec in ("Strong Buy", "Buy"):
                conflict_notes.append(
                    f"CONFLICT: Risk score is CRITICAL ({risk_score}) "
                    f"but recommendation is '{rec}'"
                )

        if conflict_notes:
            summary_parts.append(
                f"\n## CONFLICTING SIGNALS DETECTED\n"
                + "\n".join(f"- {c}" for c in conflict_notes)
            )

        summary_parts.append(
            f"\n## Metadata\n"
            f"Total agents synthesized: {len(agents_used)}\n"
            f"Agents with errors: {len(outputs) - len(agents_used)}\n"
        )

        messages = [{
            "role": "user",
            "content": (
                "Synthesize ALL the above agent outputs into a formal Investment Committee Memorandum. "
                "This is an INTERNAL decision document — be brutally honest. Reference specific data "
                "points from specific agents. Include a genuine dissenting view / devil's advocate "
                "section that challenges the recommendation. Flag any conflicting signals between agents.\n\n"
                + "".join(summary_parts)
            ),
        }]

        result = await self.call_llm(messages)
        parsed = self.parse_json(result["content"])

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.90,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
            data_sources_accessed=[f"upstream:{aid}" for aid in agents_used],
        )
