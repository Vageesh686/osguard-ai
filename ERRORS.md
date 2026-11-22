# Errors and Environment Blockers

## MCP integration check — 2026-11-22

- The first sandboxed `pip install` attempt could not contact PyPI:
  `WinError 10013` on the HTTPS socket. An approved install outside that
  network sandbox installed official `mcp` 2.3.0 and its dependencies into
  the existing Python 3.14 virtual environment. No package was reinstalled.
- An SDK import inspection command failed at `pydantic_core` with
  `ImportError: DLL load failed while importing _pydantic_core: An Application
  Control policy has blocked this file.` This is the previously documented
  host policy issue, now reproduced; the import command was not repeated.
- The first focused pytest run stopped during collection at the same
  `_pydantic_core` policy block, before any test body ran. No blocked test is
  counted as passed. Source files were parsed with Python's `ast` module,
  which does not import or execute project dependencies.
- The single full-suite attempt stopped at collection of `tests/test_app_ui.py`
  on the same `_pydantic_core` block: zero tests ran. It was not repeated.
- A repository patch attempt timed out in the Windows sandbox helper before
  opening `graph.py`. A subsequent smaller patch succeeded; no project code
  was changed by the failed attempt.
- The local MCP stdio smoke test and live Windows graph workflow are blocked
  until the host permits `_pydantic_core`. No security setting was changed or
  bypassed. Native FAISS remains separately blocked as previously recorded.

## Evidence-driven diagnostics check — 2026-11-22

- Two focused development runs exposed local test/code issues: a syntax error
  in a new dictionary comprehension and one outdated exact-dictionary test
  assertion after adding process memory fields. Both were corrected; the
  subsequent focused tests passed. Neither was a Windows tool failure.
- An initial live graph run completed, but its result-printing probe raised
  `UnicodeEncodeError` on the PowerShell console's CP1252 encoding. A distinct
  ASCII-safe read-only probe reported a completed memory workflow with two
  successful host tools, four retrieved passages, and no graph errors.
- That live response included unsupported causal and severity wording about
  aggregate RAM utilization. Deterministic filtering and regression fixtures
  were added afterward. The post-fix wording has been checked in mocked tests;
  the earlier live response is not evidence that the filter was active then.
- Native FAISS remains blocked by the existing Smart App Control policy. The
  live graph used the in-memory retrieval backend. No policy change, native
  library reinstall, arbitrary command, or repair was attempted.

## Final RAG integration review — 2026-11-21

- Native FAISS remains blocked by the Smart App Control policy described
  below. The successful live graph run used `backend=in_memory`; it is not
  evidence that `faiss.dll` can load on this host.
- An initial live verification one-liner failed before importing OSGuard with
  `NameError: name 'My' is not defined` because PowerShell stripped nested
  quotation marks. A distinct PowerShell here-string invocation succeeded.
  This was a probe invocation error, not a graph error.
- One combined focused pytest invocation produced no output for an extended
  period and was interrupted. The same test files were then run in smaller
  groups and passed. The final full suite also passed with 149 tests and one
  privilege-dependent skip.
- A read-only `Get-CimInstance Win32_Process` process-list probe returned
  `HRESULT 0x80041003` (Access denied). It was not needed for the RAG
  verification and no elevated access was requested.

## Current RAG backend check — 2026-11-21

- Windows Code Integrity event 3077 blocked
  `.venv/Lib/site-packages/faiss/faiss.dll` under the enforced
  `VerifiedAndReputableDesktop` Smart App Control policy
  `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`. Correlated event 3089
  reported zero signatures. Python names `_swigfaiss` because that extension
  attempts to load the blocked DLL. The installed `faiss-cpu` 1.16.0 wheel
  matches CPython 3.14 Windows x64, and the DLL and extension match their
  installed package hashes. Native FAISS remains unavailable; no policy or
  package change was attempted.
- The first live fallback search returned `retrieval_error` with no citations
  inside the command sandbox. A focused fetch exposed `WinError 10013` while
  opening an allowlisted Microsoft URL. A separate approved read-only check
  outside the network sandbox fetched that page, and a full fallback lookup
  returned two real Microsoft passages using local embeddings. This was a
  sandbox network restriction, not a retrieval-code defect.
- The fallback keeps its document vectors in process memory. Its initial
  construction needs the approved Microsoft URLs to be reachable; if none can
  be loaded, it returns `retrieval_error` and no citations. It does not make
  native FAISS available.

## Phase 6 checks — 2026-11-21

- **FAISS remains blocked:** `faiss-cpu` 1.16.0 is installed, but direct
  `import faiss` fails with `ImportError: DLL load failed while importing
  _swigfaiss: An Application Control policy has blocked this file.` The local
  `data/faiss/index.faiss` file is absent. No native index was built or queried,
  and no policy change or package reinstall was attempted. The published
  [CPython 3.14 Windows x64 wheel](https://pypi.org/project/faiss-cpu/) and
  [upstream Python 3.14 build configuration](https://github.com/facebookresearch/faiss/blob/main/pyproject.toml)
  support this Python/platform combination; the observed failure is the local
  code-integrity restriction, not evidence of a missing wheel. The cached
  Sentence Transformers model did produce a 384-dimensional vector offline.
- **Groq structured-output defect, fixed:** the original live Supervisor call
  reached Groq but received HTTP 400 `tool_use_failed`: the default tool-call
  path produced `available_environment: null`, while the schema required an
  object. `src/osguard/agents/_common.py` and `src/osguard/supervisor.py` now
  select Groq's JSON Schema mode (`strict=False`) for the existing Pydantic
  contracts. The post-fix structured classification succeeded;
  regression tests cover the mode selection. The configured
  `openai/gpt-oss-120b` model is listed in
  [Groq Structured Outputs](https://console.groq.com/docs/structured-outputs).
- **Network sandbox:** the initial small Groq request failed with a connection
  error inside the command sandbox. Outside that sandbox, the same smoke check
  succeeded. A structured-call attempt inside the sandbox showed Windows
  socket error `WinError 10013`; outside it, Groq was reachable. The API key
  was never printed or logged.
- **Inspection-script errors, not graph failures:** two one-line live graph
  probes completed `graph.invoke(...)` but then failed while formatting their
  results. One referenced nonexistent `FinalResponse.status`; another referenced
  nonexistent `CommandVerificationFinding.risk_level`. The actual fields are
  `FinalResponse.workflow_status` and `CommandVerificationFinding.risk`. These
  probe commands were not rerun. Distinct memory, compatibility, and safe
  command scenarios later completed and returned structured summaries.
- **One diagnostic command syntax error:** an early shell-quoted Python
  configuration probe raised `SyntaxError: unterminated string literal` before
  running project code. A separate simpler configuration check confirmed the
  Groq key was present and the configured model ID without printing the key.
- **Process sampling latency:** the live bounded process scan of 200 processes
  took 16.372 seconds on this host, despite a requested 0.05-second CPU sample.
  This is a performance limitation for the current read-only tool, not a test
  failure or evidence of an inaccurate process value.

## Historical Phase 3 check — 2026-11-21

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

## Earlier deferred checks (before Phase 6)

- Automated tests use fake model outputs and do not make live Groq requests.
- At that point the Groq client imported, but no live provider request had been
  run. Phase 6 live results are recorded above.
- Native FAISS loading remains blocked. Once it is permitted through the
  device's approved process, run the index builder and verify real retrieval.
