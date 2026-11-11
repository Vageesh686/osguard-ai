"""INTENT check: does the action serve the user's stated goal? (LLM judge)"""
from app import llm, promptlib
from app.schemas import Action, IntentCheck


def check_intent(goal: str, action: Action) -> IntentCheck:
    system, user = promptlib.render(
        "intent",
        goal=goal,
        shell=action.shell,
        command=action.command,
        rationale=action.rationale or "(none given)",
    )
    return llm.generate_structured(user, IntentCheck, system=system)
