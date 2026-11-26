"""Exercise the real Streamlit renderer with a saved, read-only RAM result."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from osguard import frontend
from osguard.rag import knowledge_base
from osguard.schemas import DiagnosticObservation, ToolExecutionResult
from test_app_ui import pending_state, result


@pytest.fixture(autouse=True)
def no_real_workspace_preparation(monkeypatch):
    monkeypatch.setattr(frontend, "_prepare_workspace_once", lambda: None)


def test_streamlit_home_input_ram_result_and_navigation(monkeypatch):
    ready = knowledge_base.KnowledgeBaseStatus(
        "faiss_ready", "faiss", "Ready", "fixture-index", retrieval_verified=True
    )
    monkeypatch.setattr(knowledge_base, "inspect_knowledge_base", lambda: ready)
    monkeypatch.setattr(knowledge_base, "initialize_knowledge_base",
                        lambda: (_ for _ in ()).throw(AssertionError("valid index rebuilt")))
    calls = []

    class Workflow:
        def invoke(self, state, config):
            calls.append((state, config))
            report = result()
            report["diagnostic_observations"] = [DiagnosticObservation(
                description="Physical memory is 50% utilized.", source="read_only_tool",
                tool_name="get_memory_info", evidence_ids=["tool:get_memory_info:fixture"],
            )]
            report["tool_results"] = [ToolExecutionResult(
                tool_name="get_memory_info", status="success", summary="Memory measured.",
                evidence_id="tool:get_memory_info:fixture",
                data={"total_bytes": 16 * 1024**3, "used_bytes": 8 * 1024**3,
                      "available_bytes": 8 * 1024**3, "utilization_percent": 50.0},
            )]
            return report

    monkeypatch.setattr(frontend, "_get_supervisor_graph", lambda: Workflow())
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=40).run()
    assert not app.exception
    assert any("Intelligent Windows Troubleshooting" in item.value for item in app.title)
    app.text_area[0].set_value("Why is my RAM usage high?").run()
    app.button[0].click().run()
    assert not app.exception
    assert len(calls) == 1
    assert any("Your analysis" in item.value for item in app.title)
    assert any(item.label == "Total RAM" for item in app.metric)
    assert any("Physical memory is 50%" in item.value for item in app.markdown)
    app.radio[0].set_value("Knowledge Base").run()
    assert not app.exception and len(calls) == 1


@pytest.mark.parametrize("button,decision", [("Approve", "approve"), ("Decline", "decline")])
def test_streamlit_exact_approval_and_decline_render_without_auto_execution(
    monkeypatch, button, decision,
):
    ready = knowledge_base.KnowledgeBaseStatus(
        "faiss_ready", "faiss", "Ready", "fixture-index", retrieval_verified=True
    )
    monkeypatch.setattr(knowledge_base, "inspect_knowledge_base", lambda: ready)
    state = pending_state()
    calls = []

    class Workflow:
        def invoke(self, command, config):
            calls.append((command.resume, config))
            return {**state, "approval_state": state["approval_state"].model_copy(
                update={"status": "approved" if decision == "approve" else "declined"}
            )}

    monkeypatch.setattr(frontend, "_get_supervisor_graph", lambda: Workflow())
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=40).run()
    app.session_state["osguard_supervisor_result"] = state
    app.session_state["osguard_pending_thread_id"] = "thread-approval"
    app.radio[0].set_value("Results").run()
    assert not app.exception
    assert any(item.value == "Approval Required" for item in app.subheader)
    assert not calls
    key = ("approve_" if button == "Approve" else "decline_") + state["repair_plan"].plan_id
    app.button(key=key).click().run()
    assert not app.exception
    assert len(calls) == 1
    assert calls[0][0]["decision"] == decision
    assert calls[0][0]["fingerprint"] == state["repair_plan"].fingerprint
    assert "osguard_pending_thread_id" not in app.session_state
    app.run()
    assert len(calls) == 1
