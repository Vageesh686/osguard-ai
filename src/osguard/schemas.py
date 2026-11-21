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
    os_build: str | None = None
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
    """A user report or measured read-only observation with provenance."""

    description: str
    source: Literal["user_report", "user_provided_log", "read_only_tool"]
    supporting_quote: str = ""
    tool_name: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class DiagnosticHypothesis(StrictModel):
    """An explicitly uncertain explanation supported by available evidence."""

    description: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    supporting_quotes: list[str] = Field(default_factory=list)
    uncertainty: str


class CommandVerificationFinding(StrictModel):
    command_text: str
    user_intent: str | None = None
    intent_match: Literal["matches", "does_not_match", "unclear"] = "unclear"
    recognized_parts: list[str] = Field(default_factory=list)
    unknown_parts: list[str] = Field(default_factory=list)
    risk: Literal["low", "medium", "high", "unknown"] = "unknown"
    potential_effects: list[str] = Field(default_factory=list)
    requires_admin: Literal["yes", "no", "unknown"] = "unknown"
    explanation: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    verified: bool = False
    should_execute: Literal[False] = False


class CompatibilityFinding(StrictModel):
    component: str
    installed_version: str | None = None
    required_version: str | None = None
    installed_os: str | None = None
    installed_architecture: str | None = None
    required_os: str | None = None
    required_architecture: str | None = None
    result: Literal["compatible", "incompatible", "unknown"] = "unknown"
    fact_status: Literal[
        "user_reported", "read_only_tool", "documented", "hypothesis", "not_established"
    ] = (
        "not_established"
    )
    installed_version_source: Literal["user_reported", "read_only_tool", "not_established"] = "not_established"
    requirement_source: Literal["user_reported", "documentation", "not_established"] = "not_established"
    hypothesis: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    documented_requirement_ids: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class RetrievedEvidence(StrictModel):
    source_id: str
    title: str
    source_url: str | None = None
    os_version: str | None = None
    passage: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(StrictModel):
    """Status and provenance for one bounded documentation lookup."""

    status: Literal[
        "success",
        "not_applicable",
        "empty_query",
        "index_missing",
        "no_results",
        "unsupported_filters",
        "index_corrupt",
        "retrieval_error",
    ]
    query: str
    backend: Literal["faiss", "in_memory", "unavailable"] | None = None
    evidence: list[RetrievedEvidence] = Field(default_factory=list)
    message: str = ""
    filters: dict[str, str] = Field(default_factory=dict)


class ToolExecutionResult(StrictModel):
    """A bounded read-only tool call; data is evidence, not an instruction."""

    tool_name: str
    status: Literal[
        "success",
        "invalid_input",
        "permission_denied",
        "unsupported_os",
        "not_found",
        "failed",
    ]
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    evidence_id: str | None = None
    error: str | None = None


class CorrectiveActionCandidate(StrictModel):
    """A recommendation candidate; it is never an executable command."""

    description: str = Field(min_length=1, max_length=500)
    intended_purpose: str = Field(min_length=1, max_length=500)
    target_subsystem: OSSubsystem
    operation: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    parameters: dict[str, str | int | float | bool | None] = Field(default_factory=dict, max_length=12)
    rationale: str = Field(min_length=1, max_length=1200)
    evidence_ids: list[str] = Field(default_factory=list, max_length=8)
    evidence_quotes: dict[str, str] = Field(default_factory=dict, max_length=8)
    required_environment_conditions: list[str] = Field(default_factory=list, max_length=8)
    potential_effects: list[str] = Field(default_factory=list, max_length=8)
    risks: list[str] = Field(default_factory=list, max_length=8)
    requires_administrator: Literal["yes", "no", "unknown"] = "unknown"
    reversible: bool | None = None
    intent_evidence_quote: str | None = Field(default=None, max_length=500)


class ProposedCorrectiveAction(CorrectiveActionCandidate):
    action_id: str = Field(pattern=r"^act-[a-f0-9]{16}$")
    risk: Literal["low", "medium", "high", "unknown"] = "unknown"


class ActionProposalOutput(StrictModel):
    """Bounded structured output from the corrective-action proposer."""

    actions: list[CorrectiveActionCandidate] = Field(default_factory=list, max_length=5)


class ActionProposalResult(StrictModel):
    status: Literal["not_run", "proposed", "no_action", "failed"] = "not_run"
    message: str = ""
    candidate_count: int = 0


