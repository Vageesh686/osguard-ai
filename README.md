
# OSGuard AI

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

Agents use shared diagnostic context and retrieved evidence.

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

### Command Verification

Analyze proposed PowerShell commands for:
- Recognized command structure
- Intended behavior
- Compatibility
- Operational risk
- Alignment with user intent

### Retrieval-Augmented Generation

Use FAISS to retrieve relevant information from trusted
operating system documentation.

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

### Controlled Repair Execution

Selected low-risk operations may be performed only after:
- Independent verification
- Eligibility checks
- Explicit user approval
- Target and parameter validation

Administrator-level, dangerous, or uncertain actions
remain recommendation-only.

### Post-Repair Validation

After an approved repair, OSGuard checks whether the action
completed successfully and whether the original issue
was resolved.

## 4. System Architecture

The architecture consists of:

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

For detailed architecture and workflows, see:

- docs/ARCHITECTURE.md
- docs/IMPLEMENTATION_GUIDE.md

## 5. Technology Stack

| Component | Technology |
|---|---|
| Language | Python 3.12 |
| Frontend | Streamlit |
| Agent Orchestration | LangGraph |
| LLM Integration | LangChain + Groq |
| LLM Provider | Groq API |
| Vector Database | FAISS |
| Embeddings | Sentence Transformers |
| Data Validation | Pydantic |
| OS Diagnostics | Python, psutil, Windows APIs |
| Testing | pytest |
| Observability | LangSmith / LangFuse (optional) |

## 6. Installation

### Prerequisites

- Windows 11
- Python 3.12
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
py -3.12 -m venv .venv
```

### Install Dependencies

Install the project and its test dependencies from `pyproject.toml`:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

Dependencies for later milestones will be added to `pyproject.toml`.

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

The current Streamlit screen checks the configured Groq connection only. It
does not diagnose Windows problems or recommend system changes. Run it locally:

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

Open the local application:

http://localhost:8501

For an explicit one-off live provider smoke check:

```powershell
.\.venv\Scripts\python.exe test_groq.py
```

The automated pytest suite uses mocked model responses and does not call Groq.

The application is intended to run locally.
No deployment is required.

## 9. Example User Interactions

### Scenario 1: High CPU Usage

User:
"My Windows laptop is running slowly and CPU usage is high."

Expected workflow:
1. Supervisor routes the request.
2. Diagnostic Agent investigates process statistics.
3. RAG retrieves supporting documentation.
4. IEEE verification checks recommendations.
5. OSGuard presents findings and next steps.

### Scenario 2: Unsafe PowerShell Command

User:
"Check whether this command is safe for my intended task."

Expected workflow:
1. Command Verification Agent analyzes the command.
2. The system checks intended effects and risks.
3. Unsupported or unsafe execution is blocked.
4. The user receives an explanation.

### Scenario 3: Software Compatibility

User:
"An application fails because a required dependency is missing."

Expected workflow:
1. Compatibility Agent examines requirements.
2. Available system and package details are checked.
3. RAG retrieves supporting documentation.
4. The system recommends verified next steps.

### Scenario 4: User-Approved Repair

User:
"Can OSGuard fix this supported application-level issue?"

Expected workflow:
1. The diagnostic workflow identifies a possible fix.
2. IEEE verification evaluates the action.
3. The execution policy checks eligibility.
4. The user approves the specific action.
5. The restricted executor performs the operation.
6. The system validates and reports the result.

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

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Testing should cover:
- Agent routing
- Structured output validation
- RAG retrieval
- Diagnostic tools
- IEEE verification
- Unsafe-action rejection
- User approval
- Restricted repair execution
- Post-repair validation

See docs/PROGRESS.md for actual implementation status
and test results.

## 12. Development Roadmap

- [ ] Initialize project structure and Groq integration
- [ ] Implement Supervisor and shared LangGraph state
- [ ] Implement three specialist agents
- [ ] Add FAISS RAG
- [ ] Add read-only Windows diagnostic tools
- [ ] Implement IEEE verification
- [ ] Add controlled repair execution
- [ ] Implement post-repair validation
- [ ] Complete end-to-end testing
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
