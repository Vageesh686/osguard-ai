"""Typed shared state for the OSGuard LangGraph workflow."""

from __future__ import annotations

import operator
from typing import Annotated, Required, TypedDict

from osguard.schemas import (
    ActionProposalResult,
    ApprovalState,
    CommandVerificationFinding,
    CompatibilityFinding,
    DiagnosticHypothesis,
    DiagnosticObservation,
    ExecutionValidationResult,
    FinalResponse,
    IEEEVerificationResult,
    IEEEVerificationSummary,
    OSSubsystem,
    ProblemType,
    ProposedCorrectiveAction,
    RepairEligibility,
    RetrievedEvidence,
    RetrievalResult,
    SpecialistName,
    SpecialistResult,
    SupervisorClassification,
    SystemEnvironment,
    ToolExecutionResult,
    WorkflowError,
)


def _merge_action_records(existing: list, incoming: list, key_name: str) -> list:
    """Merge reducer-backed action records by ID, with the newest value winning."""
    merged: dict[str, object] = {}
    order: list[str] = []
    for item in [*existing, *incoming]:
        key = item.get(key_name) if isinstance(item, dict) else getattr(item, key_name, None)
        if not isinstance(key, str) or not key:
            continue
        if key not in merged:
            order.append(key)
        merged[key] = item
    return [merged[key] for key in order]


def merge_corrective_actions(existing: list, incoming: list) -> list:
    return _merge_action_records(existing, incoming, "action_id")


def merge_ieee_results(existing: list, incoming: list) -> list:
    return _merge_action_records(existing, incoming, "action_id")


class OSGuardState(TypedDict, total=False):
    """State channels shared by the supervisor, specialists and response node."""

    user_request: Required[str]
    classification: SupervisorClassification | None
    problem_type: ProblemType
    os_subsystems: list[OSSubsystem]
    diagnostic_subsystems: Annotated[list[OSSubsystem], operator.add]
    available_environment: SystemEnvironment
    selected_specialists: list[SpecialistName]
    missing_information: Annotated[list[str], operator.add]
    uncertainty_notes: Annotated[list[str], operator.add]
    diagnostic_symptoms: Annotated[list[str], operator.add]
    safe_diagnostic_steps: Annotated[list[str], operator.add]
    diagnostic_observations: Annotated[list[DiagnosticObservation], operator.add]
    diagnostic_hypotheses: Annotated[list[DiagnosticHypothesis], operator.add]
    command_verification_findings: Annotated[
        list[CommandVerificationFinding], operator.add
    ]
    compatibility_findings: Annotated[list[CompatibilityFinding], operator.add]
    retrieved_evidence: Annotated[list[RetrievedEvidence], operator.add]
    retrieval_result: RetrievalResult | None
    tool_results: Annotated[list[ToolExecutionResult], operator.add]
    action_proposal_result: ActionProposalResult
    proposed_corrective_actions: Annotated[
        list[ProposedCorrectiveAction], merge_corrective_actions
    ]
    ieee_verification_results: Annotated[list[IEEEVerificationResult], merge_ieee_results]
    ieee_verification_summary: IEEEVerificationSummary
    repair_eligibility: RepairEligibility | None
    approval_state: ApprovalState | None
    execution_result: ExecutionValidationResult | None
    validation_result: ExecutionValidationResult | None
    specialist_results: Annotated[list[SpecialistResult], operator.add]
    completed_specialists: Annotated[list[SpecialistName], operator.add]
    errors: Annotated[list[WorkflowError], operator.add]
    final_response: FinalResponse | None
    workflow_status: str


def make_initial_state(user_request: str) -> OSGuardState:
    """Create a clean session state without claiming host diagnostic facts."""
    if not isinstance(user_request, str):
        raise TypeError("user_request must be a string")

    return {
        "user_request": user_request,
        "classification": None,
        "problem_type": ProblemType.UNKNOWN,
        "os_subsystems": [],
        "diagnostic_subsystems": [],
        "available_environment": SystemEnvironment(),
        "selected_specialists": [],
        "missing_information": [],
        "uncertainty_notes": [],
        "diagnostic_symptoms": [],
        "safe_diagnostic_steps": [],
        "diagnostic_observations": [],
        "diagnostic_hypotheses": [],
        "command_verification_findings": [],
        "compatibility_findings": [],
        "retrieved_evidence": [],
        "retrieval_result": None,
        "tool_results": [],
        "action_proposal_result": ActionProposalResult(),
        "proposed_corrective_actions": [],
        "ieee_verification_results": [],
        "ieee_verification_summary": IEEEVerificationSummary(),
        "repair_eligibility": RepairEligibility(),
        "approval_state": ApprovalState(),
        "execution_result": ExecutionValidationResult(),
        "validation_result": ExecutionValidationResult(),
        "specialist_results": [],
        "completed_specialists": [],
        "errors": [],
        "final_response": None,
        "workflow_status": "received",
    }
