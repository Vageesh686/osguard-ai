
# OSGuard AI

## Local MCP diagnostics (current development branch)

OSGuard's existing LangGraph evidence collector now prefers a local MCP stdio
server built with the official Python SDK. The client launches it with the
project's Python 3.14 interpreter, discovers its approved tools and schemas,
validates arguments again locally, makes a bounded set of calls, and closes
the session. There is no public listener or MCP repair tool.

The server wraps the existing Windows system, process, memory, disk, service,
and event-log checks. It also exposes read-only known-folder metadata scans:
`get_largest_files`, `list_directory`, and `get_directory_size` for Downloads,
Documents, and Desktop. `get_system_uptime` and `list_services` provide bounded
additional checks. File contents are never opened. Arbitrary paths, junctions,
symlinks, and unapproved commands are not accepted. A limited or inaccessible
scan is reported as partial.

Install the project and test dependencies with
`.\.venv\Scripts\python.exe -m pip install -e ".[test]"`, then run the local
server for protocol clients with
`.\.venv\Scripts\python.exe -m osguard.mcp.server`. That command reserves
stdout for MCP; it waits for a stdio client. Normal use is through
`.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1`.
The UI reports **MCP active**, **Direct fallback active**, or **Diagnostic tools
unavailable**, plus provenance for each tool result.

Set `OSGUARD_DIAGNOSTIC_BACKEND=direct` to use the controlled Python tools
without MCP. Set `OSGUARD_DIRECT_FALLBACK=0` to leave diagnostics unavailable
when MCP cannot start. Direct fallback uses the same argument registry. The
only enabled state-changing operation remains the exact OSGuard demo-cache
repair after IEEE verification and LangGraph approval. MCP cannot execute it.

The file scanners accept only named Windows known folders; add a new tool by
implementing a bounded read-only function, registering its strict arguments in
`src/osguard/tools/registry.py`, and exposing a wrapper in
`src/osguard/mcp/server.py`. Then add a capability selection rule and fixture
tests. Do not expose arbitrary path or command execution.

**Current verification:** Python 3.14, Pydantic Core, native FAISS, Groq, and
the local MCP diagnostic path work in the current development environment.
A read-only live memory investigation used MCP and the persisted FAISS index
together. See `docs/PROGRESS.md` for exact results and remaining manual checks.

### Multi-Agent Operating System Diagnostics, Verification and Controlled Self-Repair

OSGuard AI is a Python-based multi-agent system designed to
investigate operating system problems, verify AI-generated
troubleshooting recommendations, and perform selected low-risk
repairs with explicit user permission.

The project combines LangGraph, LangChain, Groq LLMs,
Retrieval-Augmented Generation (RAG), FAISS, and Windows
diagnostic tools.

**Status:** Under Development

**Platform:** Windows 11 (Local Application)

## 1. Problem Statement

Operating systems contain interconnected components such as
processes, memory, file systems, storage devices, system
services, drivers, and software dependencies.

Users frequently encounter OS failures and depend on online
resources or AI assistants for troubleshooting.

However, AI-generated solutions may contain:
- Incorrect root-cause explanations
- Nonexistent or invalid commands
- Incompatible software recommendations
- Unsupported configuration changes
- Unsafe troubleshooting instructions
- Recommendations that do not match user intent

Retrieving relevant documentation alone does not guarantee
that a suggested solution is appropriate for a specific system.

OSGuard AI aims to address these limitations through
multi-agent investigation and evidence-based verification.

## 2. Project Objectives

1. Build an intelligent OS troubleshooting assistant capable
   of understanding problems across multiple OS subsystems.

2. Implement specialized agents for diagnostics, command
   verification, and software compatibility analysis.

3. Use RAG and FAISS to retrieve relevant documentation
   and support generated explanations.

4. Implement read-only tools for collecting Windows system
   information and diagnostic evidence.

5. Develop the Intent-Environment-Evidence-Effect (IEEE)
   verification framework.

6. Reduce unsupported or potentially unsafe AI-generated
   troubleshooting recommendations.

7. Support selected low-risk, non-admin repairs with
   explicit user approval.

8. Validate repair outcomes and report unresolved problems.

## 3. Core Features

### Multi-Agent Investigation

