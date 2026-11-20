"""LangGraph orchestration for the Supervisor and three specialist workflows."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from osguard.agents._common import ModelProvider, create_model_provider
from osguard.agents.command_verify import create_command_verification_agent
from osguard.agents.compatibility import create_compatibility_agent
from osguard.agents.diagnostic import create_diagnostic_agent
from osguard.config import GroqSettings
from osguard.schemas import (
    FinalResponse,
    ProblemType,
    SpecialistName,
    SpecialistResult,
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
SpecialistNode = Callable[[OSGuardState], dict[str, Any]]


def route_to_next_specialist(
    state: OSGuardState,
) -> Literal[
    "diagnostic_agent",
    "command_verification_agent",
    "compatibility_agent",
    "aggregate_findings",
]:
    """Route to each selected specialist at most once, even after partial errors."""
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
    """Set status from completed specialist results without replacing their data."""
    classification = state.get("classification")
    results: list[SpecialistResult] = state.get("specialist_results", [])
    errors = state.get("errors", [])
    has_supervisor_error = any(error.stage == "supervisor" for error in errors)
    failed = any(result.status == "failed" for result in results)
    succeeded = any(result.status == "completed" for result in results)

    if has_supervisor_error:
        status = "classification_error"
    elif classification is not None and classification.needs_clarification:
        status = "needs_clarification"
    elif failed and succeeded:
        status = "partial_failure"
    elif failed:
        status = "specialist_failure"
    elif succeeded:
        status = "specialists_completed"
    else:
        status = "classification_complete"
    return {"workflow_status": status}


def _finding_summary(state: OSGuardState) -> str:
    symptoms = len(state.get("diagnostic_symptoms", []))
    observations = len(state.get("diagnostic_observations", []))
    hypotheses = len(state.get("diagnostic_hypotheses", []))
    command_findings = len(state.get("command_verification_findings", []))
    compatibility_findings = len(state.get("compatibility_findings", []))
    steps = len(state.get("safe_diagnostic_steps", []))
    parts: list[str] = []
    if symptoms or observations or hypotheses:
        parts.append(
            f"diagnostic analysis: {symptoms} reported symptom(s), "
            f"{observations} quoted observation(s), {hypotheses} hypothesis/hypotheses"
        )
    if command_findings:
        parts.append(f"static command review: {command_findings} finding(s)")
    if compatibility_findings:
        parts.append(f"compatibility review: {compatibility_findings} finding(s)")
    if steps:
        parts.append(f"{steps} safe information-gathering step(s)")
    return "; ".join(parts) if parts else "no structured findings"


def final_response_node(state: OSGuardState) -> dict[str, FinalResponse]:
    """Build a concise response that reflects available and failed agent results."""
    classification: SupervisorClassification | None = state.get("classification")
    selected = list(state.get("selected_specialists", []))
    results: list[SpecialistResult] = state.get("specialist_results", [])
    errors = state.get("errors", [])
    status = state.get("workflow_status", "unknown")
    issue_category = (
        classification.problem_type if classification is not None else ProblemType.UNKNOWN
    )
    has_supervisor_error = any(error.stage == "supervisor" for error in errors)

    if has_supervisor_error:
        message = (
            "OSGuard could not classify this request reliably. No specialist analysis "
            "was started. Please restate the issue with its main symptom or command."
        )
    elif classification is not None and classification.needs_clarification:
        message = classification.clarification_question or (
            "Please provide more information about the Windows issue."
        )
        message += " No specialist analysis was started."
    elif results:
        specialist_labels = ", ".join(item.value for item in selected) or "none"
        message = (
            f"Classified as {issue_category.value}. Selected specialists: {specialist_labels}. "
            f"Available output: {_finding_summary(state)}. "
            "Analysis used only the supplied request and text; OSGuard did not inspect "
            "the computer, execute commands, or perform repairs."
        )
        if any(result.status == "failed" for result in results):
            message += " One or more specialists failed; successful results were retained."
    else:
        message = (
            f"Classified as {issue_category.value}, but no specialist was selected. "
            "No findings or recommendations are available."
        )

    finding_fields = (
        state.get("diagnostic_symptoms")
        or state.get("diagnostic_subsystems")
        or state.get("diagnostic_observations")
        or state.get("diagnostic_hypotheses")
        or state.get("safe_diagnostic_steps")
        or state.get("command_verification_findings")
        or state.get("compatibility_findings")
    )
    return {
        "final_response": FinalResponse(
            message=message,
            workflow_status=status,
            issue_category=issue_category,
            selected_specialists=selected,
            findings_available=bool(finding_fields),
        )
    }


def build_supervisor_graph(
    *,
    classifier: Classifier | None = None,
    settings: GroqSettings | None = None,
    model_factory: Callable[..., Any] | None = None,
    model: Any | None = None,
    specialist_nodes: Mapping[SpecialistName, SpecialistNode] | None = None,
) -> Any:
    """Build the typed graph with one shared Groq model and injectable agents.

    The default path creates a single ChatGroq instance for classification and
    specialist structured outputs. Injected classifiers or specialist nodes
    keep graph orchestration testable without Groq credentials/network access.
    """
    model_provider: ModelProvider = create_model_provider(
        settings=settings,
        model_factory=model_factory,
        model=model,
    )
    active_classifier = classifier
    if active_classifier is None:
        active_classifier = create_supervisor_classifier(model=model_provider())

    injected_nodes = specialist_nodes or {}
    diagnostic_node = injected_nodes.get(SpecialistName.DIAGNOSTIC)
    if diagnostic_node is None:
        diagnostic_node = create_diagnostic_agent(model_provider=model_provider)
    command_node = injected_nodes.get(SpecialistName.COMMAND_VERIFICATION)
    if command_node is None:
        command_node = create_command_verification_agent(model_provider=model_provider)
    compatibility_node = injected_nodes.get(SpecialistName.COMPATIBILITY)
    if compatibility_node is None:
        compatibility_node = create_compatibility_agent(model_provider=model_provider)

    graph = StateGraph(OSGuardState)
    graph.add_node("supervisor", create_supervisor_node(active_classifier))
    graph.add_node("diagnostic_agent", diagnostic_node)
    graph.add_node("command_verification_agent", command_node)
    graph.add_node("compatibility_agent", compatibility_node)
    graph.add_node("aggregate_findings", aggregate_findings_node)
    graph.add_node("final_response", final_response_node)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges("supervisor", route_to_next_specialist)
    for node_name in _SPECIALIST_NODES.values():
        graph.add_conditional_edges(node_name, route_to_next_specialist)
    graph.add_edge("aggregate_findings", "final_response")
    graph.add_edge("final_response", END)
    return graph.compile()
