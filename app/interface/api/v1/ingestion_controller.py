"""Interface layer — data ingestion endpoints.

Allows triggering data ingestion for specific tickers or the full watchlist.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.application.services.data_ingestion_service import DataIngestionService
from app.interface.auth import AuthUser, Role, require_role

router = APIRouter(prefix="/api/v1/ingestion", tags=["ingestion"])

_ingestion: DataIngestionService | None = None


def configure(ingestion: DataIngestionService | None) -> None:
    global _ingestion
    _ingestion = ingestion


class IngestTickerRequest(BaseModel):
    ticker: str


class IngestWatchlistRequest(BaseModel):
    tickers: list[str]
    concurrency: int = 3


@router.post("/ticker")
async def ingest_ticker(
    body: IngestTickerRequest,
    user: Annotated[AuthUser, Depends(require_role(Role.admin))],
):
    """Trigger data ingestion for a single ticker. Returns immediately."""
    if not _ingestion:
        raise HTTPException(500, "Ingestion service not configured")

    # Run in background — don't block the request
    asyncio.create_task(_ingestion.ingest_ticker_background(body.ticker))
    return {"status": "accepted", "ticker": body.ticker.upper()}


@router.post("/ticker/sync")
async def ingest_ticker_sync(
    body: IngestTickerRequest,
    user: Annotated[AuthUser, Depends(require_role(Role.admin))],
):
    """Trigger data ingestion for a single ticker. Waits for completion."""
    if not _ingestion:
        raise HTTPException(500, "Ingestion service not configured")

    result = await _ingestion.ingest_ticker(body.ticker)
    return result


@router.post("/watchlist")
async def ingest_watchlist(
    body: IngestWatchlistRequest,
    user: Annotated[AuthUser, Depends(require_role(Role.admin))],
):
    """Trigger data ingestion for a list of tickers."""
    if not _ingestion:
        raise HTTPException(500, "Ingestion service not configured")

    result = await _ingestion.ingest_watchlist(body.tickers, body.concurrency)
    return result
