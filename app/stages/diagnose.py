"""Stage 3: evidence-grounded diagnosis. Separates observations from hypotheses and
removes any citation that does not point at a real retrieved passage."""
from app import llm, promptlib
from app.schemas import Chunk, Diagnosis, Extraction

MAX_CHARS = 1400


def format_passages(chunks: list[Chunk], max_chars: int = MAX_CHARS) -> str:
    if not chunks:
        return "(no passages retrieved)"
    return "\n\n".join(
        f"[{c.id}] {c.title}\n{c.text[:max_chars]}" for c in chunks
    )


def diagnose(user_text: str, extraction: Extraction, chunks: list[Chunk]) -> Diagnosis:
    system, user = promptlib.render(
        "diagnose",
        extraction=extraction.model_dump_json(indent=2),
        user_text=user_text.strip(),
        passages=format_passages(chunks),
    )
    diag = llm.generate_structured(user, Diagnosis, system=system)

    # --- deterministic guard: drop citations that do not exist ---
    valid = {c.id for c in chunks} | {"user_input"}
    for claim in diag.claims:
        claim.evidence_ids = [e for e in claim.evidence_ids if e in valid]
        if claim.kind == "observation" and not claim.evidence_ids:
            claim.evidence_ids = ["user_input"]
    return diag
