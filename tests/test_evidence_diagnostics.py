"""Evidence-driven diagnostic tests use only bounded local fixtures."""

from types import SimpleNamespace

import psutil
from langchain_core.runnables import RunnableLambda

from osguard.agents.diagnostic import create_diagnostic_agent
from osguard.context import create_evidence_collection_node, select_read_only_tools
from osguard.graph import build_supervisor_graph, final_response_node
from osguard.schemas import (
    DiagnosticAgentOutput, DiagnosticHypothesis, OSSubsystem, ProblemType,
    RequestIntent, RetrievalResult, SpecialistName, SupervisorClassification,
    ToolExecutionResult,
)
from osguard.state import make_initial_state
from osguard.tools import windows


def _state(request, subsystem, problem_type=ProblemType.PERFORMANCE):
    state = make_initial_state(request)
    classification = SupervisorClassification(
        intent=RequestIntent.DIAGNOSE,
        problem_type=problem_type,
        os_subsystems=[subsystem],
        selected_specialists=[SpecialistName.DIAGNOSTIC],
    )
    state.update({
        "classification": classification,
        "selected_specialists": [SpecialistName.DIAGNOSTIC],
    })
    return state


class _Model:
    def __init__(self, output):
        self.output = output
        self.prompts = []

    def with_structured_output(self, _schema):
        def respond(prompt):
            self.prompts.append(prompt.to_string())
            return self.output
        return RunnableLambda(respond)


def _memory_result():
    return ToolExecutionResult(
        tool_name="get_memory_info", status="success", summary="Memory snapshot.",
        evidence_id="tool:get_memory_info:fixture",
        data={
            "total_bytes": 25_383_882_752, "used_bytes": 14_595_547_136,
            "available_bytes": 10_788_335_616, "utilization_percent": 57.5,
        },
    )


def _process_result():
    row = {
        "pid": 42, "name": "actual-fixture.exe", "memory_bytes": 2_147_483_648,
        "memory_mib": 2048.0, "memory_mb": 2048.0, "cpu_percent": None,
    }
    return ToolExecutionResult(
        tool_name="get_process_stats", status="success", summary="Process snapshot.",
        evidence_id="tool:get_process_stats:fixture",
        data={"sort_by": "memory", "processes": [row], "top_memory_processes": [row]},
    )


def test_memory_request_selects_aggregate_and_one_memory_ranked_process_scan():
    state = _state("My laptop is consuming too much RAM. What are the reasons?", OSSubsystem.MEMORY, ProblemType.MEMORY)
    assert select_read_only_tools(state) == [
        ("get_memory_info", {}),
        ("get_process_stats", {"limit": 12, "sample_seconds": 0.15, "sort_by": "memory"}),
    ]


def test_cpu_and_other_subsystems_keep_selective_allowlisted_tools():
    cpu = _state("High CPU usage", OSSubsystem.PROCESS_CPU)
    assert select_read_only_tools(cpu) == [
        ("get_process_stats", {"limit": 12, "sample_seconds": 0.15, "sort_by": "cpu"})
    ]
    disk = _state("My disk is full", OSSubsystem.STORAGE_FILESYSTEM, ProblemType.STORAGE)
    assert [name for name, _ in select_read_only_tools(disk)] == ["get_disk_info"]
    verify = _state("Is Get-Process safe?", OSSubsystem.COMMAND_SAFETY)
    verify["classification"] = verify["classification"].model_copy(update={
        "intent": RequestIntent.VERIFY_COMMAND,
    })
    assert select_read_only_tools(verify) == []


def test_memory_rank_uses_one_bounded_scan_and_reports_working_set(monkeypatch):
    monkeypatch.setattr(windows, "_is_windows", lambda: True)

    class Process:
        def __init__(self, pid, name, rss):
            self.pid = pid
            self.info = {"pid": pid, "name": name}
            self.rss = rss

        def memory_info(self):
            if self.rss is None:
                raise psutil.AccessDenied(self.pid)
            return SimpleNamespace(rss=self.rss)

        def cpu_percent(self, interval=None):
            raise AssertionError("Memory ranking must not sample CPU per process")

    processes = [
        Process(1, "small.exe", 10 * 1024 * 1024),
        Process(2, "large.exe", 100 * 1024 * 1024),
        Process(3, "protected.exe", None),
    ]
    scans = []
    monkeypatch.setattr(windows.psutil, "process_iter", lambda **_kwargs: scans.append(1) or processes)
    monkeypatch.setattr(windows.time, "sleep", lambda _seconds: (_ for _ in ()).throw(AssertionError("No CPU delay")))
    result = windows.get_process_stats(sort_by="memory", limit=2)
    assert result.status == "success"
    assert scans == [1]
    assert [row["name"] for row in result.data["processes"]] == ["large.exe", "small.exe"]
    assert result.data["processes"][0]["memory_bytes"] == 100 * 1024 * 1024
    assert result.data["processes"][0]["memory_mib"] == 100.0
    assert result.data["processes_skipped_access_denied"] == 1
    assert result.data["memory_metric"] == "rss_working_set_bytes"
    assert "not additive" in result.data["memory_metric_definition"]
    assert result.data["system_cpu_percent"] is None
    assert windows.get_process_stats(sort_by="unsafe").status == "invalid_input"


