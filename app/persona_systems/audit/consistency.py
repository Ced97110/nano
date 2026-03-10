"""Layer 2 — Cross-agent consistency checks at wave boundaries.

Deterministic checks that compare outputs between agents to catch contradictions.
Runs at each barrier node after all agents in a wave complete.
"""

import structlog

logger = structlog.get_logger(__name__)


def check_wave_consistency(wave_idx: int, agent_outputs: dict) -> list[str]:
    """Run consistency checks appropriate for the given wave boundary.

    Returns list of warning strings. Empty list = no issues found.
    """
    warnings = []

    if wave_idx == 0:
        warnings.extend(_check_wave0_consistency(agent_outputs))
    elif wave_idx == 1:
        warnings.extend(_check_wave1_consistency(agent_outputs))
    elif wave_idx == 2:
        warnings.extend(_check_wave2_consistency(agent_outputs))
    elif wave_idx == 3:
        warnings.extend(_check_wave3_consistency(agent_outputs))

    return warnings


def _check_wave0_consistency(outputs: dict) -> list[str]:
    """After Wave 0: cross-check profile vs market data vs financials."""
    warnings = []

    profile = outputs.get("finagent.A0_company_profile", {})
    market = outputs.get("finagent.A2_market_data", {})
    financials = outputs.get("finagent.A1_financial_statements", {})

    # Check: market cap should be reasonable relative to revenue
    market_cap = _extract_numeric(market, "market_cap")
    revenue = _extract_revenue(financials)
    if market_cap and revenue and revenue > 0:
        ps_ratio = market_cap / revenue
        if ps_ratio > 200:
            warnings.append(
                f"CONSISTENCY: P/S ratio is {ps_ratio:.0f}x — market_cap ({market_cap:.1f}B) "
                f"vs revenue ({revenue:.1f}B) seems extreme"
            )
        if ps_ratio < 0.01:
            warnings.append(
                f"CONSISTENCY: P/S ratio is {ps_ratio:.4f}x — likely a unit mismatch "
                f"between market_cap and revenue"
            )

    # Check: sector from profile should somewhat align with industry context
    profile_sector = profile.get("sector", "")
    industry = outputs.get("finagent.A3_industry_context", {})
    industry_name = industry.get("industry", "")
    if profile_sector and industry_name:
        # Just log for awareness — sectors and industries can legitimately differ
        if profile_sector.lower() not in industry_name.lower() and industry_name.lower() not in profile_sector.lower():
            logger.debug(
                "audit.sector_industry_mismatch",
                profile_sector=profile_sector,
                industry=industry_name,
            )

    return warnings


def _check_wave1_consistency(outputs: dict) -> list[str]:
    """After Wave 1: cross-check revenue model vs financials, margins vs profitability."""
    warnings = []

    financials = outputs.get("finagent.A1_financial_statements", {})
    revenue_model = outputs.get("finagent.A5_revenue_model", {})
    profitability = outputs.get("finagent.A6_profitability", {})

    # Check: gross margin from profitability agent vs computed from financials
    fin_gross = _safe_get_nested(financials, "income_statement", "gross_profit")
    fin_revenue_val = _safe_get_nested(financials, "income_statement", "revenue")
    if fin_gross and fin_revenue_val:
        gross_val = _val(fin_gross)
        rev_val = _val(fin_revenue_val)
        if gross_val and rev_val and rev_val > 0:
            computed_margin = gross_val / rev_val * 100
            # Profitability agent stores margin under margins.gross_margin
            margins = profitability.get("margins", {})
            gm = margins.get("gross_margin", {}) if isinstance(margins, dict) else {}
            reported_margin = _val(gm) if isinstance(gm, dict) else _extract_numeric(profitability, "gross_margin")
            # Convert decimal to percentage if needed
            if reported_margin is not None and reported_margin < 1:
                reported_margin = reported_margin * 100
            if reported_margin is not None:
                diff = abs(computed_margin - reported_margin)
                if diff > 10:
                    warnings.append(
                        f"CONSISTENCY: Gross margin mismatch — computed from financials: "
                        f"{computed_margin:.1f}%, profitability agent says: {reported_margin:.1f}%"
                    )

    # Check: growth trajectory should be directionally consistent with revenue trend
    growth = outputs.get("finagent.A9_growth_trajectory", {})
    hist_growth = growth.get("historical_growth", {})
    if isinstance(hist_growth, dict):
        rev_growth = hist_growth.get("revenue_cagr_3y") or hist_growth.get("revenue_growth")
        if rev_growth is not None:
            fin_yoy = _safe_get_nested(financials, "income_statement", "revenue", "yoy_growth")
            if fin_yoy is not None and isinstance(rev_growth, (int, float)) and isinstance(fin_yoy, (int, float)):
                # Signs should match (both positive or both negative)
                if (rev_growth > 5 and fin_yoy < -5) or (rev_growth < -5 and fin_yoy > 5):
                    warnings.append(
                        f"CONSISTENCY: Growth agent says revenue CAGR={rev_growth:.1f}% "
                        f"but financials show YoY={fin_yoy:.1f}% — directional conflict"
                    )

    return warnings


