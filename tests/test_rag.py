"""FAISS RAG unit tests use deterministic embeddings and a local FAISS test double."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from osguard.rag import ingest, memory, retriever
from osguard.rag.retriever import search_documentation
from osguard.rag.sources import load_sources


class _FakeIndex:
    def __init__(self, dimension):
        self.d = dimension
        self.vectors = np.zeros((0, dimension), dtype="float32")
        self.ntotal = 0

    def add(self, vectors):
        self.vectors = np.asarray(vectors, dtype="float32")
        self.ntotal = len(self.vectors)

    def search(self, query, count):
        scores = np.asarray(query, dtype="float32") @ self.vectors.T
        order = np.argsort(scores[0])[::-1][:count]
        found = scores[0][order]
        if len(order) < count:
            pad = count - len(order)
            found = np.pad(found, (0, pad), constant_values=-1)
            order = np.pad(order, (0, pad), constant_values=-1)
        return found.reshape(1, -1), order.reshape(1, -1)


class _FakeFaiss:
    IndexFlatIP = _FakeIndex

    @staticmethod
    def normalize_L2(matrix):
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1
        matrix /= norms

    @staticmethod
    def write_index(index, path):
        Path(path).write_text(json.dumps(index.vectors.tolist()), encoding="utf-8")

    @staticmethod
    def read_index(path):
        vectors = np.asarray(json.loads(Path(path).read_text(encoding="utf-8")), dtype="float32")
        index = _FakeIndex(vectors.shape[1])
        index.add(vectors)
        return index


class _FakeEmbeddings:
    model_name = "test-hash-encoder"
    dimensions = {"process": 0, "cpu": 1, "memory": 2, "disk": 3, "service": 4}

    def _embed(self, text):
        vector = np.zeros(5, dtype="float32")
        for word, dimension in self.dimensions.items():
            if word in text.casefold():
                vector[dimension] = 1
        return vector.tolist()

    def embed_documents(self, texts):
        return [self._embed(text) for text in texts]

    def embed_query(self, text):
        return self._embed(text)


@pytest.fixture(autouse=True)
def reset_retrieval_caches():
    retriever.clear_index_cache()
    yield
    retriever.clear_index_cache()


@pytest.fixture
def fake_faiss(monkeypatch):
    bridge = lambda: (_FakeFaiss, np)
    monkeypatch.setattr(ingest, "_faiss_and_numpy", bridge)
    monkeypatch.setattr(retriever, "_faiss_and_numpy", bridge)


def _source_config(path: Path, *, url="https://learn.microsoft.com/test"):
    path.write_text(
        json.dumps([
            {
                "source_id": "cpu-process-doc",
                "title": "CPU and process guidance",
                "url": url,
                "os_version": "Windows 11",
                "category": "process_cpu",
            }
        ]),
        encoding="utf-8",
    )
    return path


def test_source_config_only_loads_allowlisted_https_microsoft_sources(tmp_path):
    config = _source_config(tmp_path / "sources.json")
    assert load_sources(config)[0].source_id == "cpu-process-doc"
    malicious = _source_config(config, url="https://example.com/guide")
    with pytest.raises(ValueError, match="approved Microsoft host"):
        load_sources(malicious)


def test_html_extraction_cleans_navigation_and_chunks_preserve_sections(tmp_path):
    source = load_sources(_source_config(tmp_path / "sources.json"))[0]
    text = ingest.extract_document_text(
        "<nav>Skip navigation</nav><main><h1>CPU process</h1>"
        "<p>Process CPU measurements can help find resource use.</p>"
        "<h2>Memory</h2><p>Memory values are read-only.</p></main>"
    )
    assert "Skip navigation" not in text
    chunks = ingest.chunk_document(text, source=source, chunk_size=200, overlap=20)
    assert chunks
    assert chunks[0].section == "CPU process"
    assert all(chunk.url == str(source.url) and chunk.source_id == source.source_id for chunk in chunks)


def test_build_load_search_and_preserve_document_metadata(tmp_path, fake_faiss):
    config = _source_config(tmp_path / "sources.json")
    index_dir = tmp_path / "index"
    html = "<main><h1>CPU process reference</h1><p>Process CPU observations are useful for troubleshooting.</p></main>"
    build = ingest.build_index(
        source_config=config,
        index_dir=index_dir,
        fetcher=lambda _url: html,
        embeddings=_FakeEmbeddings(),
    )
    assert build.status == "success"
    assert build.document_count == 1
    assert build.chunk_count >= 1

    result = search_documentation(
        "CPU process", index_dir=index_dir, embeddings=_FakeEmbeddings(), top_k=2
    )
    assert result.status == "success"
    assert result.backend == "faiss"
    evidence = result.evidence[0]
    assert evidence.source_id.startswith("cpu-process-doc#")
    assert evidence.title == "CPU and process guidance"
    assert evidence.source_url == "https://learn.microsoft.com/test"
    assert evidence.os_version == "Windows 11"
    assert evidence.metadata["category"] == "process_cpu"
    assert evidence.metadata["section"] == "CPU process reference"
    assert 0 <= evidence.metadata["relevance_score"] <= 1
    assert "Process CPU" in evidence.passage


def test_missing_corrupt_no_result_and_invalid_query_statuses(tmp_path, fake_faiss):
    missing = search_documentation("cpu", index_dir=tmp_path / "not-built")
    assert missing.status == "index_missing"
    assert search_documentation("  ", index_dir=tmp_path).status == "empty_query"
    assert search_documentation("cpu", {"unsupported": "x"}, index_dir=tmp_path).status == "unsupported_filters"

    config = _source_config(tmp_path / "sources.json")
    index_dir = tmp_path / "index"
    ingest.build_index(
        source_config=config,
        index_dir=index_dir,
        fetcher=lambda _url: "<main><h1>CPU Process</h1><p>Process and CPU diagnostics use bounded measurements to support troubleshooting without establishing a root cause.</p></main>",
        embeddings=_FakeEmbeddings(),
    )
    no_results = search_documentation(
        "unrelated text", index_dir=index_dir, embeddings=_FakeEmbeddings(), min_relevance=0.9
    )
    assert no_results.status == "no_results"
    assert search_documentation(
        "cpu", index_dir=index_dir, embeddings=_FakeEmbeddings(), top_k=99
    ).status == "retrieval_error"

    (index_dir / "index.faiss").write_text("corrupt", encoding="utf-8")
    retriever.clear_index_cache(index_dir)
    assert search_documentation("cpu", index_dir=index_dir, embeddings=_FakeEmbeddings()).status == "index_corrupt"


def test_metadata_filters_apply_exactly_after_similarity_search(tmp_path, fake_faiss):
    config = _source_config(tmp_path / "sources.json")
    index_dir = tmp_path / "index"
    ingest.build_index(
        source_config=config,
        index_dir=index_dir,
        fetcher=lambda _url: "<main><h1>CPU process</h1><p>Process CPU notes describe measurements and limits, but do not establish the cause of a high utilization report.</p></main>",
        embeddings=_FakeEmbeddings(),
    )
    found = search_documentation(
        "cpu process", {"category": "process_cpu"}, index_dir=index_dir,
        embeddings=_FakeEmbeddings(),
    )
    assert found.status == "success"
    assert search_documentation(
        "cpu process", {"category": "storage_filesystem"}, index_dir=index_dir,
        embeddings=_FakeEmbeddings(),
    ).status == "no_results"


def test_policy_block_uses_cached_cosine_fallback_and_preserves_provenance(tmp_path, monkeypatch):
    config = _source_config(tmp_path / "sources.json")
    attempts = {"faiss": 0, "fetch": 0, "embed_documents": 0}

    def blocked_faiss():
        attempts["faiss"] += 1
        raise ImportError("DLL load failed: An Application Control policy has blocked this file.")

    def fetch(_url):
        attempts["fetch"] += 1
        return "<main><h1>CPU process reference</h1><p>Process CPU measurements help investigate high CPU usage without proving a root cause.</p></main>"

    class CountingEmbeddings(_FakeEmbeddings):
        def embed_documents(self, texts):
            attempts["embed_documents"] += 1
            return super().embed_documents(texts)

    monkeypatch.setattr(retriever, "_faiss_and_numpy", blocked_faiss)
    monkeypatch.setattr(memory, "fetch_document", fetch)
    encoder = CountingEmbeddings()
    kwargs = {"index_dir": tmp_path / "missing", "source_config": config, "embeddings": encoder}

    first = search_documentation("CPU process", {"source_id": "cpu-process-doc"}, top_k=1, **kwargs)
    second = search_documentation("process", top_k=1, **kwargs)
    assert first.status == second.status == "success"
    assert first.backend == second.backend == "in_memory"
    assert len(first.evidence) == 1
    evidence = first.evidence[0]
    assert evidence.source_id.startswith("cpu-process-doc#cpu-process-doc-")
    assert evidence.title == "CPU and process guidance"
    assert evidence.source_url == "https://learn.microsoft.com/test"
    assert evidence.os_version == "Windows 11"
    assert evidence.metadata["document_source_id"] == "cpu-process-doc"
    assert evidence.metadata["category"] == "process_cpu"
    assert evidence.metadata["section"] == "CPU process reference"
    assert evidence.metadata["chunk_id"] in evidence.source_id
    assert evidence.metadata["relevance_score"] > 0
    assert attempts == {"faiss": 1, "fetch": 1, "embed_documents": 1}

    absent = search_documentation("CPU", {"category": "storage_filesystem"}, **kwargs)
    assert absent.status == "no_results"
    assert absent.backend == "in_memory"
    assert absent.evidence == []


def test_fallback_fails_without_documents_and_never_invents_evidence(tmp_path, monkeypatch):
    config = _source_config(tmp_path / "sources.json")
    monkeypatch.setattr(
        retriever, "_faiss_and_numpy",
        lambda: (_ for _ in ()).throw(ImportError("Application Control policy has blocked this file")),
    )
    monkeypatch.setattr(memory, "fetch_document", lambda _url: (_ for _ in ()).throw(OSError("offline")))
    result = search_documentation(
        "CPU", index_dir=tmp_path / "missing", source_config=config, embeddings=_FakeEmbeddings()
    )
    assert result.status == "retrieval_error"
    assert result.backend == "unavailable"
    assert result.evidence == []


def test_existing_faiss_index_uses_fallback_only_when_native_load_is_blocked(
    tmp_path, monkeypatch, fake_faiss
):
    config = _source_config(tmp_path / "sources.json")
    index_dir = tmp_path / "index"
    html = "<main><h1>CPU process reference</h1><p>Process CPU measurements help investigate high CPU usage without proving a root cause.</p></main>"
    assert ingest.build_index(
        source_config=config, index_dir=index_dir,
        fetcher=lambda _url: html, embeddings=_FakeEmbeddings(),
    ).status == "success"

    monkeypatch.setattr(
        retriever, "_faiss_and_numpy",
        lambda: (_ for _ in ()).throw(ImportError("Application Control policy has blocked this file")),
    )
    monkeypatch.setattr(memory, "fetch_document", lambda _url: html)
    result = search_documentation(
        "CPU process", index_dir=index_dir, source_config=config, embeddings=_FakeEmbeddings()
    )
    assert result.status == "success"
    assert result.backend == "in_memory"
    assert result.evidence[0].source_url == "https://learn.microsoft.com/test"


def test_non_policy_faiss_load_error_does_not_activate_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(
        retriever, "_faiss_and_numpy",
        lambda: (_ for _ in ()).throw(ImportError("unrelated native dependency missing")),
    )
    result = search_documentation("CPU", index_dir=tmp_path / "missing")
    assert result.status == "retrieval_error"
    assert result.backend == "unavailable"
    assert result.evidence == []
