# OSGuard AI Progress

## Expanded Windows diagnostics through local MCP — 2026-11-22

**Status:** The existing LangGraph collector and local MCP server now expose
bounded read-only device/driver, network, Windows Update, and software
diagnostics. Driver-problem questions select `inspect_problem_devices` instead
of relying only on Windows version information. The graph, Groq provider,
FAISS retrieval, IEEE gate, approval workflow, and sole demo-cache repair
remain in place. No Windows configuration or security policy was changed.

### Implemented

- Added 13 approved MCP tools: `inspect_problem_devices`,
  `inspect_device_status`, `inspect_device_drivers`,
  `inspect_network_adapters`, `get_network_configuration`,
  `inspect_dns_configuration`, `check_network_connectivity`,
  `get_windows_update_history`, `inspect_failed_updates`,
  `inspect_update_service_status`, `inspect_installed_software`,
  `inspect_application_process`, and `inspect_application_errors`.
- Device problem inventory uses documented read-only PnPUtil first, with a
  fixed CIM fallback. Other device/driver inventory uses fixed CIM reads.
  Problem codes distinguish reported problems, disabled, disconnected, and
  missing-driver states. A nonzero code is not treated as proof of driver
  malfunction. Native network address/DNS inventory uses psutil and read-only
  TCP/IP registry metadata; missing gateway/DNS metadata remains unknown.
- Windows Update history uses a fixed local COM read; software inventory reads
  uninstall registry names, versions, and publishers without `Win32_Product`.
  Matching application processes and bounded crash events add local evidence.
  Event filters now accept a validated provider name; service status includes
  registry dependencies when accessible. Process `memory_mb` now uses decimal
  MB; `memory_mib` remains binary MiB.
- The collector selects at most four initial approved capabilities and one
  distinct evidence-driven follow-up. Client and server schemas validate
  arguments; the MCP client rejects unknown names, duplicate calls, malformed
  results, and calls without matching success evidence IDs. Generic dependency
  text no longer triggers broad host software inventory in unit tests.
- Diagnostic prompt rules distinguish observed codes, network probe outcomes,
  unrelated events, and uncertainty. Successful new tool rows can become
  evidence-ID-backed observations. Streamlit displays relevant inventory
  tables and raw per-tool status. Private IPv4 and IPv6 values are redacted before
  shared evidence reaches Groq.
- Added four verified Microsoft Learn sources for Wi-Fi, DNS, Update errors,
  and application crashes. A source-allowlist hash now detects a stale FAISS
  index before initialization. The approved rebuild produced **679 chunks**
  and verified a real FAISS lookup; no source fetch errors were reported.

### Verification and limitations

- Focused runs: **42 passed** for MCP/Windows/UI checks before the final
  selection correction; **33 passed** for extended diagnostics, RAG, and
  privacy; **14 passed** for the previously failing graph test and extended
  fixtures after the correction; **22 passed** for the final extended-diagnostic
  and privacy regression run. Tests use mocked Windows APIs and MCP
  fixtures; they make no Groq call and perform no repair.
- The one complete pytest run reported **200 passed, 1 failed, 2 skipped,
  17 warnings** in 62.15 seconds. The failed Phase 3 graph test found an
  overbroad software-inventory selection for unnamed dependency text. That
  selection was narrowed, and the exact failed test passed in the 14-test
  focused rerun. Per the request to run the complete suite only once, the
  complete suite was not rerun after the fix; a post-fix all-suite green
  result is therefore **not claimed**. The two skips require Windows symlink
  privilege; warnings come from LangSmith's Python 3.14 deprecation usage.
- Direct live smoke: network adapter inventory succeeded with six adapters,
  Update history returned two failed/aborted entries, and installed-software
  inventory succeeded with 20 displayed records. The initial CIM device query
  failed, the PowerShell IP query timed out, and the DNS cmdlet failed; those
  commands were not retried. Separate read-only PnPUtil and native-network
  fallback probes succeeded: zero reported problem devices and six network
  interfaces, with registry metadata for one interface.
- A single approved live Groq + local MCP + native FAISS driver question
  completed: `inspect_problem_devices` and `get_system_info` both returned
  successful MCP results with evidence IDs, FAISS returned four Microsoft
  passages, the Diagnostic Agent completed, there were no graph error codes,
  and no repair executed. The Supervisor's general `software_failure` problem
  label is less specific than a driver issue, although routing selected the
  device tool. No live driver-version, external connectivity, browser UI,
  or Windows repair demonstration was performed.

### Files and next work

Added `src/osguard/tools/extended.py`, `tests/test_extended_diagnostics.py`,
`scripts/smoke_extended.py`, and `scripts/check_mcp_drivers.py`. Modified
`src/osguard/tools/registry.py`, `src/osguard/tools/windows.py`,
`src/osguard/mcp/server.py`, `src/osguard/context.py`,
`src/osguard/agents/diagnostic.py`, `src/osguard/privacy.py`,
`src/osguard/rag/ingest.py`, `src/osguard/rag/knowledge_base.py`, `app.py`,
`data/documentation_sources.json`, `tests/test_windows_tools.py`,
`tests/test_rag.py`, README and architecture/guide/error documents.
Next work is manual browser review and targeted host checks for CIM-dependent
driver details and per-interface DNS metadata; no repair expansion is planned.

## FAISS initialization and MCP integration — 2026-11-22

