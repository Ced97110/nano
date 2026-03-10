"""Infrastructure adapter — yfinance market data repository.

Implements MarketDataRepository using the yfinance library for
real-time stock data, company info, financials, and news.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

import structlog
import yfinance as yf

from app.domain.interfaces.market_data_repository import MarketDataRepository

logger = structlog.get_logger(__name__)
_executor = ThreadPoolExecutor(max_workers=4)


def _safe(val: Any) -> Any:
    """Convert numpy/pandas types to JSON-safe Python types."""
    if val is None:
        return None
    type_name = type(val).__name__
    if type_name in ("int64", "int32", "float64", "float32"):
        return float(val) if "float" in type_name else int(val)
    if type_name == "Timestamp":
        return str(val)
    if type_name == "NaTType":
        return None
    return val


def _df_to_dicts(df, max_rows: int = 0) -> list[dict]:
    """Convert a pandas DataFrame to a list of dicts with safe types."""
    if df is None or df.empty:
        return []
    if max_rows:
        df = df.tail(max_rows)
    rows = []
    for idx, row in df.iterrows():
        d = {"date": str(idx)}
        for col in df.columns:
            d[col.lower().replace(" ", "_")] = _safe(row[col])
        rows.append(d)
    return rows


def _financials_df_to_dict(df) -> dict:
    """Convert a financials DataFrame (rows=items, cols=dates) to dict."""
    if df is None or df.empty:
        return {}
    result = {}
    for item in df.index:
        key = str(item).lower().replace(" ", "_").replace("(", "").replace(")", "")
        values = {}
        for col in df.columns:
            period = str(col)[:10]
            values[period] = _safe(df.loc[item, col])
        result[key] = values
    return result


class YFinanceRepository(MarketDataRepository):
    """Fetches real market data via yfinance (Yahoo Finance)."""

    async def get_company_info(self, ticker: str) -> dict:
        def _fetch():
            t = yf.Ticker(ticker)
            info = t.info or {}
            officers = []
            for o in (info.get("companyOfficers") or [])[:8]:
                officers.append({
                    "name": o.get("name", ""),
                    "title": o.get("title", ""),
                    "age": _safe(o.get("age")),
                    "total_pay": _safe(o.get("totalPay")),
                })
            return {
                "company_name": info.get("longName") or info.get("shortName", ""),
                "ticker": ticker.upper(),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "description": info.get("longBusinessSummary", ""),
                "headquarters": f"{info.get('city', '')}, {info.get('state', '')}, {info.get('country', '')}",
                "employees": _safe(info.get("fullTimeEmployees")),
                "exchange": info.get("exchange", ""),
                "website": info.get("website", ""),
                "officers": officers,
                "founded": info.get("foundedYear"),
            }

        return await asyncio.get_running_loop().run_in_executor(_executor, _fetch)

    async def get_market_data(self, ticker: str) -> dict:
        def _fetch():
            t = yf.Ticker(ticker)
            info = t.info or {}
            return {
                "market_cap": _safe(info.get("marketCap")),
                "share_price": _safe(info.get("currentPrice") or info.get("regularMarketPrice")),
                "previous_close": _safe(info.get("previousClose")),
                "open": _safe(info.get("open") or info.get("regularMarketOpen")),
                "day_high": _safe(info.get("dayHigh") or info.get("regularMarketDayHigh")),
                "day_low": _safe(info.get("dayLow") or info.get("regularMarketDayLow")),
                "fifty_two_week_high": _safe(info.get("fiftyTwoWeekHigh")),
                "fifty_two_week_low": _safe(info.get("fiftyTwoWeekLow")),
                "volume": _safe(info.get("volume") or info.get("regularMarketVolume")),
                "avg_volume": _safe(info.get("averageVolume")),
                "avg_volume_10d": _safe(info.get("averageDailyVolume10Day")),
                "pe_ratio": _safe(info.get("trailingPE")),
                "forward_pe": _safe(info.get("forwardPE")),
                "peg_ratio": _safe(info.get("pegRatio")),
                "price_to_sales": _safe(info.get("priceToSalesTrailing12Months")),
                "price_to_book": _safe(info.get("priceToBook")),
                "ev_to_ebitda": _safe(info.get("enterpriseToEbitda")),
                "ev_to_revenue": _safe(info.get("enterpriseToRevenue")),
                "enterprise_value": _safe(info.get("enterpriseValue")),
                "beta": _safe(info.get("beta")),
                "dividend_yield": _safe(info.get("dividendYield")),
                "dividend_rate": _safe(info.get("dividendRate")),
                "payout_ratio": _safe(info.get("payoutRatio")),
                "trailing_eps": _safe(info.get("trailingEps")),
                "forward_eps": _safe(info.get("forwardEps")),
                "shares_outstanding": _safe(info.get("sharesOutstanding")),
                "float_shares": _safe(info.get("floatShares")),
                "short_ratio": _safe(info.get("shortRatio")),
                "short_percent_of_float": _safe(info.get("shortPercentOfFloat")),
                "held_percent_insiders": _safe(info.get("heldPercentInsiders")),
                "held_percent_institutions": _safe(info.get("heldPercentInstitutions")),
                "book_value": _safe(info.get("bookValue")),
                "fifty_day_average": _safe(info.get("fiftyDayAverage")),
                "two_hundred_day_average": _safe(info.get("twoHundredDayAverage")),
                "target_mean_price": _safe(info.get("targetMeanPrice")),
                "target_high_price": _safe(info.get("targetHighPrice")),
                "target_low_price": _safe(info.get("targetLowPrice")),
                "recommendation_key": info.get("recommendationKey", ""),
                "number_of_analyst_opinions": _safe(info.get("numberOfAnalystOpinions")),
                "currency": info.get("currency", "USD"),
                "data_source": "yahoo_finance",
                "fetched_at": datetime.utcnow().isoformat(),
            }

        return await asyncio.get_running_loop().run_in_executor(_executor, _fetch)

    async def get_price_history(self, ticker: str, period: str = "1y") -> list[dict]:
        def _fetch():
            t = yf.Ticker(ticker)
            hist = t.history(period=period)
            return _df_to_dicts(hist, max_rows=252)

        return await asyncio.get_running_loop().run_in_executor(_executor, _fetch)

    async def get_financials(self, ticker: str) -> dict:
        def _fetch():
            t = yf.Ticker(ticker)
            return {
                "income_statement": _financials_df_to_dict(t.income_stmt),
                "quarterly_income": _financials_df_to_dict(t.quarterly_income_stmt),
                "balance_sheet": _financials_df_to_dict(t.balance_sheet),
                "quarterly_balance_sheet": _financials_df_to_dict(t.quarterly_balance_sheet),
                "cash_flow": _financials_df_to_dict(t.cashflow),
                "quarterly_cash_flow": _financials_df_to_dict(t.quarterly_cashflow),
                "data_source": "yahoo_finance",
                "fetched_at": datetime.utcnow().isoformat(),
            }

        return await asyncio.get_running_loop().run_in_executor(_executor, _fetch)

    async def get_news(self, ticker: str) -> list[dict]:
        def _fetch():
            t = yf.Ticker(ticker)
            news = t.news or []
            result = []
            for item in news[:20]:
                # yfinance news items are nested: {id, content: {title, summary, ...}}
                content = item.get("content", item)
                provider = content.get("provider", {})
                canonical = content.get("canonicalUrl", {})
                result.append({
                    "title": content.get("title", ""),
                    "summary": content.get("summary", ""),
                    "publisher": provider.get("displayName", "") if isinstance(provider, dict) else str(provider),
                    "link": canonical.get("url", "") if isinstance(canonical, dict) else "",
                    "publish_time": content.get("pubDate", ""),
                    "type": content.get("contentType", ""),
                })
            return result

        return await asyncio.get_running_loop().run_in_executor(_executor, _fetch)
