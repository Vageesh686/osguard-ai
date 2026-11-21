"""Deterministic execution eligibility; recommendations never authorize repair."""

from __future__ import annotations

from typing import Any

from osguard.repair.demo_cache import DEMO_CACHE_ID, DEMO_EVIDENCE_ID, DEMO_TOOL_NAME, DemoCacheStore
from osguard.repair.planning import build_repair_plan, plan_is_exact
from osguard.repair.registry import CLEAR_OSGUARD_DEMO_CACHE, REPAIR_REGISTRY
from osguard.schemas import (
    ApprovalState, DemoCacheSnapshot, IEEEAssessment, IEEEVerificationResult,
    RepairEligibility, RepairPlan, VerificationCheck,
)
from osguard.state import OSGuardState
from osguard.verification.proposals import action_id_for
from osguard.verification.rules import verify_action


def _deny(action_id: str, code: str, message: str) -> RepairEligibility:
    return RepairEligibility(
        status="ineligible", action_id=action_id, reason_codes=[code], message=message,
    )


def _all_pass_assessment() -> IEEEAssessment:
    check = VerificationCheck(result="pass", rationale="Recomputed by trusted eligibility policy.")
    return IEEEAssessment(intent=check, environment=check, evidence=check, effect=check, risk="low")


def evaluate_eligibility(
    state: OSGuardState, action, verification: IEEEVerificationResult | None,
    store: DemoCacheStore, plan: RepairPlan | None = None,
) -> tuple[RepairEligibility, DemoCacheSnapshot | None]:
    """Fail closed against forged IEEE records, changed files, or altered plans."""
    if action.operation != "clear_osguard_demo_cache":
        return _deny(action.action_id, "recommendation_only", "This action has no registered executor."), None
    registration = REPAIR_REGISTRY.get(CLEAR_OSGUARD_DEMO_CACHE)
    if registration is None or registration.operation != action.operation or registration.risk != "low":
        return _deny(action.action_id, "unknown_action", "The action is absent from the trusted registry."), None
    if action.action_id != action_id_for(action):
        return _deny(action.action_id, "action_id_mismatch", "The action content changed."), None
    if action.parameters != {"cache_id": DEMO_CACHE_ID}:
        return _deny(action.action_id, "invalid_parameters", "The repair parameters are not the fixed demo parameters."), None
    if action.risk != "low" or action.requires_administrator != "no" or registration.requires_administrator:
        return _deny(action.action_id, "risk_or_privilege", "The action is not confirmed low risk and non-admin."), None
    summary = state.get("ieee_verification_summary")
    if verification is None or summary is None or summary.status != "completed":
        return _deny(action.action_id, "ieee_missing", "A complete IEEE verification result is required."), None
    if verification.action_id != action.action_id or verification.risk != "low" or verification.overall != "supported":
        return _deny(action.action_id, "ieee_not_supported", "IEEE did not support this exact low-risk action."), None
    if any(getattr(verification, name).result != "pass" for name in ("intent", "environment", "evidence", "effect")):
        return _deny(action.action_id, "ieee_check_failed", "Every IEEE check must pass."), None
    recomputed = verify_action(state, action, _all_pass_assessment())
    if recomputed.overall != "supported" or recomputed.risk != "low":
        return _deny(action.action_id, "ieee_recheck_failed", "Trusted IEEE checks no longer support this action."), None
    inspection = store.inspect()
    if inspection.status != "ready" or inspection.snapshot is None:
        return _deny(action.action_id, "demo_precondition_failed", "The owned demo cache is not ready and nonempty."), None
    snapshot = inspection.snapshot
    tool = next((
        result for result in state.get("tool_results", [])
        if result.tool_name == DEMO_TOOL_NAME and result.evidence_id == DEMO_EVIDENCE_ID
        and result.status == "success"
    ), None)
    if tool is None or (
        tool.data.get("cache_id") != DEMO_CACHE_ID
        or tool.data.get("payload_bytes") != snapshot.payload_size
        or tool.data.get("payload_sha256") != snapshot.payload_sha256
        or tool.data.get("owner_marker_sha256") != snapshot.owner_marker_sha256
    ):
        return _deny(action.action_id, "evidence_changed", "The current cache differs from the cited inspection."), None
    if plan is not None:
        if not plan_is_exact(plan, action, store):
            return _deny(action.action_id, "plan_modified", "The plan no longer matches trusted parameters."), None
        if plan.pre_state != snapshot:
            return _deny(action.action_id, "precondition_changed", "The cache changed after plan creation."), None
    return RepairEligibility(
        status="eligible", action_id=action.action_id,
        plan_id=plan.plan_id if plan else None,
        message="The exact demo-cache action passed IEEE, registry, target, and precondition checks.",
    ), snapshot


def create_repair_planning_node(store: DemoCacheStore):
    def plan_repair(state: OSGuardState) -> dict[str, Any]:
        actions = state.get("proposed_corrective_actions", [])
        results = {item.action_id: item for item in state.get("ieee_verification_results", [])}
        decisions: list[RepairEligibility] = []
        selected_plan: RepairPlan | None = None
        for action in actions:
            decision, snapshot = evaluate_eligibility(state, action, results.get(action.action_id), store)
            if decision.status == "eligible" and snapshot is not None and selected_plan is None:
                selected_plan = build_repair_plan(action, snapshot, store)
                decision = decision.model_copy(update={"plan_id": selected_plan.plan_id})
            decisions.append(decision)
        if selected_plan is not None:
            return {
                "repair_eligibility_results": decisions,
                "repair_eligibility": next(item for item in decisions if item.status == "eligible"),
                "repair_plan": selected_plan,
                "approval_state": ApprovalState(
                    status="pending", action_id=selected_plan.action_id,
                    plan_id=selected_plan.plan_id, fingerprint=selected_plan.fingerprint,
                ),
                "workflow_status": "awaiting_approval",
            }
        return {
            "repair_eligibility_results": decisions,
            "repair_eligibility": decisions[0] if decisions else RepairEligibility(),
        }
    return plan_repair
