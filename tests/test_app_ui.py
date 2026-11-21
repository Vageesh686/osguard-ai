"""UI rendering checks with a local Streamlit test double."""

import runpy
import sys
from pathlib import Path
from types import ModuleType

from osguard.schemas import (
    IEEEVerificationResult,
    IEEEVerificationSummary,
    ApprovalState,
    DemoCacheSnapshot,
    ExecutionValidationResult,
    PostRepairValidationResult,
    RepairEligibility,
    RepairPlan,
    ProposedCorrectiveAction,
    VerificationCheck,
    FinalResponse,
    ProblemType,
    RequestIntent,
    SpecialistName,
    SpecialistResult,
    SupervisorClassification,
    RetrievedEvidence,
    RetrievalResult,
    SystemEnvironment,
    ToolExecutionResult,
    OSSubsystem,
)


class _Expander:
    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return False


class _FakeStreamlit(ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.calls = []
        self.session_state = {}
        self.button_returns = {}

    def cache_resource(self, **_kwargs):
        return lambda function: function

    def expander(self, *args, **kwargs):
        self.calls.append(("expander", args, kwargs))
        return _Expander()

    def spinner(self, *args, **kwargs):
        self.calls.append(("spinner", args, kwargs))
        return _Expander()

    def text_area(self, *_args, **_kwargs):
        return ""

    def button(self, label, **kwargs):
        self.calls.append(("button", (label,), kwargs))
        return self.button_returns.pop(label, False)

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return record


def _load_app_with_fake_streamlit(monkeypatch, *, button_returns=None):
    fake_streamlit = _FakeStreamlit()
    fake_streamlit.button_returns.update(button_returns or {})
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    namespace = runpy.run_path(str(Path(__file__).parents[1] / "app.py"))
    return namespace["_render_supervisor_result"], fake_streamlit


def test_initialize_documentation_prewarms_without_groq(monkeypatch):
    from osguard.rag import retriever

    calls = []
    def prepared(query, *, top_k):
        calls.append((query, top_k))
        return RetrievalResult(status="success", query=query, backend="in_memory")

    monkeypatch.setattr(retriever, "search_documentation", prepared)
    _, fake_st = _load_app_with_fake_streamlit(
        monkeypatch, button_returns={"Initialize documentation": True}
    )
    assert calls == [("Windows troubleshooting", 1)]
    assert fake_st.session_state["osguard_kb_initialization"].backend == "in_memory"
    assert any(
        name == "success" and "In-memory fallback knowledge base is ready" in str(args)
        for name, args, _kwargs in fake_st.calls
    )


def _base_result(*, specialist_status, workflow_status, message):
    specialist = SpecialistName.DIAGNOSTIC
    classification = SupervisorClassification(
        intent=RequestIntent.DIAGNOSE,
        problem_type=ProblemType.PERFORMANCE,
        selected_specialists=[specialist],
    )
    return {
        "classification": classification,
        "selected_specialists": [specialist],
        "workflow_status": workflow_status,
        "specialist_results": [
            SpecialistResult(
                specialist=specialist,
                status=specialist_status,
                message=message,
            )
        ],
        "final_response": FinalResponse(
            message="Workflow response",
            workflow_status=workflow_status,
            issue_category=ProblemType.PERFORMANCE,
            selected_specialists=[specialist],
            findings_available=specialist_status == "completed",
        ),
    }


def test_streamlit_ui_renders_successful_specialist_workflow(monkeypatch):
    render_result, fake_st = _load_app_with_fake_streamlit(monkeypatch)
    result = _base_result(
        specialist_status="completed",
        workflow_status="specialists_completed",
        message="Diagnostic analysis completed using supplied text.",
    )
    result["diagnostic_symptoms"] = ["High CPU usage reported"]

    render_result(result)

    rendered = [(name, args) for name, args, _kwargs in fake_st.calls]
    assert any(name == "info" and "completed" in str(args).casefold() for name, args in rendered)
    assert any(name == "write" and "High CPU usage reported" in str(args) for name, args in rendered)
    assert any(name == "write" and "Workflow response" in str(args) for name, args in rendered)
    assert not any(name == "error" for name, _args in rendered)


def test_streamlit_ui_renders_failed_specialist_and_error(monkeypatch):
    render_result, fake_st = _load_app_with_fake_streamlit(monkeypatch)
    result = _base_result(
        specialist_status="failed",
        workflow_status="specialist_failure",
        message="The specialist could not complete its analysis.",
    )
    from osguard.schemas import WorkflowError

    result["errors"] = [
        WorkflowError(
            stage="diagnostic_agent",
            code="invalid_llm_output",
            message="Diagnostic: invalid structured output.",
        )
    ]

    render_result(result)

    rendered = [(name, args) for name, args, _kwargs in fake_st.calls]
    error_messages = [str(args) for name, args in rendered if name == "error"]
    assert any("could not complete" in message.casefold() for message in error_messages)
    assert any("invalid structured output" in message.casefold() for message in error_messages)
    assert any(name == "caption" and "no verified findings" in str(args).casefold()
               for name, args in rendered)


def test_streamlit_ui_shows_read_only_environment_and_retrieval_failure(monkeypatch):
    render_result, fake_st = _load_app_with_fake_streamlit(monkeypatch)
    result = _base_result(
        specialist_status="completed",
        workflow_status="specialists_completed",
        message="Evidence collection completed with limitations.",
    )
    result["available_environment"] = SystemEnvironment(
        source="read_only_tool", os_name="Windows 11", os_version="10.0.22631",
        os_build="22631", architecture="AMD64",
    )
    result["retrieval_result"] = RetrievalResult(
        status="index_missing", query="cpu", backend="unavailable",
        message="Build the local index first."
    )
    result["tool_results"] = [
        ToolExecutionResult(
            tool_name="get_process_stats", status="permission_denied",
            summary="Process statistics could not be read.", error="AccessDenied",
        )
    ]

    render_result(result)

    rendered = [(name, args) for name, args, _kwargs in fake_st.calls]
    assert any("observed by read-only tool" in str(args).casefold() for _name, args in rendered)
    assert any("index missing" in str(args).casefold() for name, args in rendered if name == "warning")
    assert any("retrieval unavailable" in str(args).casefold() for name, args in rendered if name == "write")
    assert any("permission denied" in str(args).casefold() for _name, args in rendered)
    assert not any(name == "markdown" and "Official source" in str(args) for name, args in rendered)


def test_streamlit_ui_renders_retrieved_source_and_tool_measurement(monkeypatch):
    render_result, fake_st = _load_app_with_fake_streamlit(monkeypatch)
    result = _base_result(
        specialist_status="completed",
        workflow_status="specialists_completed",
        message="Read-only evidence is available.",
    )
    evidence = RetrievedEvidence(
        source_id="cpu-doc#part-1", title="CPU guidance",
        source_url="https://learn.microsoft.com/cpu", os_version="Windows 11",
        passage="A CPU sample does not establish a root cause.",
        metadata={"relevance_score": 0.83},
    )
    result["retrieval_result"] = RetrievalResult(
        status="success", query="cpu", backend="faiss", evidence=[evidence]
    )
    result["retrieved_evidence"] = [evidence]
    result["tool_results"] = [
        ToolExecutionResult(
            tool_name="get_memory_info", status="success", summary="Memory sample",
            evidence_id="tool:get_memory_info:fixture", data={"utilization_percent": 64.0},
        )
    ]

    render_result(result)

    rendered = [(name, args) for name, args, _kwargs in fake_st.calls]
    assert any(name == "markdown" and "learn.microsoft.com/cpu" in str(args) for name, args in rendered)
    assert any(name == "write" and "utilization_percent" in str(args) for name, args in rendered)
    assert any(name == "caption" and "measured data" in str(args).casefold() for name, args in rendered)
    assert any(name == "write" and "FAISS available" in str(args) for name, args in rendered)


def test_streamlit_ui_shows_memory_process_table_and_raw_result(monkeypatch):
    render_result, fake_st = _load_app_with_fake_streamlit(monkeypatch)
    result = _base_result(
        specialist_status="completed", workflow_status="specialists_completed",
        message="The measured memory snapshot is available.",
    )
    result["tool_results"] = [
        ToolExecutionResult(
            tool_name="get_memory_info", status="success", summary="Memory snapshot",
            evidence_id="tool:get_memory_info:fixture",
            data={"total_bytes": 1000, "used_bytes": 600, "available_bytes": 400,
                  "utilization_percent": 60.0},
        ),
        ToolExecutionResult(
            tool_name="get_process_stats", status="success", summary="Process snapshot",
            evidence_id="tool:get_process_stats:fixture",
            data={"sort_by": "memory", "memory_metric_definition": "Working set is not additive.",
                  "processes": [{"name": "fixture.exe", "pid": 4, "memory_bytes": 512,
                                 "memory_mib": 0.0, "cpu_percent": None}]},
        ),
    ]
    render_result(result)
    assert any(name == "dataframe" and args[0][0]["Process"] == "fixture.exe"
               for name, args, _ in fake_st.calls)
    assert any(name == "write" and "400 bytes available" in str(args)
               for name, args, _ in fake_st.calls)
    assert any(name == "expander" and "Raw read-only Windows checks" in str(args)
               for name, args, _ in fake_st.calls)


def test_streamlit_ui_reports_in_memory_fallback_without_claiming_faiss(monkeypatch):
    render_result, fake_st = _load_app_with_fake_streamlit(monkeypatch)
    result = _base_result(
        specialist_status="completed", workflow_status="specialists_completed",
        message="Evidence collection completed.",
    )
    result["retrieval_result"] = RetrievalResult(
        status="no_results", query="cpu", backend="in_memory",
        message="No matching passages were found.",
    )
    render_result(result)
    written = [str(args) for name, args, _kwargs in fake_st.calls if name == "write"]
    assert any("In-memory fallback active" in item for item in written)
    assert not any("FAISS available" in item for item in written)


def test_streamlit_ui_displays_ieee_checks_sources_and_no_execution_controls(monkeypatch):
    render_result, fake_st = _load_app_with_fake_streamlit(monkeypatch)
    result = _base_result(
        specialist_status="completed",
        workflow_status="specialists_completed",
        message="IEEE recommendation review: 1 supported, 0 unsupported, 0 uncertain.",
    )
    action = ProposedCorrectiveAction(
        action_id="act-0123456789abcdef",
        description="Install or update Runtime to documented required version 2.0.",
        intended_purpose="Resolve the documented Runtime mismatch.",
        target_subsystem=OSSubsystem.SOFTWARE_DEPENDENCIES,
        operation="install_or_update_dependency",
        parameters={"component": "Runtime", "required_version": "2.0"},
        rationale="The user-reported installed version is below the documented requirement.",
        evidence_ids=["doc#chunk-1"],
        evidence_quotes={"doc#chunk-1": "Runtime 2.0 is required for Windows 11."},
        required_environment_conditions=["Windows 11"],
        potential_effects=["Changes installed software."],
        risks=["May affect applications using this runtime."],
        requires_administrator="unknown",
        risk="high",
    )
    check = VerificationCheck(
        result="pass", rationale="The cited documented requirement supports the target version.",
        evidence_ids=["doc#chunk-1"],
    )
    verification = IEEEVerificationResult(
        action_id=action.action_id,
        intent=check,
        environment=check.model_copy(update={"result": "unknown", "rationale": "Admin requirement unknown."}),
        evidence=check,
        effect=check,
        overall="uncertain",
        risk="high",
        reason_codes=["environment_prerequisite_unknown"],
        supporting_evidence_ids=["doc#chunk-1"],
        missing_information=["Confirm administrator requirements."],
        explanation="This is a recommendation only.",
    )
    result.update({
        "proposed_corrective_actions": [action],
        "ieee_verification_results": [verification],
        "ieee_verification_summary": IEEEVerificationSummary(
            status="completed", message="One result recorded.", result_count=1
        ),
    })

    render_result(result)

    rendered = [(name, args) for name, args, _kwargs in fake_st.calls]
    assert any(name == "subheader" and "IEEE verification" in str(args) for name, args in rendered)
    assert any(name == "warning" and "uncertain" in str(args).casefold() for name, args in rendered)
    assert any(name == "write" and "Runtime 2.0 is required" in str(args) for name, args in rendered)
    assert any(name == "warning" and "administrator requirements" in str(args).casefold() for name, args in rendered)
    button_labels = [str(args).casefold() for name, args in rendered if name == "button"]
    assert not any("approve" in label or "execute" in label or "repair" in label for label in button_labels)


def _phase5_ui_result():
    snapshot = DemoCacheSnapshot(
        target="C:/project/data/demo_app/cache",
        payload_size=64,
        payload_sha256="a" * 64,
        owner_marker_sha256="b" * 64,
    )
    plan = RepairPlan(
        plan_id="plan-" + "1" * 32,
        action_id="act-" + "2" * 16,
        executable_action_id="CLEAR_OSGUARD_DEMO_CACHE",
        target=snapshot.target,
        parameters={"cache_id": "osguard_demo"},
        intended_outcome="The disposable cache is empty.",
        expected_effects=["The known cache entry is cleared."],
        potential_risks=["Disposable demo data is discarded."],
        preconditions=["The marker and known payload are present."],
        validator_id="demo_cache_empty_and_owned",
        pre_state=snapshot,
        fingerprint="f" * 64,
    )
    return {
        "repair_plan": plan,
        "repair_eligibility": RepairEligibility(
            status="eligible", action_id=plan.action_id, plan_id=plan.plan_id,
        ),
        "repair_eligibility_results": [RepairEligibility(
            status="eligible", action_id=plan.action_id, plan_id=plan.plan_id,
        )],
        "approval_state": ApprovalState(
            status="pending", action_id=plan.action_id, plan_id=plan.plan_id,
            fingerprint=plan.fingerprint,
        ),
        "execution_result": ExecutionValidationResult(),
        "validation_result": PostRepairValidationResult(),
        "workflow_status": "awaiting_approval",
    }


def test_phase5_ui_shows_exact_plan_and_approval_only_when_pending(monkeypatch):
    render, fake_st = _load_app_with_fake_streamlit(monkeypatch)
    controls = render.__globals__["_render_approval_controls"]
    result = _phase5_ui_result()
    fake_st.session_state["osguard_pending_thread_id"] = "ui-thread"

    render(result)
    controls(result)

    rendered = [(name, args) for name, args, _kwargs in fake_st.calls]
    assert any(name == "write" and "CLEAR_OSGUARD_DEMO_CACHE" in str(args) for name, args in rendered)
    assert any(name == "write" and "C:/project/data/demo_app/cache" in str(args) for name, args in rendered)
    assert any(name == "button" and args == ("APPROVE",) for name, args in rendered)
    assert any(name == "button" and args == ("DECLINE",) for name, args in rendered)

    fake_st.calls.clear()
    ineligible = {**result, "repair_eligibility": RepairEligibility(status="ineligible")}
    controls(ineligible)
    assert not any(name == "button" for name, _args, _kwargs in fake_st.calls)


def test_phase5_ui_consumes_resume_cursor_and_does_not_repeat_on_rerun(monkeypatch):
    render, fake_st = _load_app_with_fake_streamlit(monkeypatch)
    controls = render.__globals__["_render_approval_controls"]
    result = _phase5_ui_result()
    fake_st.session_state["osguard_pending_thread_id"] = "ui-thread"
    fake_st.button_returns["APPROVE"] = True
    calls = []
    completed = {
        **result,
        "approval_state": result["approval_state"].model_copy(update={"status": "approved"}),
        "execution_result": ExecutionValidationResult(status="succeeded"),
        "validation_result": PostRepairValidationResult(status="resolved", details="Fixture empty."),
    }

    class _Workflow:
        def invoke(self, command, config):
            calls.append((command.resume, config))
            return completed

    render.__globals__["_get_supervisor_graph"] = lambda: _Workflow()
    controls(result)
    assert len(calls) == 1, [(name, args) for name, args, _ in fake_st.calls if name in {"error", "button"}]
    assert calls[0][0] == {
        "decision": "approve",
        "plan_id": result["repair_plan"].plan_id,
        "fingerprint": result["repair_plan"].fingerprint,
    }
    assert "osguard_pending_thread_id" not in fake_st.session_state
    controls(fake_st.session_state["osguard_supervisor_result"])
    assert len(calls) == 1

    render(completed)
    assert any(name == "success" and "Resolved" in str(args) for name, args, _kwargs in fake_st.calls)

