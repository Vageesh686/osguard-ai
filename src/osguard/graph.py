"""LangGraph orchestration for Phase 1 request classification and routing."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from osguard.agents.command_verify import command_verification_agent_node
from osguard.agents.compatibility import compatibility_agent_node
from osguard.agents.diagnostic import diagnostic_agent_node
from osguard.config import GroqSettings
from osguard.schemas import (
    FinalResponse,
    ProblemType,
    SpecialistName,
    SupervisorClassification,
)
from osguard.state import OSGuardState
from osguard.supervisor import (
    SPECIALIST_ORDER,
    Classifier,
    create_supervisor_classifier,
    create_supervisor_node,
)


_SPECIALIST_NODES = {
    SpecialistName.DIAGNOSTIC: "diagnostic_agent",
    SpecialistName.COMMAND_VERIFICATION: "command_verification_agent",
    SpecialistName.COMPATIBILITY: "compatibility_agent",
}


def route_to_next_specialist(
    state: OSGuardState,
) -> Literal[
    "diagnostic_agent",
    "command_verification_agent",
    "compatibility_agent",
    "aggregate_findings",
]:
    """Select the next requested agent; each specialist can run at most once."""
    classification = state.get("classification")
    if classification is None or classification.needs_clarification:
        return "aggregate_findings"

    completed = set(state.get("completed_specialists", []))
    selected = set(state.get("selected_specialists", []))
    for specialist in SPECIALIST_ORDER:
        if specialist in selected and specialist not in completed:
            return _SPECIALIST_NODES[specialist]  # type: ignore[return-value]
    return "aggregate_findings"


def aggregate_findings_node(state: OSGuardState) -> dict[str, str]:
    """Summarize workflow progress without inventing specialist results."""
    classification = state.get("classification")
    if state.get("errors"):
        status = "classification_error"
    elif classification is not None and classification.needs_clarification:
        status = "needs_clarification"
    elif state.get("specialist_results"):
        status = "specialists_not_implemented"
    else:
        status = "classification_complete"
    return {"workflow_status": status}


def final_response_node(state: OSGuardState) -> dict[str, FinalResponse]:
    """Build a user-facing status report from structured workflow state."""
    classification: SupervisorClassification | None = state.get("classification")
    selected = list(state.get("selected_specialists", []))
    results = state.get("specialist_results", [])
    errors = state.get("errors", [])
    status = state.get("workflow_status", "unknown")

    if errors:
        message = (
            "OSGuard could not classify this request reliably. No specialists were "
            "run and no findings or recommendations are available. "
            "Please restate the issue with its main symptom or command."
        )
    elif classification is not None and classification.needs_clarification:
        message = classification.clarification_question or (
            "Please provide more information about the Windows issue."
        )
        message += " No specialist checks were run."
    elif results:
        specialist_labels = ", ".join(item.value for item in selected)
        subsystem_labels = ", ".join(
            item.value for item in (classification.os_subsystems if classification else [])
        ) or "unknown"
        issue_category = (
            classification.problem_type if classification else None
        )
        category_label = issue_category.value if issue_category else "unknown"
        message = (
            f"Classified as {category_label} ({subsystem_labels}). Selected specialists: "
            f"{specialist_labels}. The selected specialist paths are placeholders in this "
            "phase; no diagnostics, command checks, compatibility checks, or corrective "
            "recommendations were produced."
        )
    else:
        issue_category = (
            classification.problem_type if classification else None
        )
        category_label = issue_category.value if issue_category else "unknown"
        message = (
            f"Classified as {category_label}, but no specialist was selected. "
            "No findings or recommendations are available."
        )

    return {
        "final_response": FinalResponse(
            message=message,
            workflow_status=status,
            issue_category=(
                classification.problem_type
                if classification is not None
                else ProblemType.UNKNOWN
            ),
            selected_specialists=selected,
            findings_available=bool(
                state.get("diagnostic_observations")
                or state.get("diagnostic_hypotheses")
                or state.get("command_verification_findings")
                or state.get("compatibility_findings")
            ),
        )
    }


def build_supervisor_graph(
    *,
    classifier: Classifier | None = None,
    settings: GroqSettings | None = None,
    model_factory: Callable[..., Any] | None = None,
) -> Any:
    """Build the supervisor graph with injectable classification for tests.

    The default path creates one ChatGroq client and binds structured output
    once for this compiled graph. UI callers should cache the compiled graph.
    """
    active_classifier = (
        classifier
        if classifier is not None
        else create_supervisor_classifier(
            settings=settings,
            model_factory=model_factory,
        )
    )

    graph = StateGraph(OSGuardState)
    graph.add_node("supervisor", create_supervisor_node(active_classifier))
    graph.add_node("diagnostic_agent", diagnostic_agent_node)
    graph.add_node("command_verification_agent", command_verification_agent_node)
    graph.add_node("compatibility_agent", compatibility_agent_node)
    graph.add_node("aggregate_findings", aggregate_findings_node)
    graph.add_node("final_response", final_response_node)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", route_to_next_specialist)
    for node_name in _SPECIALIST_NODES.values():
        graph.add_conditional_edges(node_name, route_to_next_specialist)
    graph.add_edge("aggregate_findings", "final_response")
    graph.add_edge("final_response", END)
    return graph.compile()
