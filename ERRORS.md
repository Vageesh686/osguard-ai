# Errors and Environment Blockers

## Confirmed: Pydantic Core blocked by Windows Application Control

The existing virtual environment cannot import `langchain_groq` because its
dependency chain reaches the compiled Pydantic Core extension and Windows
Application Control blocks that file.

- Python process: `Python314\python.exe`
- Blocked module: `pydantic_core\_pydantic_core.cp314-win_amd64.pyd`
- Policy ID: `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`
- Result: the live `ChatGroq` client cannot be loaded in this environment.

This is an environment policy failure, not an error in the Groq request code.
Do not bypass or change the host policy. Leave this blocker documented until
the user resolves it through the device's approved process.

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

## Compatibility check results

- Installed compatible package versions: LangGraph 1.2.23, LangChain 1.5.2,
  `langchain-groq` 1.2.1, Pydantic 2.14.4 / Pydantic Core 2.50.5, Streamlit
  1.67.0, FAISS CPU 1.16.0, and Sentence Transformers 6.3.0.
- `langgraph` and Streamlit imports succeeded. `pip check` reported no broken
  requirements; the automated tests passed (14 tests).
- `pydantic_core` and `langchain_groq` remain unimportable due to the confirmed
  Application Control block. Installing compatible Python 3.14 wheels did not
  remove this host policy restriction.
- A post-install import sweep for FAISS and Sentence Transformers was stopped
  before it completed. Their installed versions and dependency metadata are
  compatible with this interpreter, but successful imports were not verified.

## Verification deferred

- Automated tests use a fake model factory and do not import `langchain_groq`.
- A live Groq request has not been run from this environment because the
  provider import is blocked before the request can start.
- After the device policy permits the native dependency to load, run the manual
  smoke check (`python test_groq.py`) to verify the live provider path.
