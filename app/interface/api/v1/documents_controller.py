"""Interface layer -- FastAPI controller for document upload and management.

Allows users to upload PDF, DOCX, and TXT files which are parsed, chunked,
and stored in ChromaDB for RAG retrieval by agents.
"""

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from app.application.services.rag_service import RAGService, _chunk_text
from app.domain.interfaces.document_store import Document
from app.infrastructure.parsers.document_parser import parse_document
from app.interface.auth import AuthUser, Role, get_current_user, require_role

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

# Collection for user-uploaded documents
COL_USER_UPLOADS = "user_uploads"

# Max file size: 50MB
MAX_FILE_SIZE = 50 * 1024 * 1024

# Injected by the composition root (main.py)
_rag: RAGService | None = None


def configure(rag: RAGService | None = None) -> None:
    """Called once at startup to inject the RAG service."""
    global _rag
    _rag = rag


@router.post("/upload")
async def upload_document(
    user: Annotated[AuthUser, Depends(require_role(Role.analyst))],
    file: UploadFile = File(...),
    collection: str = Query(COL_USER_UPLOADS, description="ChromaDB collection to store in"),
    entity: str = Query("", description="Associated entity/ticker for filtering"),
):
    """Upload a document (PDF, DOCX, TXT) for RAG ingestion.

    The document is parsed, chunked, and stored in ChromaDB.
    Returns document_id, chunk count, and collection name.
    """
    if not _rag:
        raise HTTPException(500, "RAG service not configured")

    # Validate file size
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            413,
            f"File too large: {len(content)} bytes. Max: {MAX_FILE_SIZE} bytes (50MB)",
        )

    if not content:
        raise HTTPException(400, "Empty file")

    # Parse document
    try:
        text = parse_document(
            file_bytes=content,
            filename=file.filename or "",
            content_type=file.content_type or "",
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    if not text.strip():
        raise HTTPException(400, "Document contains no extractable text")

    # Generate document ID
    content_hash = hashlib.sha256(content).hexdigest()[:12]
    document_id = f"doc_{uuid.uuid4().hex[:8]}_{content_hash}"

    # Chunk the text
    chunks = _chunk_text(text)
    if not chunks:
        raise HTTPException(400, "Document could not be chunked — too short or empty")

    # Create Document objects with metadata
    now = datetime.now(timezone.utc).isoformat()
    docs = [
        Document(
            content=chunk,
            metadata={
                "document_id": document_id,
                "filename": file.filename or "unknown",
                "content_type": file.content_type or "unknown",
                "entity": entity.upper() if entity else "",
                "chunk_index": i,
                "total_chunks": len(chunks),
                "uploaded_at": now,
                "source": "user_upload",
            },
            doc_id=f"{document_id}_chunk_{i}",
        )
        for i, chunk in enumerate(chunks)
    ]

    # Store in ChromaDB
    try:
        await _rag._store.add_documents(collection, docs)
    except Exception as exc:
        raise HTTPException(500, f"Failed to store document: {exc}")

    return {
        "document_id": document_id,
        "filename": file.filename,
        "chunks_created": len(docs),
        "collection": collection,
        "entity": entity.upper() if entity else "",
        "total_characters": len(text),
        "uploaded_at": now,
    }


@router.get("/{document_id}")
async def get_document(
    document_id: str,
    user: Annotated[AuthUser, Depends(get_current_user)],
):
    """Return metadata for an uploaded document.

    Queries ChromaDB to find all chunks belonging to this document.
    """
    if not _rag:
        raise HTTPException(500, "RAG service not configured")

    # Search across the user uploads collection for this document's chunks
    try:
        # Use a broad query to find chunks by document_id metadata
        col = _rag._store._get_collection(COL_USER_UPLOADS)

        import asyncio
        from functools import partial

        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(
            None,
            partial(
                col.get,
                where={"document_id": document_id},
                include=["metadatas"],
            ),
        )

        if not results or not results.get("ids"):
            raise HTTPException(404, f"Document not found: {document_id}")

        metadatas = results.get("metadatas", [])
        first_meta = metadatas[0] if metadatas else {}

        return {
            "document_id": document_id,
            "filename": first_meta.get("filename", "unknown"),
            "content_type": first_meta.get("content_type", "unknown"),
            "entity": first_meta.get("entity", ""),
            "total_chunks": len(results["ids"]),
            "uploaded_at": first_meta.get("uploaded_at", ""),
            "collection": COL_USER_UPLOADS,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Failed to retrieve document: {exc}")


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    user: Annotated[AuthUser, Depends(require_role(Role.admin))],
):
    """Remove all chunks for a document from ChromaDB."""
    if not _rag:
        raise HTTPException(500, "RAG service not configured")

    try:
        col = _rag._store._get_collection(COL_USER_UPLOADS)

        import asyncio
        from functools import partial

        loop = asyncio.get_running_loop()

        # First check if document exists
        results = await loop.run_in_executor(
            None,
            partial(
                col.get,
                where={"document_id": document_id},
                include=["metadatas"],
            ),
        )

        if not results or not results.get("ids"):
            raise HTTPException(404, f"Document not found: {document_id}")

        chunk_ids = results["ids"]

        # Delete all chunks
        await loop.run_in_executor(
            None,
            partial(col.delete, ids=chunk_ids),
        )

        return {
            "document_id": document_id,
            "chunks_deleted": len(chunk_ids),
            "status": "deleted",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(500, f"Failed to delete document: {exc}")
