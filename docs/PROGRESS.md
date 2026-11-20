# OSGuard AI Progress

## Current milestone: Phase 2 — Specialist Agents

**Status:** Implementation changes are present; tests and runtime execution were
not performed in this task, as requested. Python remains 3.14. The existing
Windows Application Control restriction on `pydantic_core` remains deferred.

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
- Modified: `src/osguard/agents/diagnostic.py`,
  `src/osguard/agents/command_verify.py`,
  `src/osguard/agents/compatibility.py`, `src/osguard/graph.py`,
  `src/osguard/schemas.py`, `src/osguard/state.py`,
  `src/osguard/supervisor.py`, and `app.py`.
- Updated: `README.md`, `docs/ARCHITECTURE.md`, and this report.

### Tests and live services

- Tests were not run, per the user's instruction. No test files were added or
  updated in this task.
- No live Groq request was made.
- The existing Phase 1 supervisor tests still assert placeholder-agent results
  and need to be revised to inject structured specialist responses before the
  automated suite can validate Phase 2 behavior.
- No PowerShell command, diagnostic tool, or repair was executed.

### Known limitations

- Runtime behavior is unverified. The previously observed Windows Application
  Control policy may still block imports of `pydantic_core`; it was not bypassed
  or changed.
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

Phase 3 is not started. Per the implementation guide, the next milestone is
trusted evidence retrieval and approved read-only Windows tools. The IEEE gate
and repair workflow remain later milestones.