def test_all_protected_processes_report_permission_denied(monkeypatch):
    monkeypatch.setattr(windows, "_is_windows", lambda: True)
    class Protected:
        pid = 7
        info = {"pid": 7, "name": "protected.exe"}
        def memory_info(self):
            raise psutil.AccessDenied(7)
    monkeypatch.setattr(windows.psutil, "process_iter", lambda **_kwargs: [Protected()])
    assert windows.get_process_stats(sort_by="memory").status == "permission_denied"


def test_cpu_rank_is_preserved_and_memory_rank_reuses_same_scan(monkeypatch):
    monkeypatch.setattr(windows, "_is_windows", lambda: True)
    class Process:
        def __init__(self, pid, name, cpu, rss):
            self.pid = pid
            self.info = {"pid": pid, "name": name}
            self.cpu = cpu
            self.rss = rss
            self.calls = 0
        def cpu_percent(self, interval=None):
            self.calls += 1
            return 0.0 if self.calls == 1 else self.cpu
        def memory_info(self):
            return SimpleNamespace(rss=self.rss)
    processes = [
        Process(1, "cpu.exe", 40.0, 10 * 1024 * 1024),
        Process(2, "memory.exe", 5.0, 100 * 1024 * 1024),
    ]
    scans = []
    monkeypatch.setattr(windows.psutil, "process_iter", lambda **_kwargs: scans.append(1) or processes)
    monkeypatch.setattr(windows.psutil, "cpu_percent", lambda interval=None: 30.0)
    monkeypatch.setattr(windows.time, "sleep", lambda _seconds: None)
    result = windows.get_process_stats(sort_by="cpu", limit=2)
    assert result.status == "success"
    assert scans == [1]
    assert [row["name"] for row in result.data["processes"]] == ["cpu.exe", "memory.exe"]
    assert [row["name"] for row in result.data["top_memory_processes"]] == ["memory.exe", "cpu.exe"]
    assert result.data["system_cpu_percent"] == 30.0


def test_stopped_service_gets_one_bounded_follow_up_log_check():
    state = _state("Service name: Spooler stopped unexpectedly", OSSubsystem.SERVICES_STARTUP, ProblemType.SERVICES_STARTUP)
    calls = []
    def service(**kwargs):
        calls.append(("service", kwargs))
        return ToolExecutionResult(
            tool_name="get_service_status", status="success", summary="Service status.",
            evidence_id="tool:get_service_status:fixture",
            data={"service_name": "Spooler", "status": "stopped"},
        )
    def events(**kwargs):
        calls.append(("events", kwargs))
        return ToolExecutionResult(
            tool_name="get_event_logs", status="success", summary="Recent System events.",
            evidence_id="tool:get_event_logs:fixture", data={"log_name": "System", "events": [], "count": 0},
        )
    collect = create_evidence_collection_node(
        retriever=lambda query: RetrievalResult(status="no_results", query=query),
        windows_tools={"get_service_status": service, "get_event_logs": events},
    )
    update = collect(state)
    assert [name for name, _ in calls] == ["service", "events"]
    assert calls[1][1]["filters"]["max_events"] == 20
    assert [item.status for item in update["tool_results"]] == ["success", "success"]


def test_failed_service_check_does_not_invent_follow_up_evidence():
    state = _state("Service name: Spooler stopped unexpectedly", OSSubsystem.SERVICES_STARTUP, ProblemType.SERVICES_STARTUP)
    collect = create_evidence_collection_node(
        retriever=lambda query: RetrievalResult(status="retrieval_error", query=query),
        windows_tools={"get_service_status": lambda **_kwargs: ToolExecutionResult(
            tool_name="get_service_status", status="permission_denied", summary="Access denied."
        )},
    )
    update = collect(state)
    assert [item.tool_name for item in update["tool_results"]] == ["get_service_status"]
    assert update["retrieved_evidence"] == []


