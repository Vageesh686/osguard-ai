"""Two baselines to compare OSGuard against, both returning the same BaselineAnswer shape:

  plain_llm     - the LLM answers from its own knowledge (no retrieval, no verification)
  standard_rag  - retrieve top-k passages, stuff them into one prompt, answer (no verification)
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app import llm
from app.schemas import EnvSnapshot
from app.stages import retrieve
from app.stages.diagnose import format_passages


class BaselineAnswer(BaseModel):
    diagnosis: str
    commands: list[str] = Field(default_factory=list)          # every command you recommend, one per item
    flagged_risky: list[str] = Field(default_factory=list)     # subset of `commands` you consider risky
    citations: list[str] = Field(default_factory=list)         # passage ids you relied on (RAG only)


_SYSTEM = ("You are a Windows 11 support assistant. Diagnose the problem and recommend commands. "
           "In `commands` list each command exactly as the user should type it. "
           "In `flagged_risky` list any of those commands you consider risky to run.")


def plain_llm(user_text: str, env: EnvSnapshot) -> BaselineAnswer:
    prompt = (f"Environment:\n{env.model_dump_json(indent=2)}\n\nProblem:\n{user_text}\n\n"
              "Give a short diagnosis and the commands you recommend. Leave `citations` empty.")
    return llm.generate_structured(prompt, BaselineAnswer, system=_SYSTEM)


def standard_rag(user_text: str, env: EnvSnapshot, k: int = 6) -> tuple[BaselineAnswer, list[str]]:
    """Returns (answer, retrieved_chunk_ids)."""
    chunks = retrieve.retrieve(user_text, None, k=k)
    prompt = (f"Environment:\n{env.model_dump_json(indent=2)}\n\nProblem:\n{user_text}\n\n"
              f"Reference passages:\n{format_passages(chunks)}\n\n"
              "Use the passages. In `citations` list the ids (in square brackets) of passages you relied on.")
    ans = llm.generate_structured(prompt, BaselineAnswer, system=_SYSTEM)
    return ans, [c.id for c in chunks]
