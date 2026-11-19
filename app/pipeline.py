"""OSGuard AI pipeline:  classify -> retrieve -> diagnose -> propose -> verify (IEEE) -> result."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.config import TOP_K
from app.schemas import (Action, EnvSnapshot, Extraction, PipelineResult,
                         RequirementResult, VerifiedAction, Chunk, Diagnosis)
from app.stages import classify, diagnose, propose, retrieve
from app.stages.verify import effect, environment, evidence, intent, verdict

log = logging.getLogger("osguard.pipeline")


def load_env_snapshot(path: str | Path) -> EnvSnapshot:
    """Load the JSON written by env_probe.ps1 (Windows PowerShell writes a UTF-8 BOM)."""
    return EnvSnapshot.model_validate_json(Path(path).read_text(encoding="utf-8-sig"))


def _verify(action: Action, goal: str, env: EnvSnapshot, evidence_check) -> VerifiedAction:
    """Run the four IEEE checks on one action. `evidence_check` is already computed."""
    eff = effect.analyze_command(action.command, action.shell)
    env_verdict, env_reason, req_results = environment.check_environment(action, env, eff)
    intent_check = intent.check_intent(goal, action)

    reasons = {
        "intent": intent_check.reason,
        "environment": env_reason,
        "evidence": evidence_check.reason,
        "effect": "; ".join(eff.reasons) or "Read-only: only inspects system state",
    }
    v = verdict.combine(intent_check.verdict, env_verdict, evidence_check.verdict, eff.tier, reasons)
    return VerifiedAction(action=action, verdict=v, effect=eff, requirement_results=req_results)


def verify_action(action: Action, extraction: Extraction, diagnosis: Diagnosis,
                  chunks: list[Chunk], env: EnvSnapshot) -> VerifiedAction:
    ev = evidence.check_evidence(action, diagnosis, chunks)
    return _verify(action, extraction.user_goal, env, ev)


def run(user_text: str, env: Optional[EnvSnapshot] = None, top_k: int = TOP_K) -> PipelineResult:
    env = env or EnvSnapshot()
    notes: list[str] = []

    extraction = classify.classify(user_text, env)
    chunks = retrieve.retrieve(user_text, extraction, k=top_k)
    diagnosis = diagnose.diagnose(user_text, extraction, chunks)
    actions = propose.propose(user_text, extraction, diagnosis, chunks, env)

    verified = []
    for a in actions:
        try:
            verified.append(verify_action(a, extraction, diagnosis, chunks, env))
        except Exception as e:                                            # noqa: BLE001
            log.exception("verification failed for %r", a.command)
            notes.append(f"Could not verify '{a.command}': {e}")

    if extraction.missing_info:
        notes.append("Missing information: " + "; ".join(extraction.missing_info))
    if diagnosis.needs_more_info:
        notes.append("More diagnostic evidence needed: " + "; ".join(diagnosis.needs_more_info))
    if env.os_build == "unknown":
        notes.append("No environment snapshot supplied (run env_probe.ps1); environment checks are limited.")

    return PipelineResult(user_text=user_text, extraction=extraction, chunks=chunks,
                          diagnosis=diagnosis, verified=verified, notes=notes)


def verify_command(command: str, goal: str, env: Optional[EnvSnapshot] = None,
                   shell: str = "powershell") -> VerifiedAction:
    """Function 2 on its own: verify a command the user (or another AI) already has.
    Evidence = does retrieved documentation mention this command at all."""
    env = env or EnvSnapshot()
    action = Action(command=command, shell=shell, rationale="User-supplied command")
    chunks = retrieve.retrieve_ranked(command + " " + goal, None, k=TOP_K)
    ev = evidence.check_command_in_docs(command, chunks)
    return _verify(action, goal or "Run this command", env, ev)

