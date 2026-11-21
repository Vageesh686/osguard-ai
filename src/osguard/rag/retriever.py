"""Persistent FAISS search with bounded, source-attributed results."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from osguard.rag.embeddings import get_local_embeddings
from osguard.rag.ingest import DEFAULT_INDEX_DIR, _faiss_and_numpy
from osguard.rag.sources import DEFAULT_SOURCE_CONFIG
from osguard.schemas import RetrievedEvidence, RetrievalResult


SUPPORTED_FILTERS = {"category", "os_version", "source_id"}
DEFAULT_TOP_K = 4
MAX_TOP_K = 8
MIN_RELEVANCE = 0.18


@dataclass
class _LoadedIndex:
    index: Any
    chunks: list[dict[str, Any]]
    model_name: str
    stamp: tuple[int, int, int]


_CACHE: dict[str, _LoadedIndex] = {}
_CACHE_LOCK = RLock()
_FAISS_POLICY_BLOCKED = False


def clear_index_cache(index_dir: str | Path | None = None) -> None:
    """Discard a loaded in-memory snapshot after a local index rebuild."""
    global _FAISS_POLICY_BLOCKED
    with _CACHE_LOCK:
        if index_dir is None:
            _CACHE.clear()
            _FAISS_POLICY_BLOCKED = False
        else:
            _CACHE.pop(str(Path(index_dir).resolve()), None)
    from osguard.rag.memory import clear_memory_cache

    clear_memory_cache()


def _is_application_control_block(exc: BaseException) -> bool:
    message = str(exc).casefold()
    return "application control policy" in message and "blocked" in message


def _fallback_search(
    query: str, filters: dict[str, str], *, top_k: int,
    embeddings: Any | None, source_config: str | Path, min_relevance: float,
) -> RetrievalResult:
    from osguard.rag.memory import search_in_memory

    return search_in_memory(
        query, filters, top_k=top_k,
        embeddings=embeddings or get_local_embeddings(),
        source_config=source_config, min_relevance=min_relevance,
    )


def _load_index(index_dir: Path) -> _LoadedIndex:
    faiss_path = index_dir / "index.faiss"
    manifest_path = index_dir / "manifest.json"
    checksum_path = index_dir / "index.sha256.json"
    if not faiss_path.is_file() or not manifest_path.is_file() or not checksum_path.is_file():
        raise FileNotFoundError("The local FAISS index has not been built")
    stat = faiss_path.stat()
    manifest_stat = manifest_path.stat()
    checksum_stat = checksum_path.stat()
    stamp = (stat.st_mtime_ns, manifest_stat.st_mtime_ns, checksum_stat.st_mtime_ns)
    key = str(index_dir.resolve())
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and cached.stamp == stamp:
            return cached

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checksum = json.loads(checksum_path.read_text(encoding="utf-8"))
    if (
        manifest.get("format_version") != 1
        or not manifest.get("generation")
        or manifest.get("generation") != checksum.get("generation")
        or not isinstance(manifest.get("chunks"), list)
    ):
        raise ValueError("Index metadata is incomplete or mismatched")
    digest = hashlib.sha256(faiss_path.read_bytes()).hexdigest()
    if digest != checksum.get("sha256"):
        raise ValueError("FAISS index checksum does not match its manifest")
    faiss, _np = _faiss_and_numpy()
    index = faiss.read_index(str(faiss_path))
    chunks = manifest["chunks"]
    if index.ntotal != len(chunks) or index.d != int(manifest.get("dimension", -1)):
        raise ValueError("FAISS index shape does not match its metadata")
    snapshot = _LoadedIndex(
        index=index,
        chunks=chunks,
        model_name=str(manifest.get("embedding_model", "")),
        stamp=stamp,
    )
    with _CACHE_LOCK:
        _CACHE[key] = snapshot
    return snapshot


def search_documentation(
    query: str,
    optional_filters: dict[str, str] | None = None,
    *,
    top_k: int | None = None,
    index_dir: str | Path = DEFAULT_INDEX_DIR,
    embeddings: Any | None = None,
    min_relevance: float = MIN_RELEVANCE,
    source_config: str | Path = DEFAULT_SOURCE_CONFIG,
) -> RetrievalResult:
    """Return a small structured set of related chunks, or an explicit status.

    Supported exact-match filters are ``category``, ``os_version`` and
    ``source_id``. A missing or corrupt local index never produces mock evidence.
    """
    query_text = query.strip() if isinstance(query, str) else ""
    filters = optional_filters or {}
    if not query_text:
        return RetrievalResult(status="empty_query", query="", message="A non-empty query is required.")
    if len(query_text) > 2000:
        return RetrievalResult(
            status="retrieval_error", query=query_text[:2000], message="The retrieval query exceeds 2000 characters."
        )
    if not isinstance(filters, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) or not value.strip()
        for key, value in filters.items()
    ):
        return RetrievalResult(
            status="unsupported_filters", query=query_text, message="Filters must be non-empty string values."
        )
    unsupported = set(filters) - SUPPORTED_FILTERS
    if unsupported:
        return RetrievalResult(
            status="unsupported_filters",
            query=query_text,
            filters=filters,
            message="Unsupported filter field(s): " + ", ".join(sorted(unsupported)),
        )
    try:
        requested = top_k if top_k is not None else int(os.getenv("OSGUARD_RAG_TOP_K", str(DEFAULT_TOP_K)))
    except (TypeError, ValueError):
        return RetrievalResult(
            status="retrieval_error", query=query_text, filters=filters,
            message="OSGUARD_RAG_TOP_K must be a valid integer.",
        )
    if not isinstance(requested, int) or requested < 1 or requested > MAX_TOP_K:
        return RetrievalResult(
            status="retrieval_error", query=query_text, filters=filters,
            message=f"top_k must be between 1 and {MAX_TOP_K}.",
        )

    global _FAISS_POLICY_BLOCKED
    with _CACHE_LOCK:
        blocked = _FAISS_POLICY_BLOCKED
    if blocked:
        return _fallback_search(
            query_text, filters, top_k=requested, embeddings=embeddings,
            source_config=source_config, min_relevance=min_relevance,
        )

    path = Path(index_dir)
    if not (path / "index.faiss").exists():
        try:
            _faiss_and_numpy()
        except (ImportError, OSError) as exc:
            if _is_application_control_block(exc):
                with _CACHE_LOCK:
                    _FAISS_POLICY_BLOCKED = True
                return _fallback_search(
                    query_text, filters, top_k=requested, embeddings=embeddings,
                    source_config=source_config, min_relevance=min_relevance,
                )
            return RetrievalResult(
                status="retrieval_error", query=query_text, filters=filters,
                backend="unavailable", message=f"FAISS could not be loaded ({type(exc).__name__}).",
            )
        return RetrievalResult(
            status="index_missing", query=query_text, backend="unavailable",
            message="The local documentation index has not been built.", filters=filters,
        )
    try:
        snapshot = _load_index(path)
    except FileNotFoundError:
        return RetrievalResult(
            status="index_missing", query=query_text, backend="unavailable",
            message="The local documentation index is incomplete; rebuild it.", filters=filters,
        )
    except (ImportError, OSError) as exc:
        if _is_application_control_block(exc):
            with _CACHE_LOCK:
                _FAISS_POLICY_BLOCKED = True
            return _fallback_search(
                query_text, filters, top_k=requested, embeddings=embeddings,
                source_config=source_config, min_relevance=min_relevance,
            )
        return RetrievalResult(
            status="index_corrupt" if isinstance(exc, OSError) else "retrieval_error",
            query=query_text, backend="unavailable",
            message=f"The local FAISS index could not be loaded ({type(exc).__name__}).",
            filters=filters,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        return RetrievalResult(
            status="index_corrupt", query=query_text, backend="unavailable",
            message=f"The local documentation index could not be validated ({type(exc).__name__}).",
            filters=filters,
        )
    except Exception as exc:
        return RetrievalResult(
            status="retrieval_error", query=query_text, backend="unavailable",
            message=f"The local FAISS index could not be loaded ({type(exc).__name__}).",
            filters=filters,
        )

    encoder = embeddings or get_local_embeddings()
    configured_model = getattr(encoder, "model_name", snapshot.model_name)
    if configured_model != snapshot.model_name:
        return RetrievalResult(
            status="retrieval_error", query=query_text, backend="unavailable",
            message="The index uses a different embedding model; rebuild it with the configured local model.",
            filters=filters,
        )
    try:
        faiss, np = _faiss_and_numpy()
        vector = np.asarray([encoder.embed_query(query_text)], dtype="float32")
        if vector.ndim != 2 or vector.shape[1] != snapshot.index.d:
            raise ValueError("Query embedding dimension does not match the index")
        faiss.normalize_L2(vector)
        scores, positions = snapshot.index.search(vector, snapshot.index.ntotal)
        evidence: list[RetrievedEvidence] = []
        for score, position in zip(scores[0].tolist(), positions[0].tolist(), strict=True):
            if position < 0 or score < min_relevance:
                continue
            chunk = snapshot.chunks[position]
            metadata = {
                "document_source_id": chunk["source_id"],
                "category": chunk["category"],
                "os_version": chunk.get("os_version"),
                "section": chunk.get("section"),
                "chunk_id": chunk["chunk_id"],
                "relevance_score": round(float(score), 4),
            }
            filter_values = {
                "category": chunk["category"],
                "os_version": chunk.get("os_version"),
                "source_id": chunk["source_id"],
            }
            if any(str(filter_values[name]) != value for name, value in filters.items()):
                continue
            evidence.append(
                RetrievedEvidence(
                    source_id=f"{chunk['source_id']}#{chunk['chunk_id']}",
                    title=chunk["title"],
                    source_url=chunk["url"],
                    os_version=chunk.get("os_version"),
                    passage=chunk["passage"],
                    metadata=metadata,
                )
            )
            if len(evidence) >= requested:
                break
        if not evidence:
            return RetrievalResult(
                status="no_results", query=query_text, backend="faiss",
                message="No indexed passage met the relevance and filter criteria.", filters=filters,
            )
        return RetrievalResult(
            status="success", query=query_text, backend="faiss", evidence=evidence,
            message=f"Retrieved {len(evidence)} relevant passage(s).", filters=filters,
        )
    except Exception as exc:
        return RetrievalResult(
            status="retrieval_error", query=query_text, backend="unavailable",
            message=f"Documentation search failed ({type(exc).__name__}).", filters=filters,
        )
