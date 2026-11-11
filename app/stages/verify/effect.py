"""EFFECT check (deterministic): what will this command do, and how risky is it?

We never execute anything. The command line is split into segments (pipes, ;, &&),
each segment's command is normalised (aliases, .exe, paths) and looked up in
kb/risk_table.yaml. The highest tier across all segments wins.

Extension idea: for PowerShell, replace the regex tokenizer with the real parser
(System.Management.Automation.Language.Parser via `pwsh`) to get an exact AST.
"""
from __future__ import annotations

import re
from functools import lru_cache

import yaml

from app.config import RISK_TABLE
from app.schemas import EffectReport

TIER_ORDER = {"read_only": 0, "reversible": 1, "destructive": 2}
_TIERS = ["read_only", "reversible", "destructive"]

TOKEN_RE = re.compile(r'"[^"]*"|\'[^\']*\'|\S+')

ALIASES = {
    "rm": "remove-item", "del": "remove-item", "erase": "remove-item", "ri": "remove-item",
    "rd": "remove-item", "rmdir": "remove-item",
    "ls": "get-childitem", "gci": "get-childitem",
    "kill": "stop-process", "spps": "stop-process", "ps": "get-process", "gps": "get-process",
    "gsv": "get-service", "sasv": "start-service", "spsv": "stop-service",
    "iex": "invoke-expression", "iwr": "invoke-webrequest", "irm": "invoke-restmethod",
    "cat": "get-content", "gc": "get-content", "mv": "move-item", "move": "move-item",
    "mi": "move-item", "cp": "copy-item", "copy": "copy-item", "cpi": "copy-item",
    "ren": "rename-item", "rni": "rename-item", "sp": "set-itemproperty",
    "rp": "remove-itemproperty", "ni": "new-item", "md": "new-item", "mkdir": "new-item",
}

READ_VERBS = {"get", "test", "show", "measure", "find", "select", "out", "write", "compare",
              "resolve", "trace", "wait", "search", "read", "where", "sort", "group", "foreach",
              "format", "convertto", "convertfrom", "join", "split", "export"}
MUTATE_VERBS = {"set", "start", "stop", "restart", "enable", "disable", "add", "new", "install",
                "update", "repair", "register", "unregister", "resume", "suspend", "grant",
                "revoke", "mount", "dismount", "connect", "disconnect", "enter", "invoke",
                "import", "copy", "move", "rename", "push", "pop", "sync", "optimize", "expand",
                "restore", "save", "send", "use", "unblock", "block", "publish"}
DESTRUCT_VERBS = {"remove", "clear", "uninstall", "reset", "initialize", "erase", "delete",
                  "disconnect-all", "revoke-all"}

# Rules applied to the whole command line, independent of the command name.
GLOBAL_RULES = [
    (re.compile(r"\s-enc(odedcommand)?\b", re.I), "destructive",
     "Encoded/obfuscated PowerShell cannot be inspected before running"),
    (re.compile(r"\b(invoke-expression|iex)\b", re.I), "destructive",
     "Executes dynamically built code"),
    (re.compile(r"downloadstring|downloadfile", re.I), "destructive",
     "Downloads content from the network (possibly executing it)"),
]


@lru_cache(maxsize=1)
def load_table() -> dict:
    data = yaml.safe_load(RISK_TABLE.read_text(encoding="utf-8")) or {}
    return {k.lower(): v for k, v in (data.get("commands") or {}).items()}


def get_entry(name: str) -> dict | None:
    return load_table().get(name.lower())


def _max_tier(a: str, b: str) -> str:
    return a if TIER_ORDER[a] >= TIER_ORDER[b] else b


# ---------------------------------------------------------------- parsing helpers
def split_segments(cmd: str) -> list[str]:
    """Split on | ; && || & and newlines, ignoring separators inside quotes."""
    cmd = re.sub(r"\d?>&\d", " ", cmd)          # drop redirections like 2>&1
    segs, cur, quote = [], [], None
    for ch in cmd:
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch in "|;&\n":
            segs.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    segs.append("".join(cur))
    return [s.strip() for s in segs if s.strip()]


def normalize_name(token: str) -> str:
    t = token.strip("\"'").replace("/", "\\").split("\\")[-1].lower()
    if t.endswith(".exe"):
        t = t[:-4]
    return ALIASES.get(t, t)