A LangGraph Supervisor coordinates specialized workflows:

- Diagnostic Agent
- Command Verification Agent
- Compatibility Agent

Specialists receive the Supervisor classification and one shared evidence
snapshot. Before specialists run, OSGuard performs one bounded documentation lookup and
selects only relevant read-only Windows checks. Diagnostic findings keep user
reports, tool measurements, documentation citations, and hypotheses distinct.
Common paths and identifiers are redacted before Groq inference; redaction is
best-effort and not a guarantee for arbitrary logs.

### OS Diagnostics

The system is designed to investigate:
- Process and CPU issues
- Memory usage problems
- Storage and file system errors
- Windows service failures
- Device and driver issues
- Startup problems
- Software dependency issues
- Configuration and permission errors

The diagnostic path can read a bounded process/CPU snapshot, memory, local disk
capacity, one explicitly named Windows service, recent System or Application
events, and basic Windows version/build/architecture. Only checks relevant to
the Supervisor classification are selected. Access-denied and unsupported
results remain explicit; no administrator privileges are requested.

### Command Verification

Analyze proposed PowerShell commands for:
- Recognized command structure
- Intended behavior
- Compatibility
- Operational risk
- Alignment with user intent

The current verifier uses structured model analysis plus conservative static
command-name checks. It never invokes PowerShell. Unknown or complex commands
remain unverified.

### Retrieval-Augmented Generation

The shared RAG layer uses a curated allowlist of official Microsoft Learn
sources in `data/documentation_sources.json`. It stores title, URL, Windows
scope, category, section, chunk ID, passage, and relevance score. Retrieved
text is untrusted reference material and cannot authorize commands or establish
a diagnosis by itself.

FAISS remains the primary persistent index. If Windows Application Control
blocks its native library, a separate LangChain `InMemoryVectorStore` fetches
the same allowlisted pages, uses the same local Sentence Transformers model and
chunking, and caches document embeddings for the application process. Search
uses cosine similarity and returns at most eight passages. The first fallback
lookup needs network access to the Microsoft pages; later lookups in the same
process reuse the in-memory index. No embedding service is called. The UI shows
whether FAISS, the in-memory fallback, or neither backend served the request.
Failed retrieval returns no citations.

Open **Documentation knowledge base** in Streamlit and select **Initialize
documentation** to download the allowlisted pages, embed chunks, persist the
FAISS index under `data/faiss/`, reload and validate it, and verify one search.
The UI distinguishes a missing or incomplete index, a validated FAISS index,
a verified FAISS lookup, an active in-memory fallback, and initialization
failure. Repeating initialization reuses a valid index. The command-line
equivalent is `python -m osguard.rag.build_index` in the project environment.

Generate explanations that distinguish supporting evidence
from possible diagnostic hypotheses.

### IEEE Verification

Evaluate recommendations using:

**Intent**
Does the action address the user's problem?

**Environment**
Is it applicable to the current OS configuration?

**Evidence**
Is it supported by available diagnostic information?

**Effect**
What changes will the action make?

Every proposed recommendation receives all four structured checks. The Groq
assessment is combined with deterministic source, intent, environment, target,
operation, and risk rules. A missing or mismatched fact remains unknown or
fails; a model risk label cannot override policy. Current proposals cover
documented dependency mismatches with a user-reported installed version and
the explicitly requested OSGuard disposable demo-cache action. Only the latter
can become eligible for execution.
`supported`, `unsupported`, and `uncertain` describe recommendation evidence
only. High-risk, privileged, unknown, registry, deletion, driver, service,
security, permission, and command operations are never authorized for
execution. The IEEE gate precedes every repair eligibility decision.

### Controlled Repair Execution

The sole registered operation, `CLEAR_OSGUARD_DEMO_CACHE`, truncates a known
disposable payload in `data/demo_app/cache`. The user must first prepare this
fixture explicitly. The action can run only after:
- Independent verification
- Eligibility checks
- Exact plan preview and explicit approval through a checkpointed LangGraph
  interrupt/resume session
- Target, parameter, fingerprint, and current file-state validation

The restricted executor rechecks eligibility after approval and records each
plan as attempted before the file change, so repeated submissions cannot run
the same plan twice. It does not execute shell or PowerShell commands.

