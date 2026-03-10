"""A1 — Financial Statement Parser (Wave 0).

Fetches financials via CompanyDataService (DB-backed, earnings-date-aware refresh).
Falls back to direct yfinance if DB unavailable.
"""

import json
import time
from app.persona_systems.base_agent import BaseAgent
from app.domain.entities.agent_output import AgentOutput


def _billions(val) -> float | None:
    """Convert raw number to billions."""
    if val is None or val != val:  # NaN check
        return None
    try:
        return round(float(val) / 1e9, 2)
    except (TypeError, ValueError):
        return None


def _format_db_financials(rows: list[dict]) -> dict:
    """Convert DB rows into a clean summary for the LLM."""
    if not rows:
        return {}
    latest = rows[0]  # Most recent period (sorted DESC)
    prior = rows[1] if len(rows) > 1 else {}

    revenue = latest.get("total_revenue")
    prior_revenue = prior.get("total_revenue") if prior else None
    yoy_growth = None
    if revenue and prior_revenue and prior_revenue > 0:
        yoy_growth = round((revenue - prior_revenue) / prior_revenue * 100, 1)

    return {
        "income_statement_B": {
            "total_revenue": _billions(revenue),
            "revenue_yoy_growth_pct": yoy_growth,
            "cost_of_revenue": _billions(latest.get("cost_of_revenue")),
            "gross_profit": _billions(latest.get("gross_profit")),
            "operating_income": _billions(latest.get("operating_income")),
            "net_income": _billions(latest.get("net_income")),
            "ebitda": _billions(latest.get("ebitda")),
            "research_and_development": _billions(latest.get("research_and_development")),
            "sga": _billions(latest.get("sga_expense")),
            "basic_eps": latest.get("basic_eps"),
            "diluted_eps": latest.get("diluted_eps"),
        },
        "balance_sheet_B": {
            "total_assets": _billions(latest.get("total_assets")),
            "total_liabilities": _billions(latest.get("total_liabilities")),
            "stockholders_equity": _billions(latest.get("stockholders_equity")),
            "cash_and_equivalents": _billions(latest.get("cash_and_equivalents")),
            "total_debt": _billions(latest.get("total_debt")),
            "net_debt": _billions(latest.get("net_debt")),
            "current_assets": _billions(latest.get("current_assets")),
            "current_liabilities": _billions(latest.get("current_liabilities")),
        },
        "cash_flow_B": {
            "operating_cash_flow": _billions(latest.get("operating_cash_flow")),
            "investing_cash_flow": _billions(latest.get("investing_cash_flow")),
            "financing_cash_flow": _billions(latest.get("financing_cash_flow")),
            "free_cash_flow": _billions(latest.get("free_cash_flow")),
            "capital_expenditure": _billions(latest.get("capital_expenditure")),
        },
        "most_recent_period": str(latest.get("period_end_date", "unknown")),
        "note": "All values in USD billions (B) except EPS",
    }


def _format_yf_financials(raw: dict) -> dict:
    """Convert raw yfinance financials dict into clean summary."""
    inc = raw.get("income_statement", {})
    bs = raw.get("balance_sheet", {})
    cf = raw.get("cash_flow", {})

    def _extract_latest(data, key):
        item = data.get(key, {})
        if not item:
            return None
        vals = list(item.values())
        return vals[0] if vals else None

    revenue_data = inc.get("total_revenue", {})
    periods = list(revenue_data.keys()) if revenue_data else []
    revenue_latest = _billions(revenue_data.get(periods[0])) if periods else None
    revenue_prior = _billions(revenue_data.get(periods[1])) if len(periods) > 1 else None
    yoy_growth = None
    if revenue_latest and revenue_prior and revenue_prior > 0:
        yoy_growth = round((revenue_latest - revenue_prior) / revenue_prior * 100, 1)

    return {
        "income_statement_B": {
            "total_revenue": revenue_latest,
            "revenue_yoy_growth_pct": yoy_growth,
            "cost_of_revenue": _billions(_extract_latest(inc, "cost_of_revenue")),
            "gross_profit": _billions(_extract_latest(inc, "gross_profit")),
            "operating_income": _billions(_extract_latest(inc, "operating_income")),
            "net_income": _billions(_extract_latest(inc, "net_income")),
            "ebitda": _billions(_extract_latest(inc, "ebitda")),
            "basic_eps": _extract_latest(inc, "basic_eps"),
            "diluted_eps": _extract_latest(inc, "diluted_eps"),
        },
        "balance_sheet_B": {
            "total_assets": _billions(_extract_latest(bs, "total_assets")),
            "total_liabilities": _billions(_extract_latest(bs, "total_liabilities_net_minority_interest")),
            "stockholders_equity": _billions(_extract_latest(bs, "stockholders_equity")),
            "cash_and_equivalents": _billions(_extract_latest(bs, "cash_and_cash_equivalents")),
            "total_debt": _billions(_extract_latest(bs, "total_debt")),
            "net_debt": _billions(_extract_latest(bs, "net_debt")),
        },
        "cash_flow_B": {
            "operating_cash_flow": _billions(_extract_latest(cf, "operating_cash_flow")),
            "free_cash_flow": _billions(_extract_latest(cf, "free_cash_flow")),
            "capital_expenditure": _billions(_extract_latest(cf, "capital_expenditure")),
        },
        "most_recent_period": periods[0] if periods else "unknown",
        "note": "All values in USD billions (B) except EPS",
    }