**Status:** Native FAISS 1.16.0 imports on the current Python 3.14 Windows
environment. The approved Microsoft corpus was built under `data/faiss/` with
**536 chunks**, and a saved-index load and lookup were verified. A live
LangGraph investigation combined **MCP** memory/process measurements with
**FAISS** retrieval and a completed Groq-backed Diagnostic Agent. No repair
ran and no Windows security setting was changed.

### Cause and implementation

- The Streamlit **Initialize documentation** button previously called
  `search_documentation` only. With no `data/faiss/index.faiss`, that correctly
  returned `index_missing`; no ingestion was started. Its static caption also
  claimed the in-memory fallback was active on this device.
- Added one explicit preparation path for Streamlit and the CLI. It inspects
  native availability and the configured index, rebuilds a missing, partial,
  corrupt, or embedding-incompatible index from the allowlisted sources,
  reloads it, and verifies a bounded search before reporting **FAISS ready**.
  A valid index is reused across questions and app restarts. A per-process
  initialization lock prevents duplicate concurrent builds.
- Format version 2 records generation/producer and hashes both native index
  and JSON manifest. Load checks dimensions, chunk count, source hosts,
  provenance IDs, size limits, and link/junction status before native load.
  No pickle-based metadata deserialization is used. Checksums detect
  corruption, not malicious replacement of all files; only locally generated
  index artifacts are trusted.
- The existing in-memory backend remains limited to the recognized native
  Application Control block. A missing index is still explicit; no fabricated
  evidence or silent fallback is reported. Public Microsoft URLs, evidence
  IDs, scores, and section metadata continue into specialist prompts.
- The evidence collector now keeps RAG enabled for explanatory requests that
  explicitly ask why or request documentation, while simple local factual
  questions continue to use only relevant MCP measurements.
- Streamlit now shows missing, incomplete, invalid, model-mismatched,
  unavailable, validated, verified FAISS, and verified fallback states. It
  reports the actual initialization failure and distinguishes backend status
  from a successful retrieval. A browser-driven UI session was not run.

### Verification

- Native `import faiss` reported **1.16.0**. The live initializer downloaded
  the approved source pages, generated embeddings, persisted the three index
  artifacts, and reported `faiss_ready`, `retrieval_verified=true`,
  `document_count=536`, with no source errors. A later read-only status check
  reloaded the saved index and found 536 chunks.
- The live MCP + FAISS + Groq smoke check returned `diagnostic_backend=mcp`,
  `retrieval_status=success`, `retrieval_backend=faiss`, **4 genuine Microsoft
  passages**, successful `get_memory_info` and `get_process_stats` results,
  a completed Diagnostic Agent, no graph errors, and `repair_executed=false`.
  The fetched performance page is scoped as Windows Server guidance, so its
  applicability to Windows 11 remains explicitly qualified.
- Initial focused development run: **26 passed, 2 failed**. The failures were
  a zero-vector generic readiness probe in a deterministic encoder and a
  too-broad local-fact shortcut that skipped an explicit documentation request.
  Both were fixed. Targeted rerun: **2 passed**. Later focused RAG/UI/graph
  run: **29 passed**; additional RAG validation run: **14 passed**.
- The first live index attempt inside the command sandbox failed to fetch
  Microsoft pages with `WinError 10013`; an approved network-capable run
  succeeded. The first sandboxed live graph attempt returned
  `provider_unavailable` before diagnostics; the approved network-capable run
  succeeded. The errors and their resolution are also in `ERRORS.md`.
- Automated tests use fixture Microsoft HTML and deterministic embeddings for
  most index cases; the graph integration test uses native FAISS with fixture
  MCP results. The separate live smoke check used actual MCP, native FAISS,
  Groq and host measurements. Streamlit rendering is covered with a local UI
  test double, not a browser session.
- One complete pytest suite run after implementation: **189 passed, 2 skipped,
  17 warnings** in 17.37 seconds. The two skips need Windows symlink privilege
  for disposable filesystem and repair fixtures; the warnings are LangSmith
  deprecations of `asyncio.iscoroutinefunction` on Python 3.14.

### Files and remaining work

Changed `src/osguard/rag/ingest.py`, `retriever.py`, `memory.py`,
`build_index.py`; added `src/osguard/rag/knowledge_base.py` and
`scripts/check_mcp_faiss.py`; updated `src/osguard/context.py`, `app.py`,
`tests/test_rag.py`, `tests/test_rag_graph_integration.py`,
`tests/test_app_ui.py`, `README.md`, `docs/ARCHITECTURE.md`,
`docs/IMPLEMENTATION_GUIDE.md`, `ERRORS.md`, and this report.
The in-memory fallback still must fetch and embed once per process when used.
Browser interaction and rerun behavior need manual Streamlit verification.

## RAG documentation URL redaction fix — 2026-11-22

- Fixed the prompt privacy filter so a public HTTP(S) documentation URL keeps
  its route and query string when shared RAG evidence is serialized for a
  specialist. The previous POSIX path matcher treated `/test/cpu` in
  `https://learn.microsoft.com/test/cpu` as a local path and produced
  `https:/<PATH>`.
- Windows drive paths (including forward-slash form), UNC paths, and local
  POSIX paths remain masked. Private-host URLs and URLs with credentials are
  masked before the URL-aware POSIX path check. Evidence IDs, titles, OS
  versions, section metadata, and public source URLs are retained.
