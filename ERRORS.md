# Errors and Environment Blockers

## Current check — 2026-11-21

- `.venv` runs CPython 3.14.8 x64.
- `pydantic_core` 2.50.5, `langchain_groq`, `langgraph`,
  `sentence_transformers` 6.3.0, and `psutil` 7.2.2 imported successfully.
- `faiss` still fails to import: `DLL load failed while importing _swigfaiss:
  An Application Control policy has blocked this file.` No policy was changed
  or bypassed. Native FAISS index build/load and live retrieval remain blocked.
- `pytest -q`: 66 passed, 17 dependency deprecation warnings. Tests inject a
  deterministic FAISS test double and do not establish native FAISS runtime
  compatibility.
- No live Groq request, documentation download, local embedding inference, or
  live Windows diagnostic was performed.

## Historical incident: Pydantic Core blocked by Windows Application Control

The existing virtual environment cannot import `langchain_groq` because its
dependency chain reaches the compiled Pydantic Core extension and Windows
Application Control blocks that file.

- Python process: `Python314\python.exe`
- Blocked module: `pydantic_core\_pydantic_core.cp314-win_amd64.pyd`
- Policy ID: `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`
- Result: the live `ChatGroq` client cannot be loaded in this environment.

This was an environment policy failure, not an error in the Groq request code.
The block was not reproduced in the current check above; no explanation for
that change has been established. Do not bypass or change the host policy.

## Pytest plugin import

The first plain pytest run stopped during plugin loading: the optional
LangSmith pytest plugin imported Pydantic and hit the same blocked native
module. This project does not use LangSmith tracing yet, so pytest is
configured not to auto-load that plugin. The normal project test command then
ran successfully. This does not change Windows policy or enable the live Groq
import.

The project and existing `.venv` both target CPython 3.14. The venv reports
Python 3.14.8 (64-bit Windows). Dependency installation and the mocked test
suite completed under that interpreter.

## Earlier compatibility check results

- Installed compatible package versions: LangGraph 1.2.23, LangChain 1.5.2,
  `langchain-groq` 1.2.1, Pydantic 2.14.4 / Pydantic Core 2.50.5, Streamlit
  1.67.0, FAISS CPU 1.16.0, and Sentence Transformers 6.3.0.
- `langgraph` and Streamlit imports succeeded. `pip check` reported no broken
  requirements; the automated tests passed (14 tests).
- At the time of the earlier check, `pydantic_core` and `langchain_groq` were
  unimportable due to the Application Control block. Current import results
  are recorded at the top of this file.
- The earlier import sweep did not verify FAISS or Sentence Transformers;
  their current observed import results are also recorded above.

## Verification deferred

- Automated tests use fake model outputs and do not make live Groq requests.
- The Groq client imports now, but a live provider request has not been run.
- Native FAISS loading remains blocked. Once it is permitted through the
  device's approved process, run the index builder and verify real retrieval.
