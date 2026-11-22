"""Immutable registry of the single executable OSGuard demo operation."""

from dataclasses import dataclass
from types import MappingProxyType


CLEAR_OSGUARD_DEMO_CACHE = "CLEAR_OSGUARD_DEMO_CACHE"
DEMO_VALIDATOR_ID = "demo_cache_empty_and_owned"


@dataclass(frozen=True)
class RepairRegistration:
    executable_action_id: str
    operation: str
    validator_id: str
    risk: str
    requires_administrator: bool
    risk_classification: str = "CONTROLLED_CHANGE"
    required_permissions: str = "standard_user"
    approval_required: bool = True


REPAIR_REGISTRY = MappingProxyType({
    CLEAR_OSGUARD_DEMO_CACHE: RepairRegistration(
        executable_action_id=CLEAR_OSGUARD_DEMO_CACHE,
        operation="clear_osguard_demo_cache",
        validator_id=DEMO_VALIDATOR_ID,
        risk="low",
        requires_administrator=False,
    ),
})