- Added `tests/test_privacy_urls.py` covering public HTTPS and Microsoft Learn
  URLs, query strings, local and network paths, private hosts, and local paths
  inside serialized diagnostic evidence. The existing RAG graph integration
  test confirms the in-memory retrieval result and provenance reach the
  Diagnostic Agent prompt.
- Focused run: **11 passed**, 17 LangSmith deprecation warnings.
- One complete suite run after the fix: **181 passed, 2 skipped**, 17 LangSmith
  deprecation warnings. The two skips require unavailable Windows symlink
  privilege in disposable fixtures. No live Groq request, native FAISS load,
  Windows repair, or MCP protocol run was part of this focused change.
- Files changed for this fix: `src/osguard/privacy.py`,
  `tests/test_privacy_urls.py`, `ERRORS.md`, and this progress report.

## Current milestone: Local MCP diagnostics integration — 2026-11-22

**Implementation status:** A local stdio MCP diagnostic server and client are
implemented in source. The existing Supervisor, three specialists, shared
LangGraph state, FAISS/in-memory RAG, IEEE gate, approval interrupt, and
restricted demo-cache repair remain in place. MCP does not expose a repair or
generic command tool. Runtime completion is **blocked** by Windows Application
Control on `_pydantic_core`; the new integration is not claimed as live verified.

### Implemented changes

- Added official Python MCP SDK 2.3.0 to the Python 3.14 virtual environment
  and `mcp>=2.3,<3` plus `jsonschema>=4.20,<5` to the project manifest.
  The server exposes 11 structured read-only tools: the six existing Windows
  tools, known-folder largest-file/list/size scans, system uptime, and bounded
  service listing. Stdio is the only configured transport.
- The existing evidence collector now prefers MCP, discovers advertised
  names, descriptions and JSON schemas, intersects them with a strict local
  Pydantic argument registry, and makes at most four initial calls and one
  follow-up in one session. Calls are not repeated by name. Connection,
  discovery, per-call timeout and structured-result failures remain explicit.
  A configurable direct Python fallback uses the same allowlist and is
  reported separately in state, tool results and Streamlit.
- Known folders are resolved through the Windows Known Folder API; the scanner
  reads metadata only, rejects arbitrary folder strings and reparse points,
  limits depth/entries/time, and labels partial results. Direct answers for
  measured file, directory size, service state, memory-ranked process and
  uptime questions precede broader diagnostic text. Simple local factual
  checks skip unnecessary documentation retrieval. Official Get-ChildItem
  and Remove-Item pages were added to the existing allowlisted source list
  for command explanations, not execution permission.
- Added `OperationMetadata` to exact repair plans for target, validated
  parameters, effect, risk class, preconditions, permissions, reversibility,
  validation and approval. It is included in the plan fingerprint. The only
  executable registration is still `CLEAR_OSGUARD_DEMO_CACHE`; IEEE and exact
  approval checks remain mandatory. Static command review now marks an
  inspection request paired with a known mutating command as an intent
  mismatch.
- Added disposable filesystem and MCP protocol/client/collector regression
  tests. Updated the Streamlit backend label, file/service tables, partial
  scan warnings, and exact-plan presentation.

### Actual verification and blockers

- Static parse: **57 Python files parsed** with `ast.parse`; the Microsoft
  source-list JSON parsed; `git diff --check` reported no whitespace errors.
  `pip check` reported no broken dependency requirements. These checks do not
  execute application code.
- Focused pytest: **0 tests ran**. Collection failed while importing
  `tests/test_evidence_diagnostics.py` because Windows Application Control
  blocked `_pydantic_core`.
- One full-suite attempt during this milestone:
  `.\.venv\Scripts\python.exe -m pytest tests -q --maxfail=1 --disable-warnings`:
  **0 tests ran**; collection stopped at `tests/test_app_ui.py` on the same
  `_pydantic_core` block. No test is reported as passed. A local MCP stdio
  smoke test and live Windows graph run could not be performed for the same
  reason. No policy bypass, Python version switch, or repair was attempted.
- Native FAISS remains independently blocked by Smart App Control. Filesystem
  and MCP behavior have fixture tests in source but no successful runtime
  verification in this environment. Directory scanning may be partial under
  depth, entry, timeout or permission limits; no device/driver inventory was
  added because a safe read-only API contract is not yet established.

### Files and next check

- Added `src/osguard/mcp/__init__.py`, `src/osguard/mcp/server.py`,
  `src/osguard/mcp/client.py`, `src/osguard/tools/filesystem.py`,
  `src/osguard/tools/registry.py`, `tests/test_filesystem_diagnostics.py`,
  `tests/test_mcp_diagnostics.py`. Modified `src/osguard/context.py`,
  `src/osguard/graph.py`, `src/osguard/state.py`, `src/osguard/schemas.py`,
  `src/osguard/tools/windows.py`, `src/osguard/agents/diagnostic.py`,
  `src/osguard/agents/command_verify.py`, `src/osguard/agents/_common.py`,
  `src/osguard/repair/registry.py`, `src/osguard/repair/planning.py`, `app.py`,
  `pyproject.toml`, `data/documentation_sources.json`, `README.md`,
  `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION_GUIDE.md`, `ERRORS.md`, and
  this progress report.