Administrator-level, dangerous, or uncertain actions
remain recommendation-only.

### Post-Repair Validation

After the approved demo repair, OSGuard freshly inspects the actual cache
payload and ownership marker. It reports resolved, partially resolved,
unresolved, failed, or unverifiable according to the measured result.

## 4. System Architecture

The target architecture consists of:

1. Streamlit User Interface
2. LangGraph Supervisor
3. Diagnostic Agent
4. Command Verification Agent
5. Compatibility Agent
6. Shared RAG and Windows diagnostic tools
7. IEEE Verification Gate
8. Repair Planning and Approval
9. Restricted Execution Engine
10. Post-Repair Validation
11. Final Report Generator

Currently implemented: Supervisor, typed shared state, three specialist
workflows, multi-specialist routing, FAISS retrieval with a cached in-memory
fallback, bounded read-only
Windows tools, result aggregation, corrective recommendation proposals,
mandatory IEEE verification, exact demo repair planning and eligibility,
checkpointed approval, one restricted executor, post-repair validation, and
the Streamlit evidence display. Other repair operations remain unsupported.

For detailed architecture and workflows, see:

- docs/ARCHITECTURE.md
- docs/IMPLEMENTATION_GUIDE.md

## 5. Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.14 |
| Frontend | Streamlit |
| Agent Orchestration | LangGraph |
| LLM Integration | LangChain + Groq |
| LLM Provider | Groq API |
| Vector Database | FAISS primary; LangChain InMemoryVectorStore fallback |
| Embeddings | Sentence Transformers |
| Data Validation | Pydantic |
| OS Diagnostics | Python, psutil, Windows APIs |
| Testing | pytest |
| Observability | LangSmith / LangFuse (optional) |

## 6. Installation

### Prerequisites

- Windows 11
- CPython 3.14 (Windows x64)
- Git
- VS Code
- Groq API key

### Clone the Repository

Once the project is published:

```powershell
git clone <repository-url>
cd OSGuard-AI
```

Or open the existing project directory in VS Code.

### Create a Virtual Environment

```powershell
py -3.14 -m venv .venv
```

### Install Dependencies

Install the project and its test dependencies from `pyproject.toml`:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

The project dependency set includes LangGraph, LangChain, `langchain-groq`,
Pydantic, FAISS CPU, Sentence Transformers, psutil, Streamlit, and dotenv
support.

## 7. Environment Configuration

Create a `.env` file in the project root.

```dotenv
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
LLM_PROVIDER=groq
```

Obtain a key from:

https://console.groq.com/keys

Never commit `.env` or expose actual API credentials.

Model availability and supported API features should be
checked against Groq's current documentation.

## 8. Running OSGuard AI

The main Streamlit screen accepts a Windows issue, asks Groq for structured
classification and selected specialist analyses, and displays read-only
measurements and retrieved documentation where available. The exact request
`Clear the OSGuard demo cache.` uses a fixed local route without a Groq call.
After explicit fixture preparation and exact-plan approval, it can clear only
that disposable cache. Submitted commands are never executed. Configure `.env`
and build the local documentation index once, either with the Streamlit
**Initialize documentation** button or this command:

```powershell
.\.venv\Scripts\python.exe -m osguard.rag.build_index
```

Index construction fetches only the Microsoft URLs listed in
`data/documentation_sources.json` and uses local Sentence Transformers
embeddings. The first build needs network access to those sources and may
download the embedding model. Later requests reuse the persisted `data/faiss/`
index instead of rebuilding it. The generated index is local and gitignored.
The current development machine successfully initialized 536 chunks and
verified native FAISS retrieval. The CLI exits successfully only after a
validated FAISS load and a search. If the native library is blocked by the
documented Application Control policy on another machine, the app can use its
process-cached in-memory fallback; a missing FAISS index alone does not
activate that fallback.

Only locally generated, trusted `data/faiss/` artifacts should be loaded.
The index uses a native FAISS file and JSON metadata, with checksums and
source-host/shape validation. It does not use pickle deserialization. The
checksums detect accidental alteration but are not cryptographic proof of
origin; do not copy untrusted index files into this directory. If files are
missing, incomplete, corrupt, or from a different embedding model, use the
initialization button or CLI to rebuild from the allowlisted sources.

