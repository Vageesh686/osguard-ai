"""Stage 4: propose candidate actions (safest first). These are only CANDIDATES;
nothing here is shown to the user until the IEEE verification stage has judged it."""
from app import llm, promptlib
from app.schemas import Action, ActionList, Chunk, Diagnosis, EnvSnapshot, Extraction
from app.stages.diagnose import format_passages

MAX_ACTIONS = 4


def propose(user_text: str, extraction: Extraction, diagnosis: Diagnosis,
            chunks: list[Chunk], env: EnvSnapshot) -> list[Action]:
    obs = [c for c in diagnosis.claims if c.kind == "observation"]
    hyps = [c for c in diagnosis.claims if c.kind == "hypothesis"]

    system, user = promptlib.render(
        "propose",
        goal=extraction.user_goal,
        env=env.model_dump_json(indent=2),
        observations="\n".join(f"- {c.text}" for c in obs) or "(none)",
        hypotheses="\n".join(f"{i}: {c.text}" for i, c in enumerate(hyps)) or "(none)",
        needs_more_info="; ".join(diagnosis.needs_more_info) or "(nothing noted)",
        passages=format_passages(chunks, max_chars=900),
    )
    result = llm.generate_structured(user, ActionList, system=system)

    actions = []
    for a in result.actions[:MAX_ACTIONS]:
        a.addresses = [i for i in a.addresses if 0 <= i < len(hyps)]   # drop bad indices
        actions.append(a)
    return actions