- Once Windows permits `_pydantic_core` through its authorized process, run
  focused MCP/filesystem tests, one full suite, an MCP stdio discovery/call
  smoke test, and a manual Streamlit check. Fix any runtime defects those
  checks reveal before claiming MCP is working live.

## Current milestone: Evidence-driven Windows diagnostics — 2026-11-22

**Status:** The existing Supervisor → shared evidence collector → specialist
graph now selects approved read-only measurements from the classified issue.
There is one shared workflow, not a separate RAM pipeline. A memory request
collects system memory and a memory-ranked process snapshot; CPU requests use
the same process tool with CPU ranking. The Diagnostic Agent and final report
carry measured facts with tool evidence IDs and identify hypotheses as
unconfirmed.

### Implementation

- The collector chooses at most four distinct initial allowlisted tools and
  supports one bounded System event-log follow-up when a successful named
  service check reports a stopped service. No generic command execution or
  new graph node was added.
- `get_process_stats` now ranks by CPU or working-set memory. The memory path
  scans at most 500 processes once without a CPU sampling delay; the CPU path
  keeps its 200-process bound. The tool reports scan limits, denied/terminated
  processes, memory bytes and MiB, and whether the cap was reached. Working
  sets are not summed to infer physical RAM use.
- Successful tool values become bounded diagnostic observations with actual
  evidence IDs. The agent filters unsupported memory-leak, causal, and
  pressure-severity claims from a single snapshot and does not request already
  measured values again. The final report starts with the user problem and
  separates observations, hypotheses, uncertainty, and safe next steps.
  Streamlit displays memory totals and a ranked process table before raw
  technical output.
- Duplicate tool facts are removed when a grounded model observation quotes
  the same measurement. Missing CPU sample-window metadata is no longer
  printed as `None seconds`.

### Verification

- Focused regression tests cover tool selection, CPU and memory ranking,
  permission-denied processes, stopped-service follow-up, grounded diagnostic
  facts, unsupported claims, final report, and Streamlit display. The final
  focused run of the affected agent/evidence tests: **16 passed**.
- The first complete suite found one duplicate CPU observation:
  **1 failed, 161 passed, 1 skipped**. After the fix, the complete suite run
  `.\.venv\Scripts\python.exe -m pytest tests -q --disable-warnings`:
  **162 passed, 1 skipped, 17 warnings** in 12.58 seconds. The skipped
  directory-symlink fixture lacks Windows symlink privilege (`WinError 1314`).
  The warnings are dependency deprecations in LangSmith.
- A real read-only memory/process scan on this host succeeded. After the
  single-pass process-scan change, 325 processes were inspected without
  reaching the 500-process cap in 13.86 seconds. These are snapshots, not a
  trend or diagnosis. A live Supervisor → collector → in-memory RAG →
  Diagnostic Agent graph run completed with Groq, two successful host tools,
  four Microsoft passages, seven measured observations, and no graph errors.
  That live run preceded the later unsupported-claim filter; the filter and
  duplicate-observation fix were verified with mocked Groq tests, not a new
  post-fix live call. Native FAISS remains blocked by Smart App Control.

### Files and next work

- Modified `src/osguard/context.py`, `src/osguard/tools/windows.py`,
  `src/osguard/agents/diagnostic.py`, `src/osguard/graph.py`, `app.py`,
  `tests/test_windows_tools.py`, `tests/test_specialist_agents.py`,
  `tests/test_app_ui.py`, `docs/ARCHITECTURE.md`, `ERRORS.md`, and this report;
  added `tests/test_evidence_diagnostics.py`.
- A single process snapshot cannot establish growth, a memory leak, or the
  exact cause of memory pressure. UI behavior has automated Streamlit tests;
  manual browser inspection and post-fix live Groq wording remain unverified.
  FAISS native loading remains subject to the host policy. No repair or OS
  modification was performed.

## Current milestone: Final RAG integration review — 2026-11-21

**Status:** The complete live Supervisor → in-memory RAG → Diagnostic Agent
graph ran on Python 3.14.8 with Groq and retrieved Microsoft documentation.
FAISS remains the preferred configured backend but is blocked on this host by
Smart App Control. No Windows security setting, repair workflow, or agent
architecture was changed.

### Changes and verification

- Fixed exact `os_version` filtering in FAISS and aligned its `source_id`
  filter with the in-memory backend. Both backends now retain the OS version
  in evidence metadata. Fake-FAISS and in-memory regression tests cover
  matching and nonmatching filters; native FAISS could not be exercised here.
- The final response now mentions retrieved documentation only when retrieval
  succeeded and evidence is present. Failed retrieval passes no passages to
  specialists and produces no documentation claim. A LangGraph regression
  test covers this failure path.
- Added an explicit **Initialize documentation** Streamlit control. It warms
  the existing process-cached in-memory index before analysis, so later
  requests in that app process reuse document downloads and embeddings.
  The first initialization still needs network access and local embedding
  work; the index is not persisted between app processes.
- A real LangGraph fixture with an allowlisted Microsoft-page HTML sample,
  deterministic embeddings, and a mocked structured Diagnostic Agent checked
  that the passage, evidence ID, URL, title, OS version, section, category,
  chunk ID, and metadata reach the specialist prompt and stay attached to a
  grounded diagnostic hypothesis. The fixture made no Groq or network calls.
