"""Integration of the evidence collector with the existing bounded specialist graph."""

from osguard.context import create_evidence_collection_node, select_read_only_tools
from osguard.graph import build_supervisor_graph
from osguard.schemas import (
    DiagnosticObservation,
    OSSubsystem,
    ProblemType,
    RequestIntent,
    RetrievedEvidence,
    RetrievalResult,
    SpecialistName,
    SpecialistResult,
    SupervisorClassification,
    SystemEnvironment,
    ToolExecutionResult,
)
from osguard.state import make_initial_state


def _classification(specialists, subsystems):
    return SupervisorClassification(
        intent=RequestIntent.DIAGNOSE,
        problem_type=ProblemType.SOFTWARE_FAILURE,
        os_subsystems=subsystems,
        selected_specialists=specialists,
    )


def test_tool_selector_is_bounded_to_relevant_routes_and_explicit_service_names():
    high_cpu = make_initial_state("My PC has high CPU usage")
    high_cpu["classification"] = _classification(
        [SpecialistName.DIAGNOSTIC], [OSSubsystem.PROCESS_CPU]
    )
    high_cpu["selected_specialists"] = [SpecialistName.DIAGNOSTIC]
    assert [name for name, _ in select_read_only_tools(high_cpu)] == ["get_process_stats"]

    vague_service = make_initial_state("A Windows service failed to start")
    vague_service["classification"] = _classification(
        [SpecialistName.DIAGNOSTIC], [OSSubsystem.SERVICES_STARTUP]
    )
    vague_service["selected_specialists"] = [SpecialistName.DIAGNOSTIC]
    assert [name for name, _ in select_read_only_tools(vague_service)] == ["get_event_logs"]

    named_service = make_initial_state("Check service name: Spooler")
    named_service["classification"] = vague_service["classification"]
    named_service["selected_specialists"] = [SpecialistName.DIAGNOSTIC]
    assert select_read_only_tools(named_service) == [("get_service_status", {"service_name": "Spooler"})]


def test_graph_shares_one_retrieval_and_tool_snapshot_across_multiple_agents():
    evidence = RetrievedEvidence(
        source_id="cpu-doc#chunk-0",
        title="CPU and process guidance",
        source_url="https://learn.microsoft.com/cpu",
        passage="A CPU sample does not alone identify the root cause.",
        metadata={"category": "process_cpu"},
    )
    observed_processes = ToolExecutionResult(
        tool_name="get_process_stats",
        status="success",
        summary="Bounded CPU sample.",
        evidence_id="tool:get_process_stats:fixture",
        data={"system_cpu_percent": 88.0, "processes": [{"name": "app.exe", "cpu_percent": 61.0}]},
    )
    observed_system = ToolExecutionResult(
        tool_name="get_system_info",
        status="success",
        summary="Windows metadata.",
        evidence_id="tool:get_system_info:fixture",
        data={"os_name": "Windows 11", "os_version": "10.0.22631", "os_build": "22631", "architecture": "AMD64"},
    )
    collector_calls = []
    tool_calls = []

    def fake_retriever(query):
        collector_calls.append(query)
        return RetrievalResult(status="success", query=query, evidence=[evidence])

    def fake_process(**kwargs):
        tool_calls.append(("process", kwargs))
        return observed_processes

    def fake_system(**kwargs):
        tool_calls.append(("system", kwargs))
        return observed_system

    classification = _classification(
        [SpecialistName.DIAGNOSTIC, SpecialistName.COMPATIBILITY],
        [OSSubsystem.PROCESS_CPU, OSSubsystem.SOFTWARE_DEPENDENCIES],
    )
    calls = []

    def diagnostic(state):
        calls.append("diagnostic")
        assert state["retrieved_evidence"][0].source_id == evidence.source_id
        assert state["tool_results"][0].evidence_id == observed_system.evidence_id
        assert state["tool_results"][1].evidence_id == observed_processes.evidence_id
        return {
            "diagnostic_observations": [
                DiagnosticObservation(
                    description="Measured CPU data",
                    source="read_only_tool",
                    supporting_quote='"system_cpu_percent": 88.0',
                    tool_name="get_process_stats",
                    evidence_ids=[observed_processes.evidence_id],
                )
            ],
            "specialist_results": [
                SpecialistResult(specialist=SpecialistName.DIAGNOSTIC, status="completed", message="fixture")
            ],
            "completed_specialists": [SpecialistName.DIAGNOSTIC],
        }

    def compatibility(state):
        calls.append("compatibility")
        assert state["available_environment"].source == "read_only_tool"
        assert state["available_environment"].os_name == "Windows 11"
        assert state["retrieved_evidence"][0].source_id == evidence.source_id
        return {
            "specialist_results": [
                SpecialistResult(specialist=SpecialistName.COMPATIBILITY, status="completed", message="fixture")
            ],
            "completed_specialists": [SpecialistName.COMPATIBILITY],
        }

    collector = create_evidence_collection_node(
        retriever=fake_retriever,
        windows_tools={"get_process_stats": fake_process, "get_system_info": fake_system},
    )
    graph = build_supervisor_graph(
        classifier=lambda _request: classification,
        specialist_nodes={
            SpecialistName.DIAGNOSTIC: diagnostic,
            SpecialistName.COMPATIBILITY: compatibility,
        },
        evidence_collection_node=collector,
    )
    result = graph.invoke(
        make_initial_state("High CPU usage and a missing Runtime dependency")
    )

    assert collector_calls == ["High CPU usage and a missing Runtime dependency"]
    assert [item[0] for item in tool_calls] == ["system", "process"]
    assert calls == ["diagnostic", "compatibility"]
    assert result["retrieved_evidence"][0].source_id == evidence.source_id
    assert len(result["tool_results"]) == 2
    assert result["diagnostic_observations"][0].evidence_ids == [observed_processes.evidence_id]
    assert result["workflow_status"] == "specialists_completed"
    assert result["final_response"].findings_available is True


def test_partial_retrieval_and_tool_failures_do_not_create_evidence():
    classification = _classification([SpecialistName.DIAGNOSTIC], [OSSubsystem.PROCESS_CPU])
    denied = ToolExecutionResult(
        tool_name="get_process_stats",
        status="permission_denied",
        summary="Access denied.",
        error="AccessDenied",
    )
    collector = create_evidence_collection_node(
        retriever=lambda _query: (_ for _ in ()).throw(RuntimeError("fixture error")),
        windows_tools={"get_process_stats": lambda **_kwargs: denied},
    )
    graph = build_supervisor_graph(
        classifier=lambda _request: classification,
        evidence_collection_node=collector,
        specialist_nodes={
            SpecialistName.DIAGNOSTIC: lambda _state: {
                "specialist_results": [
                    SpecialistResult(specialist=SpecialistName.DIAGNOSTIC, status="completed", message="text-only")
                ],
                "completed_specialists": [SpecialistName.DIAGNOSTIC],
            }
        },
    )

    result = graph.invoke(make_initial_state("My PC has high CPU usage"))

    assert result["retrieval_result"].status == "retrieval_error"
    assert result["retrieved_evidence"] == []
    assert result["tool_results"][0].status == "permission_denied"
    assert result["workflow_status"] == "specialists_completed"
