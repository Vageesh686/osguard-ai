"""Explicit preparation and status for the existing documentation backends."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Literal

from osguard.privacy import redact_sensitive_text
from osguard.rag import ingest, memory, retriever
from osguard.rag.sources import DEFAULT_SOURCE_CONFIG, load_sources


KnowledgeBaseState = Literal[
    "index_missing", "index_incomplete", "index_corrupt", "embedding_mismatch",
    "faiss_unavailable", "faiss_ready", "fallback_active", "initialization_failed",
]


@dataclass(frozen=True)
class KnowledgeBaseStatus:
    state: KnowledgeBaseState
    backend: Literal["faiss", "in_memory", "unavailable"]
    message: str
    index_dir: str
    document_count: int = 0
    retrieval_verified: bool = False
    errors: tuple[str, ...] = ()
    fallback_allowed: bool = False
    generation: str | None = None


_INITIALIZE_LOCK = RLock()


def _error_summary(errors: tuple[str, ...]) -> str:
    visible = "; ".join(errors[:2])
    remaining = len(errors) - 2
    return f"{visible}; {remaining} more source error(s)" if remaining > 0 else visible


def _probe_query(source_config: str | Path) -> str:
    """Use a configured source title so deterministic and local encoders get a useful vector."""
    try:
        sources = load_sources(source_config)
        if sources:
            return sources[0].title
    except (OSError, ValueError):
        pass
    return "Windows troubleshooting documentation"


def inspect_knowledge_base(
    *, index_dir: str | Path = ingest.DEFAULT_INDEX_DIR,
    source_config: str | Path = DEFAULT_SOURCE_CONFIG,
    embeddings: Any | None = None,
) -> KnowledgeBaseStatus:
    """Inspect native availability and the persistent index without fetching pages."""
    path = Path(index_dir)
    location = str(path.resolve())
    if path.is_symlink() or (path.exists() and path.is_junction()):
        return KnowledgeBaseStatus(
            "initialization_failed", "unavailable",
            "The index directory is a link or junction and cannot be trusted.", location,
        )
    try:
        retriever.refresh_faiss_native_availability()
    except (ImportError, OSError) as exc:
        policy_blocked = retriever._is_application_control_block(exc)
        if policy_blocked and memory.has_cached_memory_index(source_config):
            return KnowledgeBaseStatus(
                "fallback_active", "in_memory",
                "In-memory documentation fallback active; FAISS is blocked by Application Control.",
                location, fallback_allowed=True,
            )
        return KnowledgeBaseStatus(
            "faiss_unavailable", "unavailable",
            f"FAISS native library unavailable ({type(exc).__name__}: {redact_sensitive_text(str(exc))[:200]}).",
            location, fallback_allowed=policy_blocked,
        )
    artifacts = [path / name for name in ("index.faiss", "manifest.json", "index.sha256.json")]
    present = [item.is_file() for item in artifacts]
    if not any(present):
        return KnowledgeBaseStatus(
            "index_missing", "unavailable",
            "FAISS available. Documentation index not built.", location,
        )
    if not all(present):
        return KnowledgeBaseStatus(
            "index_incomplete", "unavailable",
            "The local FAISS index is incomplete; initialize documentation to rebuild it.",
            location,
        )
    try:
        snapshot = retriever._load_index(path)
        encoder = embeddings or retriever.get_local_embeddings()
        if getattr(encoder, "model_name", None) != snapshot.model_name:
            return KnowledgeBaseStatus(
                "embedding_mismatch", "unavailable",
                "The index uses a different embedding model; initialize documentation to rebuild it.",
                location,
            )
    except (ValueError, OSError, TypeError) as exc:
        return KnowledgeBaseStatus(
            "index_corrupt", "unavailable",
            f"The local FAISS index failed validation ({type(exc).__name__}: {redact_sensitive_text(str(exc))[:200]}).",
            location,
        )
    return KnowledgeBaseStatus(
        "faiss_ready", "faiss", "FAISS documentation index validated.",
        location, document_count=len(snapshot.chunks), generation=snapshot.generation,
    )


def initialize_knowledge_base(
    *, index_dir: str | Path = ingest.DEFAULT_INDEX_DIR,
    source_config: str | Path = DEFAULT_SOURCE_CONFIG,
    fetcher: Callable[[str], str] | None = None,
    embeddings: Any | None = None,
) -> KnowledgeBaseStatus:
    """Build only when needed, then verify a real search through the selected backend."""
    with _INITIALIZE_LOCK:
        status = inspect_knowledge_base(
            index_dir=index_dir, source_config=source_config, embeddings=embeddings
        )
        if status.state == "initialization_failed":
            return status
        if status.state == "faiss_unavailable":
            if not status.fallback_allowed:
                return status
            probe = retriever.search_documentation(
                _probe_query(source_config), top_k=1,
                index_dir=index_dir, source_config=source_config,
                embeddings=embeddings, min_relevance=-1.0,
            )
            if probe.status == "success" and probe.backend == "in_memory":
                return KnowledgeBaseStatus(
                    "fallback_active", "in_memory",
                    "In-memory documentation fallback active; one retrieval was verified.",
                    status.index_dir, document_count=len(probe.evidence), retrieval_verified=True,
                )
            return KnowledgeBaseStatus(
                "initialization_failed", "unavailable", probe.message,
                status.index_dir, errors=(probe.message,),
            )
        if status.state == "fallback_active":
            probe = retriever.search_documentation(
                _probe_query(source_config), top_k=1,
                index_dir=index_dir, source_config=source_config,
                embeddings=embeddings, min_relevance=-1.0,
            )
            if probe.status == "success" and probe.backend == "in_memory":
                return KnowledgeBaseStatus(
                    "fallback_active", "in_memory",
                    "In-memory documentation fallback active; one retrieval was verified.",
                    status.index_dir, document_count=len(probe.evidence), retrieval_verified=True,
                )
            return KnowledgeBaseStatus(
                "initialization_failed", "unavailable", probe.message,
                status.index_dir, errors=(probe.message,),
            )
        build_errors: tuple[str, ...] = ()
        if status.state != "faiss_ready":
            result = ingest.build_index(
                index_dir=index_dir, source_config=source_config,
                fetcher=fetcher or ingest.fetch_document, embeddings=embeddings,
            )
            build_errors = tuple(result.errors)
            if result.status not in {"success", "partial_success"}:
                detail = _error_summary(build_errors) or "No documentation could be indexed."
                return KnowledgeBaseStatus(
                    "initialization_failed", "unavailable",
                    f"Documentation initialization failed: {detail}", status.index_dir,
                    errors=build_errors,
                )
            status = inspect_knowledge_base(
                index_dir=index_dir, source_config=source_config, embeddings=embeddings
            )
            if status.state != "faiss_ready":
                return KnowledgeBaseStatus(
                    "initialization_failed", "unavailable",
                    f"Index build completed but validation failed: {status.message}",
                    status.index_dir, errors=build_errors + (status.message,),
                )
        probe = retriever.search_documentation(
            _probe_query(source_config), top_k=1,
            index_dir=index_dir, source_config=source_config,
            embeddings=embeddings, min_relevance=-1.0,
        )
        if probe.status != "success" or probe.backend != "faiss":
            return KnowledgeBaseStatus(
                "initialization_failed", "unavailable",
                f"FAISS index loaded but retrieval verification failed: {probe.message}",
                status.index_dir, errors=build_errors + (probe.message,),
            )
        note = f" {len(build_errors)} source(s) could not be indexed." if build_errors else ""
        return KnowledgeBaseStatus(
            "faiss_ready", "faiss",
            f"FAISS documentation index ready; retrieval verified.{note}",
            status.index_dir, document_count=status.document_count,
            retrieval_verified=True, errors=build_errors, generation=status.generation,
        )
