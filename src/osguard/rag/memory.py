"""Session-cached cosine retrieval when Smart App Control blocks native FAISS."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore

from osguard.rag.ingest import chunk_document, extract_document_text, fetch_document
from osguard.rag.sources import DEFAULT_SOURCE_CONFIG, load_sources
from osguard.schemas import RetrievedEvidence, RetrievalResult


@dataclass
class _MemoryIndex:
    store: InMemoryVectorStore
    document_count: int
    failed_sources: int


_CACHE: dict[tuple[str, int], _MemoryIndex] = {}
_CACHE_LOCK = RLock()


def clear_memory_cache() -> None:
    """Allow a new session or changed source collection to rebuild the snapshot."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _load_memory_index(source_config: str | Path, embeddings: Any) -> _MemoryIndex:
    key = (str(Path(source_config).resolve()), id(embeddings))
    with _CACHE_LOCK:
        if key in _CACHE:
            return _CACHE[key]

        sources = load_sources(source_config)
        documents: list[Document] = []
        failures = 0
        for source in sources:
            try:
                text = extract_document_text(fetch_document(str(source.url)))
                if len(text) < 80:
                    raise ValueError("No usable document text was extracted")
                chunks = chunk_document(text, source=source)
                if not chunks:
                    raise ValueError("No text chunks were produced")
                documents.extend(
                    Document(
                        id=f"{chunk.source_id}#{chunk.chunk_id}",
                        page_content=chunk.text,
                        metadata={
                            "source_id": chunk.source_id,
                            "chunk_id": chunk.chunk_id,
                            "title": chunk.title,
                            "url": chunk.url,
                            "os_version": chunk.os_version,
                            "category": chunk.category,
                            "section": chunk.section,
                        },
                    )
                    for chunk in chunks
                )
            except (OSError, ValueError, UnicodeError):
                failures += 1

        if not documents:
            raise ValueError("No curated Microsoft documentation could be loaded")
        store = InMemoryVectorStore(embeddings)
        store.add_documents(documents)
        snapshot = _MemoryIndex(store=store, document_count=len(documents), failed_sources=failures)
        _CACHE[key] = snapshot
        return snapshot


def search_in_memory(
    query: str,
    filters: dict[str, str],
    *,
    top_k: int,
    embeddings: Any,
    source_config: str | Path = DEFAULT_SOURCE_CONFIG,
    min_relevance: float,
) -> RetrievalResult:
    """Search the curated corpus with cached vectors and exact metadata filters."""
    try:
        snapshot = _load_memory_index(source_config, embeddings)
        matches = snapshot.store.similarity_search_with_score(
            query,
            k=top_k,
            filter=lambda doc: all(
                str(doc.metadata.get("source_id" if key == "source_id" else key, "")) == value
                for key, value in filters.items()
            ),
        )
        evidence = []
        for doc, score in matches:
            if score < min_relevance:
                continue
            metadata = doc.metadata
            evidence.append(
                RetrievedEvidence(
                    source_id=f"{metadata['source_id']}#{metadata['chunk_id']}",
                    title=metadata["title"],
                    source_url=metadata["url"],
                    os_version=metadata.get("os_version"),
                    passage=doc.page_content,
                    metadata={
                        "document_source_id": metadata["source_id"],
                        "category": metadata["category"],
                        "os_version": metadata.get("os_version"),
                        "section": metadata.get("section"),
                        "chunk_id": metadata["chunk_id"],
                        "relevance_score": round(float(score), 4),
                    },
                )
            )
        note = (
            f" {snapshot.failed_sources} configured source(s) could not be loaded."
            if snapshot.failed_sources else ""
        )
        if not evidence:
            return RetrievalResult(
                status="no_results", query=query, filters=filters, backend="in_memory",
                message="No indexed passage met the relevance and filter criteria." + note,
            )
        return RetrievalResult(
            status="success", query=query, filters=filters, backend="in_memory",
            evidence=evidence, message=f"Retrieved {len(evidence)} relevant passage(s)." + note,
        )
    except Exception as exc:
        return RetrievalResult(
            status="retrieval_error", query=query, filters=filters, backend="unavailable",
            message=f"In-memory documentation retrieval is unavailable ({type(exc).__name__}).",
        )
