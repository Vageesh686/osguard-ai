"""EVIDENCE check: is the action backed by the user's logs and retrieved documentation?

Deterministic guards run first (links, citation validity, command name appears in docs);
an LLM entailment check then judges whether the cited passages really support the claim.
"""
from __future__ import annotations

from app import llm, promptlib
from app.schemas import Action, Chunk, Diagnosis, EvidenceCheck
from app.stages.verify.effect import TOKEN_RE, normalize_name

PASSAGE_CHARS = 1500


def _command_names(command: str) -> list[str]:
    toks = TOKEN_RE.findall(command.strip())
    return [normalize_name(toks[0])] if toks else []


def command_in_docs(command: str, chunks: list[Chunk]) -> bool:
    names = [n for n in _command_names(command) if len(n) > 2]
    if not names:
        return False
    blob = " ".join(c.text.lower() + " " + c.title.lower() for c in chunks)
    return any(n in blob for n in names)


def check_command_in_docs(command: str, chunks: list[Chunk]) -> EvidenceCheck:
    """Used when verifying a standalone command (no diagnosis to link to)."""
    if command_in_docs(command, chunks):
        return EvidenceCheck(verdict="weak",
                             reason="The command name appears in retrieved documentation, but no diagnosis is linked to it")
    return EvidenceCheck(verdict="unsupported",
                         reason="The command was not found in the retrieved documentation")


def check_evidence(action: Action, diagnosis: Diagnosis, chunks: list[Chunk]) -> EvidenceCheck:
    hyps = [c for c in diagnosis.claims if c.kind == "hypothesis"]
    linked = [hyps[i] for i in action.addresses if 0 <= i < len(hyps)]
    if not linked:
        return EvidenceCheck(verdict="unsupported",
                             reason="The action is not linked to any evidence-backed hypothesis")

    by_id = {c.id: c for c in chunks}
    cited_ids = list(dict.fromkeys(e for h in linked for e in h.evidence_ids if e in by_id))
    if not cited_ids:
        return EvidenceCheck(verdict="unsupported",
                             reason="The linked hypothesis cites no retrieved documentation")

    cited = [by_id[i] for i in cited_ids]
    system, user = promptlib.render(
        "evidence",
        claims="\n".join(f"- {h.text}" for h in linked),
        shell=action.shell,
        command=action.command,
        passages="\n\n".join(f"[{c.id}] {c.title}\n{c.text[:PASSAGE_CHARS]}" for c in cited),
    )
    result = llm.generate_structured(user, EvidenceCheck, system=system)

    # Deterministic downgrade: a "supported" verdict needs the command to appear in the docs we retrieved.
    if (result.verdict == "supported" and action.shell != "gui"
            and not command_in_docs(action.command, chunks)):
        result = EvidenceCheck(
            verdict="weak",
            reason=result.reason + " (Downgraded: command name not found in any retrieved passage.)",
        )
    return result
