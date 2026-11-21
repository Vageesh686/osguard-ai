"""Real LangGraph and in-memory retrieval with an isolated Microsoft-page fixture."""

import json

import pytest
from langchain_core.runnables import RunnableLambda

from osguard.graph import build_supervisor_graph
from osguard.rag import memory, retriever
from osguard.schemas import (
    DiagnosticAgentOutput, DiagnosticHypothesis, OSSubsystem, ProblemType,
    RequestIntent, RetrievalResult, SpecialistName, SupervisorClassification,
    ToolExecutionResult,
)
from osguard.state import make_initial_state


class _Embeddings:
    model_name = "graph-fixture-encoder"

    def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, _text):
        return [1.0, 0.0]


class _CapturingModel:
    def __init__(self, output):
        self.output = output
        self.prompts = []

    def with_structured_output(self, schema):
        assert schema is DiagnosticAgentOutput

        def respond(prompt):
            self.prompts.append(prompt.to_string())
            return self.output

        return RunnableLambda(respond)


@pytest.fixture(autouse=True)
def _clear_rag_caches():
    retriever.clear_index_cache()
    yield
    retriever.clear_index_cache()


def _graph(model, retrieval):
    classification = SupervisorClassification(
        intent=RequestIntent.DIAGNOSE,
        problem_type=ProblemType.PERFORMANCE,
        os_subsystems=[OSSubsystem.PROCESS_CPU],
        selected_specialists=[SpecialistName.DIAGNOSTIC],
    )
    return build_supervisor_graph(
        classifier=lambda _request: classification,
        model=model,
        retriever=retrieval,
        windows_tools={
            "get_process_stats": lambda **_kwargs: ToolExecutionResult(
                tool_name="get_process_stats", status="failed",
                summary="No host measurement was made in this fixture.",
            )
        },
    )


def _prompt_evidence(model):
    raw = model.prompts[0].split("<shared_evidence>", 1)[1].split("</shared_evidence>", 1)[0]
    return json.loads(raw)


def test_graph_passes_real_fallback_result_and_provenance_to_diagnostic_agent(tmp_path, monkeypatch):
    source = {
        "source_id": "cpu-doc", "title": "CPU guidance",
        "url": "https://learn.microsoft.com/test/cpu", "os_version": "Windows 11",
        "category": "process_cpu",
    }
    config = tmp_path / "sources.json"
    config.write_text(json.dumps([source]), encoding="utf-8")
    html = (
        "<main><h1>Process guidance</h1><p>Process CPU measurements help investigate "
        "high CPU usage but cannot prove a root cause.</p></main>"
    )
    monkeypatch.setattr(memory, "fetch_document", lambda _url: html)
    monkeypatch.setattr(
        retriever, "_faiss_and_numpy",
        lambda: (_ for _ in ()).throw(ImportError("Application Control policy has blocked this file")),
    )
    evidence_id = "cpu-doc#cpu-doc-0000"
    model = _CapturingModel(DiagnosticAgentOutput(
        reported_symptoms=["high CPU usage"],
        hypotheses=[DiagnosticHypothesis(
            description="Process measurements may help identify the busy process.",
            supporting_evidence_ids=[evidence_id],
            supporting_quotes=["Process CPU measurements help investigate high CPU usage"],
            uncertainty="A process measurement is still needed.",
        )],
    ))
    encoder = _Embeddings()
    graph = _graph(model, lambda query: retriever.search_documentation(
        query, index_dir=tmp_path / "missing", source_config=config, embeddings=encoder
    ))

    result = graph.invoke(make_initial_state("My Windows PC has high CPU usage."))
    evidence = result["retrieved_evidence"][0]
    assert result["retrieval_result"].status == "success"
    assert result["retrieval_result"].backend == "in_memory"
    assert evidence.source_id == evidence_id
    assert evidence.title == source["title"]
    assert evidence.source_url == source["url"]
    assert evidence.os_version == source["os_version"]
    assert evidence.metadata["category"] == source["category"]
    assert evidence.metadata["section"] == "Process guidance"
    assert evidence.metadata["chunk_id"] == "cpu-doc-0000"
    prompt_passage = _prompt_evidence(model)["documentation_passages"][0]
    assert prompt_passage["evidence_id"] == evidence_id
    assert prompt_passage["source_url"] == source["url"]
    assert prompt_passage["metadata"] == evidence.metadata
    assert result["diagnostic_hypotheses"][0].supporting_evidence_ids == [evidence_id]
    assert "retrieved documentation" in result["final_response"].message


def test_graph_does_not_claim_documentation_after_retrieval_failure():
    model = _CapturingModel(DiagnosticAgentOutput(reported_symptoms=["high CPU usage"]))
    graph = _graph(model, lambda query: RetrievalResult(
        status="retrieval_error", query=query, backend="unavailable",
        message="The documentation source was unavailable.",
    ))
    result = graph.invoke(make_initial_state("My Windows PC has high CPU usage."))
    assert result["retrieval_result"].status == "retrieval_error"
    assert result["retrieved_evidence"] == []
    assert _prompt_evidence(model)["documentation_passages"] == []
    assert "retrieved documentation" not in result["final_response"].message
    assert "No documentation passages were used." in result["final_response"].message
