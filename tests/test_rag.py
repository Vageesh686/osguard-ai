"""FAISS RAG unit tests use deterministic embeddings and a local FAISS test double."""

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from osguard.rag import ingest, knowledge_base, memory, retriever
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
    assert search_documentation(
        "cpu process", {"os_version": "Windows 11", "source_id": "cpu-process-doc"},
        index_dir=index_dir, embeddings=_FakeEmbeddings(),
    ).status == "success"
    assert search_documentation(
        "cpu process", {"os_version": "Windows 10"},
        index_dir=index_dir, embeddings=_FakeEmbeddings(),
    ).status == "no_results"
    assert search_documentation(
        "cpu process", {"source_id": "other-doc"},
        index_dir=index_dir, embeddings=_FakeEmbeddings(),
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
    assert search_documentation(
        "CPU", {"os_version": "Windows 11", "source_id": "cpu-process-doc"}, **kwargs
    ).status == "success"
    assert search_documentation(
        "CPU", {"os_version": "Windows 10"}, **kwargs
    ).status == "no_results"


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


def test_native_faiss_imports_on_this_environment():
    import faiss

    assert hasattr(faiss, "IndexFlatIP")


def test_explicit_initialization_persists_and_reuses_verified_index(tmp_path, fake_faiss):
    config = _source_config(tmp_path / "sources.json")
    index_dir = tmp_path / "index"
    calls = {"fetch": 0, "embed_documents": 0}

    def fetch(_url):
        calls["fetch"] += 1
        return "<main><h1>CPU process</h1><p>Process CPU measurements can support an investigation, but one sample cannot prove the cause of sustained CPU use.</p></main>"

    class CountingEmbeddings(_FakeEmbeddings):
        def embed_documents(self, texts):
            calls["embed_documents"] += 1
            return super().embed_documents(texts)

    encoder = CountingEmbeddings()
    missing = knowledge_base.inspect_knowledge_base(index_dir=index_dir, embeddings=encoder)
    assert missing.state == "index_missing"
    assert missing.backend == "unavailable"

    first = knowledge_base.initialize_knowledge_base(
        index_dir=index_dir, source_config=config, fetcher=fetch, embeddings=encoder
    )
    assert first.state == "faiss_ready"
    assert first.backend == "faiss" and first.retrieval_verified
    assert all((index_dir / name).is_file() for name in (
        "index.faiss", "manifest.json", "index.sha256.json"
    ))
    assert calls["fetch"] == 1
    assert calls["embed_documents"] == 1

    second = knowledge_base.initialize_knowledge_base(
        index_dir=index_dir, source_config=config, fetcher=fetch, embeddings=encoder
    )
    assert second.state == "faiss_ready" and second.retrieval_verified
    assert calls["fetch"] == 1
    assert calls["embed_documents"] == 1

    retriever.clear_index_cache()
    reloaded = knowledge_base.inspect_knowledge_base(index_dir=index_dir, source_config=config, embeddings=encoder)
    assert reloaded.state == "faiss_ready"
    found = search_documentation("CPU process", index_dir=index_dir, embeddings=encoder)
    assert found.status == "success" and found.backend == "faiss"
    assert found.evidence[0].source_url == "https://learn.microsoft.com/test"
    changed = json.loads(config.read_text(encoding="utf-8"))
    changed[0]["title"] = "Updated CPU and process guidance"
    config.write_text(json.dumps(changed), encoding="utf-8")
    assert knowledge_base.inspect_knowledge_base(
        index_dir=index_dir, source_config=config, embeddings=encoder
    ).state == "index_incomplete"
    rebuilt = knowledge_base.initialize_knowledge_base(
        index_dir=index_dir, source_config=config, fetcher=fetch, embeddings=encoder
    )
    assert rebuilt.state == "faiss_ready" and rebuilt.retrieval_verified
    assert calls["fetch"] == 2


def test_incomplete_corrupt_and_incompatible_indexes_can_be_rebuilt(tmp_path, fake_faiss):
    config = _source_config(tmp_path / "sources.json")
    index_dir = tmp_path / "index"
    encoder = _FakeEmbeddings()
    fetch = lambda _url: "<main><h1>CPU process</h1><p>Process CPU measurements can support an investigation, but one sample cannot prove the cause of sustained CPU use.</p></main>"
    assert knowledge_base.initialize_knowledge_base(
        index_dir=index_dir, source_config=config, fetcher=fetch, embeddings=encoder
    ).state == "faiss_ready"

    (index_dir / "index.sha256.json").unlink()
    assert knowledge_base.inspect_knowledge_base(index_dir=index_dir, source_config=config, embeddings=encoder).state == "index_incomplete"
    incomplete = search_documentation("CPU", index_dir=index_dir, embeddings=encoder)
    assert incomplete.status == "index_missing" and "incomplete" in incomplete.message
    assert knowledge_base.initialize_knowledge_base(
        index_dir=index_dir, source_config=config, fetcher=fetch, embeddings=encoder
    ).state == "faiss_ready"

    manifest = index_dir / "manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["chunks"][0]["url"] = "https://untrusted.example.invalid/page"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    receipt = index_dir / "index.sha256.json"
    receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
    receipt_payload["manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
    receipt.write_text(json.dumps(receipt_payload), encoding="utf-8")
    retriever.clear_index_cache(index_dir)
    assert knowledge_base.inspect_knowledge_base(index_dir=index_dir, source_config=config, embeddings=encoder).state == "index_corrupt"
    assert knowledge_base.initialize_knowledge_base(
        index_dir=index_dir, source_config=config, fetcher=fetch, embeddings=encoder
    ).state == "faiss_ready"

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["chunks"][0]["url"] = "https://untrusted.example.invalid/page"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    retriever.clear_index_cache(index_dir)
    assert knowledge_base.inspect_knowledge_base(index_dir=index_dir, source_config=config, embeddings=encoder).state == "index_corrupt"
    assert search_documentation("CPU", index_dir=index_dir, embeddings=encoder).status == "index_corrupt"
    assert knowledge_base.initialize_knowledge_base(
        index_dir=index_dir, source_config=config, fetcher=fetch, embeddings=encoder
    ).state == "faiss_ready"

    class OtherEncoder(_FakeEmbeddings):
        model_name = "another-local-model"

    assert knowledge_base.inspect_knowledge_base(
        index_dir=index_dir, source_config=config, embeddings=OtherEncoder()
    ).state == "embedding_mismatch"
    assert knowledge_base.initialize_knowledge_base(
        index_dir=index_dir, source_config=config, fetcher=fetch, embeddings=OtherEncoder()
    ).state == "faiss_ready"


def test_initializer_does_not_fallback_for_other_native_failure(tmp_path, monkeypatch):
    config = _source_config(tmp_path / "sources.json")
    monkeypatch.setattr(
        retriever, "_faiss_and_numpy",
        lambda: (_ for _ in ()).throw(ImportError("native library missing")),
    )
    status = knowledge_base.initialize_knowledge_base(
        index_dir=tmp_path / "index", source_config=config, embeddings=_FakeEmbeddings()
    )
    assert status.state == "faiss_unavailable" and status.backend == "unavailable"
    assert not (tmp_path / "index" / "index.faiss").exists()


def test_initializer_uses_fallback_only_for_recognized_native_block(tmp_path, monkeypatch):
    config = _source_config(tmp_path / "sources.json")
    attempts = {"fetch": 0}

    def fetch(_url):
        attempts["fetch"] += 1
        return "<main><h1>CPU process</h1><p>Process CPU measurements can support an investigation, but one sample cannot prove the cause of sustained CPU use.</p></main>"

    monkeypatch.setattr(
        retriever, "_faiss_and_numpy",
        lambda: (_ for _ in ()).throw(ImportError("Application Control policy has blocked this file")),
    )
    monkeypatch.setattr(memory, "fetch_document", fetch)
    index_dir = tmp_path / "index"
    status = knowledge_base.initialize_knowledge_base(
        index_dir=index_dir, source_config=config, embeddings=_FakeEmbeddings()
    )
    assert status.state == "fallback_active"
    assert status.backend == "in_memory" and status.retrieval_verified
    assert attempts["fetch"] == 1
    assert not (index_dir / "index.faiss").exists()
    assert knowledge_base.inspect_knowledge_base(
        index_dir=index_dir, source_config=config
    ).state == "fallback_active"
