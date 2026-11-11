"""Stage 1: classify the problem and extract structured facts (role prompt + few-shot)."""
from app import llm, promptlib
from app.schemas import EnvSnapshot, Extraction


def classify(user_text: str, env: EnvSnapshot) -> Extraction:
    system, user = promptlib.render(
        "classify",
        env=env.model_dump_json(indent=2),
        user_text=user_text.strip(),
    )
    return llm.generate_structured(user, Extraction, system=system)