Then start Streamlit:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

Open the local application:

http://localhost:8501

For an explicit one-off live provider smoke check:

```powershell
.\.venv\Scripts\python.exe test_groq.py
```

The Groq connection check is available in a separate expander. Automated unit
tests use deterministic fixtures and do not send live Groq requests. See
`docs/PROGRESS.md` for exact test and environment results.

The application is intended to run locally.
No deployment is required.

## 9. Example User Interactions

### Scenario 1: High CPU Usage

User:
"My Windows laptop is running slowly and CPU usage is high."

Current behavior:
1. Supervisor classifies the request and selects Diagnostic Agent.
2. OSGuard collects a short process/CPU sample and retrieves up to four relevant
   documentation passages when a local index exists.
3. Diagnostic Agent separates the reported symptom from measured values and
   unconfirmed hypotheses. High CPU use alone is not treated as a root cause.

### Scenario 2: Unsafe PowerShell Command

User:
"Check whether this command is safe for my intended task."

Current behavior:
1. Supervisor selects Command Verification Agent when command text is present.
2. The agent returns a static risk and intent review. Unknown commands remain
   unverified and no command is executed.

### Scenario 3: Software Compatibility

User:
"An application fails because a required dependency is missing."

Current behavior:
1. Supervisor selects Compatibility Agent.
2. The agent distinguishes facts stated by the user from hypotheses and asks
   for missing versions or documented requirements. It does not inspect
   installed software or invent versions.

### Scenario 4: Application crashes after a Windows update

The Supervisor selects both Diagnostic and Compatibility Agents. OSGuard shares
retrieved documentation, basic Windows metadata, and relevant read-only
measurements across both agents. Missing evidence and agent errors are surfaced;
an uncertain result is not presented as a confirmed cause.

### Scenario 5: User-Approved Demo Repair

User:
"Clear the OSGuard demo cache."

Current workflow:
1. In Streamlit, select **Prepare disposable demo cache** to create known
   application-owned fixture data.
2. Submit the exact request above. The read-only inspection supplies evidence.
3. IEEE verification and eligibility checks produce an exact plan preview.
4. **APPROVE** or **DECLINE** the plan. Approval resumes the same LangGraph
   thread and rechecks its fingerprint and current preconditions.
5. The restricted handler clears the known payload once; fresh inspection
   determines the reported outcome.

Only predefined, low-risk, non-admin operations
are eligible for execution.

## 10. Safety Restrictions

OSGuard must not autonomously execute arbitrary
LLM-generated commands.

The initial system must not:
- Modify critical Windows configuration
- Change registry settings
- Install or uninstall drivers
- Disable security controls
- Delete arbitrary files
- Execute administrator-level repairs

Unsafe or unsupported repairs are recommendation-only.

Read-only investigation is preferred by default.

## 11. Testing

Run the automated suite:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The automated suite covers mocked Supervisor/specialist routing, evidence
aggregation, retrieval ingestion and search, Windows-tool result handling,
action proposals, all four IEEE checks, fail-closed policies, graph integration,
Streamlit success/failure displays, and Phase 5 approval and execution. Phase 5
tests use isolated disposable cache fixtures and execute the one registered
Python handler inside pytest temporary directories. They exercise LangGraph
interrupt/resume, rejection paths, repeat-submission protection, and fresh
post-repair measurement. Other tests use deterministic models and tools; no
test calls Groq, runs PowerShell, or repairs Windows. Phase 6 separately
verified live Groq calls, local embeddings, read-only Windows tools, and
Streamlit startup. A later live fallback lookup retrieved real Microsoft
passages. Native FAISS now also loads and retrieves from the local persistent
index, and a live MCP + FAISS + Groq memory investigation succeeded.
Browser-based Streamlit interaction remains a manual check. Exact results are
in `docs/PROGRESS.md`.

See docs/PROGRESS.md for actual implementation status
and test results.

## 12. Development Roadmap

