"""Persistent FAISS search with bounded, source-attributed results."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any
from urllib.parse import urlparse

from osguard.rag.embeddings import get_local_embeddings
from osguard.rag.ingest import DEFAULT_INDEX_DIR, _faiss_and_numpy
from osguard.rag.sources import ALLOWED_SOURCE_HOSTS, DEFAULT_SOURCE_CONFIG
from osguard.schemas import RetrievedEvidence, RetrievalResult


SUPPORTED_FILTERS = {"category", "os_version", "source_id"}
DEFAULT_TOP_K = 4
MAX_TOP_K = 8
MIN_RELEVANCE = 0.18
MAX_INDEX_BYTES = 256_000_000
MAX_MANIFEST_BYTES = 25_000_000
MAX_CHUNKS = 50_000


@dataclass
class _LoadedIndex:
    index: Any
    chunks: list[dict[str, Any]]
    model_name: str
    stamp: tuple[int, int, int]
    generation: str


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


def refresh_faiss_native_availability() -> None:
    """Recheck a former policy failure when explicitly inspecting the index."""
    global _FAISS_POLICY_BLOCKED
    _faiss_and_numpy()
    with _CACHE_LOCK:
        _FAISS_POLICY_BLOCKED = False


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
    if index_dir.is_symlink() or (index_dir.exists() and index_dir.is_junction()):
        raise ValueError("The index directory is a link or junction")
    if not faiss_path.is_file() or not manifest_path.is_file() or not checksum_path.is_file():
        raise FileNotFoundError("The local FAISS index has not been built")
    if any(path.is_symlink() for path in (faiss_path, manifest_path, checksum_path)):
        raise ValueError("Index artifacts must be local regular files")
    if (
        faiss_path.stat().st_size > MAX_INDEX_BYTES
        or manifest_path.stat().st_size > MAX_MANIFEST_BYTES
        or checksum_path.stat().st_size > 4096
    ):
        raise ValueError("Index artifacts exceed local size limits")
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
    if not isinstance(manifest, dict) or not isinstance(checksum, dict):
        raise ValueError("Index metadata must be JSON objects")
    if (
        manifest.get("format_version") != 2
        or manifest.get("producer") != "osguard-ai"
        or not isinstance(manifest.get("generation"), str)
        or re.fullmatch(r"[0-9a-f]{32}", manifest["generation"]) is None
        or manifest.get("generation") != checksum.get("generation")
        or not isinstance(manifest.get("chunks"), list)
        or not isinstance(checksum.get("sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", checksum["sha256"]) is None
        or not isinstance(checksum.get("manifest_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", checksum["manifest_sha256"]) is None
    ):
        raise ValueError("Index metadata is incomplete or mismatched")
    if hashlib.sha256(manifest_path.read_bytes()).hexdigest() != checksum.get("manifest_sha256"):
        raise ValueError("FAISS manifest checksum does not match")
    chunks = manifest["chunks"]
    dimension = manifest.get("dimension")
    if (
        not chunks or len(chunks) > MAX_CHUNKS
        or manifest.get("document_count") != len(chunks)
        or not isinstance(dimension, int) or not 1 <= dimension <= 4096
        or not isinstance(manifest.get("embedding_model"), str)
        or not manifest["embedding_model"]
    ):
        raise ValueError("Index metadata has invalid dimensions or chunk count")
    for chunk in chunks:
        if not isinstance(chunk, dict) or any(
            not isinstance(chunk.get(key), str) or not chunk[key]
            for key in ("source_id", "chunk_id", "title", "url", "category", "passage")
        ):
            raise ValueError("Index metadata contains an invalid chunk")
        url = urlparse(chunk["url"])
        if url.scheme != "https" or url.hostname not in ALLOWED_SOURCE_HOSTS:
            raise ValueError("Index metadata contains an unapproved source URL")
        if not chunk["chunk_id"].startswith(chunk["source_id"] + "-"):
            raise ValueError("Index metadata contains an invalid chunk ID")
        if len(chunk["passage"]) > 6000:
            raise ValueError("Index metadata contains an oversized passage")
    digest = hashlib.sha256(faiss_path.read_bytes()).hexdigest()
    if digest != checksum.get("sha256"):
        raise ValueError("FAISS index checksum does not match its manifest")
    faiss, _np = _faiss_and_numpy()
    index = faiss.read_index(str(faiss_path))
    if index.ntotal != len(chunks) or index.d != dimension:
        raise ValueError("FAISS index shape does not match its metadata")
    snapshot = _LoadedIndex(
        index=index,
        chunks=chunks,
        model_name=str(manifest.get("embedding_model", "")),
        stamp=stamp,
        generation=manifest["generation"],
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
            message=(
                "The local documentation index is incomplete; rebuild it."
                if (path / "manifest.json").exists() or (path / "index.sha256.json").exists()
                else "The local documentation index has not been built."
            ), filters=filters,
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
