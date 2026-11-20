# OSGuard AI Progress

## Current milestone: Phase 1 — LangGraph Supervisor

**Status:** Implementation is present but was not tested in this turn, as
requested. The known Windows Application Control restriction on Pydantic Core
remains unresolved; no policy changes or bypass attempts were made.

### Implemented

- Added strict Pydantic contracts for request classification, OS environment,
  specialist findings, evidence provenance, proposed actions, IEEE results,
  repair eligibility, approval, execution/validation, errors, and final reports.
- Added a typed LangGraph shared state with reducer-backed finding/result lists.
- Added a Groq-backed Supervisor classifier using the existing `ChatGroq`
  factory and LangChain structured output. One classifier/client is built per
  cached graph; routing and graph execution support classifier injection.
- Added bounded conditional routing to the Diagnostic, Command Verification,
  and Compatibility specialists. Each selected specialist runs at most once;
  complex requests can select multiple specialists.
- Added an aggregation node and a final response node. Specialist placeholders
  return `not_implemented` and empty findings; no Windows checks, PowerShell
  commands, repairs, or fabricated results are produced.
- Updated Streamlit with a problem input, classification/category, subsystem,
  selected specialists, workflow status, missing information, and explicit
  placeholder status. The existing Groq connection check remains available in
  a separate expander.
- Added seven offline tests for high CPU, PowerShell safety, missing software
  dependency, crash after Windows update, unclear input, unsupported environment
  claims, and invalid structured output.
- Updated README examples to describe Phase 1 behavior.

### Files added or modified

- Added: `src/osguard/schemas.py`, `src/osguard/state.py`,
  `src/osguard/supervisor.py`, `src/osguard/graph.py`.
- Added: `src/osguard/agents/__init__.py`, `diagnostic.py`,
  `command_verify.py`, and `compatibility.py`.
- Added: `tests/test_supervisor_graph.py`.
- Modified: `app.py`, `README.md`, and this progress report.

### Tests and live services

- Tests were **not run**, per the user's instruction.
- No live Groq request was made.
- Supervisor routing tests use injected classifications; they do not require
  Groq credentials or make network requests.

### Known limitations

- Specialist agents are placeholders. No diagnostic observations, hypotheses,
  command verification, compatibility findings, RAG evidence, IEEE decisions,
  repairs, approvals, or post-repair validation are implemented in this phase.
- The Windows Application Control block on `pydantic_core` was previously
  confirmed and can prevent Pydantic-dependent app imports in this environment.
  It is intentionally left for the user to resolve later.
- The new code and UI were not executed during this turn, so runtime behavior
  remains unverified.

### Next milestone

The next planned milestone is the three specialist workflows, beginning with
approved read-only diagnostics. It was not started as part of this Phase 1 task.
