"""Command-verification specialist placeholder for Phase 1."""

from __future__ import annotations

from typing import Any

from osguard.schemas import SpecialistName, SpecialistResult
from osguard.state import OSGuardState


def command_verification_agent_node(_state: OSGuardState) -> dict[str, Any]:
    """Mark the command-review path without parsing or executing commands."""
    return {
        "specialist_results": [
            SpecialistResult(
                specialist=SpecialistName.COMMAND_VERIFICATION,
                status="not_implemented",
                message=(
                    "Command Verification Agent is not implemented yet. No command "
                    "was parsed, verified, or executed."
                ),
            )
        ],
        "completed_specialists": [SpecialistName.COMMAND_VERIFICATION],
    }
