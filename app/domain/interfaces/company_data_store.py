"""Port — company data store interface.

Abstracts the database layer for cached company financial data.
Domain decides WHAT to store/retrieve. Infrastructure decides WHERE (Postgres, SQLite, etc.).
"""

from abc import ABC, abstractmethod
from datetime import datetime


class CompanyDataStore(ABC):
    # ── Profile (A0) ──
    @abstractmethod
    async def get_profile(self, ticker: str) -> dict | None: ...

    @abstractmethod
    async def upsert_profile(self, ticker: str, data: dict) -> None: ...

    # ── Market snapshot (A2) ──
    @abstractmethod
    async def get_market_snapshot(self, ticker: str) -> dict | None: ...

    @abstractmethod
    async def upsert_market_snapshot(self, ticker: str, data: dict) -> None: ...

    # ── Financial statements (A1) ──
    @abstractmethod
    async def get_financial_statements(self, ticker: str, period_type: str = "annual", limit: int = 4) -> list[dict]: ...

    @abstractmethod
    async def upsert_financial_statement(self, ticker: str, period_end_date: str, period_type: str, data: dict) -> None: ...

    # ── News (A4) ──
    @abstractmethod
    async def get_news(self, ticker: str, limit: int = 20) -> list[dict]: ...

    @abstractmethod
    async def replace_news(self, ticker: str, articles: list[dict]) -> None: ...

    # ── Freshness tracking ──
    @abstractmethod
    async def is_stale(self, ticker: str, data_type: str) -> bool: ...

    @abstractmethod
    async def mark_fresh(self, ticker: str, data_type: str, stale_after_seconds: int, next_earnings_date: str | None = None) -> None: ...