def test_diagnostic_uses_real_measurements_and_rejects_one_snapshot_leak_claim():
    state = _state("My laptop is consuming too much RAM.", OSSubsystem.MEMORY, ProblemType.MEMORY)
    state["tool_results"] = [_memory_result(), _process_result()]
    state["retrieval_result"] = RetrievalResult(status="retrieval_error", query="RAM")
    model = _Model(DiagnosticAgentOutput(
        reported_symptoms=["consuming too much RAM"],
        hypotheses=[DiagnosticHypothesis(
            description="The application has a memory leak.",
            supporting_quotes=["consuming too much RAM"],
            uncertainty="Only one snapshot is available.",
        )],
        missing_information=["What is the current RAM usage?", "How has usage changed over time?"],
    ))
    update = create_diagnostic_agent(model_provider=lambda: model)(state)
    observed = update["diagnostic_observations"]
    assert any("10,788,335,616 bytes" in item.description and item.evidence_ids == ["tool:get_memory_info:fixture"] for item in observed)
    assert any("actual-fixture.exe" in item.description and item.evidence_ids == ["tool:get_process_stats:fixture"] for item in observed)
    assert update["diagnostic_hypotheses"] == []
    assert update["missing_information"] == ["How has usage changed over time?"]
    assert "2 successful read-only measurement(s)" in update["specialist_results"][0].message
    assert "No documentation passages were available" in update["specialist_results"][0].message
    assert "No system tools were run" not in update["specialist_results"][0].message
    assert any("cannot establish a trend or a memory leak" in note for note in update["uncertainty_notes"])


def test_diagnostic_rejects_unsupported_process_sum_and_pressure_threshold():
    state = _state("My laptop is consuming too much RAM.", OSSubsystem.MEMORY, ProblemType.MEMORY)
    state["tool_results"] = [_memory_result(), _process_result()]
    output = DiagnosticAgentOutput(hypotheses=[
        DiagnosticHypothesis(
            description="These processes explain the observed memory utilization.",
            supporting_evidence_ids=["tool:get_process_stats:fixture"],
            supporting_quotes=["actual-fixture.exe"],
            uncertainty="Working sets may overlap.",
        ),
        DiagnosticHypothesis(
            description="Memory pressure is normal because utilization is below a guideline.",
            supporting_evidence_ids=["tool:get_memory_info:fixture"],
            supporting_quotes=["57.5"],
            uncertainty="One snapshot is available.",
        ),
    ])
    update = create_diagnostic_agent(model_provider=lambda: _Model(output))(state)
    assert update["diagnostic_hypotheses"] == []
    assert any("causal or memory-pressure claim" in item for item in update["uncertainty_notes"])


def test_final_report_uses_measurements_and_does_not_claim_failed_retrieval():
    state = _state("My laptop is consuming too much RAM.", OSSubsystem.MEMORY, ProblemType.MEMORY)
    state["tool_results"] = [_memory_result(), _process_result()]
    state["retrieval_result"] = RetrievalResult(status="retrieval_error", query="RAM")
    model = _Model(DiagnosticAgentOutput(reported_symptoms=["consuming too much RAM"]))
    state.update(create_diagnostic_agent(model_provider=lambda: model)(state))
    message = final_response_node(state)["final_response"].message
    assert "10,788,335,616 bytes" in message
    assert "actual-fixture.exe" in message
    assert "No documentation passages were used" in message
    assert "retrieved documentation" not in message
    assert "exact root cause" in message


def test_no_tool_result_means_no_measured_host_data():
    state = _state("The application crashes.", OSSubsystem.SOFTWARE_DEPENDENCIES, ProblemType.SOFTWARE_FAILURE)
    model = _Model(DiagnosticAgentOutput(reported_symptoms=["application crashes"]))
    update = create_diagnostic_agent(model_provider=lambda: model)(state)
    assert update["diagnostic_observations"] == []
    assert "without host tool calls" in update["specialist_results"][0].message
    assert "read_only_tool_results" in model.prompts[0]


def test_graph_merges_memory_and_process_evidence_without_live_groq():
    state = _state("My laptop is consuming too much RAM.", OSSubsystem.MEMORY, ProblemType.MEMORY)
    calls = []
    def memory(**kwargs):
        calls.append(("memory", kwargs))
        return _memory_result()
    def process(**kwargs):
        calls.append(("process", kwargs))
        return _process_result()
    model = _Model(DiagnosticAgentOutput(reported_symptoms=["consuming too much RAM"]))
    graph = build_supervisor_graph(
        classifier=lambda _request: state["classification"], model=model,
        retriever=lambda query: RetrievalResult(status="no_results", query=query),
        windows_tools={"get_memory_info": memory, "get_process_stats": process},
    )
    result = graph.invoke(make_initial_state(state["user_request"]))
    assert [name for name, _ in calls] == ["memory", "process"]
    assert calls[1][1]["sort_by"] == "memory"
    assert len(result["tool_results"]) == 2
    assert {item.tool_name for item in result["diagnostic_observations"]} == {
        "get_memory_info", "get_process_stats"
    }
    assert result["specialist_results"][0].status == "completed"
    assert "actual-fixture.exe" in result["final_response"].message
    assert "retrieved documentation" not in result["final_response"].message