- A separate **live** read-only graph run used real Microsoft retrieval, local
  embeddings, Groq classification, and Groq Diagnostic Agent output. The
  warmup and graph both returned `backend=in_memory`, `status=success`.
  The graph retained four passages; its first was
  `windows-performance-troubleshooting#windows-performance-troubleshooting-0006`
  from `https://learn.microsoft.com/en-us/troubleshoot/windows-server/performance/troubleshoot-performance-problems-in-windows`.
  Diagnostic Agent status was `completed`, workflow status was
  `specialists_completed`, and graph errors were empty. The final response
  acknowledged retrieved documentation. This live run did not exercise
  native FAISS or a repair.

### Test results and remaining limits

- Focused tests: `tests/test_rag_graph_integration.py`: **2 passed**;
  `tests/test_rag.py`: **9 passed**; `tests/test_app_ui.py` and
  `tests/test_phase3_graph.py`: **12 passed**. These tests use mocked
  Groq responses and deterministic or fixture-backed retrieval.
- One complete suite run after code changes:
  `.\.venv\Scripts\python.exe -m pytest -q --disable-warnings
  --log-disable=langgraph.checkpoint.serde.jsonplus`:
  **149 passed, 1 skipped, 17 warnings** in 15.16 seconds. The skipped
  symlink test requires Windows directory-symlink privilege (`WinError 1314`).
- Native `faiss.dll` remains blocked by Smart App Control; its retrieval
  behavior is covered only with the FAISS test double. The in-memory index
  must be rebuilt after each app restart, and its first load needs access to
  the allowlisted Microsoft pages. If retrieval fails, no citation is made.

### Files changed

- `src/osguard/rag/retriever.py`, `src/osguard/rag/memory.py`,
  `src/osguard/agents/_common.py`, `src/osguard/graph.py`, `app.py`,
  `tests/test_rag.py`, `tests/test_app_ui.py`,
  `tests/test_rag_graph_integration.py`, `ERRORS.md`, and this report.

## Current milestone: RAG fallback for the documented FAISS policy block

**Status:** FAISS remains the primary backend and is still blocked by Smart App
Control on this Windows 11 / Python 3.14.8 host. A separate LangChain
`InMemoryVectorStore` fallback completed a real lookup of the allowlisted
Microsoft documentation, using the existing local Sentence Transformers model.
The Supervisor, specialists, IEEE gate, and repair path were not changed.

### Implemented

- Added policy-block-only backend selection to `search_documentation`. When
  FAISS is available, its persisted index and cosine search remain unchanged.
  Other FAISS failures remain explicit errors rather than silently switching
  backends.
- Added a process-cached in-memory cosine index from the same validated source
  list, HTML extractor, chunker, and local embedding model. Documents are
  embedded once per cached index; each request embeds only its query. Exact
  category, OS version, and source-ID filters and the existing 1–8 top-k bound
  apply. Retrieved evidence retains title, URL, OS scope, section, chunk ID,
  source ID, passage, and score. Failed loads produce no citations.
- Added an explicit retrieval backend field and Streamlit labels: **FAISS
  available**, **In-memory fallback active**, and **Retrieval unavailable**.

### Verification and restrictions

- Focused RAG and UI tests: `tests/test_rag.py tests/test_app_ui.py`:
  **16 passed, 17 warnings** in 4.91 seconds. Tests use deterministic
  embeddings and do not call Groq or make network requests. One additional
  persisted-index block test was added afterward and included in the full run.
- One complete suite run after implementation:
  `.\.venv\Scripts\python.exe -m pytest -q --disable-warnings
  --log-disable=langgraph.checkpoint.serde.jsonplus`:
  **146 passed, 1 skipped, 17 warnings** in 13.54 seconds. The skipped test
  requires directory-symlink creation privilege (`WinError 1314`); the
  junction and mocked symlink guards remain covered. The warnings are the
  existing dependency deprecations.
- One live in-sandbox fallback attempt returned `retrieval_error`, zero
  evidence. A focused source fetch failed with `WinError 10013` because the
  command sandbox denied the socket. A separate read-only approved fetch
  outside the sandbox succeeded, and a real fallback search returned
  `status=success`, `backend=in_memory`, two Microsoft passages with IDs,
  URLs, and cosine scores 0.5937 and 0.5559. This verifies live fallback
  retrieval, not native FAISS or a full Groq-to-RAG graph run.
- Native `faiss.dll` is unsigned and remains blocked by enforced Smart App
  Control policy `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`. No policy or
  package change was made. The fallback fetches source pages and embeds them
  on first use in each application process; it is not persisted and needs
  network access for that first load. Browser interaction remains manual.

### Files changed

- `src/osguard/rag/memory.py`, `src/osguard/rag/retriever.py`,
  `src/osguard/schemas.py`, `app.py`, `tests/test_rag.py`,
  `tests/test_app_ui.py`, `README.md`, `ERRORS.md`,
  `docs/ARCHITECTURE.md`, and this progress report.

## Current milestone: Phase 6 — end-to-end integration review

**Status:** Independent live Groq, read-only Windows, local embedding, and
Streamlit startup paths were verified on Python 3.14.8 / Windows 11. Native
FAISS remains blocked by Windows Application Control, so a full live RAG-backed
workflow and browser-based approval demonstration are **not yet verified**.
The architecture and sole executable demo repair were preserved.

### Integration work and defects fixed

