"""One-plan human approval through LangGraph interrupt and checkpoint resume."""

from typing import Any

from langgraph.types import interrupt
from pydantic import ValidationError

from osguard.repair.demo_cache import DemoCacheStore
from osguard.repair.eligibility import evaluate_eligibility
from osguard.repair.planning import fingerprint_for
from osguard.schemas import ApprovalDecision, ApprovalState
from osguard.state import OSGuardState


def create_approval_node(store: DemoCacheStore):
    def await_approval(state: OSGuardState) -> dict[str, Any]:
        plan = state.get("repair_plan")
        eligibility = state.get("repair_eligibility")
        if plan is None or eligibility is None or eligibility.status != "eligible":
            return {
                "approval_state": ApprovalState(status="expired", reason_codes=["eligible_plan_missing"]),
                "workflow_status": "approval_failed",
            }
        verification = next((item for item in state.get("ieee_verification_results", []) if item.action_id == plan.action_id), None)
        payload = {
            "question": "Approve this exact OSGuard demo-cache repair?",
            "plan": plan.model_dump(mode="json"),
            "ieee": verification.model_dump(mode="json") if verification else None,
            "eligibility": eligibility.model_dump(mode="json"),
        }
        response = interrupt(payload)
        try:
            decision = ApprovalDecision.model_validate(response)
        except (ValidationError, TypeError, ValueError):
            return {
                "approval_state": ApprovalState(
                    status="expired", action_id=plan.action_id, plan_id=plan.plan_id,
                    reason_codes=["invalid_approval_response"],
                ),
                "workflow_status": "approval_failed",
            }
        if decision.decision == "decline":
            return {
                "approval_state": ApprovalState(
                    status="declined", action_id=plan.action_id, plan_id=plan.plan_id,
                    fingerprint=plan.fingerprint,
                ),
                "workflow_status": "declined",
            }
        if (
            decision.plan_id != plan.plan_id
            or decision.fingerprint != plan.fingerprint
            or fingerprint_for(plan) != plan.fingerprint
        ):
            return {
                "approval_state": ApprovalState(
                    status="expired", action_id=plan.action_id, plan_id=plan.plan_id,
                    reason_codes=["approval_plan_mismatch"],
                ),
                "workflow_status": "approval_failed",
            }
        action = next((item for item in state.get("proposed_corrective_actions", []) if item.action_id == plan.action_id), None)
        if action is None:
            reason = "action_missing"
        else:
            rechecked, _ = evaluate_eligibility(state, action, verification, store, plan)
            reason = rechecked.reason_codes[0] if rechecked.status != "eligible" else ""
        if reason:
            return {
                "approval_state": ApprovalState(
                    status="expired", action_id=plan.action_id, plan_id=plan.plan_id,
                    reason_codes=[reason],
                ),
                "workflow_status": "approval_failed",
            }
        return {
            "approval_state": ApprovalState(
                status="approved", action_id=plan.action_id, plan_id=plan.plan_id,
                fingerprint=plan.fingerprint,
            ),
            "workflow_status": "approved",
        }
    return await_approval
