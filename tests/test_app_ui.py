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

