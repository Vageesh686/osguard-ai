"""ENVIRONMENT check (deterministic): can this action run on THIS machine?

Checks, in order:
  1. Does each command exist? (kb/known_commands.txt exported from a real Windows 11 box,
     falling back to the risk table when the file is absent)
  2. Is the command available on this Windows build? (risk_table `unavailable_from_build`)
  3. Do the action's declared requirements (versions of Windows, PowerShell, software) hold?
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from app.config import KNOWN_COMMANDS
from app.schemas import Action, EffectReport, EnvSnapshot, RequirementResult
from app.stages.verify import compat
from app.stages.verify.effect import get_entry


@lru_cache(maxsize=1)
def known_commands() -> Optional[frozenset[str]]:
    if not KNOWN_COMMANDS.exists():
        return None
    names = set()
    for line in KNOWN_COMMANDS.read_text(encoding="utf-8-sig").splitlines():
        n = line.strip().lower()
        if n.endswith(".exe"):
            n = n[:-4]
        if n:
            names.add(n)
    return frozenset(names)


def command_exists(name: str) -> Optional[bool]:
    """True / False, or None if we cannot tell (no known-commands list and not in risk table)."""
    if get_entry(name):
        return True
    known = known_commands()
    if known is None:
        return None
    return name.lower() in known


def check_environment(action: Action, env: EnvSnapshot,
                      effect: EffectReport) -> tuple[str, str, list[RequirementResult]]:
    """Return (verdict, reason, requirement_results). verdict in pass | fail | unknown."""
    if action.shell == "gui":
        return "pass", "Manual/GUI step; no command to validate", []

    fails: list[str] = []
    unknowns: list[str] = []
    build = compat.os_build_number(env.os_build)

    for name in effect.commands:
        exists = command_exists(name)
        if exists is False:
            fails.append(f"'{name}' was not found on the target system (possible hallucinated command)")
            continue
        if exists is None:
            unknowns.append(f"cannot confirm '{name}' exists (no known-commands list)")
        entry = get_entry(name) or {}
        gone = entry.get("unavailable_from_build")
        if gone and build is not None and build >= gone:
            fails.append(f"'{name}' is not available by default on Windows build {build} (removed from build {gone})")
        elif gone and build is None:
            unknowns.append(f"'{name}' availability depends on the Windows build, which is unknown")

    for name in effect.unknown_commands:
        if name != "script file":
            unknowns.append(f"'{name}' is not a recognised Windows command")

    if effect.requires_admin and env.is_admin is False:
        fails.append("needs an elevated (administrator) shell but the current shell is not elevated")

    req_results = compat.check_requirements(action.requires, env)
    for r in req_results:
        if r.status == "fail":
            fails.append(r.detail)
        elif r.status == "unknown":
            unknowns.append(r.detail)

    if fails:
        return "fail", "; ".join(fails), req_results
    if unknowns:
        return "unknown", "; ".join(unknowns), req_results
    return "pass", "Commands exist and requirements are satisfied", req_results