- Live text completion via the centralized `ChatGroq` factory succeeded using
  configured model `openai/gpt-oss-120b`; the API key was not printed.
- A live structured Supervisor request exposed a real defect: the default
  function-calling path returned HTTP 400 `tool_use_failed` when Groq supplied
  `available_environment: null`. Shared structured invocations now select
  Groq JSON Schema mode (`strict=False`) for Pydantic contracts. The configured
  model supports that mode, and a subsequent live structured classification
  returned `SupervisorClassification(intent=diagnose,
  selected_specialists=[diagnostic])`. Two offline regression tests verify the
  mode and compatibility with injected model doubles.
- Distinct live single-specialist graph workflows completed: memory diagnosis
  selected Diagnostic Agent, collected a successful `get_memory_info` result,
  and retained two observations and two hypotheses; software dependency review
  selected Compatibility Agent and kept an undocumented requirement `unknown`;
  `Get-Process` review selected Command Verification Agent, reported low risk
  for the stated listing intent, and kept `should_execute=False`. Each ended
  with IEEE `no_actions`, no repair, and no graph errors. The missing FAISS
  index was reported as `index_missing` rather than fabricated evidence.
- The read-only Windows smoke script returned success for system metadata,
  process/CPU, memory, local disk, an existing service, and System event logs.
  A nonexistent service returned `not_found`. A separate 24-hour System query
  returned three records with expected event ID/data types. The host reported
  Windows 11 build 26300 / AMD64. The bounded 200-process scan took 16.372
  seconds on this machine; process names and event contents were not printed.
- The cached Sentence Transformers model produced a 384-dimensional embedding
  with offline mode enabled. Streamlit started on loopback, returned HTTP 200
  from `/_stcore/health`, and the script ran in headless AppTest with zero
  exceptions, three buttons, and one text area. A browser session was not run.
- The existing full graph tests cover selective and multiple specialist routing,
  state aggregation, evidence preservation, IEEE ordering and denial, partial
  failures, exact-plan approval/decline, once-per-plan execution, and fresh
  post-repair validation. The registered handler ran only against disposable
  pytest temporary data. No host repair or PowerShell command was run.

### Exact automated and runtime results

- Focused structured-output affected tests:
  `pytest tests/test_supervisor_graph.py tests/test_specialist_agents.py
  tests/test_ieee_verification.py -q --disable-warnings
  --log-disable=langgraph.checkpoint.serde.jsonplus`:
  **54 passed, 17 warnings** in 5.12 seconds.
- New regression module run:
  `pytest tests/test_groq_client.py -q --disable-warnings
  --log-disable=langgraph.checkpoint.serde.jsonplus`:
  **11 passed, 17 warnings** in 3.49 seconds.
- One final full-suite run:
  `.\.venv\Scripts\python.exe -m pytest -q --disable-warnings
  --log-disable=langgraph.checkpoint.serde.jsonplus`:
  **141 passed, 1 skipped, 17 warnings** in 40.42 seconds. The one skip was
  actual directory-symlink creation (`WinError 1314`, privilege unavailable);
  mocked junction and symlink guard tests passed. The warnings are existing
  `langsmith` deprecations.
