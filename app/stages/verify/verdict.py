"""Combine the four IEEE checks into one final decision. Strictness scales with risk."""
from __future__ import annotations

from app.schemas import IEEEVerdict


def combine(intent: str, environment: str, evidence: str, tier: str,
            reasons: dict[str, str]) -> IEEEVerdict:
    # Hard stops: wrong goal, or can't run here (includes hallucinated commands)
    if intent == "fail" or environment == "fail":
        final = "withhold"
    elif tier == "destructive":
        # Needs everything to line up, and is NEVER a plain "recommend"
        if evidence == "supported" and intent == "pass" and environment == "pass":
            final = "recommend_with_warning"
        elif evidence == "unsupported":
            final = "withhold"
        else:
            final = "need_more_info"
    elif tier == "reversible":
        if evidence == "unsupported":
            final = "need_more_info"
        elif evidence == "supported" and intent == "pass" and environment == "pass":
            final = "recommend"
        else:
            final = "recommend_with_warning"
    else:  # read_only: safe to run, and often the best way to gather missing evidence
        if evidence == "supported" and intent == "pass" and environment == "pass":
            final = "recommend"
        else:
            final = "recommend_with_warning"

    return IEEEVerdict(intent=intent, environment=environment, evidence=evidence,
                       effect_tier=tier, reasons=reasons, final=final)
