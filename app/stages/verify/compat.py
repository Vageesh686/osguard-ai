"""Software / configuration compatibility checking (deterministic).

Requirements look like  Requirement(name="powershell", spec=">=5.1")  or
Requirement(name="windows", spec=">=22000")  (a bare build number compares the build only).
They come from the `propose` stage (LLM) or from user input in the UI, and are checked
against the EnvSnapshot with real version arithmetic - no LLM involved.
"""
from __future__ import annotations

import re
from typing import Optional

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from app.schemas import EnvSnapshot, Requirement, RequirementResult

OS_NAMES = {"windows", "windows_build", "os", "win", "windows 11", "windows11"}
PS_NAMES = {"powershell", "pwsh", "windows powershell"}


def parse_version(text: str | None) -> Optional[Version]:
    if not text:
        return None
    m = re.search(r"\d+(?:\.\d+)*", text)
    if not m:
        return None
    try:
        return Version(m.group())
    except InvalidVersion:
        return None


def os_build_number(os_build: str) -> Optional[int]:
    """'10.0.22631.4037' -> 22631 ; '22631' -> 22631 ; 'Windows 11 23H2 (22631)' -> 22631."""
    m = re.search(r"10\.0\.(\d+)", os_build) or re.search(r"\b(\d{5})\b", os_build)
    return int(m.group(1)) if m else None


def parse_requirement_line(line: str) -> Requirement:
    """'powershell>=5.1' / 'Python 3.12' -> Requirement."""
    line = line.strip()
    m = re.match(r"^(.*?)\s*((?:[<>=!~]=?|==)\s*[\w.\-*]+(?:\s*,\s*[<>=!~]=?\s*[\w.\-*]+)*)\s*$", line)
    if m and m.group(1):
        return Requirement(name=m.group(1).strip(), spec=m.group(2).replace(" ", ""))
    m = re.match(r"^(.*?)\s+v?(\d+(?:\.\d+)*)\s*$", line)
    if m and m.group(1):
        return Requirement(name=m.group(1).strip(), spec=">=" + m.group(2))
    return Requirement(name=line, spec="")


def _installed_version(name: str, env: EnvSnapshot) -> tuple[Optional[str], str]:
    n = name.strip().lower()
    if n in PS_NAMES:
        return env.powershell_version, "PowerShell"
    if n in OS_NAMES:
        return env.os_build, "Windows"
    for k, v in env.installed.items():           # exact (case-insensitive)
        if k.lower() == n:
            return v, k
    for k, v in env.installed.items():           # substring fallback
        if n in k.lower():
            return v, k
    return None, name


def _normalise_spec(spec: str) -> str:
    spec = spec.strip()
    if not spec:
        return ""
    if re.match(r"^\d", spec):                   # bare version -> minimum version
        spec = ">=" + spec
    return spec


def check_requirement(req: Requirement, env: EnvSnapshot) -> RequirementResult:
    spec_text = _normalise_spec(req.spec)
    if not spec_text:
        return RequirementResult(requirement=req, status="unknown", detail="No version constraint given")

    have_text, label = _installed_version(req.name, env)
    if have_text is None or have_text == "unknown":
        return RequirementResult(requirement=req, status="unknown",
                                 detail=f"{label} not found in the environment snapshot")

    # OS requirement given as a bare build number (>=22000) -> compare build only
    is_os = req.name.strip().lower() in OS_NAMES
    spec_ver = parse_version(spec_text)
    if is_os and spec_ver is not None and len(spec_ver.release) < 3:
        build = os_build_number(have_text)
        if build is None:
            return RequirementResult(requirement=req, status="unknown", detail="Could not read OS build number")
        have = Version(str(build))
        shown = str(build)
    else:
        have = parse_version(have_text)
        shown = have_text
        if have is None:
            return RequirementResult(requirement=req, status="unknown",
                                     detail=f"Cannot parse installed version '{have_text}'")
    try:
        ok = SpecifierSet(spec_text).contains(have, prereleases=True)
    except InvalidSpecifier:
        return RequirementResult(requirement=req, status="unknown", detail=f"Unparseable constraint '{req.spec}'")

    return RequirementResult(
        requirement=req,
        status="pass" if ok else "fail",
        detail=f"{label} {shown} {'satisfies' if ok else 'does NOT satisfy'} {spec_text}",
    )


def check_requirements(reqs: list[Requirement], env: EnvSnapshot) -> list[RequirementResult]:
    return [check_requirement(r, env) for r in reqs]


def overall_status(results: list[RequirementResult]) -> str:
    if any(r.status == "fail" for r in results):
        return "fail"
    if results and all(r.status == "pass" for r in results):
        return "pass"
    return "unknown" if results else "pass"
