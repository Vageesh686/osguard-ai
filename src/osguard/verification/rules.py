"""Deterministic, fail-closed rules for IEEE recommendation verification."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from osguard.privacy import redact_sensitive_text
from osguard.schemas import (
    CompatibilityFinding,
    IEEEAssessment,
    IEEEVerificationResult,
    OSSubsystem,
    ProposedCorrectiveAction,
    RequestIntent,
    RetrievedEvidence,
    SystemEnvironment,
    ToolExecutionResult,
    VerificationCheck,
)
from osguard.state import OSGuardState


@dataclass(frozen=True)
class OperationPolicy:
    subsystem: OSSubsystem | None
    risk: str
    effects: tuple[str, ...]
    risks: tuple[str, ...]


KNOWN_RECOMMENDATION_OPERATIONS: dict[str, OperationPolicy] = {
    "install_or_update_dependency": OperationPolicy(
        subsystem=OSSubsystem.SOFTWARE_DEPENDENCIES,
        risk="high",
        effects=(
            "Changes installed software by installing or updating the named dependency.",
            "May affect applications that depend on the installed runtime or package.",
        ),
        risks=(
            "The installer and privilege requirements vary by package and installation scope.",
            "A version change can affect other applications; OSGuard will not perform it.",
        ),
    ),
}

PROHIBITED_OPERATIONS: dict[str, str] = {
    "delete_files": "arbitrary_file_deletion_prohibited",
    "modify_registry": "registry_modification_prohibited",
    "modify_security_settings": "security_configuration_change_prohibited",
    "install_driver": "driver_installation_prohibited",
    "change_service": "service_modification_prohibited",
    "restart_service": "service_modification_prohibited",
    "run_command": "command_execution_prohibited",
    "execute_command": "command_execution_prohibited",
    "run_powershell": "command_execution_prohibited",
    "modify_permissions": "permission_change_prohibited",
}

_REMEDIATION_TERMS = (
    "fix", "resolve", "repair", "remedy", "recommend", "what should i do",
    "how can i", "how do i", "solution", "corrective action",
)
_NO_CHANGE_TERMS = ("only explain", "just explain", "do not change", "don't change", "no changes")


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _contains(needle: str, haystack: str) -> bool:
    return bool(needle.strip()) and _normalize(needle) in _normalize(haystack)


def _content_action_id(action: ProposedCorrectiveAction) -> str:
    payload = action.model_dump(mode="json")
    payload.pop("action_id", None)
    payload.pop("risk", None)
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return "act-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def evidence_catalog(state: OSGuardState) -> dict[str, str]:
    """Expose only state evidence whose provenance can be independently checked."""
    catalog = {"user_request_redacted": redact_sensitive_text(state.get("user_request", ""))}
    for item in state.get("retrieved_evidence", []):
        if isinstance(item, RetrievedEvidence) and item.source_id:
            catalog[item.source_id] = item.passage
    for item in state.get("tool_results", []):
        if isinstance(item, ToolExecutionResult) and item.status == "success" and item.evidence_id:
            catalog[item.evidence_id] = item.summary + "\n" + str(item.data)
    return catalog


def _compatibility_match(
    action: ProposedCorrectiveAction, state: OSGuardState
) -> CompatibilityFinding | None:
    if action.operation != "install_or_update_dependency":
        return None
    component = str(action.parameters.get("component", "")).strip()
    version = str(action.parameters.get("required_version", "")).strip()
    if set(action.parameters) != {"component", "required_version"} or not component or not version:
        return None
    for finding in state.get("compatibility_findings", []):
        if (
            finding.result == "incompatible"
            and _normalize(finding.component) == _normalize(component)
            and finding.required_version == version
            and finding.installed_version
        ):
            return finding
    return None


def _intent_check(
    action: ProposedCorrectiveAction,
    state: OSGuardState,
    finding: CompatibilityFinding | None,
) -> VerificationCheck:
    classification = state.get("classification")
    request = redact_sensitive_text(state.get("user_request", ""))
    if classification and classification.intent == RequestIntent.VERIFY_COMMAND:
        return VerificationCheck(
            result="fail",
            rationale="A command-safety request cannot be converted into an approved corrective action.",
            reason_codes=["command_review_is_not_action_authorization"],
        )
    if any(term in _normalize(request) for term in _NO_CHANGE_TERMS):
        return VerificationCheck(
            result="fail",
            rationale="The user explicitly limited the request to explanation or asked for no changes.",
            reason_codes=["action_contradicts_user_scope"],
        )
    if not finding:
        return VerificationCheck(
            result="fail",
            rationale="This operation is not tied to a grounded incompatible dependency finding.",
            reason_codes=["action_not_derived_from_supported_finding"],
        )
    quote = action.intent_evidence_quote or ""
    if not _contains(quote, request):
        return VerificationCheck(
            result="unknown",
            rationale="No exact user-request excerpt establishes that a corrective recommendation was requested.",
            reason_codes=["intent_evidence_missing"],
            missing_information=["Confirm that you want a corrective recommendation for this dependency."],
        )
    if not any(term in _normalize(quote) for term in _REMEDIATION_TERMS):
        return VerificationCheck(
            result="unknown",
            rationale="The request excerpt does not clearly ask for a fix or recommendation.",
            reason_codes=["intent_unclear"],
            missing_information=["Clarify whether you want a corrective recommendation or only an explanation."],
        )
    if action.target_subsystem != OSSubsystem.SOFTWARE_DEPENDENCIES:
        return VerificationCheck(
            result="fail",
            rationale="The action target does not match the dependency finding.",
            reason_codes=["target_subsystem_mismatch"],
        )
    if not _contains(finding.component, action.description) or not _contains(
        finding.required_version or "", action.description
    ):
        return VerificationCheck(
            result="fail",
            rationale="The recommendation description does not identify the grounded dependency and required version.",
            reason_codes=["action_target_or_version_mismatch"],
        )
    expected_purpose = f"Address the reported {finding.component} compatibility mismatch."
    if _normalize(action.intended_purpose) != _normalize(expected_purpose):
        return VerificationCheck(
            result="fail",
            rationale="The action purpose is not the deterministic purpose supported by the compatibility finding.",
            reason_codes=["action_purpose_not_grounded"],
        )
    return VerificationCheck(
        result="pass",
        rationale="The exact request excerpt asks for a fix, and the action addresses its incompatible dependency finding.",
        evidence_ids=["user_request_redacted"],
    )


def _environment_check(
    action: ProposedCorrectiveAction,
    state: OSGuardState,
    finding: CompatibilityFinding | None,
    catalog: dict[str, str],
) -> VerificationCheck:
    if not finding:
        return VerificationCheck(
            result="unknown",
            rationale="No matching compatibility finding establishes the target requirements.",
            reason_codes=["compatibility_prerequisite_missing"],
            missing_information=["A verified dependency requirement and installed version."],
        )
    environment = state.get("available_environment", SystemEnvironment())
    missing: list[str] = []
    if not action.required_environment_conditions:
        missing.append("The recommendation's required environment conditions were not specified.")
    else:
        for condition in action.required_environment_conditions:
            if not any(_contains(condition, source) for source in catalog.values()):
                missing.append("A stated environment condition lacks an exact supporting source excerpt.")
                break
    if not environment.os_name:
        missing.append("The Windows version/build was not established.")
    elif finding.required_os:
        os_match = _os_requirement_matches(environment.os_name, finding.required_os)
        if os_match is False:
            return VerificationCheck(
                result="fail",
                rationale="The observed operating system conflicts with the documented requirement.",
                reason_codes=["os_requirement_mismatch"],
            )
        if os_match is None:
            missing.append("Whether the observed Windows version satisfies the documented OS requirement.")
    if finding.required_architecture:
        if not environment.architecture:
            missing.append("The system architecture was not established.")
        elif not _architecture_matches(environment.architecture, finding.required_architecture):
            return VerificationCheck(
                result="fail",
                rationale="The observed architecture conflicts with the documented requirement.",
                reason_codes=["architecture_requirement_mismatch"],
            )
    if action.requires_administrator == "unknown":
        missing.append("Whether the documented installation method requires administrator privileges.")
    else:
        privilege_terms = ("administrator", "elevation", "elevated", "admin rights")
        privilege_evidence = [
            quote
            for evidence_id, quote in action.evidence_quotes.items()
            if evidence_id in catalog
            and any(term in _normalize(quote) for term in privilege_terms)
            and _contains(quote, catalog[evidence_id])
        ]
        if action.requires_administrator == "no":
            privilege_supported = any(
                re.search(r"\b(?:not require|does not require|doesn't require|without (?:administrator|admin)|no (?:administrator|admin))\b", _normalize(quote))
                for quote in privilege_evidence
            )
        else:
            privilege_supported = any(
                re.search(r"\b(?:requires? (?:administrator|admin)|administrator privileges? required|elevation required)\b", _normalize(quote))
                for quote in privilege_evidence
            )
        if not privilege_supported:
            missing.append("A cited source confirming the administrator requirement for the installation method.")
    if missing:
        return VerificationCheck(
            result="unknown",
            rationale="The dependency action has unresolved environment or privilege prerequisites.",
            reason_codes=["environment_prerequisite_unknown"],
            missing_information=missing,
        )
    return VerificationCheck(
        result="pass",
        rationale="The observed OS and architecture match the documented dependency requirements, and privilege requirements are cited.",
        evidence_ids=list(action.evidence_ids),
    )


def _architecture_matches(installed: str, required: str) -> bool:
    aliases = {
        "amd64": "x64", "x86_64": "x64", "x64": "x64",
        "arm64": "arm64", "aarch64": "arm64", "x86": "x86", "i386": "x86",
    }
    return aliases.get(_normalize(installed), _normalize(installed)) == aliases.get(
        _normalize(required), _normalize(required)
    )


def _os_requirement_matches(installed: str, required: str) -> bool | None:
    installed_normalized = _normalize(installed)
    required_normalized = _normalize(required)
    if installed_normalized == required_normalized:
        return True
    installed_version = re.search(r"\bwindows\s+(\d{1,2})\b", installed_normalized)
    required_version = re.search(r"\bwindows\s+(\d{1,2})\b", required_normalized)
    if not installed_version or not required_version:
        return None
    if any(term in required_normalized for term in ("or later", "or newer", "and later", "+")):
        return int(installed_version.group(1)) >= int(required_version.group(1))
    return int(installed_version.group(1)) == int(required_version.group(1))


def _evidence_check(
    action: ProposedCorrectiveAction,
    state: OSGuardState,
    finding: CompatibilityFinding | None,
    catalog: dict[str, str],
) -> VerificationCheck:
    if action.action_id != _content_action_id(action):
        return VerificationCheck(
            result="fail",
            rationale="The action ID does not match the action contents.",
            reason_codes=["action_id_mismatch"],
        )
    if not action.evidence_ids:
        return VerificationCheck(
            result="unknown",
            rationale="The proposal has no supporting evidence references.",
            reason_codes=["supporting_evidence_missing"],
            missing_information=["Relevant user-reported or official documentation evidence."],
        )
    invalid = [evidence_id for evidence_id in action.evidence_ids if evidence_id not in catalog]
    if invalid:
        return VerificationCheck(
            result="fail",
            rationale="One or more cited evidence IDs do not exist in this workflow state.",
            reason_codes=["invalid_evidence_id"],
        )
    if set(action.evidence_quotes) != set(action.evidence_ids):
        return VerificationCheck(
            result="fail",
            rationale="Every cited evidence ID must have an exact supporting excerpt.",
            reason_codes=["evidence_quote_mapping_invalid"],
        )
    for evidence_id, quote in action.evidence_quotes.items():
        if not _contains(quote, catalog[evidence_id]):
            return VerificationCheck(
                result="fail",
                rationale="A cited excerpt is absent from its source passage or tool result.",
                reason_codes=["evidence_quote_not_in_source"],
            )
    if not finding:
        return VerificationCheck(
            result="fail",
            rationale="The recommendation is not derived from a grounded incompatible compatibility finding.",
            reason_codes=["action_not_derived_from_supported_finding"],
        )
    documented_ids = set(finding.documented_requirement_ids)
    user_ids = set(finding.evidence_ids) & {"user_request_redacted"}
    if not documented_ids:
        return VerificationCheck(
            result="unknown",
            rationale="No retrieved documentation establishes the dependency requirement.",
            reason_codes=["documented_requirement_missing"],
            missing_information=["An official passage stating the required dependency/version."],
        )
    if not documented_ids.intersection(action.evidence_ids):
        return VerificationCheck(
            result="fail",
            rationale="The proposal does not cite the documentation used to establish the incompatibility.",
            reason_codes=["requirement_source_not_cited"],
        )
    if finding.installed_version and not user_ids:
        return VerificationCheck(
            result="unknown",
            rationale="The installed version has no validated user-report source.",
            reason_codes=["installed_version_source_missing"],
            missing_information=["The installed dependency version and where it was observed."],
        )
    if finding.installed_version and user_ids and not user_ids.intersection(action.evidence_ids):
        return VerificationCheck(
            result="fail",
            rationale="The proposal omits the user-reported installed version evidence.",
            reason_codes=["installed_version_source_not_cited"],
        )
    if finding.installed_version:
        user_quote = action.evidence_quotes.get("user_request_redacted", "")
        if not _contains(finding.installed_version, user_quote) or not _contains(finding.component, user_quote):
            return VerificationCheck(
                result="fail",
                rationale="The user-request excerpt does not contain the cited installed component and version.",
                reason_codes=["installed_version_quote_mismatch"],
            )
    required = finding.required_version or ""
    expected_description = f"Install or update {finding.component} to meet the documented requirement {required}."
    expected_rationale = (
        f"The Compatibility Agent found the user-reported installed version "
        f"{finding.installed_version} incompatible with the documented requirement {required}."
    )
    if (
        _normalize(action.description) != _normalize(expected_description)
        or _normalize(action.rationale) != _normalize(expected_rationale)
    ):
        return VerificationCheck(
            result="fail",
            rationale="The action description or rationale contains claims outside the grounded compatibility finding.",
            reason_codes=["action_claim_not_grounded"],
        )
    if not any(
        evidence_id in documented_ids
        and _contains(required, quote)
        and _contains(finding.component, quote)
        for evidence_id, quote in action.evidence_quotes.items()
    ):
        return VerificationCheck(
            result="fail",
            rationale="The cited documentation does not support the required version used by this action.",
            reason_codes=["documented_requirement_does_not_support_action"],
        )
    return VerificationCheck(
        result="pass",
        rationale="Every excerpt exists in its cited source, including the user-reported version and documented requirement that ground this recommendation.",
        evidence_ids=list(action.evidence_ids),
    )


def _effect_check(action: ProposedCorrectiveAction) -> tuple[VerificationCheck, str]:
    operation = action.operation.casefold()
    if operation in PROHIBITED_OPERATIONS:
        code = PROHIBITED_OPERATIONS[operation]
        return (
            VerificationCheck(
                result="fail",
                rationale="Deterministic safety policy prohibits recommending this operation as an OSGuard corrective action.",
                reason_codes=[code],
            ),
            "high",
        )
    policy = KNOWN_RECOMMENDATION_OPERATIONS.get(operation)
    if policy is None:
        return (
            VerificationCheck(
                result="fail",
                rationale="The operation is not in the deterministic recommendation policy.",
                reason_codes=["unknown_operation"],
            ),
            "unknown",
        )
    if action.target_subsystem != policy.subsystem:
        return (
            VerificationCheck(
                result="fail",
                rationale="The operation's target subsystem conflicts with its deterministic policy.",
                reason_codes=["target_subsystem_mismatch"],
            ),
            policy.risk,
        )
    details_missing = []
    if not action.potential_effects:
        details_missing.append("Describe the expected state changes.")
    if not action.risks:
        details_missing.append("Describe the relevant risks.")
    if (
        set(action.potential_effects) != set(policy.effects)
        or set(action.risks) != set(policy.risks)
        or action.reversible is not False
    ):
        return (
            VerificationCheck(
                result="fail",
                rationale="The proposed effects, risks, or reversibility do not match the deterministic operation policy.",
                reason_codes=["effect_claim_not_grounded"],
            ),
            policy.risk,
        )
    if details_missing:
        return (
            VerificationCheck(
                result="unknown",
                rationale="The proposal did not state its effects and risks; the deterministic policy supplies a conservative risk level.",
                reason_codes=["effect_details_missing"],
                missing_information=details_missing,
            ),
            policy.risk,
        )
    return (
        VerificationCheck(
            result="pass",
            rationale="The known operation's effects and risks are bounded by deterministic policy; it remains recommendation-only and is not executable.",
            reason_codes=["recommendation_only_high_risk"] if policy.risk == "high" else [],
        ),
        policy.risk,
    )


def _merge_check(deterministic: VerificationCheck, llm: VerificationCheck | None) -> VerificationCheck:
    if deterministic.result == "fail":
        return deterministic
    if llm is None:
        return deterministic.model_copy(
            update={
                "result": "unknown",
                "reason_codes": list(dict.fromkeys(deterministic.reason_codes + ["llm_assessment_unavailable"])),
                "missing_information": list(dict.fromkeys(
                    deterministic.missing_information + ["A valid structured IEEE assessment."]
                )),
            }
        )
    if llm.result == "fail":
        return VerificationCheck(
            result="fail",
            rationale="The structured assessment raised a concern; the action is not supported.",
            reason_codes=list(dict.fromkeys(deterministic.reason_codes + llm.reason_codes + ["llm_concern"])),
            evidence_ids=deterministic.evidence_ids,
            missing_information=list(dict.fromkeys(deterministic.missing_information + llm.missing_information)),
        )
    if deterministic.result == "unknown" or llm.result == "unknown":
        return VerificationCheck(
            result="unknown",
            rationale=deterministic.rationale,
            reason_codes=list(dict.fromkeys(deterministic.reason_codes + llm.reason_codes)),
            evidence_ids=deterministic.evidence_ids,
            missing_information=list(dict.fromkeys(deterministic.missing_information + llm.missing_information)),
        )
    return deterministic


def verify_action(
    state: OSGuardState,
    action: ProposedCorrectiveAction,
    assessment: IEEEAssessment | None,
) -> IEEEVerificationResult:
    """Combine structured assessment with deterministic safety/provenance rules."""
    catalog = evidence_catalog(state)
    finding = _compatibility_match(action, state)
    checks = {
        "intent": _intent_check(action, state, finding),
        "environment": _environment_check(action, state, finding, catalog),
        "evidence": _evidence_check(action, state, finding, catalog),
    }
    effect, risk = _effect_check(action)
    checks["effect"] = effect

    if assessment is None:
        llm_checks: dict[str, VerificationCheck | None] = {name: None for name in checks}
    else:
        llm_checks = {
            "intent": assessment.intent,
            "environment": assessment.environment,
            "evidence": assessment.evidence,
            "effect": assessment.effect,
        }
        unknown_llm_ids = {
            evidence_id
            for check in llm_checks.values() if check is not None
            for evidence_id in check.evidence_ids if evidence_id not in catalog
        }
        if unknown_llm_ids:
            checks["evidence"] = VerificationCheck(
                result="fail",
                rationale="The structured assessment cited evidence IDs absent from the workflow state.",
                reason_codes=["invalid_llm_evidence_reference"],
            )

    final_checks = {
        name: _merge_check(check, llm_checks[name])
        for name, check in checks.items()
    }
    results = [check.result for check in final_checks.values()]
    overall = (
        "unsupported" if "fail" in results
        else "supported" if all(result == "pass" for result in results)
        else "uncertain"
    )
    reason_codes = list(dict.fromkeys(
        code for check in final_checks.values() for code in check.reason_codes
    ))
    evidence_ids = list(dict.fromkeys(
        evidence_id
        for check in final_checks.values()
        for evidence_id in check.evidence_ids
        if evidence_id in catalog
    ))
    missing_information = list(dict.fromkeys(
        item for check in final_checks.values() for item in check.missing_information
    ))
    explanation = (
        f"IEEE result is {overall}. This recommendation is not execution authorization."
        if risk == "high"
        else f"IEEE result is {overall}. No action was executed."
    )
    return IEEEVerificationResult(
        action_id=action.action_id,
        intent=final_checks["intent"],
        environment=final_checks["environment"],
        evidence=final_checks["evidence"],
        effect=final_checks["effect"],
        overall=overall,
        risk=risk,
        reason_codes=reason_codes,
        supporting_evidence_ids=evidence_ids,
        missing_information=missing_information,
        explanation=explanation,
    )


def deterministic_assessment() -> IEEEAssessment:
    """Explicit all-unknown baseline used only when model assessment is absent."""
    unknown = VerificationCheck(result="unknown", rationale="No structured assessment was produced.")
    return IEEEAssessment(intent=unknown, environment=unknown, evidence=unknown, effect=unknown)
