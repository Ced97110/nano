"""Data Ingestion Service — pre-fetches all external data before pipeline execution.

Runs at startup and on-demand for new tickers. Populates:
  - PostgreSQL: company_profiles, market_snapshots, financial_statements, company_news
  - ChromaDB: SEC filing sections (risk factors, MD&A, proxy) for RAG

Agents never call external APIs directly — they read from DB/ChromaDB only.
"""

import asyncio

import structlog

from app.application.services.company_data_service import CompanyDataService
from app.application.services.rag_service import RAGService

logger = structlog.get_logger(__name__)


class DataIngestionService:
    """Orchestrates all external data fetching and storage.

    Usage:
        svc = DataIngestionService(company_data, rag)
        await svc.ingest_watchlist(["AAPL", "MSFT", "TSLA"])  # startup
        await svc.ingest_ticker("NVDA")                        # on-demand
    """

    def __init__(
        self,
        company_data: CompanyDataService,
        rag: RAGService | None = None,
    ) -> None:
        self._company_data = company_data
        self._rag = rag
        self._ingesting: set[str] = set()  # tickers currently being ingested

    async def ingest_ticker(self, ticker: str, skip_fresh: bool = True) -> dict:
        """Ingest all data for a single ticker.

        Args:
            ticker: Stock ticker symbol
            skip_fresh: If True, skip data types that are still fresh in DB

        Returns:
            {"ticker": ..., "profile": bool, "market": bool, "financials": bool,
             "news": bool, "rag": bool}
        """
        ticker = ticker.upper()

        if ticker in self._ingesting:
            logger.debug("ingestion.already_running", ticker=ticker)
            return {"ticker": ticker, "skipped": True, "reason": "already_ingesting"}

        self._ingesting.add(ticker)
        result = {"ticker": ticker}

        try:
            # Fetch all data types in parallel via CompanyDataService
            # (it handles freshness checks internally — only fetches if stale)
            profile_task = self._safe_fetch(
                self._company_data.get_profile, ticker, "profile"
            )
            market_task = self._safe_fetch(
                self._company_data.get_market_snapshot, ticker, "market"
            )
            financials_task = self._safe_fetch(
                self._company_data.get_financials, ticker, "financials"
            )
            news_task = self._safe_fetch(
                self._company_data.get_news, ticker, "news"
            )

            outcomes = await asyncio.gather(
                profile_task, market_task, financials_task, news_task,
                return_exceptions=True,
            )

            result["profile"] = not isinstance(outcomes[0], Exception) and bool(outcomes[0])
            result["market"] = not isinstance(outcomes[1], Exception) and bool(outcomes[1])
            result["financials"] = not isinstance(outcomes[2], Exception) and bool(outcomes[2])
            result["news"] = not isinstance(outcomes[3], Exception) and bool(outcomes[3])

            # RAG: ingest SEC filings into ChromaDB (if not already done for this ticker)
            result["rag"] = False
            if self._rag:
                try:
                    has = await self._rag.has_filings(ticker)
                    if not has:
                        logger.info("ingestion.rag.starting", ticker=ticker)
                        rag_result = await self._rag.ingest_sec_filings(ticker)
                        result["rag"] = rag_result.get("chunks_added", 0) > 0
                        logger.info("ingestion.rag.done", ticker=ticker, **rag_result)
                    else:
                        result["rag"] = True  # already ingested
                except Exception as exc:
                    logger.warning("ingestion.rag.failed", ticker=ticker, error=str(exc))

            logger.info("ingestion.ticker.done", **result)
            return result

        finally:
            self._ingesting.discard(ticker)

    async def ingest_watchlist(self, tickers: list[str], concurrency: int = 3) -> dict:
        """Ingest data for a list of tickers with controlled concurrency.

        Args:
            tickers: List of ticker symbols
            concurrency: Max parallel ingestions (avoid rate limiting)

        Returns:
            {"total": int, "succeeded": int, "failed": int, "results": [...]}
        """
        tickers = [t.upper() for t in tickers]
        logger.info("ingestion.watchlist.starting", count=len(tickers), tickers=tickers)

        semaphore = asyncio.Semaphore(concurrency)
        results = []

        async def _bounded_ingest(ticker: str):
            async with semaphore:
                return await self.ingest_ticker(ticker)

        outcomes = await asyncio.gather(
            *[_bounded_ingest(t) for t in tickers],
            return_exceptions=True,
        )

        succeeded = 0
        failed = 0
        for i, outcome in enumerate(outcomes):
            if isinstance(outcome, Exception):
                failed += 1
                results.append({"ticker": tickers[i], "error": str(outcome)})
                logger.error("ingestion.ticker.failed", ticker=tickers[i], error=str(outcome))
            else:
                succeeded += 1
                results.append(outcome)

        summary = {
            "total": len(tickers),
            "succeeded": succeeded,
            "failed": failed,
            "results": results,
        }
        logger.info("ingestion.watchlist.done", total=len(tickers), succeeded=succeeded, failed=failed)
        return summary

    async def ingest_ticker_background(self, ticker: str) -> None:
        """Fire-and-forget ingestion for a new ticker.

        Called when a user requests analysis for a ticker not in the watchlist.
        The pipeline starts immediately with whatever data is available;
        this ensures the data is ready for the next run.
        """
        try:
            await self.ingest_ticker(ticker)
        except Exception as exc:
            logger.error("ingestion.background.failed", ticker=ticker, error=str(exc))

    @staticmethod
    async def _safe_fetch(fn, ticker: str, label: str):
        """Call a fetch function, logging but not raising on failure."""
        try:
            return await fn(ticker)
        except Exception as exc:
            logger.warning(f"ingestion.{label}.failed", ticker=ticker, error=str(exc))
            return None
