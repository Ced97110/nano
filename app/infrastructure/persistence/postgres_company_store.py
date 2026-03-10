"""Infrastructure adapter — PostgreSQL company data store.

Raw SQL via asyncpg. No ORM.
"""

from datetime import datetime, timezone

import asyncpg
import structlog

from app.domain.interfaces.company_data_store import CompanyDataStore

logger = structlog.get_logger(__name__)


class PostgresCompanyStore(CompanyDataStore):
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── Profile (A0) ──

    async def get_profile(self, ticker: str) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM company_profiles WHERE ticker = $1", ticker.upper()
        )
        return dict(row) if row else None

    async def upsert_profile(self, ticker: str, data: dict) -> None:
        await self._pool.execute("""
            INSERT INTO company_profiles (ticker, company_name, sector, industry, description,
                headquarters, employees, exchange, website, founded, officers, fetched_at, source)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, now(), $12)
            ON CONFLICT (ticker) DO UPDATE SET
                company_name = EXCLUDED.company_name,
                sector = EXCLUDED.sector,
                industry = EXCLUDED.industry,
                description = EXCLUDED.description,
                headquarters = EXCLUDED.headquarters,
                employees = EXCLUDED.employees,
                exchange = EXCLUDED.exchange,
                website = EXCLUDED.website,
                founded = EXCLUDED.founded,
                officers = EXCLUDED.officers,
                fetched_at = now(),
                source = EXCLUDED.source
        """,
            ticker.upper(),
            data.get("company_name", ""),
            data.get("sector"),
            data.get("industry"),
            data.get("description"),
            data.get("headquarters"),
            data.get("employees"),
            data.get("exchange"),
            data.get("website"),
            data.get("founded"),
            _json_str(data.get("officers", [])),
            data.get("source", "yahoo_finance"),
        )

    # ── Market snapshot (A2) ──

    async def get_market_snapshot(self, ticker: str) -> dict | None:
        row = await self._pool.fetchrow(
            "SELECT * FROM market_snapshots WHERE ticker = $1", ticker.upper()
        )
        return dict(row) if row else None

    async def upsert_market_snapshot(self, ticker: str, data: dict) -> None:
        cols = [
            "share_price", "previous_close", "day_high", "day_low",
            "fifty_two_week_high", "fifty_two_week_low", "market_cap", "enterprise_value",
            "volume", "avg_volume", "pe_ratio", "forward_pe", "peg_ratio",
            "price_to_sales", "price_to_book", "ev_to_ebitda", "ev_to_revenue",
            "trailing_eps", "forward_eps", "book_value", "beta",
            "shares_outstanding", "float_shares", "short_ratio", "short_percent_of_float",
            "held_percent_insiders", "held_percent_institutions",
            "dividend_yield", "dividend_rate", "payout_ratio",
            "fifty_day_average", "two_hundred_day_average",
            "target_mean_price", "target_high_price", "target_low_price",
            "recommendation_key", "number_of_analyst_opinions", "currency",
        ]
        placeholders = ", ".join(f"${i+2}" for i in range(len(cols)))
        col_names = ", ".join(cols)
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)

        values = [ticker.upper()]
        for c in cols:
            v = data.get(c)
            # Coerce types for bigint columns
            if c in ("market_cap", "enterprise_value", "volume", "avg_volume", "shares_outstanding", "float_shares"):
                values.append(int(v) if v is not None else None)
            elif c in ("recommendation_key", "currency"):
                values.append(str(v) if v is not None else None)
            elif c == "number_of_analyst_opinions":
                values.append(int(v) if v is not None else None)
            else:
                values.append(float(v) if v is not None else None)

        await self._pool.execute(
            f"""INSERT INTO market_snapshots (ticker, {col_names}, fetched_at, source)
                VALUES ($1, {placeholders}, now(), 'yahoo_finance')
                ON CONFLICT (ticker) DO UPDATE SET
                    {updates}, fetched_at = now(), source = 'yahoo_finance'""",
            *values,
        )

    # ── Financial statements (A1) ──

    async def get_financial_statements(self, ticker: str, period_type: str = "annual", limit: int = 4) -> list[dict]:
        rows = await self._pool.fetch(
            """SELECT * FROM financial_statements
               WHERE ticker = $1 AND period_type = $2
               ORDER BY period_end_date DESC LIMIT $3""",
            ticker.upper(), period_type, limit,
        )
        return [dict(r) for r in rows]

    async def upsert_financial_statement(self, ticker: str, period_end_date: str, period_type: str, data: dict) -> None:
        from datetime import date as date_type
        # Convert string to date object for asyncpg
        if isinstance(period_end_date, str):
            period_end_date = date_type.fromisoformat(period_end_date[:10])

        fin_cols = [
            "total_revenue", "cost_of_revenue", "gross_profit", "operating_income",
            "net_income", "ebitda", "research_and_development", "sga_expense",
            "total_assets", "total_liabilities", "stockholders_equity",
            "cash_and_equivalents", "total_debt", "net_debt",
            "current_assets", "current_liabilities",
            "operating_cash_flow", "investing_cash_flow", "financing_cash_flow",
            "free_cash_flow", "capital_expenditure",
        ]
        float_cols = ["basic_eps", "diluted_eps"]

        placeholders = ", ".join(f"${i+4}" for i in range(len(fin_cols) + len(float_cols)))
        all_cols = fin_cols + float_cols
        col_names = ", ".join(all_cols)
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in all_cols)

        values = [ticker.upper(), period_end_date, period_type]
        for c in fin_cols:
            v = data.get(c)
            values.append(int(v) if v is not None and v == v else None)  # NaN check
        for c in float_cols:
            v = data.get(c)
            values.append(float(v) if v is not None and v == v else None)

        await self._pool.execute(
            f"""INSERT INTO financial_statements (ticker, period_end_date, period_type, {col_names}, fetched_at, source)
                VALUES ($1, $2, $3, {placeholders}, now(), 'yahoo_finance')
                ON CONFLICT (ticker, period_end_date, period_type) DO UPDATE SET
                    {updates}, fetched_at = now()""",
            *values,
        )

    # ── News (A4) ──

    async def get_news(self, ticker: str, limit: int = 20) -> list[dict]:
        rows = await self._pool.fetch(
            """SELECT title, summary, publisher, link, published_at, content_type
               FROM company_news
               WHERE ticker = $1
               ORDER BY fetched_at DESC LIMIT $2""",
            ticker.upper(), limit,
        )
        return [dict(r) for r in rows]

    async def replace_news(self, ticker: str, articles: list[dict]) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM company_news WHERE ticker = $1", ticker.upper())
                for a in articles:
                    pub_at = a.get("publish_time") or a.get("published_at")
                    if isinstance(pub_at, str) and pub_at:
                        try:
                            pub_at = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
                        except ValueError:
                            pub_at = None
                    elif not isinstance(pub_at, datetime):
                        pub_at = None

                    await conn.execute(
                        """INSERT INTO company_news (ticker, title, summary, publisher, link, published_at, content_type, fetched_at, source)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, now(), 'yahoo_finance')""",
                        ticker.upper(),
                        a.get("title", ""),
                        a.get("summary"),
                        a.get("publisher"),
                        a.get("link"),
                        pub_at,
                        a.get("type") or a.get("content_type"),
                    )

    # ── Freshness tracking ──

    async def is_stale(self, ticker: str, data_type: str) -> bool:
        row = await self._pool.fetchrow(
            """SELECT last_fetched_at, stale_after_seconds, next_earnings_date
               FROM data_freshness WHERE ticker = $1 AND data_type = $2""",
            ticker.upper(), data_type,
        )
        if not row:
            return True  # Never fetched → stale

        now = datetime.now(timezone.utc)
        last = row["last_fetched_at"]
        stale_secs = row["stale_after_seconds"]

        # For financials: also check if earnings date has passed
        if data_type == "financials" and row["next_earnings_date"]:
            earnings_date = datetime.combine(
                row["next_earnings_date"],
                datetime.min.time(),
                tzinfo=timezone.utc,
            )
            if now > earnings_date:
                return True

        age = (now - last).total_seconds()
        return age > stale_secs

    async def mark_fresh(self, ticker: str, data_type: str, stale_after_seconds: int, next_earnings_date: str | None = None) -> None:
        earnings = None
        if next_earnings_date:
            try:
                earnings = datetime.fromisoformat(next_earnings_date).date()
            except (ValueError, TypeError):
                pass

        await self._pool.execute(
            """INSERT INTO data_freshness (ticker, data_type, last_fetched_at, stale_after_seconds, next_earnings_date)
               VALUES ($1, $2, now(), $3, $4)
               ON CONFLICT (ticker, data_type) DO UPDATE SET
                   last_fetched_at = now(),
                   stale_after_seconds = EXCLUDED.stale_after_seconds,
                   next_earnings_date = EXCLUDED.next_earnings_date""",
            ticker.upper(), data_type, stale_after_seconds, earnings,
        )


import json as _json

def _json_str(obj) -> str:
    return _json.dumps(obj, default=str)
