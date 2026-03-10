"""Port — Document store for RAG retrieval.

Domain defines WHAT it needs. Infrastructure decides HOW (ChromaDB, Pinecone, etc.).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Document:
    """A chunk of text with metadata for retrieval."""
    content: str
    metadata: dict = field(default_factory=dict)
    doc_id: str = ""
    score: float = 0.0


class DocumentStore(ABC):
    @abstractmethod
    async def add_documents(
        self,
        collection: str,
        documents: list[Document],
    ) -> None:
        """Add documents to a named collection."""
        ...

    @abstractmethod
    async def query(
        self,
        collection: str,
        query_text: str,
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[Document]:
        """Retrieve the most relevant documents for a query."""
        ...

    @abstractmethod
    async def delete_collection(self, collection: str) -> None:
        """Delete an entire collection."""
        ...

    @abstractmethod
    async def collection_exists(self, collection: str) -> bool:
        """Check if a collection has documents."""
        ...
