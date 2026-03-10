"""Layer 1 — Deterministic schema validation rules per agent.

Each agent has required keys and optional type constraints.
Validation is fast and runs on every agent output at every barrier.
"""

from typing import Any

# Required top-level keys for each agent's output.
# Format: agent_id -> {key: expected_type_or_None}
# None means any type is accepted, just check presence.
AGENT_SCHEMAS: dict[str, dict[str, type | None]] = {
    # Wave 0
    "finagent.A0_company_profile": {
        "company_name": str,
        "sector": (str, type(None)),
        "industry": (str, type(None)),
    },
    "finagent.A1_financial_statements": {
        "income_statement": dict,
        "balance_sheet": dict,
        "cash_flow": dict,
        "key_ratios": dict,
    },
    "finagent.A2_market_data": {
        "share_price": None,
        "market_cap": None,
    },
    "finagent.A3_industry_context": {
        "industry": str,
        "key_trends": list,
    },
    "finagent.A4_news_sentiment": {
        "overall_sentiment": str,
    },
    # Wave 1
    "finagent.A5_revenue_model": {
        "revenue_segments": None,
    },
    "finagent.A6_profitability": {
        "margins": dict,
    },
    "finagent.A7_balance_sheet": {
        "financial_health_rating": None,
    },
    "finagent.A8_cash_flow": {
        "fcf_analysis": None,
    },
    "finagent.A9_growth_trajectory": {
        "historical_growth": None,
    },
    # Wave 2
    "finagent.A10_dcf": {
        "assumptions": dict,
        "projected_fcf": list,
    },
    "finagent.A11_comps": {
        "peer_group": list,
        "multiple_summary": dict,
        "implied_valuation": dict,
    },
    "finagent.A12_precedent_transactions": {
        "transactions": list,
    },
    "finagent.A13_sum_of_parts": {
        "segments": None,
    },
    # Wave 3
    "finagent.A14_risk_assessment": {
        "overall_risk_score": None,
        "risk_tier": str,
        "risk_dimensions": dict,
        "key_risks": list,
        "risk_matrix": dict,
    },
    "finagent.A15_management_quality": {
        "overall_management_score": None,
    },
    "finagent.A16_esg_governance": {
        "esg_score": None,
    },
    "finagent.A17_competitive_moat": {
        "moat_rating": None,
    },
    # Wave 4
    "finagent.A18_investment_thesis": {
        "recommendation": str,
        "target_price": None,
        "bull_case": dict,
        "bear_case": dict,
    },
    "finagent.A19_executive_summary": {
        "headline": str,
        "recommendation": str,
        "executive_summary": str,
    },
    # Wave 5 — IC Memo
    "finagent.A20_ic_memo": {
        "recommendation": str,
        "conviction_level": str,
        "investment_thesis": dict,
        "valuation_summary": dict,
        "dissenting_view": dict,
    },
}


def validate_schema(agent_id: str, output: dict) -> list[str]:
    """Validate agent output against its schema.

    Returns list of violation strings. Empty list = passed.
    """
    violations = []

    if not isinstance(output, dict):
        return [f"{agent_id}: output is not a dict (got {type(output).__name__})"]

    if "error" in output:
        return [f"{agent_id}: agent returned error: {output['error']}"]

    if "raw" in output and len(output) == 1:
        return [f"{agent_id}: output is unparsed raw text (JSON parsing failed)"]

    schema = AGENT_SCHEMAS.get(agent_id)
    if not schema:
        return []  # No schema defined — skip

    for key, expected_type in schema.items():
        if key not in output:
            violations.append(f"{agent_id}: missing required key '{key}'")
        elif expected_type is not None and not isinstance(output[key], expected_type if isinstance(expected_type, tuple) else (expected_type,)):
            violations.append(
                f"{agent_id}: key '{key}' expected {expected_type}, got {type(output[key]).__name__}"
            )

    return violations
