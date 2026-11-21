"""UI rendering checks with a local Streamlit test double."""

import runpy
import sys
from pathlib import Path
from types import ModuleType

from osguard.schemas import (
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

    def cache_resource(self, **_kwargs):
        return lambda function: function

    def expander(self, *args, **kwargs):
        self.calls.append(("expander", args, kwargs))
        return _Expander()

    def text_area(self, *_args, **_kwargs):
        return ""

    def button(self, *_args, **_kwargs):
        return False

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return record


def _load_app_with_fake_streamlit(monkeypatch):
    fake_streamlit = _FakeStreamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake_streamlit)
    namespace = runpy.run_path(str(Path(__file__).parents[1] / "app.py"))
    return namespace["_render_supervisor_result"], fake_streamlit


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
        status="index_missing", query="cpu", message="Build the local index first."
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
        status="success", query="cpu", evidence=[evidence]
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

