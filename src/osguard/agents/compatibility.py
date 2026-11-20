"""Compatibility specialist placeholder for Phase 1."""

from __future__ import annotations

from typing import Any

from osguard.schemas import SpecialistName, SpecialistResult
from osguard.state import OSGuardState


def compatibility_agent_node(_state: OSGuardState) -> dict[str, Any]:
    """Mark the compatibility path without asserting package requirements."""
    return {
        "specialist_results": [
            SpecialistResult(
                specialist=SpecialistName.COMPATIBILITY,
                status="not_implemented",
                message=(
                    "Compatibility Agent is not implemented yet. No dependency "
                    "requirements or environment versions were checked."
                ),
            )
        ],
        "completed_specialists": [SpecialistName.COMPATIBILITY],
    }
