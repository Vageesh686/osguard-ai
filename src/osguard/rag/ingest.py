"""Fetch, clean, chunk, embed and persist the curated Microsoft corpus."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from osguard.rag.embeddings import LocalSentenceTransformerEmbeddings, get_local_embeddings
from osguard.rag.sources import DEFAULT_SOURCE_CONFIG, DocumentationSource, load_sources
from osguard.privacy import redact_sensitive_text


DEFAULT_INDEX_DIR = Path(__file__).resolve().parents[3] / "data" / "faiss"
MAX_DOCUMENT_BYTES = 2_500_000
DEFAULT_TIMEOUT_SECONDS = 15


class IndexBuildResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    index_dir: str
    document_count: int = 0
    chunk_count: int = 0
    source_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class _Chunk:
    source_id: str
    chunk_id: str
    title: str
    url: str
    os_version: str | None
    category: str
    section: str | None
    text: str


class _TextExtractor(HTMLParser):
    """Extract readable text while dropping navigation and executable markup."""

    _SKIP = {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside"}
    _BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "pre", "blockquote", "br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        if lowered in self._SKIP:
            self._skip_depth += 1
        elif not self._skip_depth and lowered in {"h1", "h2", "h3", "h4"}:
            self.parts.append("\n## ")
        elif not self._skip_depth and lowered in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif not self._skip_depth and lowered in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace("\r", "\n")
    text = re.sub(r"[\t\f\v ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_document_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return clean_text("".join(parser.parts))


def fetch_document(url: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> str:
    """Fetch one already-allowlisted URL with bounded time and response size."""
    request = Request(
        url,
        headers={"User-Agent": "OSGuard-AI documentation index builder/1.0", "Accept": "text/html"},
    )
    with urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise ValueError("Configured documentation source did not return HTML")
        payload = response.read(MAX_DOCUMENT_BYTES + 1)
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise ValueError("Configured documentation source exceeded the size limit")
    return payload.decode("utf-8", errors="replace")


def chunk_document(
    text: str,
    *,
    source: DocumentationSource,
    chunk_size: int = 1400,
    overlap: int = 180,
) -> list[_Chunk]:
    """Split cleaned document text into bounded, section-aware chunks."""
    if chunk_size < 200 or chunk_size > 6000 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Invalid chunk size or overlap")
    lines = [line.strip() for line in clean_text(text).splitlines() if line.strip()]
    chunks: list[_Chunk] = []
    current: list[str] = []
    current_length = 0
    section = source.title
    current_section = section
    chunk_index = 0

    def emit(value: str, current_section: str) -> None:
        nonlocal chunk_index
        value = value.strip()
        if not value:
            return
        chunks.append(
            _Chunk(
                source_id=source.source_id,
                chunk_id=f"{source.source_id}-{chunk_index:04d}",
                title=source.title,
                url=str(source.url),
                os_version=source.os_version,
                category=source.category,
                section=current_section,
                text=value,
            )
        )
        chunk_index += 1

    for line in lines:
        is_heading = line.startswith("## ") or (len(line) < 120 and (
            line in {source.title, "Syntax", "Description", "Examples", "Notes"}
            or line.endswith("?")
        ))
        if is_heading:
            if current:
                emit("\n".join(current), current_section)
                current = []
                current_length = 0
            section = line[3:].strip() if line.startswith("## ") else line
            line = section
            current_section = section
        addition = ("\n" if current else "") + line
        if current and current_length + len(addition) > chunk_size:
            emitted = "\n".join(current)
            emit(emitted, current_section)
            tail = emitted[-overlap:] if overlap else ""
            current = [tail] if tail else []
            current_length = len(tail)
        current.append(line)
        current_length += len(addition)
        while current_length > chunk_size:
            joined = "\n".join(current)
            emit(joined[:chunk_size], current_section)
            remainder = joined[max(0, chunk_size - overlap):]
            current = [remainder] if remainder else []
            current_length = len(remainder)
    if current:
        emit("\n".join(current), section)
    return chunks


def _faiss_and_numpy() -> tuple[Any, Any]:
    import faiss
    import numpy as np

    return faiss, np


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
    ) as stream:
        temp_path = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temp_path.replace(path)


def build_index(
    *,
    source_config: str | Path = DEFAULT_SOURCE_CONFIG,
    index_dir: str | Path = DEFAULT_INDEX_DIR,
    fetcher: Callable[[str], str] = fetch_document,
    embeddings: Any | None = None,
    chunk_size: int = 1400,
    overlap: int = 180,
) -> IndexBuildResult:
    """Build a local cosine-similarity FAISS index from curated sources.

    Source failures are retained in the result. The index is committed only
    after at least one valid chunk has been embedded successfully.
    """
    target = Path(index_dir)
    if target.is_symlink() or (target.exists() and target.is_junction()):
        return IndexBuildResult(
            status="failed", index_dir=str(target),
            errors=["Index directory is a link or junction; choose a local directory."],
        )
    errors: list[str] = []
    documents: list[_Chunk] = []
    loaded_sources: list[str] = []
    try:
        sources = load_sources(source_config)
    except Exception as exc:
        return IndexBuildResult(
            status="failed", index_dir=str(target), errors=[f"Source configuration: {type(exc).__name__}"]
        )

    for source in sources:
        try:
            html = fetcher(str(source.url))
            text = extract_document_text(html)
            if len(text) < 80:
                raise ValueError("No usable document text was extracted")
            source_chunks = chunk_document(
                text, source=source, chunk_size=chunk_size, overlap=overlap
            )
            if not source_chunks:
                raise ValueError("No text chunks were produced")
            documents.extend(source_chunks)
            loaded_sources.append(source.source_id)
        except Exception as exc:
            errors.append(f"{source.source_id}: {type(exc).__name__}: {redact_sensitive_text(str(exc))[:240]}")

    if not documents:
        return IndexBuildResult(
            status="failed", index_dir=str(target), errors=errors or ["No documents were loaded"]
        )

    encoder = embeddings or get_local_embeddings()
    try:
        vectors = encoder.embed_documents([chunk.text for chunk in documents])
        faiss, np = _faiss_and_numpy()
        matrix = np.asarray(vectors, dtype="float32")
        if matrix.ndim != 2 or matrix.shape[0] != len(documents) or matrix.shape[1] == 0:
            raise ValueError("Embedding output has an invalid shape")
        faiss.normalize_L2(matrix)
        index = faiss.IndexFlatIP(int(matrix.shape[1]))
        index.add(matrix)
        target.mkdir(parents=True, exist_ok=True)
        generation = uuid.uuid4().hex
        index_tmp = target / f"index.{generation}.tmp"
        faiss.write_index(index, str(index_tmp))
        manifest = {
            "format_version": 2,
            "producer": "osguard-ai",
            "generation": generation,
            "source_config_sha256": hashlib.sha256(Path(source_config).read_bytes()).hexdigest(),
            "embedding_model": getattr(encoder, "model_name", "injected-test-encoder"),
            "dimension": int(matrix.shape[1]),
            "document_count": len(documents),
            "chunks": [
                {
                    "source_id": chunk.source_id,
                    "chunk_id": chunk.chunk_id,
                    "title": chunk.title,
                    "url": chunk.url,
                    "os_version": chunk.os_version,
                    "category": chunk.category,
                    "section": chunk.section,
                    "passage": chunk.text,
                }
                for chunk in documents
            ],
        }
        index_tmp.replace(target / "index.faiss")
        _atomic_write_json(target / "manifest.json", manifest)
        # Included to detect accidental/no-op persistence mistakes without
        # depending on a native FAISS checksum API.
        checksum = hashlib.sha256((target / "index.faiss").read_bytes()).hexdigest()
        manifest_checksum = hashlib.sha256((target / "manifest.json").read_bytes()).hexdigest()
        _atomic_write_json(
            target / "index.sha256.json",
            {"generation": generation, "sha256": checksum, "manifest_sha256": manifest_checksum},
        )
        from osguard.rag.retriever import clear_index_cache

        clear_index_cache(target)
    except Exception as exc:
        try:
            if "index_tmp" in locals() and index_tmp.exists():
                index_tmp.unlink()
        except OSError:
            pass
        return IndexBuildResult(
            status="partial_failure" if errors else "failed",
            index_dir=str(target),
            document_count=len(loaded_sources),
            chunk_count=0,
            source_ids=loaded_sources,
            errors=errors + [f"Index build: {type(exc).__name__}: {redact_sensitive_text(str(exc))[:240]}"],
        )

    return IndexBuildResult(
        status="partial_success" if errors else "success",
        index_dir=str(target),
        document_count=len(loaded_sources),
        chunk_count=len(documents),
        source_ids=loaded_sources,
        errors=errors,
    )
