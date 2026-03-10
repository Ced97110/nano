"""Infrastructure adapter -- Tavily web search gateway.

Implements WebSearchGateway using the Tavily API for web and news search.
Features:
  - Async semaphore for rate limiting (max 5 concurrent requests)
  - Redis-backed result caching (1 hour TTL)
  - Graceful degradation: returns empty list on any error
"""

import asyncio
import hashlib
import json
from datetime import datetime, timezone

import structlog

from app.domain.interfaces.web_search import WebSearchGateway

logger = structlog.get_logger(__name__)

CACHE_TTL = 3600  # 1 hour
MAX_CONCURRENT = 5


class TavilySearchGateway(WebSearchGateway):
    """Tavily API-backed web search gateway."""

    def __init__(self, api_key: str, redis_client=None) -> None:
        self._api_key = api_key
        self._redis = redis_client
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        self._client = None

    def _get_client(self):
        """Lazy-init the Tavily client."""
        if self._client is None:
            try:
                from tavily import TavilyClient
                self._client = TavilyClient(api_key=self._api_key)
            except ImportError:
                logger.error("tavily_search.import_error", msg="tavily-python not installed")
                return None
        return self._client

    def _cache_key(self, prefix: str, query: str, **kwargs) -> str:
        raw = f"{prefix}:{query}:{json.dumps(kwargs, sort_keys=True)}"
        return f"websearch:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"

    async def _get_cached(self, key: str) -> list[dict] | None:
        if not self._redis:
            return None
        try:
            data = await self._redis.get(key)
            if data:
                return json.loads(data)
        except Exception:
            pass
        return None

    async def _set_cached(self, key: str, results: list[dict]) -> None:
        if not self._redis:
            return
        try:
            await self._redis.set(key, json.dumps(results, default=str), ex=CACHE_TTL)
        except Exception:
            pass

    async def search(
        self, query: str, max_results: int = 5, search_depth: str = "basic"
    ) -> list[dict]:
        """Search the web via Tavily. Returns list of {title, url, content, score}."""
        cache_key = self._cache_key("search", query, max_results=max_results, depth=search_depth)
        cached = await self._get_cached(cache_key)
        if cached is not None:
            logger.debug("tavily_search.cache_hit", query=query[:80])
            return cached

        client = self._get_client()
        if not client:
            return []

        try:
            async with self._semaphore:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: client.search(
                        query=query,
                        max_results=max_results,
                        search_depth=search_depth,
                    ),
                )

            results = []
            for item in response.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", ""),
                    "score": item.get("score", 0.0),
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                })

            await self._set_cached(cache_key, results)
            logger.info("tavily_search.completed", query=query[:80], results=len(results))
            return results

        except Exception as exc:
            logger.warning("tavily_search.error", query=query[:80], error=str(exc))
            return []

    async def search_news(
        self, query: str, days: int = 7, max_results: int = 5
    ) -> list[dict]:
        """Search recent news via Tavily. Returns list of {title, url, content, published_date, score}."""
        cache_key = self._cache_key("news", query, max_results=max_results, days=days)
        cached = await self._get_cached(cache_key)
        if cached is not None:
            logger.debug("tavily_search.news.cache_hit", query=query[:80])
            return cached

        client = self._get_client()
        if not client:
            return []

        try:
            async with self._semaphore:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: client.search(
                        query=query,
                        max_results=max_results,
                        search_depth="basic",
                        topic="news",
                        days=days,
                    ),
                )

            results = []
            for item in response.get("results", []):
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": item.get("content", ""),
                    "published_date": item.get("published_date", ""),
                    "score": item.get("score", 0.0),
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                })

            await self._set_cached(cache_key, results)
            logger.info("tavily_search.news.completed", query=query[:80], results=len(results))
            return results

        except Exception as exc:
            logger.warning("tavily_search.news.error", query=query[:80], error=str(exc))
            return []
