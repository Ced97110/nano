"""Port — market data repository interface.

Provides real-time and historical market data for public equities.
Domain never knows if it's yfinance, Bloomberg, or a mock.
"""

from abc import ABC, abstractmethod


class MarketDataRepository(ABC):
    @abstractmethod
    async def get_company_info(self, ticker: str) -> dict:
        """Return company profile: name, sector, industry, employees, description, officers, etc."""
        ...

    @abstractmethod
    async def get_market_data(self, ticker: str) -> dict:
        """Return current market data: price, market cap, PE, volume, beta, 52w range, etc."""
        ...

    @abstractmethod
    async def get_price_history(self, ticker: str, period: str = "1y") -> list[dict]:
        """Return historical price data as list of {date, open, high, low, close, volume}."""
        ...

    @abstractmethod
    async def get_financials(self, ticker: str) -> dict:
        """Return income statement, balance sheet, cash flow from market data provider."""
        ...

    @abstractmethod
    async def get_news(self, ticker: str) -> list[dict]:
        """Return recent news articles: [{title, publisher, link, publish_time}]."""
        ...
