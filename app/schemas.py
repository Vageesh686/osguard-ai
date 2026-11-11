"""All data contracts for OSGuard AI. Every pipeline stage consumes/produces these."""
from typing import Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["process", "memory", "filesystem", "storage",
                   "device", "service", "permission", "software"]
Tier = Literal["read_only", "reversible", "destructive"]


# ---------- input side ----------
class EnvSnapshot(BaseModel):
    os_build: str = "unknown"                 # e.g. "10.0.22631.4037"
    edition: Optional[str] = None             # e.g. "Windows 11 Pro"
    is_admin: Optional[bool] = None
    powershell_version: Optional[str] = None
    installed: dict[str, str] = Field(default_factory=dict)   # name -> version


class Extraction(BaseModel):
    category: Category
    error_codes: list[str] = Field(default_factory=list)
    component: Optional[str] = None
    user_goal: str
    missing_info: list[str] = Field(default_factory=list)


# ---------- retrieval ----------
class Chunk(BaseModel):
    id: str
    text: str
    url: str
    title: str
    category: str = "general"
    os_scope: str = "windows-11"


# ---------- diagnosis ----------
class Claim(BaseModel):
    text: str
    kind: Literal["observation", "hypothesis"]
    evidence_ids: list[str] = Field(default_factory=list)   # chunk ids or "user_input"


class Diagnosis(BaseModel):
    claims: list[Claim] = Field(default_factory=list)
    needs_more_info: list[str] = Field(default_factory=list)


# ---------- proposed actions ----------
class Requirement(BaseModel):
    name: str            # "windows", "powershell", or an installed software name
    spec: str            # e.g. ">=5.1", ">=22000", "5.1"


class Action(BaseModel):
    command: str
    shell: Literal["powershell", "cmd", "gui"] = "powershell"
    addresses: list[int] = Field(default_factory=list)   # indices into the hypothesis list
    rationale: str = ""
    requires: list[Requirement] = Field(default_factory=list)


class ActionList(BaseModel):
    actions: list[Action] = Field(default_factory=list)


# ---------- verification ----------
class EffectReport(BaseModel):
    tier: Tier
    reasons: list[str] = Field(default_factory=list)
    commands: list[str] = Field(default_factory=list)          # normalised command names
    unknown_commands: list[str] = Field(default_factory=list)  # not in risk table / not cmdlet-shaped
    requires_admin: bool = False
    whatif: bool = False


class RequirementResult(BaseModel):
    requirement: Requirement
    status: Literal["pass", "fail", "unknown"]
    detail: str = ""


class IntentCheck(BaseModel):
    verdict: Literal["pass", "partial", "fail"]
    reason: str


class EvidenceCheck(BaseModel):
    verdict: Literal["supported", "weak", "unsupported"]
    reason: str


class IEEEVerdict(BaseModel):
    intent: Literal["pass", "partial", "fail"]
    environment: Literal["pass", "fail", "unknown"]
    evidence: Literal["supported", "weak", "unsupported"]
    effect_tier: Tier
    reasons: dict[str, str] = Field(default_factory=dict)
    final: Literal["recommend", "recommend_with_warning", "withhold", "need_more_info"]


class VerifiedAction(BaseModel):
    action: Action
    verdict: IEEEVerdict
    effect: EffectReport
    requirement_results: list[RequirementResult] = Field(default_factory=list)


class PipelineResult(BaseModel):
    user_text: str
    extraction: Extraction
    chunks: list[Chunk] = Field(default_factory=list)
    diagnosis: Diagnosis
    verified: list[VerifiedAction] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
