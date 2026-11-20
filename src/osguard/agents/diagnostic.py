"""Diagnostic specialist placeholder for Phase 1."""

from __future__ import annotations

from typing import Any

from osguard.schemas import SpecialistName, SpecialistResult
from osguard.state import OSGuardState


def diagnostic_agent_node(_state: OSGuardState) -> dict[str, Any]:
    """Mark the diagnostic path as selected without fabricating observations."""
    return {
        "specialist_results": [
            SpecialistResult(
                specialist=SpecialistName.DIAGNOSTIC,
                status="not_implemented",
                message=(
                    "Diagnostic Agent is not implemented yet. No system checks were run "
                    "and no observations or hypotheses are available."
                ),
            )
        ],
        "completed_specialists": [SpecialistName.DIAGNOSTIC],
    }