- [x] Initialize project structure and Groq integration
- [x] Implement Supervisor and shared LangGraph state
- [x] Implement three specialist agents (live single-specialist paths verified)
- [x] Add FAISS RAG and curated Microsoft documentation
- [x] Add cached in-memory retrieval when Smart App Control blocks FAISS
- [x] Add bounded read-only Windows diagnostic tools
- [x] Implement corrective action proposals and IEEE verification
- [x] Add controlled execution for the disposable OSGuard demo cache only
- [x] Implement post-repair validation for that action
- [x] Add mocked Phase 3 and Phase 4 integration coverage
- [x] Verify native FAISS indexing, persistence and retrieval on this machine
- [x] Verify live Groq structured classification, three specialists, and read-only Windows tools
- [ ] Prepare final demonstration

Update this checklist as features are implemented.

## 13. Current Limitations

The initial prototype targets Windows 11 and a limited set
of diagnostic and repair scenarios.

It does not aim to provide:
- Universal OS fault diagnosis
- Unrestricted system automation
- Guaranteed repair success
- Automatic administrator-level repairs
- Production-grade endpoint management

The earlier Smart App Control block on FAISS is not present in the current
development environment. Native FAISS 1.16.0 built and loaded the local index,
and a live graph run combined FAISS retrieval with MCP measurements and Groq.
No security policy was changed by OSGuard. The in-memory fallback still needs
network access on first use in each process and does not persist its index.
The Microsoft performance page retrieved in the live memory check is marked
as Windows Server guidance, so applicability to Windows 11 needs care.
Browser-based Streamlit approval and operation of the demo repair outside
isolated pytest fixtures still require manual Windows verification. The local
checkpoint and execution ledger are process-memory
only; restarting the app does not preserve a pending approval session.

### Repeatable local verification

These steps are for a local Windows 11 session with Python 3.14 and the project
dependencies installed. The tool smoke check prints only statuses, bounded
counts, and basic numeric system measurements; it omits process names and event
contents.

```powershell
.\.venv\Scripts\python.exe scripts/verify_windows_tools.py
.\.venv\Scripts\python.exe -m osguard.rag.build_index
.\.venv\Scripts\python.exe scripts/check_mcp_faiss.py
.\.venv\Scripts\python.exe test_groq.py
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

In Streamlit, try these requests separately:

1. `My Windows laptop has high CPU usage. Can you investigate what is happening?`
   Check that Diagnostic Agent shows read-only measurements separately from
   user reports and hypotheses.
2. `I want to list files in a directory. Is this PowerShell command safe for
   that intent: Remove-Item -Recurse -Force C:\TestFolder` Check that Command
   Verification flags the destructive command and never executes it.
3. `My app reports a missing .NET Desktop Runtime. I have version 7.0
   installed. Which version does it require?` Without indexed documentation,
   the requirement must remain unknown and no installation should run.
4. Select **Prepare disposable demo cache**, then submit
   `Clear the OSGuard demo cache.` Review the IEEE checks and exact plan. First
   choose **DECLINE** and confirm no execution is reported. Submit the same
   request again, choose **APPROVE**, and confirm post-repair inspection reports
   the actual result. Refresh the page to confirm it does not submit again.

In Streamlit, open **Documentation knowledge base**. With no index it should
show **Not initialized** while FAISS is available. Select **Initialize
documentation** and wait for **FAISS ready** after a verified search. A later
analysis should report **FAISS retrieval successful** and show linked evidence.
If Smart App Control blocks `faiss.dll` on another device, the UI should show
**In-memory fallback active** only after its own retrieval succeeds. If neither
backend can retrieve, it should show an explicit error and no citations.

## 14. Project Documentation

| Document | Description |
|---|---|
| AGENTS.md | Instructions for Codex |
| docs/IMPLEMENTATION_GUIDE.md | Detailed implementation specification |
| docs/ARCHITECTURE.md | System architecture and workflows |
| docs/PROGRESS.md | Development status and test results |
| ERRORS.md | Confirmed environment blockers and deferred verification |

## 15. Project Purpose

OSGuard AI is developed as a college and resume project
to demonstrate:

- Multi-agent AI orchestration
- Prompt engineering
- Retrieval-Augmented Generation
- Tool calling
- Operating system diagnostics
- Evidence-based verification
- Human-in-the-loop execution
- LangGraph workflow design

The objective is to build a functional,
testable local prototype that can be extended later.
