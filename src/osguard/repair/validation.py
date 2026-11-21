"""Post-repair measurement of the owned cache, independent of handler return."""

from typing import Any

from osguard.repair.demo_cache import DemoCacheStore
from osguard.schemas import PostRepairValidationResult
from osguard.state import OSGuardState


def validate_demo_repair(state: OSGuardState, store: DemoCacheStore) -> PostRepairValidationResult:
    plan = state.get("repair_plan")
    execution = state.get("execution_result")
    if plan is None or execution is None or execution.status in {"not_started", "blocked", "already_executed"}:
        return PostRepairValidationResult(
            status="unverifiable", details="No new completed repair execution can be validated.",
            reason_codes=["execution_evidence_missing"],
        )
    if execution.status == "failed":
        return PostRepairValidationResult(
            status="failed", action_id=plan.action_id, plan_id=plan.plan_id,
            details="The repair handler failed; the original demo problem is not marked resolved.",
            reason_codes=execution.reason_codes, before_snapshot=execution.before_snapshot,
        )
    if execution.status != "succeeded" or execution.before_snapshot is None or execution.after_snapshot is None:
        return PostRepairValidationResult(
            status="unverifiable", action_id=plan.action_id, plan_id=plan.plan_id,
            details="Execution or before/after measurements are incomplete.",
            reason_codes=["validation_evidence_missing"],
        )
    observed = store.inspect()
    if observed.snapshot is None or observed.status not in {"empty", "ready"}:
        return PostRepairValidationResult(
            status="unverifiable", action_id=plan.action_id, plan_id=plan.plan_id,
            details="The approved cache could not be safely inspected after execution.",
            reason_codes=["post_inspection_unavailable"],
            before_snapshot=execution.before_snapshot, after_snapshot=execution.after_snapshot,
        )
    before = execution.before_snapshot
    after = observed.snapshot
    if (
        before != plan.pre_state
        or after.target != plan.target
        or after.owner_marker_sha256 != before.owner_marker_sha256
        or execution.after_snapshot != after
    ):
        return PostRepairValidationResult(
            status="unverifiable", action_id=plan.action_id, plan_id=plan.plan_id,
            details="The after-state or ownership evidence does not match the approved cache.",
            reason_codes=["post_state_mismatch"], before_snapshot=before, after_snapshot=after,
        )
    if before.payload_size <= 0:
        status = "unverifiable"
        reason = "no_original_problem"
    elif after.payload_size == 0 and observed.status == "empty":
        status = "resolved"
        reason = "demo_cache_cleared"
    elif 0 < after.payload_size < before.payload_size:
        status = "partially_resolved"
        reason = "demo_cache_partially_cleared"
    else:
        status = "unresolved"
        reason = "demo_cache_still_nonempty"
    return PostRepairValidationResult(
        status=status, action_id=plan.action_id, plan_id=plan.plan_id,
        details=(
            f"Fresh inspection measured {before.payload_size} disposable bytes before and "
            f"{after.payload_size} bytes after; ownership marker remained valid."
        ),
        evidence=["approved_pre_state", "executor_after_state", "fresh_demo_cache_inspection"],
        reason_codes=[reason], before_snapshot=before, after_snapshot=after,
    )


def create_post_repair_validation_node(store: DemoCacheStore):
    def validate(state: OSGuardState) -> dict[str, Any]:
        result = validate_demo_repair(state, store)
        return {"validation_result": result, "workflow_status": result.status}
    return validate
