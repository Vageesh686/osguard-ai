# OSGuard AI Progress

## Current milestone: Phase 2 — Specialist Agents

**Status:** Phase 2 specialist workflows and automated coverage are implemented.
The full pytest suite passed on `.venv` Python 3.14.8: 41 passed, with 17
dependency deprecation warnings. No live Groq request or OS command was used.
The historical Windows Application Control block on `pydantic_core` was not
encountered in this run; no security policy was bypassed or changed.

### Implemented in code

- Replaced all three placeholder specialists with reusable structured-output
  LangChain workflows backed by the existing Groq model factory.
- Changed graph construction to share one `ChatGroq` model instance among the
  Supervisor and selected specialists. Classifiers, model factories, models,
  and specialist node functions can be injected.
- Added prompt-boundary redaction for common Windows paths, account labels,
  email addresses, SIDs, and labeled IP addresses before user text is sent to
  Groq. Quote grounding and static command matching use the redacted text.
- Diagnostic Agent: extracts user-reported symptoms, potential subsystems,
  quote-grounded observations and hypotheses, missing information, uncertainty,
  and non-invasive information-gathering steps. It does not inspect the host;
  unsupported quotes and steps that appear to modify the system are omitted.
- Command Verification Agent: reviews supplied command text without running
  it, reports intent fit, recognized and unknown command names, possible
  effects, risk, and administrator uncertainty. Deterministic static rules flag
  known mutating commands and preserve unknown commands as unverified. The
  structured contract prohibits execution.
- Compatibility Agent: retains version and OS/architecture facts only when
  present in user input, distinguishes user-reported facts from hypotheses,
  and leaves the result unknown unless explicit versions and a comparison
  constraint can be checked.
- Added append reducers for specialist findings, missing information, and
  uncertainty. Specialist failures are recorded without dropping completed
  results from other agents; graph routing remains bounded to one invocation
  per selected specialist.
- Updated the final response and Streamlit UI to show agent status, diagnostic
  quotes and hypotheses, unperformed safe steps, command review, compatibility
  facts, missing information, uncertainty, and partial failures.
- Populated `docs/ARCHITECTURE.md` with the frozen architecture and current
  implementation boundaries. Updated README behavior and examples.

### Files added or modified

- Added: `src/osguard/agents/_common.py`.
- Added: `tests/test_app_ui.py` and `tests/test_specialist_agents.py`.
- Modified: `src/osguard/agents/diagnostic.py`,
  `src/osguard/agents/command_verify.py`,
  `src/osguard/agents/compatibility.py`, `src/osguard/graph.py`,
  `src/osguard/schemas.py`, `src/osguard/state.py`,
  `src/osguard/supervisor.py`, `app.py`, and
  `tests/test_supervisor_graph.py`.
- Updated: `README.md`, `docs/ARCHITECTURE.md`, and this report.

### Tests and live services

- Ran `.\.venv\Scripts\python.exe -m pytest -q`: **41 passed, 17 warnings** in
  5.38 seconds. The warnings are `langsmith` deprecations for
  `asyncio.iscoroutinefunction`; there were no test failures or blocked tests.
- Replaced Phase 1 placeholder assertions with Phase 2 routing and graph tests
  using injected specialist nodes. Coverage includes single and multiple
  routing, reducer-backed state preservation, partial failures, and invalid
  structured specialist output.
- Exercised the Supervisor through all three real specialist nodes using an
  injected deterministic structured-output model; this made no Groq request.
- Added deterministic tests for Diagnostic, Command Verification, and
  Compatibility agents, plus Streamlit result rendering for successful and
  failed specialist workflows.
- Every graph test injects its classifier and specialist nodes, or supplies a
  fake structured-output model. Tests do not require Groq credentials or send
  network requests. Groq client tests also use fake model factories.
- Pydantic model imports and validation succeeded during this run. The prior
  Application Control block was not reproduced; no policy changes or bypasses
  were attempted.
- No live Groq request, Streamlit server, Windows diagnostic, PowerShell
  command, or repair was run.

### Known limitations

- Runtime behavior is unverified. The previously observed Windows Application
  Control policy was not reproduced by this test run, but live app startup and
  a real Groq call were not tested.
- Specialist analysis is based on the request text only. There is no live
  Windows inspection, PowerShell parser, FAISS retrieval, vendor-document
  verification, or authoritative software inventory.
- Privacy redaction covers common patterns only; it cannot guarantee that all
  sensitive content in arbitrary logs is removed.
- Command recognition uses a small conservative static name policy, not a
  complete PowerShell grammar. Unknown or complex syntax remains unverified.
- Compatibility results remain unknown when explicit, comparable requirements
  are absent.
- The mandatory IEEE gate, repair plan, approval mechanism, restricted repair
  executor, and post-repair validation are not implemented yet.

### Next phase

Phase 3 is not started. Phase 2 is ready to proceed based on the full local
automated suite; live Groq behavior and browser-based Streamlit startup remain
unverified. Per the implementation guide, the next milestone is trusted
evidence retrieval and approved read-only Windows tools. The IEEE gate and
repair workflow remain later milestones.
