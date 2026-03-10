"""Port -- web search gateway interface.

Domain defines WHAT it needs. Infrastructure decides HOW (Tavily, Serper, etc.).
"""

from abc import ABC, abstractmethod


class WebSearchGateway(ABC):
    @abstractmethod
    async def search(
        self, query: str, max_results: int = 5, search_depth: str = "basic"
    ) -> list[dict]:
        """Search the web. Returns list of {title, url, content, score}."""
        ...

    @abstractmethod
    async def search_news(
        self, query: str, days: int = 7, max_results: int = 5
    ) -> list[dict]:
        """Search recent news. Returns list of {title, url, content, published_date, score}."""
        ...