- Direct `import faiss` failed on `faiss-cpu` 1.16.0 with `DLL load failed while
  importing _swigfaiss: An Application Control policy has blocked this file.`
  `data/faiss/index.faiss` is absent. No index build, persistence/load, real
  retrieval query, or metadata retrieval could be verified. The installed
  release provides a [CPython 3.14 Windows x64 wheel](https://pypi.org/project/faiss-cpu/),
  so this remains an observed local policy restriction; it was not bypassed.
- Two live graph probe commands completed graph invocation but failed while
  formatting summaries because the probes used nonexistent schema attributes
  (`FinalResponse.status` and `CommandVerificationFinding.risk_level`). They
  were not rerun. Distinct later workflows used the actual fields and returned
  successful structured summaries. See `ERRORS.md` for all observed errors.

### Files modified in Phase 6

- `src/osguard/agents/_common.py`, `src/osguard/supervisor.py`: Groq JSON Schema
  structured-output selection.
- `tests/test_groq_client.py`: two regression tests.
- `scripts/verify_windows_tools.py`: privacy-limited read-only runtime check.
- `README.md`, `docs/ARCHITECTURE.md`, `docs/PROGRESS.md`, `ERRORS.md`:
  runtime status, manual demonstration steps, and errors.
- A pre-existing modified `osguard-review.zip` was not changed by this work.

### Remaining checks

- Native FAISS index build/load/search and source metadata preservation require
  the device's approved resolution of the existing Application Control block.
  No backend substitution, untrusted DLL, or security-policy change was made.
- Browser interaction with Streamlit, including visual review of approval,
  decline, and post-repair status, remains manual. Headless startup and fixture
  UI tests do not prove a browser session. The README gives exact steps.
- Live multi-specialist coordination and live Groq-generated proposals with
  documentation evidence were not exercised; deterministic tests cover those
  flows. Rate-limit and timeout translation were tested with injected errors,
  and were not triggered by live Groq requests.
- The process scan latency on this host may be noticeable in the UI. The
  checkpoint and execution ledger remain process-local; other repairs remain
  recommendation-only. Phase 6 cannot be called fully verified while native
  retrieval is blocked.

## Historical report: Phase 5 — controlled demo repair review and verification

**Status:** The existing Phase 5 implementation passed focused and full
automated verification on `.venv` CPython 3.14.8. This review found no
implementation defect requiring a code change. Phase 6 had not started at the
time of that review.

### Implemented and reviewed

- LangGraph routes every proposed action through the IEEE node, deterministic
  eligibility, and exact repair planning. Only the registered
  `CLEAR_OSGUARD_DEMO_CACHE` action can reach the restricted executor.
- A checkpointed `interrupt()` pauses for a separate human decision. Resume
  requires the same thread, an affirmative decision, and the exact plan ID and
  SHA-256 fingerprint. The action, IEEE result, target, parameters, and current
  cache precondition are checked again after approval and before execution.
- The single handler truncates only the known OSGuard-owned disposable cache
  payload under `data/demo_app/cache`. It rejects unknown entries, altered
  fixture bytes, arbitrary targets, and detected symlinks/junctions/reparse
  points. No shell, PowerShell, privileged Windows repair, or arbitrary path
  execution is present in the repair registry.
- A process-local execution ledger claims a plan before the file change, so
  repeat submissions do not execute it twice. Fresh post-repair inspection
  checks the actual payload and ownership marker before reporting resolved,
  partially resolved, unresolved, failed, or unverifiable.
- Streamlit presents the exact plan and separate `APPROVE`/`DECLINE` controls
  only for an eligible pending checkpoint. It clears its resume cursor before
  submitting a decision. The demo fixture requires an explicit preparation
  action in the UI.

### Exact test results

- `.\.venv\Scripts\python.exe --version`: **Python 3.14.8**.
- `python -m pytest tests/test_phase5_repair.py -q --disable-warnings
  --log-disable=langgraph.checkpoint.serde.jsonplus`: **36 passed, 1 skipped,
  17 warnings** in 10.62 seconds.
- `python -m pytest tests/test_app_ui.py -q --disable-warnings
  --log-disable=langgraph.checkpoint.serde.jsonplus`: **7 passed, 17 warnings**
  in 3.38 seconds. This includes the two Phase 5 UI tests.
- One final full-suite run, `python -m pytest -q --disable-warnings
  --log-disable=langgraph.checkpoint.serde.jsonplus`: **139 passed, 1 skipped,
  17 warnings** in 12.57 seconds. The suite was run once after the focused
  review; no failures occurred.
- The single skip was the actual directory-symlink creation test on this
  Windows account: `WinError 1314` (required symlink privilege unavailable).
  Separate mocked junction and symlink guard tests passed. The 17 warnings
  are existing `langsmith` deprecation warnings; warning/log output was
  suppressed in the command but counted by pytest.

### What the tests establish

The isolated `tmp_path` fixture exercised real LangGraph interrupt/resume and
the registered Python handler, with an unrelated sibling file checked intact.
Tests covered missing or failed IEEE results, no approval, decline, stale or
changed plan approval, unregistered actions, modified parameters and arbitrary
paths, duplicate direct execution and graph resume, changed cache evidence,
permission failure, malformed agent output, partial specialist failure, and
fresh validation that refuses to claim success when the payload remains. The
default exact demo request was exercised without a Groq call or FAISS lookup.
Streamlit tests used a fake UI and graph; they verified the pending-plan controls
and one-time resume cursor, not a browser session.

### Limitations and manual Windows checks

- Native FAISS loading remains blocked by the previously observed Windows
  Application Control policy for `_swigfaiss`; no policy bypass was attempted.
  The full suite uses a FAISS test double where needed. This blocker is
  independent of the exact local demo-cache route.
- A real directory symlink guard needs a Windows account permitted to create
  that symlink. The guard's junction and payload-symlink branches passed with
  isolated mocked filesystem responses.
- No live Groq request, browser-based Streamlit approval session, live FAISS
  retrieval, host diagnostic sampling, or demo repair outside pytest temporary
  fixtures was performed during this review. Those need manual Windows checks
  before claiming a complete live demonstration.
- `InMemorySaver` and the execution ledger are process-local. Restarting the
  app loses a pending approval session; no persistent or multi-process
  execution guarantee is claimed. Only the OSGuard disposable demo cache is
  repairable. Other recommendations remain recommendation-only.

### Files modified in this review

- `README.md`, `docs/ARCHITECTURE.md`, and `docs/PROGRESS.md` were updated to
  describe the verified Phase 5 behavior and limitations. No implementation or
  test code was changed.

### Next phase

Phase 5 is ready for a manual Windows demonstration of the disposable fixture
once the remaining environment restrictions are handled. Phase 6 had not begun
at the time of this historical report.

## Historical report: Phase 4 — IEEE verification framework

**Status:** Phase 4 implementation is complete. The focused Phase 4 tests
passed: **39 passed, 17 warnings** in 13.63 seconds. The final full-suite run
passed on CPython 3.14.8 (64-bit): **101 passed, 17 warnings** in 5.01 seconds.
No live Groq request, Windows inspection, or repair was performed.

### Implemented

- Added typed corrective-action candidates, evidence quotes, action proposals,
  per-action IEEE results, and explicit workflow summary states.
- Added a bounded structured-output proposal node and a structured IEEE
  assessment node. They reuse the graph's shared Groq model and support
  dependency injection for deterministic tests.
- Connected the required graph path from specialist aggregation through
  proposal and IEEE verification to the final response; there is no graph edge
  that skips the verification stage.
- Added deterministic intent, environment, evidence, effect, target, and action
  identity checks. A result is supported only when every check passes; missing
  facts remain uncertain and prohibited/unsupported operations fail closed.
- Kept proposals limited to evidence-backed dependency mismatches with an
  explicitly requested remediation. The graph does not execute commands,
  approve repairs, or modify Windows.
- Updated Streamlit to show proposals, source excerpts, four verification
  checks, unsupported/uncertain outcomes, and no-action/failure states without
  presenting approval or execution controls.
- Added focused unit, graph integration, and UI coverage using mocked models,
  specialists, evidence, and tools. No unit test needs a live Groq API call.

### Phase 4 files added or modified

- Added `src/osguard/verification/__init__.py`, `proposals.py`, `rules.py`,
  `ieee.py`, `tests/test_ieee_verification.py`, and
  `tests/test_phase4_graph.py`.
- Modified `src/osguard/schemas.py`, `src/osguard/state.py`,
  `src/osguard/graph.py`, `app.py`, `tests/test_app_ui.py`, `README.md`,
  `docs/ARCHITECTURE.md`, and this progress report.

### Phase 4 limitations

- Only documented dependency-version mismatches can currently produce
  candidate recommendations. Other repair classes remain unsupported.
- `supported` means the recommendation passed the evidence and policy checks;
  it does not mean the operation is eligible for execution or approved.
- Native FAISS loading remains blocked by the existing Windows Application
  Control policy, as recorded in the Phase 3 report below. It was not bypassed.
- No live Groq call, live corpus retrieval, host inspection, command execution,
  repair, or user approval was performed.

## Historical report: Phase 3 — FAISS RAG and read-only Windows tools

**Status:** Phase 3 implementation and mocked automated coverage are complete.
At the time Phase 3 was completed, the full suite passed on CPython 3.14.8
(64-bit): **66 passed, 17 warnings** in 4.71 seconds. `compileall` also
completed successfully. No Groq request, Windows inspection, documentation
download, or repair was performed.

### Implemented

- Added typed shared retrieval and tool-result state, including reducer-backed
  aggregation across the selected specialists.
- Added a curated Microsoft Learn source list, HTTPS/host validation, HTML
  cleaning, section-aware chunking, local Sentence Transformers embeddings,
  FAISS cosine search, source metadata, checksums, bounded results, exact
  metadata filters, and explicit missing/corrupt/error statuses.
- Added an index builder (`python -m osguard.rag.build_index`) that persists
  the generated index locally under gitignored `data/faiss/`. The application
  reuses a loaded index and does not rebuild it per request.
- Added six bounded read-only Windows checks: system information, process/CPU
  sampling, memory, disk capacity, exact-name service status, and filtered
  Application/System/Setup event logs. They do not invoke PowerShell, request
  elevation, or modify Windows.
- Added one shared evidence-collection node after Supervisor classification.
  It performs at most one retrieval and selects only fixed tools relevant to
  the classified problem. The three existing specialists receive the same
  evidence snapshot and validate claims against source IDs and quoted evidence.
- Updated Streamlit to display observed environment data, retrieval status and
  citations, tool statuses, findings, and partial failures without inventing
  evidence.
- Added deterministic RAG, Windows-tool, specialist, graph, and UI coverage.
  Tests inject fake embeddings/FAISS, tools, retrievers, and model outputs;
  they do not call Groq or inspect the host.

### Files added or modified

- Added `src/osguard/context.py`, `src/osguard/rag/` modules,
  `src/osguard/tools/windows.py`, `data/documentation_sources.json`,
  `tests/test_rag.py`, `tests/test_windows_tools.py`,
  `tests/test_phase3_agents.py`, and `tests/test_phase3_graph.py`.
- Modified `src/osguard/agents/`, `src/osguard/graph.py`,
  `src/osguard/schemas.py`, `src/osguard/state.py`, `app.py`,
  `tests/test_app_ui.py`, `tests/test_supervisor_graph.py`, `pyproject.toml`,
  `.gitignore`, `README.md`, and `docs/ARCHITECTURE.md`.

### Verification and remaining environment blocker

- `.venv` is CPython 3.14.8 x64. Direct imports of `pydantic_core` 2.50.5,
  `langchain_groq`, and `langgraph` succeeded. `sentence_transformers` 6.3.0
  and `psutil` 7.2.2 imported successfully.
- Direct `import faiss` failed while loading `_swigfaiss` with
  `ImportError: DLL load failed while importing _swigfaiss: An Application
  Control policy has blocked this file.` No security setting was bypassed or
  changed. The native index build/load and real retrieval path therefore remain
  unverified; tests use a deterministic FAISS test double.
- The corpus has not been fetched and the local embedding model has not been
  run. No live Groq request or Windows tool sampling was performed.
- Pytest reported 17 `langsmith` deprecation warnings for
  `asyncio.iscoroutinefunction`, slated for removal in Python 3.16; no test
  failures remained.

### Limitations at Phase 3 completion

The indexed evidence and read-only tools now flow through the existing graph,
but native FAISS runtime verification is still blocked by Windows Application
Control. IEEE verification was the next milestone at that point; it is now
implemented. Repair planning/approval/execution and post-repair validation
remain future work.

## Historical report: Phase 2 — Specialist Agents

The following section records Phase 2 results from before Phase 3 was started.

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
