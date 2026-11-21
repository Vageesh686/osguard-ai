"""Exact repair-plan construction and content fingerprinting."""

import hashlib
import json
import uuid

from osguard.repair.demo_cache import DEMO_CACHE_ID, DemoCacheStore
from osguard.repair.registry import CLEAR_OSGUARD_DEMO_CACHE, DEMO_VALIDATOR_ID
from osguard.schemas import DemoCacheSnapshot, ProposedCorrectiveAction, RepairPlan
from osguard.verification.rules import KNOWN_RECOMMENDATION_OPERATIONS


_OUTCOME = "The OSGuard demo cache payload is empty and its ownership marker remains valid."
_PRECONDITIONS = [
    "The fixed OSGuard demo cache contains only its owner marker and known disposable payload.",
    "The current payload exactly matches the approved pre-repair snapshot.",
    "No symbolic link, junction, or other reparse point occurs in the target path.",
]


def _plan_fields(
    action: ProposedCorrectiveAction, snapshot: DemoCacheSnapshot,
    store: DemoCacheStore, plan_id: str,
) -> dict:
    policy = KNOWN_RECOMMENDATION_OPERATIONS["clear_osguard_demo_cache"]
    return {
        "plan_id": plan_id,
        "action_id": action.action_id,
        "executable_action_id": CLEAR_OSGUARD_DEMO_CACHE,
        "target": str(store.cache_dir),
        "parameters": {"cache_id": DEMO_CACHE_ID},
        "intended_outcome": _OUTCOME,
        "expected_effects": list(policy.effects),
        "potential_risks": list(policy.risks),
        "preconditions": list(_PRECONDITIONS),
        "requires_user_approval": True,
        "validator_id": DEMO_VALIDATOR_ID,
        "pre_state": snapshot.model_dump(mode="json"),
    }


def _fingerprint(fields: dict) -> str:
    canonical = json.dumps(fields, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprint_for(plan: RepairPlan) -> str:
    return _fingerprint(plan.model_dump(mode="json", exclude={"fingerprint"}))


def build_repair_plan(
    action: ProposedCorrectiveAction, snapshot: DemoCacheSnapshot, store: DemoCacheStore,
) -> RepairPlan:
    if action.operation != "clear_osguard_demo_cache":
        raise ValueError("Only the registered demo-cache operation has a repair plan.")
    if snapshot.target != str(store.cache_dir) or snapshot.payload_size <= 0:
        raise ValueError("The demo cache is not a nonempty approved target.")
    fields = _plan_fields(action, snapshot, store, "plan-" + uuid.uuid4().hex)
    return RepairPlan(**fields, fingerprint=_fingerprint(fields))


def plan_is_exact(plan: RepairPlan, action: ProposedCorrectiveAction, store: DemoCacheStore) -> bool:
    if plan.executable_action_id != CLEAR_OSGUARD_DEMO_CACHE:
        return False
    if plan.fingerprint != fingerprint_for(plan):
        return False
    return plan.model_dump(mode="json", exclude={"fingerprint"}) == _plan_fields(
        action, plan.pre_state, store, plan.plan_id
    )
