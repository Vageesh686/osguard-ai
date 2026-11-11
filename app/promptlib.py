"""Tiny prompt-template loader.

Each file in app/prompts/ has the form:

    <system prompt>
    === USER ===
    <user prompt with {{placeholders}}>

We use {{name}} placeholders (not str.format) so JSON examples with braces are safe.
"""
from app.config import PROMPT_DIR

SEPARATOR = "=== USER ==="


def load(name: str) -> tuple[str, str]:
    text = (PROMPT_DIR / f"{name}.txt").read_text(encoding="utf-8")
    system, sep, user = text.partition(SEPARATOR)
    if not sep:
        raise ValueError(f"prompt '{name}' is missing the '{SEPARATOR}' separator")
    return system.strip(), user.strip()


def render(name: str, **values) -> tuple[str, str]:
    """Return (system, user) with {{key}} placeholders filled in."""
    system, user = load(name)
    for key, val in values.items():
        user = user.replace("{{" + key + "}}", str(val))
    return system, user
