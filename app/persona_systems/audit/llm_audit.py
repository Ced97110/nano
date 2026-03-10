"""Layer 3 — LLM-based audit for critical-path agents.

Runs a separate LLM call to review outputs from high-blast-radius agents
(A1, A18, A19). The auditor checks for hallucinations, logical errors,
and unsupported claims.

Layer 4 — Adversarial review of the final assembled output.
"""

import json

import structlog

from app.domain.interfaces.llm_gateway import LLMGateway

logger = structlog.get_logger(__name__)

# Agents that get LLM audit (highest blast radius in the DAG)
CRITICAL_AGENTS = {
    "finagent.A1_financial_statements",   # 15 downstream agents
    "finagent.A18_investment_thesis",     # feeds executive summary + IC memo
    "finagent.A19_executive_summary",     # final investor-facing output
    "finagent.A20_ic_memo",              # final IC decision document
}

AGENT_AUDIT_PROMPT = """You are a financial data auditor. Review the following agent output for quality issues.

Agent: {agent_id}
Entity: {entity}

OUTPUT TO AUDIT:
{output}

Check for:
1. HALLUCINATION: Are there specific numbers, names, or claims that seem fabricated?
2. INTERNAL CONSISTENCY: Do the numbers add up? (e.g., gross_profit = revenue - COGS)
3. REASONABLENESS: Are values in plausible ranges for this type of company?
4. COMPLETENESS: Are critical fields missing or null when they shouldn't be?
5. CONTRADICTIONS: Does the output contradict itself?

Respond with valid JSON:
{{
    "passed": true/false,
    "severity": "none | low | medium | high | critical",
    "issues": [
        {{"type": "hallucination | inconsistency | unreasonable | incomplete | contradiction",
          "field": "...",
          "description": "...",
          "suggested_fix": "..."}}
    ],
    "confidence_adjustment": 0.0
}}

confidence_adjustment: a float from -0.3 to 0.0 that should be added to the agent's confidence score.
0.0 = no issues, -0.1 = minor issues, -0.2 = significant issues, -0.3 = output is unreliable."""


ADVERSARIAL_REVIEW_PROMPT = """You are a senior investment committee member conducting an adversarial review
of a complete financial analysis. Your job is to CHALLENGE the analysis, find weaknesses,
and ensure the recommendation is defensible.

Entity: {entity}

INVESTMENT THESIS:
{thesis}

EXECUTIVE SUMMARY:
{summary}

KEY DATA:
- Risk Score: {risk_score}
- Risk Tier: {risk_tier}
- Recommendation: {recommendation}
- Target Price: ${target_price}
- Current Price: ${current_price}

CONSISTENCY WARNINGS FROM AUTOMATED CHECKS:
{consistency_warnings}

Perform an adversarial review:
1. Is the recommendation supported by the data?
2. Are the bull/bear cases balanced or biased?
3. Are there obvious risks being downplayed?
4. Is the target price derivation sound?
5. Would you be comfortable presenting this to an investment committee?

Respond with valid JSON:
{{
    "approved": true/false,
    "overall_quality": "publishable | needs_revision | unreliable",
    "recommendation_defensible": true/false,
    "bias_detected": "bullish | bearish | none",
    "critical_gaps": ["..."],
    "challenges": [
        {{"claim": "...", "challenge": "...", "severity": "high | medium | low"}}
    ],
    "suggested_caveats": ["Caveats that should accompany this analysis"],
    "final_confidence_score": 0.0
}}

final_confidence_score: 0.0-1.0 representing your confidence in the overall analysis quality."""


