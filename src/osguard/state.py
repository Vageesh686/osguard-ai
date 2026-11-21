"""Typed shared state for the OSGuard LangGraph workflow."""

from __future__ import annotations

import operator
from typing import Annotated, Required, TypedDict

from osguard.schemas import (
    ApprovalState,
    CommandVerificationFinding,
    CompatibilityFinding,
    DiagnosticHypothesis,
    DiagnosticObservation,
    ExecutionValidationResult,
    FinalResponse,
    IEEEVerificationResult,
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
    proposed_corrective_actions: Annotated[
        list[ProposedCorrectiveAction], operator.add
    ]
    ieee_verification_results: Annotated[list[IEEEVerificationResult], operator.add]
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
        "proposed_corrective_actions": [],
        "ieee_verification_results": [],
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