def _verb_tier(name: str) -> tuple[str, str] | None:
    m = re.match(r"^([a-z]+)-[a-z0-9]", name)
    if not m:
        return None
    verb = m.group(1)
    if verb in READ_VERBS:
        return "read_only", ""
    if verb in DESTRUCT_VERBS:
        return "destructive", f"'{verb}' verbs remove or reset things"
    if verb in MUTATE_VERBS:
        return "reversible", f"'{verb}' verbs change system state"
    return "reversible", f"unrecognised verb '{verb}', assuming it changes state"


# ---------------------------------------------------------------- core
def _analyze_segment(seg: str, shell: str, state: dict) -> None:
    seg = seg.strip()
    if seg.startswith("&"):
        seg = seg[1:].strip()
    toks = TOKEN_RE.findall(seg)
    if not toks:
        return
    raw = toks[0].strip("\"'")
    args = " ".join(toks[1:])

    # PowerShell-specific alias clash: 'sc' is Set-Content, not sc.exe
    if shell == "powershell" and raw.lower() == "sc":
        name = "set-content"
        state["reasons"].append("In PowerShell 'sc' is Set-Content; use 'sc.exe' for the service controller")
    else:
        name = normalize_name(raw)

    # wrappers: powershell -Command "...", cmd /c "..."
    if name in ("powershell", "pwsh"):
        m = re.search(r"(?:^|\s)-c(?:ommand)?\s+(.*)$", args, re.I)
        if m:
            _collect(m.group(1).strip().strip("\"'"), "powershell", state)
            return
        if re.search(r"(?:^|\s)-f(?:ile)?\s", args, re.I):
            state["unknown"].append("script file")
            state["tier"] = _max_tier(state["tier"], "reversible")
            state["reasons"].append("Runs a script file whose contents are not visible")
            return
    if name == "cmd":
        m = re.search(r"(?:^|\s)/[ck]\s+(.*)$", args, re.I)
        if m:
            _collect(m.group(1).strip().strip("\"'"), "cmd", state)
            return

    state["commands"].append(name)
    whatif = bool(re.search(r"(?:^|\s)-whatif\b", args, re.I))
    if whatif:
        state["whatif"] = True

    entry = get_entry(name)
    tier, why = "reversible", ""
    if entry:
        tier = entry.get("base", "reversible")
        why = entry.get("base_why", "") if tier != "read_only" else ""
        for rule in entry.get("rules") or []:
            if re.search(rule["when"], args, re.I):
                if TIER_ORDER[rule["tier"]] > TIER_ORDER[tier]:
                    tier, why = rule["tier"], rule.get("why", "")
                elif rule.get("why") and rule["tier"] == tier and tier != "read_only" and not why:
                    why = rule["why"]
        if entry.get("requires_admin"):
            state["requires_admin"] = True
        if entry.get("note"):
            state["notes"].append(entry["note"])
    else:
        vt = _verb_tier(name)
        if vt:
            tier, why = vt
        else:
            tier = "reversible"
            why = f"'{name}' is not in the risk table; treated as state-changing until verified"
            state["unknown"].append(name)

    if whatif and tier != "read_only":
        tier, why = "read_only", "-WhatIf only simulates the change"

    if why:
        state["reasons"].append(f"{name}: {why}")
    state["tier"] = _max_tier(state["tier"], tier)


def _collect(command: str, shell: str, state: dict) -> None:
    for pat, tier, why in GLOBAL_RULES:
        if pat.search(" " + command):
            state["tier"] = _max_tier(state["tier"], tier)
            state["reasons"].append(why)
    for seg in split_segments(command):
        _analyze_segment(seg, shell, state)


def analyze_command(command: str, shell: str = "powershell") -> EffectReport:
    """Return the effect tier + reasons for a command line (never executes it)."""
    if shell == "gui":
        return EffectReport(
            tier="reversible",
            reasons=["Manual/GUI step: effect depends on the setting changed"],
        )
    state = {"tier": "read_only", "reasons": [], "commands": [], "unknown": [],
             "requires_admin": False, "whatif": False, "notes": []}
    _collect(command, shell, state)
    # de-duplicate, keep order
    uniq = lambda xs: list(dict.fromkeys(xs))
    return EffectReport(
        tier=state["tier"],
        reasons=uniq(state["reasons"] + state["notes"]),
        commands=uniq(state["commands"]),
        unknown_commands=uniq(state["unknown"]),
        requires_admin=state["requires_admin"],
        whatif=state["whatif"],
    )
