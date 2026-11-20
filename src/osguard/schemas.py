"""Structured contracts shared by OSGuard's supervisor and specialists."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """Base for data crossing agent boundaries; reject unexpected fields."""

    model_config = ConfigDict(extra="forbid")


class RequestIntent(StrEnum):
    DIAGNOSE = "diagnose"
    ANALYZE_LOGS = "analyze_logs"
    VERIFY_COMMAND = "verify_command"
    CHECK_COMPATIBILITY = "check_compatibility"
    UNCLEAR = "unclear"


class ProblemType(StrEnum):
    PERFORMANCE = "performance"
    SOFTWARE_FAILURE = "software_failure"
    COMMAND_SAFETY = "command_safety"
    COMPATIBILITY = "compatibility"
    SYSTEM_CONFIGURATION = "system_configuration"
    SECURITY_PERMISSIONS = "security_permissions"
    NETWORKING = "networking"
    STORAGE = "storage"
    MEMORY = "memory"
    SERVICES_STARTUP = "services_startup"
    UNKNOWN = "unknown"


class OSSubsystem(StrEnum):
    PROCESS_CPU = "process_cpu"
    MEMORY = "memory"
    STORAGE_FILESYSTEM = "storage_filesystem"
    SERVICES_STARTUP = "services_startup"
    DEVICES_DRIVERS = "devices_drivers"
    SOFTWARE_DEPENDENCIES = "software_dependencies"
    SYSTEM_CONFIGURATION = "system_configuration"
    SECURITY_PERMISSIONS = "security_permissions"
    NETWORKING = "networking"
    COMMAND_SAFETY = "command_safety"
    UNKNOWN = "unknown"


class SpecialistName(StrEnum):
    DIAGNOSTIC = "diagnostic"
    COMMAND_VERIFICATION = "command_verification"
    COMPATIBILITY = "compatibility"


class SystemEnvironment(StrictModel):
    """Environment details explicitly reported or later collected by tools."""

    source: Literal["user_reported", "read_only_tool", "unknown"] = "unknown"
    os_name: str | None = None
    os_version: str | None = None
    architecture: str | None = None
    application_name: str | None = None
    application_version: str | None = None
    runtime_versions: dict[str, str] = Field(default_factory=dict)
    other_known_facts: list[str] = Field(default_factory=list)


class SupervisorClassification(StrictModel):
    """One structured classification and routing decision for a user request."""

    intent: RequestIntent
    problem_type: ProblemType = ProblemType.UNKNOWN
    os_subsystems: list[OSSubsystem] = Field(default_factory=list)
    available_environment: SystemEnvironment = Field(
        default_factory=SystemEnvironment,
        description="Only facts explicitly stated by the user; do not inspect the host.",
    )
    selected_specialists: list[SpecialistName] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    routing_rationale: str = ""


class DiagnosticObservation(StrictModel):
    """A confirmed observation with provenance; never use for an inference."""

    description: str
    source: str
    evidence_ids: list[str] = Field(default_factory=list)


class DiagnosticHypothesis(StrictModel):
    """An explicitly uncertain explanation supported by available evidence."""

    description: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    uncertainty: str


class CommandVerificationFinding(StrictModel):
    command_text: str
    user_intent: str | None = None
    recognized_parts: list[str] = Field(default_factory=list)
    unknown_parts: list[str] = Field(default_factory=list)
    risk: Literal["low", "medium", "high", "unknown"] = "unknown"
    potential_effects: list[str] = Field(default_factory=list)
    verified: bool = False
    should_execute: Literal[False] = False


class CompatibilityFinding(StrictModel):
    component: str
    installed_version: str | None = None
    required_version: str | None = None
    result: Literal["compatible", "incompatible", "unknown"] = "unknown"
    evidence_ids: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class RetrievedEvidence(StrictModel):
    source_id: str
    title: str
    source_url: str | None = None
    os_version: str | None = None
    passage: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProposedCorrectiveAction(StrictModel):
    action_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    rationale: str
    risk: Literal["low", "medium", "high", "unknown"] = "unknown"


class VerificationCheck(StrictModel):
    result: Literal["pass", "fail", "unknown"] = "unknown"
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)


class IEEEVerificationResult(StrictModel):
    action_id: str
    intent: VerificationCheck
    environment: VerificationCheck
    evidence: VerificationCheck
    effect: VerificationCheck
    overall: Literal["supported", "unsupported", "uncertain"] = "uncertain"
    reason_codes: list[str] = Field(default_factory=list)


class RepairEligibility(StrictModel):
    status: Literal["not_evaluated", "eligible", "ineligible", "unknown"] = (
        "not_evaluated"
    )
    action_id: str | None = None
    reason_codes: list[str] = Field(default_factory=list)


class ApprovalState(StrictModel):
    status: Literal["not_requested", "pending", "approved", "declined", "expired"] = (
        "not_requested"
    )
    action_id: str | None = None


class ExecutionValidationResult(StrictModel):
    status: Literal["not_started", "succeeded", "failed", "unknown"] = "not_started"
    action_id: str | None = None
    details: str | None = None


class SpecialistResult(StrictModel):
    specialist: SpecialistName
    status: Literal["not_implemented", "completed", "failed"]
    message: str


class WorkflowError(StrictModel):
    stage: str
    code: str
    message: str


class FinalResponse(StrictModel):
    message: str
    workflow_status: str
    issue_category: ProblemType = ProblemType.UNKNOWN
    selected_specialists: list[SpecialistName] = Field(default_factory=list)
    findings_available: bool = False
