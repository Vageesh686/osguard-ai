# OSGuard AI Progress

## Current milestone: Project setup and Groq integration

**Status:** Implementation is in place. Live Groq verification is pending
because the current Windows Application Control policy blocks Pydantic Core;
this milestone is not marked fully verified.

### Implemented

- Added a `pyproject.toml` for the Python 3.12 package, runtime dependencies,
  editable installation, and pytest configuration.
- Added centralized Groq settings loaded from environment variables and the
  project `.env`; API keys are excluded from settings representations.
- Added a `ChatGroq` factory and text request wrapper with timeout/retry
  settings and readable rate-limit, timeout, connection, import, and response
  errors.
- Added a local Streamlit connection-check screen using a fixed prompt. It
  does not diagnose Windows or recommend system changes.
- Converted `test_groq.py` into an explicit manual live smoke check; importing
  it no longer calls the Groq API.
- Added mock-based tests for configuration, model construction, requests, and
  common provider errors.
- Updated the local `.env` model and `.env.example` to `openai/gpt-oss-120b`,
  Groq's documented replacement for the prior Llama 3.3 70B model ID.

### Verification

- `.\.venv\Scripts\python.exe -m pytest -q` — **14 passed**.
- `py_compile` completed for the app, smoke script, package modules, and tests.
- `pyproject.toml` parsed successfully with Python's `tomllib`.
- Plain pytest initially failed before collection because its optional
  LangSmith plugin imported the policy-blocked Pydantic Core module. Since
  LangSmith is not used in this milestone, pytest is configured not to load
  that plugin.
- No live Groq request was made. Importing `langchain_groq` reaches the blocked
  native Pydantic Core extension in the existing Python 3.14 environment.
- The repository targets Python 3.12; a clean install under that interpreter
  remains unverified.

### Known limitations and next work

- Ask the device administrator for an approved Python/package environment,
  then run `python test_groq.py` to verify live Groq connectivity.
- Once the provider path is verified, continue with the LangGraph Supervisor
  and typed shared state milestone.
- The Supervisor, specialists, RAG, diagnostics, IEEE gate, approval flow,
  repair executor, and post-repair validation are not implemented yet.

