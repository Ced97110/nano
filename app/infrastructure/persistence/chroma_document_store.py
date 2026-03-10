"""Infrastructure adapter — ChromaDB document store for RAG.

Persistent ChromaDB with default embedding function (all-MiniLM-L6-v2).
Collections are partitioned by document type (e.g. "sec_risk_factors", "industry_reports").
"""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import structlog

from app.domain.interfaces.document_store import Document, DocumentStore

logger = structlog.get_logger(__name__)


class ChromaDocumentStore(DocumentStore):
    """ChromaDB-backed vector store for RAG retrieval.

    Supports two modes:
      - Cloud: api_key set → uses chromadb.CloudClient (hosted)
      - Local: no api_key → uses chromadb.PersistentClient (filesystem)

    Lazy initialization — chromadb is only imported and the client
    created on first use, avoiding a 10-30s blocking import at startup.
    """

    def __init__(
        self,
        persist_directory: str = "./chroma_data",
        api_key: str = "",
        tenant: str = "",
        database: str = "",
    ) -> None:
        self._persist_directory = persist_directory
        self._api_key = api_key
        self._tenant = tenant
        self._database = database
        self._client = None
        self._executor = ThreadPoolExecutor(max_workers=2)

    def _get_client(self):
        if self._client is None:
            import chromadb
            if self._api_key:
                kwargs = {"api_key": self._api_key}
                if self._tenant:
                    kwargs["tenant"] = self._tenant
                if self._database:
                    kwargs["database"] = self._database
                self._client = chromadb.CloudClient(**kwargs)
                logger.info("chroma.client.cloud.initialized")
            else:
                self._client = chromadb.PersistentClient(path=self._persist_directory)
                logger.info("chroma.client.local.initialized")
        return self._client

    def _get_collection(self, name: str):
        return self._get_client().get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    async def add_documents(
        self,
        collection: str,
        documents: list[Document],
    ) -> None:
        if not documents:
            return

        col = self._get_collection(collection)

        ids = []
        texts = []
        metadatas = []

        for doc in documents:
            doc_id = doc.doc_id or hashlib.sha256(doc.content.encode()).hexdigest()[:16]
            ids.append(doc_id)
            texts.append(doc.content)
            metadatas.append(doc.metadata or {})

        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            self._executor,
            partial(col.upsert, ids=ids, documents=texts, metadatas=metadatas),
        )
        logger.info("chroma.add_documents", collection=collection, count=len(documents))

    async def query(
        self,
        collection: str,
        query_text: str,
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[Document]:
        try:
            col = self._get_collection(collection)
        except Exception:
            return []

        import asyncio
        loop = asyncio.get_running_loop()

        kwargs = {"query_texts": [query_text], "n_results": n_results}
        if where:
            kwargs["where"] = where

        try:
            results = await loop.run_in_executor(
                self._executor,
                partial(col.query, **kwargs),
            )
        except Exception as exc:
            logger.warning("chroma.query.failed", collection=collection, error=str(exc))
            return []

        docs = []
        if results and results.get("documents"):
            for i, text in enumerate(results["documents"][0]):
                meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                dist = results["distances"][0][i] if results.get("distances") else 0.0
                doc_id = results["ids"][0][i] if results.get("ids") else ""
                docs.append(Document(
                    content=text,
                    metadata=meta,
                    doc_id=doc_id,
                    score=1.0 - dist,  # cosine distance → similarity
                ))

        return docs

    async def delete_collection(self, collection: str) -> None:
        try:
            self._get_client().delete_collection(collection)
            logger.info("chroma.delete_collection", collection=collection)
        except Exception:
            pass

    async def collection_exists(self, collection: str) -> bool:
        try:
            col = self._get_client().get_collection(collection)
            return col.count() > 0
        except Exception:
            return False