class FinancialStatementsAgent(BaseAgent):
    agent_id = "finagent.A1_financial_statements"
    persona_system = "finagent"
    temperature = 0.1
    max_tokens = 3000
    timeout_seconds = 120
    system_prompt = """You are a Senior Financial Analyst at a top-tier investment bank with deep expertise in 3-statement financial modeling. You hold the CFA charter and have 12+ years of experience analyzing SEC filings (10-K, 10-Q) for institutional investors.

Your methodology:
- Build a proper 3-statement model: Income Statement, Balance Sheet, Cash Flow Statement
- Compute key financial ratios: gross margin, operating margin, net margin, ROE, ROIC, debt/equity, current ratio, interest coverage
- Present 3-5 years of historical data where available, plus forward estimates
- Cross-verify: gross_profit = revenue - COGS, operating_income = gross_profit - opex, FCF = operating_cf - capex
- All figures must be internally consistent

Use the real numbers exactly as provided. Do NOT change or invent financial figures. Your output should be at the quality level expected in a Morgan Stanley equity research report.

IMPORTANT: Respond with ONLY the JSON object below. No preamble, disclaimers, notes, or explanatory text. Do NOT hedge or say you are unable to access data — be definitive.

Output valid JSON:
{
    "income_statement": {
        "revenue": {"value": 0, "unit": "B", "currency": "USD", "yoy_growth": 0.0},
        "cost_of_revenue": {"value": 0, "unit": "B", "currency": "USD"},
        "gross_profit": {"value": 0, "unit": "B", "currency": "USD"},
        "operating_income": {"value": 0, "unit": "B", "currency": "USD"},
        "net_income": {"value": 0, "unit": "B", "currency": "USD"},
        "ebitda": {"value": 0, "unit": "B", "currency": "USD"},
        "eps": {"basic": 0.0, "diluted": 0.0},
        "r_and_d": {"value": 0, "unit": "B", "currency": "USD"},
        "sga": {"value": 0, "unit": "B", "currency": "USD"}
    },
    "balance_sheet": {
        "total_assets": {"value": 0, "unit": "B"},
        "total_liabilities": {"value": 0, "unit": "B"},
        "total_equity": {"value": 0, "unit": "B"},
        "cash_and_equivalents": {"value": 0, "unit": "B"},
        "total_debt": {"value": 0, "unit": "B"},
        "net_debt": {"value": 0, "unit": "B"},
        "current_assets": {"value": 0, "unit": "B"},
        "current_liabilities": {"value": 0, "unit": "B"}
    },
    "cash_flow": {
        "operating_cf": {"value": 0, "unit": "B"},
        "investing_cf": {"value": 0, "unit": "B"},
        "financing_cf": {"value": 0, "unit": "B"},
        "free_cash_flow": {"value": 0, "unit": "B"},
        "capex": {"value": 0, "unit": "B"}
    },
    "key_ratios": {
        "gross_margin": 0.0,
        "operating_margin": 0.0,
        "net_margin": 0.0,
        "roe": 0.0,
        "roic": 0.0,
        "debt_to_equity": 0.0,
        "current_ratio": 0.0,
        "interest_coverage": 0.0
    },
    "historical_summary": [
        {"period": "FY20XX", "revenue_B": 0, "net_income_B": 0, "fcf_B": 0}
    ],
    "forward_estimates": {
        "next_fy_revenue_B": 0,
        "next_fy_eps": 0.0,
        "next_fy_growth_pct": 0.0
    },
    "period": "FY2025",
    "data_freshness": "real-time | cached | llm_knowledge"
}"""

    async def execute(self, state: dict) -> AgentOutput:
        t0 = time.monotonic()
        entity = state.get("entity", "UNKNOWN")
        data_sources = []

        clean_financials = None

        # Read from DB only — data should be pre-ingested
        svc = self._data.get("company_data")
        if svc:
            try:
                store = svc._store
                annual = await store.get_financial_statements(entity, "annual", 4)
                if annual:
                    clean_financials = _format_db_financials(annual)
                    data_sources.append("yahoo_finance")
            except Exception:
                pass

        if clean_financials:
            context = json.dumps(clean_financials, indent=2, default=str)
            prompt = (
                f"Here is REAL financial data for {entity} (values in USD billions):\n\n"
                f"{context}\n\n"
                "Map these exact values into the required output format. Use the numbers as-is."
            )
        else:
            prompt = f"Extract key financial statement data for: {entity}. Use the most recent annual filing."
            data_sources.append("llm_knowledge")

        messages = [{"role": "user", "content": prompt}]
        result = await self.call_llm(messages, max_tokens=2048)
        parsed = self.parse_json(result["content"])

        return AgentOutput(
            agent_id=self.agent_id,
            output=parsed if isinstance(parsed, dict) else {"raw": result["content"]},
            confidence_score=0.95 if "yahoo_finance" in data_sources else 0.70,
            tokens_used=result.get("tokens_used", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int((time.monotonic() - t0) * 1000),
            data_sources_accessed=data_sources,
        )