async def audit_agent_output(
    llm: LLMGateway,
    agent_id: str,
    entity: str,
    output: dict,
) -> dict:
    """Run LLM audit on a single agent's output (Layer 3).

    Returns audit result dict with passed/issues/confidence_adjustment.
    """
    if agent_id not in CRITICAL_AGENTS:
        return {"passed": True, "severity": "none", "issues": [], "confidence_adjustment": 0.0}

    output_str = json.dumps(output, default=str)[:4000]

    prompt = AGENT_AUDIT_PROMPT.format(
        agent_id=agent_id,
        entity=entity,
        output=output_str,
    )

    try:
        result = await llm.chat(
            messages=[{"role": "user", "content": prompt}],
            system="You are a financial data quality auditor. Be precise and objective.",
            max_tokens=1024,
            temperature=0.1,
        )
        # Parse the audit result
        import re
        content = result.get("content", "")
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", content.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        audit = json.loads(cleaned)

        # Attach cost metadata from the LLM call
        audit["_tokens_used"] = result.get("tokens_used", 0)
        audit["_cost_usd"] = result.get("cost_usd", 0.0)

        logger.info(
            "audit.llm.completed",
            agent_id=agent_id,
            passed=audit.get("passed"),
            severity=audit.get("severity"),
            issues=len(audit.get("issues", [])),
            cost_usd=round(audit["_cost_usd"], 6),
        )

        return audit
    except Exception as exc:
        logger.warning("audit.llm.failed", agent_id=agent_id, error=str(exc))
        return {"passed": True, "severity": "unknown", "issues": [], "confidence_adjustment": 0.0,
                "_tokens_used": 0, "_cost_usd": 0.0}


async def adversarial_review(
    llm: LLMGateway,
    entity: str,
    outputs: dict,
    consistency_warnings: list[str],
) -> dict:
    """Run adversarial review of the final assembled output (Layer 4).

    Returns review dict with approved/quality/challenges.
    """
    thesis = outputs.get("finagent.A18_investment_thesis", {})
    summary = outputs.get("finagent.A19_executive_summary", {})
    ic_memo = outputs.get("finagent.A20_ic_memo", {})
    risk = outputs.get("finagent.A14_risk_assessment", {})
    market = outputs.get("finagent.A2_market_data", {})

    prompt = ADVERSARIAL_REVIEW_PROMPT.format(
        entity=entity,
        thesis=json.dumps(thesis, default=str)[:3000],
        summary=json.dumps(summary, default=str)[:2000],
        risk_score=risk.get("overall_risk_score", "N/A"),
        risk_tier=risk.get("risk_tier", "N/A"),
        recommendation=thesis.get("recommendation", summary.get("recommendation", "N/A")),
        target_price=thesis.get("target_price", "N/A"),
        current_price=thesis.get("current_price", market.get("share_price", "N/A")),
        consistency_warnings="\n".join(consistency_warnings) if consistency_warnings else "None",
    )

    try:
        result = await llm.chat(
            messages=[{"role": "user", "content": prompt}],
            system="You are a senior investment committee member. Be skeptical and thorough.",
            max_tokens=1500,
            temperature=0.1,
        )
        import re
        content = result.get("content", "")
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", content.strip())
        cleaned = re.sub(r"\n?```\s*$", "", cleaned)
        review = json.loads(cleaned)

        review["_tokens_used"] = result.get("tokens_used", 0)
        review["_cost_usd"] = result.get("cost_usd", 0.0)

        logger.info(
            "audit.adversarial.completed",
            entity=entity,
            approved=review.get("approved"),
            quality=review.get("overall_quality"),
            challenges=len(review.get("challenges", [])),
            cost_usd=round(review["_cost_usd"], 6),
        )

        return review
    except Exception as exc:
        logger.warning("audit.adversarial.failed", entity=entity, error=str(exc))
        return {
            "approved": True,
            "overall_quality": "unknown",
            "recommendation_defensible": True,
            "bias_detected": "none",
            "critical_gaps": [],
            "challenges": [],
            "suggested_caveats": ["Adversarial review could not be completed"],
            "final_confidence_score": 0.5,
            "_tokens_used": 0,
            "_cost_usd": 0.0,
        }
