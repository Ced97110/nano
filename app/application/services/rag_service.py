"""Application service — RAG document ingestion and retrieval.

Ingests SEC filings (10-K risk factors, MD&A, proxy statements) and
industry data into ChromaDB, then retrieves relevant chunks for agents.
"""

import hashlib
import re

import structlog

from app.domain.interfaces.document_store import Document, DocumentStore
from app.domain.interfaces.financial_data_repository import FinancialDataRepository

logger = structlog.get_logger(__name__)

# Collection names
COL_RISK_FACTORS = "sec_risk_factors"
COL_MDA = "sec_mda"
COL_PROXY = "sec_proxy"
COL_INDUSTRY = "industry_reports"

# Chunking config
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200


def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks by sentence boundaries."""
    if not text or len(text) < chunk_size:
        return [text] if text else []

    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) > chunk_size and current_chunk:
            chunks.append(current_chunk.strip())
            # Keep overlap from end of current chunk
            words = current_chunk.split()
            overlap_words = []
            overlap_len = 0
            for w in reversed(words):
                if overlap_len + len(w) > overlap:
                    break
                overlap_words.insert(0, w)
                overlap_len += len(w) + 1
            current_chunk = " ".join(overlap_words) + " " + sentence
        else:
            current_chunk += " " + sentence if current_chunk else sentence

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


class RAGService:
    """Manages document ingestion and retrieval for RAG-enhanced agents."""

    def __init__(
        self,
        doc_store: DocumentStore,
        filings_repo: FinancialDataRepository,
    ) -> None:
        self._store = doc_store
        self._filings = filings_repo

    # ── Ingestion ──

    async def ingest_sec_filings(self, ticker: str) -> dict:
        """Ingest 10-K risk factors, MD&A, and proxy statements for a ticker.

        Returns: {"collections_updated": [...], "chunks_added": int}
        """
        ticker = ticker.upper()
        total_chunks = 0
        collections = []

        try:
            filings = await self._filings.get_company_filings(ticker)
        except Exception as exc:
            logger.warning("rag.filings.fetch_failed", ticker=ticker, error=str(exc))
            return {"collections_updated": [], "chunks_added": 0}

        # Ingest 10-K sections
        ten_k = None
        for f in filings if isinstance(filings, list) else [filings]:
            filing_form = ""
            if isinstance(f, dict):
                filing_form = f.get("form", "")
            else:
                filing_form = getattr(f, "form", "")
            if filing_form == "10-K":
                ten_k = f
                break

        if ten_k:
            # Risk factors (Item 1A)
            risk_text = await self._extract_filing_section(ten_k, "risk_factors")
            if risk_text:
                chunks = _chunk_text(risk_text)
                docs = [
                    Document(
                        content=chunk,
                        metadata={
                            "ticker": ticker,
                            "source": "10-K",
                            "section": "risk_factors",
                            "chunk_index": i,
                        },
                        doc_id=f"{ticker}_risk_{hashlib.md5(chunk.encode()).hexdigest()[:8]}",
                    )
                    for i, chunk in enumerate(chunks)
                ]
                await self._store.add_documents(COL_RISK_FACTORS, docs)
                total_chunks += len(docs)
                collections.append(COL_RISK_FACTORS)
                logger.info("rag.ingested", ticker=ticker, section="risk_factors", chunks=len(docs))

            # MD&A (Item 7)
            mda_text = await self._extract_filing_section(ten_k, "mda")
            if mda_text:
                chunks = _chunk_text(mda_text)
                docs = [
                    Document(
                        content=chunk,
                        metadata={
                            "ticker": ticker,
                            "source": "10-K",
                            "section": "mda",
                            "chunk_index": i,
                        },
                        doc_id=f"{ticker}_mda_{hashlib.md5(chunk.encode()).hexdigest()[:8]}",
                    )
                    for i, chunk in enumerate(chunks)
                ]
                await self._store.add_documents(COL_MDA, docs)
                total_chunks += len(docs)
                collections.append(COL_MDA)
                logger.info("rag.ingested", ticker=ticker, section="mda", chunks=len(docs))

        # Ingest proxy statement (DEF 14A)
        proxy = None
        for f in filings if isinstance(filings, list) else [filings]:
            filing_form = ""
            if isinstance(f, dict):
                filing_form = f.get("form", "")
            else:
                filing_form = getattr(f, "form", "")
            if filing_form in ("DEF 14A", "DEFA14A"):
                proxy = f
                break

        if proxy:
            proxy_text = await self._extract_filing_text(proxy)
            if proxy_text:
                chunks = _chunk_text(proxy_text)
                docs = [
                    Document(
                        content=chunk,
                        metadata={
                            "ticker": ticker,
                            "source": "DEF_14A",
                            "section": "proxy",
                            "chunk_index": i,
                        },
                        doc_id=f"{ticker}_proxy_{hashlib.md5(chunk.encode()).hexdigest()[:8]}",
                    )
                    for i, chunk in enumerate(chunks)
                ]
                await self._store.add_documents(COL_PROXY, docs)
                total_chunks += len(docs)
                collections.append(COL_PROXY)
                logger.info("rag.ingested", ticker=ticker, section="proxy", chunks=len(docs))

        return {"collections_updated": collections, "chunks_added": total_chunks}

    # ── Retrieval ──

    async def get_risk_factors(self, ticker: str, query: str, n_results: int = 5) -> list[Document]:
        """Retrieve risk factor chunks relevant to a query."""
        return await self._store.query(
            COL_RISK_FACTORS,
            query_text=query,
            n_results=n_results,
            where={"ticker": ticker.upper()},
        )

    async def get_mda_context(self, ticker: str, query: str, n_results: int = 5) -> list[Document]:
        """Retrieve MD&A chunks relevant to a query."""
        return await self._store.query(
            COL_MDA,
            query_text=query,
            n_results=n_results,
            where={"ticker": ticker.upper()},
        )

    async def get_proxy_context(self, ticker: str, query: str, n_results: int = 5) -> list[Document]:
        """Retrieve proxy statement chunks relevant to a query."""
        return await self._store.query(
            COL_PROXY,
            query_text=query,
            n_results=n_results,
            where={"ticker": ticker.upper()},
        )

    async def get_industry_context(self, query: str, n_results: int = 5) -> list[Document]:
        """Retrieve industry report chunks relevant to a query."""
        return await self._store.query(
            COL_INDUSTRY,
            query_text=query,
            n_results=n_results,
        )

    async def has_filings(self, ticker: str) -> bool:
        """Check if we've already ingested filings for this specific ticker."""
        ticker = ticker.upper()
        try:
            docs = await self._store.query(
                COL_RISK_FACTORS,
                query_text="risk",
                n_results=1,
                where={"ticker": ticker},
            )
            return len(docs) > 0
        except Exception:
            return False

    # ── Filing extraction helpers ──

    async def _extract_filing_section(self, filing, section: str) -> str:
        """Extract a named section from a filing object (edgartools or dict)."""
        try:
            if isinstance(filing, dict):
                return filing.get(section, "")

            # edgartools Filing object
            if hasattr(filing, "sections"):
                sections = filing.sections()
                for s in sections:
                    label = getattr(s, "title", "") or str(s)
                    if section == "risk_factors" and "risk" in label.lower():
                        return s.text if hasattr(s, "text") else str(s)
                    if section == "mda" and ("management" in label.lower() or "md&a" in label.lower()):
                        return s.text if hasattr(s, "text") else str(s)

            # Fallback: try to get full text and extract
            text = await self._extract_filing_text(filing)
            if text and section == "risk_factors":
                match = re.search(
                    r'(?:Item\s*1A[.\s]*Risk\s*Factors)(.*?)(?:Item\s*1B|Item\s*2)',
                    text, re.DOTALL | re.IGNORECASE,
                )
                return match.group(1).strip() if match else ""
            if text and section == "mda":
                match = re.search(
                    r"(?:Item\s*7[.\s]*Management's\s*Discussion)(.*?)(?:Item\s*7A|Item\s*8)",
                    text, re.DOTALL | re.IGNORECASE,
                )
                return match.group(1).strip() if match else ""
        except Exception as exc:
            logger.warning("rag.extract_section.failed", section=section, error=str(exc))
        return ""

    async def _extract_filing_text(self, filing) -> str:
        """Get full text from a filing."""
        try:
            if isinstance(filing, dict):
                return filing.get("text", filing.get("content", ""))
            if hasattr(filing, "text"):
                return filing.text() if callable(filing.text) else filing.text
            if hasattr(filing, "html"):
                html = filing.html() if callable(filing.html) else filing.html
                # Strip HTML tags for plain text
                return re.sub(r'<[^>]+>', ' ', html)
        except Exception as exc:
            logger.warning("rag.extract_text.failed", error=str(exc))
        return ""
