"""Null-object implementation of WebSearchGateway.

Returns empty results when no search API key is configured.
Prevents crashes — agents gracefully degrade to LLM-only mode.
"""

from app.domain.interfaces.web_search import WebSearchGateway


class NullSearchGateway(WebSearchGateway):
    """No-op search gateway. Always returns empty results."""

    async def search(
        self, query: str, max_results: int = 5, search_depth: str = "basic"
    ) -> list[dict]:
        return []

    async def search_news(
        self, query: str, days: int = 7, max_results: int = 5
    ) -> list[dict]:
        return []
