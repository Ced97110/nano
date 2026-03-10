"""Composition root — FastAPI application entry-point.

This is the ONLY file that touches both interface and infrastructure layers.
It wires the DI container and mounts the API controller.
"""

import asyncio
import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.container import Container

logger = structlog.get_logger(__name__)

container = Container()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await container.init()
    # Inject use cases into the controller
    from app.interface.api.v1 import analysis_controller, documents_controller
    analysis_controller.configure(
        container.run_analysis, container.stream_analysis,
        container.events, container.llm, container.cache,
        container.audit_store,
    )
    documents_controller.configure(rag=container.rag)
    from app.interface.api.v1 import ingestion_controller
    ingestion_controller.configure(ingestion=container.ingestion)
    logger.info("app.started")

    # Pre-warm watchlist data in the background (non-blocking)
    from app.infrastructure.config import settings
    ingestion_task = None
    if container.ingestion and settings.watchlist:
        logger.info("app.ingestion.starting", tickers=settings.watchlist)
        ingestion_task = asyncio.create_task(
            container.ingestion.ingest_watchlist(
                settings.watchlist,
                concurrency=settings.ingestion_concurrency,
            )
        )

    yield

    if ingestion_task and not ingestion_task.done():
        ingestion_task.cancel()
    await container.shutdown()


app = FastAPI(
    title="Nano Bana Pro — Intelligence API",
    version="0.1.0",
    lifespan=lifespan,
)

_cors_origins = os.getenv("CORS_ORIGINS", "*")
_allowed_origins = (
    [o.strip() for o in _cors_origins.split(",") if o.strip()]
    if _cors_origins != "*"
    else ["*"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the interface-layer routers
from app.interface.api.v1.analysis_controller import router as analysis_router  # noqa: E402
from app.interface.api.v1.auth_controller import router as auth_router  # noqa: E402
from app.interface.api.v1.export_controller import router as export_router  # noqa: E402
from app.interface.api.v1.documents_controller import router as documents_router  # noqa: E402
from app.interface.api.v1.ingestion_controller import router as ingestion_router  # noqa: E402
app.include_router(analysis_router)
app.include_router(auth_router)
app.include_router(export_router)
app.include_router(documents_router)
app.include_router(ingestion_router)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "nanobana-backend"}
