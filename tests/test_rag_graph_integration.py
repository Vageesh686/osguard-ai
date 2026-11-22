"""Real LangGraph and in-memory retrieval with an isolated Microsoft-page fixture."""

import json

import pytest
from langchain_core.runnables import RunnableLambda

from osguard.graph import build_supervisor_graph
from osguard.mcp.client import MCPCollection
from osguard.rag import ingest, memory, retriever
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


def test_real_faiss_retrieval_and_mock_mcp_measurements_reach_diagnostic_prompt(tmp_path):
    source = {
        "source_id": "memory-doc", "title": "Memory guidance",
        "url": "https://learn.microsoft.com/test/memory", "os_version": "Windows 11",
        "category": "memory",
    }
    config = tmp_path / "sources.json"
    config.write_text(json.dumps([source]), encoding="utf-8")
    html = (
        "<main><h1>Memory guidance</h1><p>Memory measurements and process working "
        "sets can support an investigation but cannot alone prove why memory usage is high.</p></main>"
    )
    index_dir = tmp_path / "index"
    encoder = _Embeddings()
    assert ingest.build_index(
        source_config=config, index_dir=index_dir,
        fetcher=lambda _url: html, embeddings=encoder,
    ).status == "success"
    classification = SupervisorClassification(
        intent=RequestIntent.DIAGNOSE, problem_type=ProblemType.MEMORY,
        os_subsystems=[OSSubsystem.MEMORY], selected_specialists=[SpecialistName.DIAGNOSTIC],
    )
    evidence_id = "memory-doc#memory-doc-0000"
    model = _CapturingModel(DiagnosticAgentOutput(
        reported_symptoms=["high RAM usage"],
        hypotheses=[DiagnosticHypothesis(
            description="The process snapshot may help explain memory use.",
            supporting_evidence_ids=[evidence_id],
            supporting_quotes=["Memory measurements and process working sets can support an investigation"],
            uncertainty="The cause remains unconfirmed.",
        )],
    ))
    called = []

    def mcp_fixture(planner, follow_up):
        available = {
            "get_memory_info": "Physical memory",
            "get_process_stats": "Processes by working set",
            "get_system_info": "Windows version",
        }
        selected = planner(available)
        called.extend(name for name, _ in selected)
        results = [ToolExecutionResult(
            tool_name=name, status="success", summary=f"Fixture {name} measurement",
            evidence_id=f"tool:{name}:fixture", backend="mcp",
            data={"total_bytes": 1000, "used_bytes": 600, "available_bytes": 400,
                  "utilization_percent": 60.0} if name == "get_memory_info" else
                 {"sort_by": "memory", "processes": [{"name": "fixture.exe", "pid": 1,
                    "memory_bytes": 300}]} if name == "get_process_stats" else
                 {"os_name": "Windows 11"},
        ) for name, _ in selected]
        assert follow_up(results) == []
        return MCPCollection(results=results, available=available, selected=selected)

    graph = build_supervisor_graph(
        classifier=lambda _request: classification, model=model,
        retriever=lambda query: retriever.search_documentation(
            query, index_dir=index_dir, source_config=config, embeddings=encoder
        ),
        diagnostic_backend="mcp", mcp_runner=mcp_fixture,
    )
    result = graph.invoke(make_initial_state(
        "Why is my PC using so much RAM? Check memory and processes and explain using Microsoft documentation."
    ))
    assert result["diagnostic_backend"] == "mcp"
    assert {"get_memory_info", "get_process_stats"}.issubset(called)
    assert result["retrieval_result"].status == "success"
    assert result["retrieval_result"].backend == "faiss"
    prompt = _prompt_evidence(model)
    passage = prompt["documentation_passages"][0]
    assert passage["evidence_id"] == evidence_id
    assert passage["source_url"] == source["url"]
    assert passage["metadata"]["category"] == "memory"
    assert passage["metadata"]["relevance_score"] > 0
    assert {item["evidence_id"] for item in prompt["read_only_tool_results"]} >= {
        "tool:get_memory_info:fixture", "tool:get_process_stats:fixture"
    }
    assert "retrieved documentation" in result["final_response"].message