class VerificationCheck(StrictModel):
    result: Literal["pass", "fail", "unknown"] = "unknown"
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class IEEEAssessment(StrictModel):
    """Structured LLM review; deterministic rules remain authoritative."""

    intent: VerificationCheck
    environment: VerificationCheck
    evidence: VerificationCheck
    effect: VerificationCheck
    risk: Literal["low", "medium", "high", "unknown"] = "unknown"
    explanation: str = ""


class IEEEVerificationResult(StrictModel):
    action_id: str
    intent: VerificationCheck
    environment: VerificationCheck
    evidence: VerificationCheck
    effect: VerificationCheck
    overall: Literal["supported", "unsupported", "uncertain"] = "uncertain"
    risk: Literal["low", "medium", "high", "unknown"] = "unknown"
    reason_codes: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    explanation: str = ""


class IEEEVerificationSummary(StrictModel):
    status: Literal["not_run", "completed", "no_actions", "partial_failure"] = "not_run"
    message: str = ""
    result_count: int = 0


class RepairEligibility(StrictModel):
    status: Literal["not_evaluated", "eligible", "ineligible", "unknown"] = (
        "not_evaluated"
    )
    action_id: str | None = None
    plan_id: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    message: str = ""


class DemoCacheSnapshot(StrictModel):
    """Measured state of the one OSGuard-owned disposable cache entry."""

    cache_id: Literal["osguard_demo"] = "osguard_demo"
    target: str
    payload_size: int = Field(ge=0)
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    owner_marker_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class DemoCacheInspection(StrictModel):
    status: Literal["ready", "empty", "missing", "unsafe", "invalid", "failed", "unsupported_os"]
    snapshot: DemoCacheSnapshot | None = None
    reason_code: str = ""
    message: str = ""


class RepairPlan(StrictModel):
    """An exact, immutable-by-fingerprint preview; not execution authority."""

    plan_id: str = Field(pattern=r"^plan-[a-f0-9]{32}$")
    action_id: str = Field(pattern=r"^act-[a-f0-9]{16}$")
    executable_action_id: str
    target: str
    parameters: dict[str, str]
    intended_outcome: str
    expected_effects: list[str]
    potential_risks: list[str]
    preconditions: list[str]
    requires_user_approval: Literal[True] = True
    validator_id: str
    pre_state: DemoCacheSnapshot
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class ApprovalState(StrictModel):
    status: Literal["not_requested", "pending", "approved", "declined", "expired"] = (
        "not_requested"
    )
    action_id: str | None = None
    plan_id: str | None = None
    fingerprint: str | None = None
    reason_codes: list[str] = Field(default_factory=list)


class ApprovalDecision(StrictModel):
    decision: Literal["approve", "decline"]
    plan_id: str
    fingerprint: str


class ExecutionValidationResult(StrictModel):
    status: Literal[
        "not_started", "succeeded", "failed", "unknown", "blocked", "already_executed"
    ] = "not_started"
    action_id: str | None = None
    plan_id: str | None = None
    details: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    before_snapshot: DemoCacheSnapshot | None = None
    after_snapshot: DemoCacheSnapshot | None = None


class PostRepairValidationResult(StrictModel):
    status: Literal[
        "not_started", "resolved", "unresolved", "partially_resolved", "failed", "unverifiable"
    ] = "not_started"
    action_id: str | None = None
    plan_id: str | None = None
    details: str = ""
    evidence: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    before_snapshot: DemoCacheSnapshot | None = None
    after_snapshot: DemoCacheSnapshot | None = None


class SpecialistResult(StrictModel):
    specialist: SpecialistName
    status: Literal["completed", "failed"]
    message: str


class DiagnosticAgentOutput(StrictModel):
    """Structured analysis grounded only in the request and supplied logs."""

    reported_symptoms: list[str] = Field(default_factory=list)
    potentially_affected_subsystems: list[OSSubsystem] = Field(default_factory=list)
    observations: list[DiagnosticObservation] = Field(default_factory=list)
    hypotheses: list[DiagnosticHypothesis] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    safe_diagnostic_steps: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)


class CommandVerificationOutput(StrictModel):
    """Static review result; the command is never executed by OSGuard."""

    findings: list[CommandVerificationFinding] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)


class CompatibilityAgentOutput(StrictModel):
    """Compatibility assessment separated into reports and hypotheses."""

    findings: list[CompatibilityFinding] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)


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
