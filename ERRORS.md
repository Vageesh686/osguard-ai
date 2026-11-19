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
Do not retry the blocked native import or attempt to bypass the policy. Use an
administrator-approved Python environment or package when available.

## Pytest plugin import

The first plain pytest run stopped during plugin loading: the optional
LangSmith pytest plugin imported Pydantic and hit the same blocked native
module. This project does not use LangSmith tracing yet, so pytest is
configured not to auto-load that plugin. The normal project test command then
ran successfully. This does not change Windows policy or enable the live Groq
import.

The existing `.venv` uses Python 3.14, while this project currently targets
Python 3.12. The current mocked tests pass under the existing interpreter, but
a clean install on the declared target interpreter has not been verified.

## Verification deferred

- Automated tests use a fake model factory and do not import `langchain_groq`.
- A live Groq request has not been run from this environment because the
  provider import is blocked before the request can start.
- After an approved environment is available, run the manual smoke check
  (`python test_groq.py`) to verify the live provider path.
