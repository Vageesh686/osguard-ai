"""Focused presentation checks using saved graph results and safe backend fixtures."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from osguard import frontend
from osguard.rag import knowledge_base
from osguard.schemas import (
    ApprovalState, CommandVerificationFinding, DemoCacheSnapshot, DiagnosticObservation, ExecutionValidationResult,
    FinalResponse, IEEEVerificationSummary, PostRepairValidationResult, ProblemType,
    RepairEligibility, RepairPlan, RetrievalResult, RetrievedEvidence, SpecialistName,
    SpecialistResult, SupervisorClassification, RequestIntent, ToolExecutionResult,
)


class FakeStreamlit:
    def __init__(self):
        self.calls = []
        self.session_state = {}
        self.button_returns = {}
        self.input_value = None
        self.sidebar = nullcontext()

    def record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    def cache_resource(self, **kwargs):
        return lambda function: function

    def columns(self, count):
        self.record("columns", count)
        return [nullcontext() for _ in range(count)]

    def container(self, **kwargs):
        self.record("container", **kwargs)
        return nullcontext()

    def expander(self, *args, **kwargs):
        self.record("expander", *args, **kwargs)
        return nullcontext()

    def spinner(self, *args, **kwargs):
        self.record("spinner", *args, **kwargs)
        return nullcontext()

    def radio(self, label, options, **kwargs):
        self.record("radio", label, options, **kwargs)
        return self.session_state.get(kwargs["key"], options[0])

    def text_area(self, label, **kwargs):
        self.record("text_area", label, **kwargs)
        value = self.input_value if self.input_value is not None else self.session_state.get(
            kwargs["key"], kwargs.get("value", "")
        )
        self.session_state[kwargs["key"]] = value
        return value

    def button(self, label, **kwargs):
        self.record("button", label, **kwargs)
        return self.button_returns.pop(label, False)

    def __getattr__(self, name):
        return lambda *args, **kwargs: self.record(name, *args, **kwargs)

    def visible(self):
        return "\n".join(f"{args} {kwargs}" for name, args, kwargs in self.calls
                         if name not in {"set_page_config", "columns"})


@pytest.fixture
def ui(monkeypatch):
    fake = FakeStreamlit()
    monkeypatch.setattr(frontend, "st", fake)
    return fake


def ready_status():
    return knowledge_base.KnowledgeBaseStatus(
        "faiss_ready", "faiss", "Ready", "fixture-index", retrieval_verified=True
    )


def result(*, completed=True):
    specialist = SpecialistName.DIAGNOSTIC
    return {
        "classification": SupervisorClassification(
            intent=RequestIntent.DIAGNOSE, problem_type=ProblemType.MEMORY,
            selected_specialists=[specialist],
        ),
        "selected_specialists": [specialist],
        "workflow_status": "specialists_completed" if completed else "specialist_failure",
        "specialist_results": [SpecialistResult(
            specialist=specialist, status="completed" if completed else "failed",
            message="Analysis complete" if completed else "Analysis unavailable",
        )],
        "final_response": FinalResponse(
            message="Classified as memory. Selected specialists: diagnostic.",
            workflow_status="specialists_completed" if completed else "specialist_failure",
            issue_category=ProblemType.MEMORY,
            selected_specialists=[specialist], findings_available=completed,
        ),
    }


def tool(name, data, *, status="success"):
    return ToolExecutionResult(
        tool_name=name, status=status, summary="Measured local data.", data=data,
        evidence_id=f"tool:{name}:fixture" if status == "success" else None,
    )


def test_home_navigation_and_draft_are_stable(ui, monkeypatch):
    monkeypatch.setattr(frontend, "_knowledge_status", ready_status)
    frontend.main()
    assert "Intelligent Windows Troubleshooting" in ui.visible()
    assert "Analyze Issue" in ui.visible()
    assert all(page in ui.visible() for page in frontend.PAGES)
    ui.session_state["osguard_draft"] = "My RAM is full"
    ui.session_state["osguard_issue_input"] = "My RAM is full"
    ui.session_state["osguard_page"] = "Troubleshoot"
    ui.calls.clear()
    frontend.main()
    assert ui.session_state["osguard_draft"] == "My RAM is full"
    assert "My RAM is full" in ui.visible()
    ui.session_state["osguard_page"] = "Results"
    ui.calls.clear()
    frontend.main()
    assert "No analysis is available yet" in ui.visible()


def test_shortcut_populates_input_without_running_analysis(ui, monkeypatch):
    monkeypatch.setattr(frontend, "_knowledge_status", ready_status)
    ui.button_returns["Networking"] = True
    frontend.main()
    assert "Wi-Fi" in ui.session_state["osguard_draft"]
    assert "osguard_supervisor_result" not in ui.session_state
    ui.calls.clear()
    frontend.main()
    assert ui.session_state["osguard_issue_input"] == ui.session_state["osguard_draft"]


def test_graph_runs_once_and_results_survive_navigation(ui, monkeypatch):
    monkeypatch.setattr(frontend, "_knowledge_status", ready_status)
    calls = []
    class Workflow:
        def invoke(self, state, config):
            calls.append((state, config))
            return result()
    monkeypatch.setattr(frontend, "_get_supervisor_graph", lambda: Workflow())
    ui.input_value = "Why is my RAM full?"
    ui.button_returns["Analyze Issue"] = True
    frontend.main()
    assert len(calls) == 1
    assert ui.session_state["osguard_next_page"] == "Results"
    ui.input_value = None
    ui.calls.clear()
    frontend.main()
    assert "Your analysis" in ui.visible()
    ui.session_state["osguard_page"] = "Knowledge Base"
    frontend.main()
    assert len(calls) == 1
    assert ui.session_state["osguard_draft"] == "Why is my RAM full?"


def test_result_uses_real_ram_values_and_hides_internal_names(ui):
    state = result()
    state["tool_results"] = [
        tool("get_memory_info", {"total_bytes": 16 * 1024**3,
                                 "used_bytes": 8 * 1024**3,
                                 "available_bytes": 8 * 1024**3,
                                 "utilization_percent": 50.0}),
        tool("get_process_stats", {"system_cpu_percent": 12.0,
                                   "processes": [{"name": "editor.exe", "pid": 1,
                                                  "cpu_percent": 4.0, "memory_mib": 128.0}]}),
    ]
    state["diagnostic_observations"] = [DiagnosticObservation(
        description="Physical memory is 50% utilized.", source="read_only_tool",
        tool_name="get_memory_info", evidence_ids=["tool:get_memory_info:fixture"],
    )]
    state["safe_diagnostic_steps"] = ["Close an application you no longer need."]
    frontend._render_supervisor_result(state)
    visible = ui.visible()
    assert "Main finding" in visible and "Physical memory is 50% utilized" in visible
    assert "8.0 GiB" in visible and "12.0%" in visible
    assert "editor.exe" in visible and "Close an application" in visible
    assert "get_memory_info" not in visible and "tool:get_" not in visible
    assert "Selected specialists" not in visible


def test_components_and_sources_follow_actual_result(ui):
    state = result()
    source = "https://learn.microsoft.com/en-us/windows/test"
    passages = [RetrievedEvidence(source_id=f"doc#{n}", title="Memory guidance",
                                  source_url=source, passage=f"Passage {n}",
                                  metadata={"section": "Overview"}) for n in (1, 2)]
    state["retrieval_result"] = RetrievalResult(status="success", query="memory",
                                                backend="faiss", evidence=passages)
    state["tool_results"] = [tool("get_memory_info", {"utilization_percent": 50})]
    frontend._render_supervisor_result(state)
    visible = ui.visible()
    assert visible.count("Read on Microsoft Learn") == 1
    assert "2 supporting passages" in visible
    assert "Windows System Analysis" in visible and "Microsoft Knowledge Base" in visible
    assert "Completed" in visible
    ui.calls.clear()
    state["retrieval_result"] = RetrievalResult(status="retrieval_error", query="memory",
                                                backend="unavailable")
    state["tool_results"] = [tool("get_memory_info", {}, status="failed")]
    frontend._render_supervisor_result(state)
    visible = ui.visible()
    assert "Microsoft documentation is temporarily unavailable" in visible
    assert "Read on Microsoft Learn" not in visible
    assert "Unavailable" in visible


def test_failed_workflow_does_not_claim_completion(ui):
    frontend._render_supervisor_result(result(completed=False))
    visible = ui.visible()
    assert "Analysis incomplete" in visible
    assert "Analysis complete" not in visible
    assert "No confirmed finding" in visible


def test_command_review_omits_raw_command_text(ui):
    state = result()
    state["command_verification_findings"] = [CommandVerificationFinding(
        command_text="Get-Process | Stop-Process", risk="high",
        explanation="Do not run Get-Process | Stop-Process.", verified=False,
    )]
    state["safe_diagnostic_steps"] = ["Run Get-Process to inspect the host."]
    frontend._render_supervisor_result(state)
    visible = ui.visible()
    assert "Command review" in visible and "Risk: High" in visible
    assert "Get-Process" not in visible and "Stop-Process" not in visible


def test_existing_knowledge_index_reused_and_missing_index_built_once(ui, monkeypatch):
    calls = []
    monkeypatch.setattr(knowledge_base, "inspect_knowledge_base", lambda: calls.append("inspect") or ready_status())
    monkeypatch.setattr(knowledge_base, "initialize_knowledge_base", lambda: calls.append("initialize") or ready_status())
    frontend.main()
    frontend.main()
    assert calls == ["inspect"]
    ui.session_state.clear()
    missing = knowledge_base.KnowledgeBaseStatus("index_missing", "unavailable", "Missing", "fixture")
    monkeypatch.setattr(knowledge_base, "inspect_knowledge_base", lambda: calls.append("missing") or missing)
    frontend.main()
    frontend.main()
    assert calls[-2:] == ["missing", "initialize"]


def test_failed_indexing_is_reported_and_retried_only_on_click(ui, monkeypatch):
    calls = []
    missing = knowledge_base.KnowledgeBaseStatus("index_missing", "unavailable", "Missing", "fixture")
    failed = knowledge_base.KnowledgeBaseStatus("initialization_failed", "unavailable", "Offline", "fixture")
    monkeypatch.setattr(knowledge_base, "inspect_knowledge_base", lambda: missing)
    monkeypatch.setattr(knowledge_base, "initialize_knowledge_base", lambda: calls.append(1) or failed)
    frontend.main()
    assert len(calls) == 1
    ui.session_state["osguard_page"] = "Knowledge Base"
    ui.calls.clear()
    frontend.main()
    assert len(calls) == 1 and "temporarily unavailable" in ui.visible()
    ui.button_returns["Retry documentation preparation"] = True
    frontend.main()
    assert len(calls) == 2


def pending_state():
    snapshot = DemoCacheSnapshot(target="C:/project/data/demo_app/cache", payload_size=64,
                                 payload_sha256="a" * 64, owner_marker_sha256="b" * 64)
    plan = RepairPlan(
        plan_id="plan-" + "1" * 32, action_id="act-" + "2" * 16,
        executable_action_id="CLEAR_OSGUARD_DEMO_CACHE", target=snapshot.target,
        parameters={"cache_id": "osguard_demo"}, intended_outcome="Owned cache empty",
        expected_effects=["Known entry cleared"], potential_risks=["Owned temporary data is discarded"],
        preconditions=["Known entry present"], validator_id="demo_cache_empty_and_owned",
        pre_state=snapshot, fingerprint="f" * 64,
    )
    state = result()
    state.update({
        "repair_plan": plan,
        "repair_eligibility": RepairEligibility(status="eligible", action_id=plan.action_id,
                                                 plan_id=plan.plan_id),
        "approval_state": ApprovalState(status="pending", action_id=plan.action_id,
                                        plan_id=plan.plan_id, fingerprint=plan.fingerprint),
        "workflow_status": "awaiting_approval",
    })
    return state


@pytest.mark.parametrize("button,decision", [("Approve", "approve"), ("Decline", "decline")])
def test_exact_approval_resume_once_and_no_automatic_change(ui, monkeypatch, button, decision):
    state = pending_state()
    ui.session_state["osguard_pending_thread_id"] = "thread-1"
    commands = []
    class Workflow:
        def invoke(self, command, config):
            commands.append((command.resume, config))
            finished = {**state, "approval_state": state["approval_state"].model_copy(
                update={"status": "approved" if decision == "approve" else "declined"})}
            return finished
    monkeypatch.setattr(frontend, "_get_supervisor_graph", lambda: Workflow())
    frontend._render_approval_controls(state)
    assert not commands
    assert "Approval Required" in ui.visible()
    assert "OSGuard Workspace Cleanup" in ui.visible()
    assert "CLEAR_OSGUARD_DEMO_CACHE" not in ui.visible()
    ui.button_returns[button] = True
    frontend._render_approval_controls(state)
    assert len(commands) == 1
    assert commands[0][0] == {"decision": decision, "plan_id": state["repair_plan"].plan_id,
                              "fingerprint": state["repair_plan"].fingerprint}
    frontend._render_approval_controls(state)
    assert len(commands) == 1


def test_ineligible_plan_has_no_approval_and_cleanup_not_prepared_automatically(ui, monkeypatch):
    state = pending_state()
    state["repair_eligibility"] = RepairEligibility(status="ineligible")
    ui.session_state["osguard_pending_thread_id"] = "thread-1"
    frontend._render_approval_controls(state)
    assert not any(name == "button" for name, _, _ in ui.calls)
    monkeypatch.setattr(frontend, "_knowledge_status", ready_status)
    ui.session_state["osguard_page"] = "Settings"
    frontend.main()
    assert "Workspace Maintenance" in ui.visible()
    assert "Prepare workspace files" in ui.visible()
    assert "Review workspace cleanup" in ui.visible()


def test_resolved_cleanup_only_shows_confirmed_completion(ui):
    state = pending_state()
    state["approval_state"] = ApprovalState(status="approved")
    state["execution_result"] = ExecutionValidationResult(status="succeeded")
    state["validation_result"] = PostRepairValidationResult(status="resolved", details="Fresh check complete")
    frontend._render_supervisor_result(state)
    assert "confirmed by a fresh check" in ui.visible()
    assert not any(name == "button" and args[0] == "Approve" for name, args, _ in ui.calls)
