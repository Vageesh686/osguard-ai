"""Restricted executor: one registered Python handler after exact approval."""

from __future__ import annotations

from threading import Lock
from typing import Any

from osguard.repair.demo_cache import DemoCacheError, DemoCacheStore
from osguard.repair.eligibility import evaluate_eligibility
from osguard.repair.registry import CLEAR_OSGUARD_DEMO_CACHE, REPAIR_REGISTRY
from osguard.schemas import ExecutionValidationResult
from osguard.state import OSGuardState


class ExecutionLedger:
    """Process-local, once-per-plan claim; never grants reusable approval."""

    def __init__(self):
        self._lock = Lock()
        self._claimed: set[str] = set()
        self._results: dict[str, ExecutionValidationResult] = {}

    def claim(self, plan_id: str) -> bool:
        with self._lock:
            if plan_id in self._claimed:
                return False
            self._claimed.add(plan_id)
            return True

    def record(self, result: ExecutionValidationResult) -> None:
        if result.plan_id:
            with self._lock:
                self._results[result.plan_id] = result

    def result(self, plan_id: str) -> ExecutionValidationResult | None:
        with self._lock:
            return self._results.get(plan_id)

    def was_claimed(self, plan_id: str) -> bool:
        with self._lock:
            return plan_id in self._claimed


def execute_approved_repair(
    state: OSGuardState, store: DemoCacheStore, ledger: ExecutionLedger,
) -> ExecutionValidationResult:
    plan = state.get("repair_plan")
    approval = state.get("approval_state")
    if plan is None:
        return ExecutionValidationResult(status="blocked", details="No repair plan exists.", reason_codes=["plan_missing"])
    if plan.executable_action_id not in REPAIR_REGISTRY or plan.executable_action_id != CLEAR_OSGUARD_DEMO_CACHE:
        return ExecutionValidationResult(
            status="blocked", action_id=plan.action_id, plan_id=plan.plan_id,
            details="The executable action is not registered.", reason_codes=["unknown_action"],
        )
    if not (
        approval is not None and approval.status == "approved"
        and approval.action_id == plan.action_id
        and approval.plan_id == plan.plan_id
        and approval.fingerprint == plan.fingerprint
    ):
        return ExecutionValidationResult(
            status="blocked", action_id=plan.action_id, plan_id=plan.plan_id,
            details="Exact human approval is missing or stale.", reason_codes=["approval_missing_or_mismatched"],
        )
    if ledger.was_claimed(plan.plan_id):
        return ExecutionValidationResult(
            status="already_executed", action_id=plan.action_id, plan_id=plan.plan_id,
            details="This approved repair plan was already attempted; it will not run again.",
            reason_codes=["duplicate_plan_submission"],
            before_snapshot=plan.pre_state,
        )
    action = next((item for item in state.get("proposed_corrective_actions", []) if item.action_id == plan.action_id), None)
    verification = next((item for item in state.get("ieee_verification_results", []) if item.action_id == plan.action_id), None)
    if action is None:
        return ExecutionValidationResult(
            status="blocked", action_id=plan.action_id, plan_id=plan.plan_id,
            details="The proposed action is missing.", reason_codes=["action_missing"],
        )
    decision, snapshot = evaluate_eligibility(state, action, verification, store, plan)
    if decision.status != "eligible" or snapshot is None:
        return ExecutionValidationResult(
            status="blocked", action_id=plan.action_id, plan_id=plan.plan_id,
            details=decision.message, reason_codes=decision.reason_codes,
        )
    if not ledger.claim(plan.plan_id):
        return ExecutionValidationResult(
            status="already_executed", action_id=plan.action_id, plan_id=plan.plan_id,
            details="This approved repair plan was already attempted; it will not run again.",
            reason_codes=["duplicate_plan_submission"],
            before_snapshot=plan.pre_state,
        )
    try:
        handlers = {CLEAR_OSGUARD_DEMO_CACHE: store.clear}
        after = handlers[plan.executable_action_id](snapshot)
        result = ExecutionValidationResult(
            status="succeeded", action_id=plan.action_id, plan_id=plan.plan_id,
            details="The registered demo-cache handler completed; post-repair validation is required.",
            before_snapshot=snapshot, after_snapshot=after,
        )
    except (DemoCacheError, PermissionError, OSError) as exc:
        result = ExecutionValidationResult(
            status="failed", action_id=plan.action_id, plan_id=plan.plan_id,
            details="The restricted demo-cache handler failed; it was not retried.",
            reason_codes=[exc.code if isinstance(exc, DemoCacheError) else type(exc).__name__],
            before_snapshot=snapshot,
        )
    ledger.record(result)
    return result


def create_restricted_executor_node(store: DemoCacheStore, ledger: ExecutionLedger):
    def execute(state: OSGuardState) -> dict[str, Any]:
        result = execute_approved_repair(state, store, ledger)
        return {
            "execution_result": result,
            "workflow_status": "executed" if result.status == "succeeded" else "execution_failed",
        }
    return execute