def _check_wave2_consistency(outputs: dict) -> list[str]:
    """After Wave 2: cross-check valuation approaches."""
    warnings = []

    dcf = outputs.get("finagent.A10_dcf", {})
    comps = outputs.get("finagent.A11_comps", {})
    market = outputs.get("finagent.A2_market_data", {})

    # Get implied values from each method
    dcf_value = _extract_numeric(dcf, "fair_value_per_share") or _extract_numeric(dcf, "implied_share_price")
    comps_value = _extract_numeric(comps, "implied_value_per_share") or _extract_numeric(comps, "fair_value")
    share_price = _extract_numeric(market, "share_price")

    # Check: DCF and comps shouldn't diverge by more than 100%
    if dcf_value and comps_value and dcf_value > 0 and comps_value > 0:
        ratio = max(dcf_value, comps_value) / min(dcf_value, comps_value)
        if ratio > 3.0:
            warnings.append(
                f"CONSISTENCY: DCF (${dcf_value:.0f}) and comps (${comps_value:.0f}) "
                f"diverge by {ratio:.1f}x — review assumptions"
            )

    # Check: implied values shouldn't be more than 5x current price
    for label, val in [("DCF", dcf_value), ("Comps", comps_value)]:
        if val and share_price and share_price > 0:
            ratio = val / share_price
            if ratio > 5.0 or ratio < 0.1:
                warnings.append(
                    f"CONSISTENCY: {label} implied value (${val:.0f}) is {ratio:.1f}x "
                    f"current price (${share_price:.0f}) — may indicate an error"
                )

    return warnings


def _check_wave3_consistency(outputs: dict) -> list[str]:
    """After Wave 3: cross-check risk vs moat, management vs ESG."""
    warnings = []

    risk = outputs.get("finagent.A14_risk_assessment", {})
    moat = outputs.get("finagent.A17_competitive_moat", {})

    # Check: very high risk + very strong moat is unusual
    risk_score = _extract_numeric(risk, "overall_risk_score")
    moat_rating = moat.get("moat_rating", "")
    if risk_score is not None and isinstance(moat_rating, str):
        if risk_score > 75 and moat_rating.lower() in ("wide", "strong", "very strong"):
            warnings.append(
                f"CONSISTENCY: Risk score is CRITICAL ({risk_score}) but moat is "
                f"'{moat_rating}' — strong moats typically have lower risk"
            )
        if risk_score < 20 and moat_rating.lower() in ("none", "weak", "narrow"):
            warnings.append(
                f"CONSISTENCY: Risk score is STABLE ({risk_score}) but moat is "
                f"'{moat_rating}' — weak moats typically carry more risk"
            )

    # Check: risk tier label matches score range
    risk_tier = risk.get("risk_tier", "")
    if risk_score is not None and risk_tier:
        expected_tier = _score_to_tier(risk_score)
        if expected_tier and risk_tier.upper() != expected_tier:
            warnings.append(
                f"CONSISTENCY: Risk score {risk_score} should be '{expected_tier}' "
                f"but agent labeled it '{risk_tier}'"
            )

    return warnings


# ── Helpers ──

def _extract_numeric(data: dict, key: str) -> float | None:
    """Extract a numeric value from a dict, handling nested value/unit dicts."""
    if not isinstance(data, dict):
        return None
    val = data.get(key)
    if isinstance(val, dict):
        val = val.get("value", val.get("score"))
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            cleaned = val.replace("$", "").replace(",", "").replace("B", "").replace("T", "").strip()
            return float(cleaned)
        except (ValueError, AttributeError):
            pass
    return None


def _extract_revenue(financials: dict) -> float | None:
    """Extract revenue value from A1 financial statements output."""
    inc = financials.get("income_statement", {})
    rev = inc.get("revenue", {})
    if isinstance(rev, dict):
        return _extract_numeric(rev, "value")
    return _extract_numeric(inc, "revenue")


def _safe_get_nested(data: dict, *keys):
    """Safely traverse nested dict keys."""
    current = data
    for k in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(k)
    return current


def _val(item) -> float | None:
    """Extract numeric value from a dict with 'value' key or direct number."""
    if isinstance(item, dict):
        v = item.get("value")
        return float(v) if isinstance(v, (int, float)) else None
    if isinstance(item, (int, float)):
        return float(item)
    return None


def _score_to_tier(score: float) -> str | None:
    """Map 0-100 risk score to tier label."""
    if score < 0 or score > 100:
        return None
    if score <= 25:
        return "STABLE"
    if score <= 50:
        return "WATCH"
    if score <= 75:
        return "ELEVATED"
    return "CRITICAL"
