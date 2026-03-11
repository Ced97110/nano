"""Composition root — wires infrastructure to domain interfaces.

This is the ONLY place where concrete implementations are imported
and bound to abstract interfaces. Everything else depends on ports.

Heavy libraries (yfinance, edgartools, langgraph) are deferred to init()
to keep server startup fast (<2s).
"""

from __future__ import annotations

import structlog

from app.infrastructure.config import settings

logger = structlog.get_logger(__name__)


class Container:
    """Dependency injection container.

    Lifecycle:
        container = Container()
        await container.init()       # connect to external services
        ...
        await container.shutdown()   # release connections
    """

    def __init__(self) -> None:
        self._redis = None
        self._pg_pool = None

        # Ports (populated in init)
        self.llm = None
        self.cache = None
        self.events = None
        self.audit_store = None
        self.web_search = None

        # Application services
        self.orchestrator = None
        self.run_analysis = None
        self.stream_analysis = None
        self.company_data = None
        self.rag = None
        self.ingestion = None

    async def init(self) -> None:
        # ── Heavy imports deferred to here (not module level) ──
        import asyncpg
        import redis.asyncio as aioredis

        from app.application.services.company_data_service import CompanyDataService
        from app.application.services.data_ingestion_service import DataIngestionService
        from app.application.services.rag_service import RAGService
        from app.application.use_cases.run_analysis import RunAnalysisUseCase
        from app.application.use_cases.stream_analysis import StreamAnalysisUseCase
        from app.core.orchestrator import Orchestrator
        from app.infrastructure.data.sec_edgar_repository import SECEdgarRepository
        from app.infrastructure.data.yfinance_repository import YFinanceRepository
        from app.infrastructure.llm.openai_gateway import OpenAIGateway
        from app.infrastructure.messaging.redis_event_publisher import RedisEventPublisher
        from app.infrastructure.persistence.chroma_document_store import ChromaDocumentStore
        from app.infrastructure.persistence.postgres_audit_store import PostgresAuditStore
        from app.infrastructure.persistence.postgres_company_store import PostgresCompanyStore
        from app.infrastructure.persistence.redis_cache_repository import RedisCacheRepository
        from app.infrastructure.web.null_search import NullSearchGateway

        # ── LLM adapter (OpenAI-compatible — works with OpenAI, Ollama, etc.) ──
        self.llm = OpenAIGateway(
            default_model=settings.llm_model,
            default_max_tokens=settings.llm_max_tokens,
            base_url=settings.openai_base_url or None,
        )

        # ── Redis ──
        try:
            self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
            await self._redis.ping()
            logger.info("container.redis.connected")
        except Exception as exc:
            logger.warning("container.redis.unavailable", error=str(exc))
            self._redis = None

        if self._redis:
            self.cache = RedisCacheRepository(self._redis)
            self.events = RedisEventPublisher(self._redis)
        else:
            self.cache = _NullCache()
            self.events = _NullEvents()

        # ── PostgreSQL ──
        try:
            self._pg_pool = await asyncpg.create_pool(
                settings.database_url,
                min_size=2,
                max_size=10,
            )
            logger.info("container.postgres.connected")

            # Auto-migrate: run init.sql if tables don't exist yet
            await self._auto_migrate()
        except Exception as exc:
            logger.warning("container.postgres.unavailable", error=str(exc))
            self._pg_pool = None

        # ── Audit store (immutable, append-only, 7-year retention) ──
        if self._pg_pool:
            self.audit_store = PostgresAuditStore(self._pg_pool)
            logger.info("container.audit_store.connected")
        else:
            self.audit_store = _NullAuditStore()

        # ── Data repositories (external API adapters) ──
        market_repo = YFinanceRepository()
        filings_repo = SECEdgarRepository()

        # ── Company data service (DB-backed fetch-through cache) ──
        if self._pg_pool:
            store = PostgresCompanyStore(self._pg_pool)
            self.company_data = CompanyDataService(store, market_repo, filings_repo)
        else:
            self.company_data = None

        # ── ChromaDB document store (RAG — Cloud if api_key set, else local) ──
        doc_store = ChromaDocumentStore(
            persist_directory="./chroma_data",
            api_key=settings.chroma_api_key,
            tenant=settings.chroma_tenant,
            database=settings.chroma_database,
        )
        self.rag = RAGService(doc_store, filings_repo)

        # ── Data Ingestion Service ──
        if self.company_data:
            self.ingestion = DataIngestionService(
                company_data=self.company_data,
                rag=self.rag,
            )

        self.data_repos = {
            "market": market_repo,
            "filings": filings_repo,
            "company_data": self.company_data,
            "rag": self.rag,
            "ingestion": self.ingestion,
        }

        # ── Web search gateway (Tavily or Null) ──
        if settings.tavily_api_key:
            try:
                from app.infrastructure.web.tavily_search import TavilySearchGateway
                self.web_search = TavilySearchGateway(
                    api_key=settings.tavily_api_key,
                    redis_client=self._redis,
                )
                logger.info("container.web_search.tavily_configured")
            except ImportError:
                self.web_search = NullSearchGateway()
                logger.warning("container.web_search.tavily_import_failed")
        else:
            self.web_search = NullSearchGateway()
            logger.info("container.web_search.disabled", msg="No tavily_api_key configured")

        # ── Orchestrator (domain ← infrastructure via DI) ──
        self.orchestrator = Orchestrator(
            llm=self.llm,
            cache=self.cache,
            events=self.events,
            data_repos=self.data_repos,
            audit_store=self.audit_store,
            web_search=self.web_search,
        )

        # ── Use cases ──
        self.run_analysis = RunAnalysisUseCase(self.orchestrator)
        self.stream_analysis = StreamAnalysisUseCase(self.orchestrator, self.events)

    async def _auto_migrate(self) -> None:
        """Run db/init.sql if tables don't exist (idempotent, all CREATE IF NOT EXISTS)."""
        if not self._pg_pool:
            return
        try:
            from pathlib import Path
            init_sql = Path(__file__).resolve().parent.parent.parent / "db" / "init.sql"
            if init_sql.exists():
                sql = init_sql.read_text()
                async with self._pg_pool.acquire() as conn:
                    await conn.execute(sql)
                logger.info("container.auto_migrate.ok")
            else:
                logger.debug("container.auto_migrate.skip", reason="init.sql not found")
        except Exception as exc:
            logger.warning("container.auto_migrate.failed", error=str(exc))

    async def shutdown(self) -> None:
        if self._redis:
            await self._redis.aclose()
            self._redis = None
        if self._pg_pool:
            await self._pg_pool.close()
            self._pg_pool = None


# ── Null-object fallbacks (no Redis → no crash, just no caching/events) ──

class _NullCache:
    async def get_pipeline(self, system_id, entity):
        return None

    async def set_pipeline(self, system_id, entity, data, ttl):
        pass

    async def get_agent(self, agent_id, input_hash):
        return None

    async def set_agent(self, agent_id, input_hash, data, ttl):
        pass


class _NullEvents:
    async def publish(self, channel_id, event):
        pass

    async def subscribe(self, channel_id):
        async def _empty():
            return
            yield  # make it an async generator
        return _empty()

    async def wait_for_input(self, channel_id: str, timeout: float = 300) -> dict | None:
        """No-op HITL wait — returns None immediately (auto-approve)."""
        return None

    async def send_input(self, channel_id: str, data: dict) -> None:
        """No-op HITL send — silently discards input."""
        pass


class _NullAuditStore:
    async def log_event(self, event):
        pass

    async def get_trail(self, workflow_id):
        return []

    async def generate_compliance_report(self, workflow_id):
        return {"workflow_id": workflow_id, "error": "Audit store not configured"}
