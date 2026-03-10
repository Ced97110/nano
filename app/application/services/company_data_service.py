"""Application service — company data ingestion & refresh.

Coordinates: check freshness → fetch from source → store in DB → return to agent.
Agents call this service instead of hitting external APIs directly.

Staleness rules:
    profile:     7 days   (604800s) — rarely changes
    market:      15 min   (900s)    — prices move intraday
    financials:  event    (86400s default, but re-fetches when next_earnings_date passes)
    news:        1 hour   (3600s)   — news cycle
"""

import structlog

from app.domain.interfaces.company_data_store import CompanyDataStore
from app.domain.interfaces.market_data_repository import MarketDataRepository
from app.domain.interfaces.financial_data_repository import FinancialDataRepository

logger = structlog.get_logger(__name__)

STALENESS = {
    "profile": 604800,     # 7 days
    "market": 900,         # 15 minutes
    "financials": 86400,   # 1 day (but also event-driven by earnings date)
    "news": 3600,          # 1 hour
}


class CompanyDataService:
    """Fetch-through cache for company data.

    On each call: check DB freshness → if stale, fetch from source API → store → return.
    If source API fails, falls back to stale DB data (better stale than nothing).
    """

    def __init__(
        self,
        store: CompanyDataStore,
        market_repo: MarketDataRepository,
        filings_repo: FinancialDataRepository,
    ) -> None:
        self._store = store
        self._market = market_repo
        self._filings = filings_repo

    async def get_profile(self, ticker: str) -> dict:
        """Return company profile, refreshing from yfinance if stale."""
        ticker = ticker.upper()

        if not await self._store.is_stale(ticker, "profile"):
            cached = await self._store.get_profile(ticker)
            if cached:
                logger.debug("data.profile.fresh", ticker=ticker)
                return cached

        # Fetch fresh
        try:
            data = await self._market.get_company_info(ticker)
            if data and data.get("company_name"):
                await self._store.upsert_profile(ticker, data)
                await self._store.mark_fresh(ticker, "profile", STALENESS["profile"])
                logger.info("data.profile.refreshed", ticker=ticker)
                return data
        except Exception as exc:
            logger.warning("data.profile.fetch_failed", ticker=ticker, error=str(exc))

        # Fallback to stale DB data
        cached = await self._store.get_profile(ticker)
        return cached or {}

    async def get_market_snapshot(self, ticker: str) -> dict:
        """Return market data, refreshing from yfinance if stale (>15 min)."""
        ticker = ticker.upper()

        if not await self._store.is_stale(ticker, "market"):
            cached = await self._store.get_market_snapshot(ticker)
            if cached:
                logger.debug("data.market.fresh", ticker=ticker)
                return cached

        try:
            data = await self._market.get_market_data(ticker)
            if data and data.get("share_price"):
                await self._store.upsert_market_snapshot(ticker, data)

                # Grab next earnings date for financials staleness
                next_earnings = data.get("next_earnings_date")
                await self._store.mark_fresh(ticker, "market", STALENESS["market"])
                logger.info("data.market.refreshed", ticker=ticker)
                return data
        except Exception as exc:
            logger.warning("data.market.fetch_failed", ticker=ticker, error=str(exc))

        cached = await self._store.get_market_snapshot(ticker)
        return cached or {}

    async def get_financials(self, ticker: str) -> dict:
        """Return financial statements, refreshing if stale or earnings have been released."""
        ticker = ticker.upper()

        if not await self._store.is_stale(ticker, "financials"):
            cached = await self._store.get_financial_statements(ticker, "annual", 4)
            quarterly = await self._store.get_financial_statements(ticker, "quarterly", 4)
            if cached:
                logger.debug("data.financials.fresh", ticker=ticker)
                return {"annual": cached, "quarterly": quarterly}

        try:
            raw = await self._market.get_financials(ticker)
            if raw and "income_statement" in raw:
                await self._store_financials(ticker, raw)

                # Get next earnings date from yfinance for refresh trigger
                next_earnings = await self._get_next_earnings(ticker)
                await self._store.mark_fresh(
                    ticker, "financials", STALENESS["financials"],
                    next_earnings_date=next_earnings,
                )
                logger.info("data.financials.refreshed", ticker=ticker)
        except Exception as exc:
            logger.warning("data.financials.fetch_failed", ticker=ticker, error=str(exc))

        annual = await self._store.get_financial_statements(ticker, "annual", 4)
        quarterly = await self._store.get_financial_statements(ticker, "quarterly", 4)
        return {"annual": annual, "quarterly": quarterly}

    async def get_news(self, ticker: str) -> list[dict]:
        """Return recent news, refreshing from yfinance if stale (>1 hour)."""
        ticker = ticker.upper()

        if not await self._store.is_stale(ticker, "news"):
            cached = await self._store.get_news(ticker)
            if cached:
                logger.debug("data.news.fresh", ticker=ticker)
                return cached

        try:
            articles = await self._market.get_news(ticker)
            if articles:
                await self._store.replace_news(ticker, articles)
                await self._store.mark_fresh(ticker, "news", STALENESS["news"])
                logger.info("data.news.refreshed", ticker=ticker, count=len(articles))
                return articles
        except Exception as exc:
            logger.warning("data.news.fetch_failed", ticker=ticker, error=str(exc))

        cached = await self._store.get_news(ticker)
        return cached or []

    # ── Internal helpers ──

    async def _store_financials(self, ticker: str, raw: dict) -> None:
        """Parse yfinance financials DataFrames into DB rows."""
        for period_type, inc_key, bs_key, cf_key in [
            ("annual", "income_statement", "balance_sheet", "cash_flow"),
            ("quarterly", "quarterly_income", "quarterly_balance_sheet", "quarterly_cash_flow"),
        ]:
            inc = raw.get(inc_key, {})
            bs = raw.get(bs_key, {})
            cf = raw.get(cf_key, {})
            if not inc:
                continue

            # Get all period dates from income statement
            first_item = next(iter(inc.values()), {})
            periods = list(first_item.keys()) if isinstance(first_item, dict) else []

            for period_date in periods:
                data = {
                    "total_revenue": _get_val(inc, "total_revenue", period_date),
                    "cost_of_revenue": _get_val(inc, "cost_of_revenue", period_date),
                    "gross_profit": _get_val(inc, "gross_profit", period_date),
                    "operating_income": _get_val(inc, "operating_income", period_date),
                    "net_income": _get_val(inc, "net_income", period_date),
                    "ebitda": _get_val(inc, "ebitda", period_date),
                    "basic_eps": _get_val(inc, "basic_eps", period_date),
                    "diluted_eps": _get_val(inc, "diluted_eps", period_date),
                    "research_and_development": _get_val(inc, "research_and_development", period_date),
                    "sga_expense": _get_val(inc, "selling_general_and_administration", period_date),
                    "total_assets": _get_val(bs, "total_assets", period_date),
                    "total_liabilities": _get_val(bs, "total_liabilities_net_minority_interest", period_date),
                    "stockholders_equity": _get_val(bs, "stockholders_equity", period_date),
                    "cash_and_equivalents": _get_val(bs, "cash_and_cash_equivalents", period_date),
                    "total_debt": _get_val(bs, "total_debt", period_date),
                    "net_debt": _get_val(bs, "net_debt", period_date),
                    "current_assets": _get_val(bs, "current_assets", period_date),
                    "current_liabilities": _get_val(bs, "current_liabilities", period_date),
                    "operating_cash_flow": _get_val(cf, "operating_cash_flow", period_date),
                    "investing_cash_flow": _get_val(cf, "investing_cash_flow", period_date),
                    "financing_cash_flow": _get_val(cf, "financing_cash_flow", period_date),
                    "free_cash_flow": _get_val(cf, "free_cash_flow", period_date),
                    "capital_expenditure": _get_val(cf, "capital_expenditure", period_date),
                }
                # period_date is like "2025-09-30 00:00:00" — extract date part
                date_str = str(period_date)[:10]
                await self._store.upsert_financial_statement(ticker, date_str, period_type, data)

    async def _get_next_earnings(self, ticker: str) -> str | None:
        """Try to get next earnings date from yfinance info."""
        try:
            import yfinance as yf
            import asyncio
            from concurrent.futures import ThreadPoolExecutor

            def _fetch():
                t = yf.Ticker(ticker)
                cal = t.calendar
                if isinstance(cal, dict) and "Earnings Date" in cal:
                    dates = cal["Earnings Date"]
                    if dates:
                        return str(dates[0])[:10]
                return None

            return await asyncio.get_event_loop().run_in_executor(
                ThreadPoolExecutor(max_workers=1), _fetch
            )
        except Exception:
            return None


def _get_val(data: dict, key: str, period: str):
    """Safely extract a value from {key: {period: value}} structure."""
    item = data.get(key, {})
    if not isinstance(item, dict):
        return None
    val = item.get(period)
    if val is None:
        return None
    # NaN check
    try:
        if val != val:
            return None
    except (TypeError, ValueError):
        pass
    return val
