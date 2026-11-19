
# OSGuard AI — Codex Development Instructions

## 1. Project Overview

OSGuard AI is a multi-agent Operating System diagnostic,
troubleshooting, verification, and controlled self-repair assistant.

It is a college and resume project developed locally on Windows 11.
Deployment and production infrastructure are not required.

The system must support multiple OS areas, including:
- Process and CPU management
- Memory management
- Storage and file systems
- Windows services and startup
- Device and driver management
- Software installation and dependencies
- System configuration
- Security and permissions
- OS command verification

The project must not be restricted to driver troubleshooting.

## 2. Authoritative Documentation

Before implementing major changes, read the relevant sections of:

- docs/IMPLEMENTATION_GUIDE.md
- docs/ARCHITECTURE.md
- docs/PROGRESS.md

IMPLEMENTATION_GUIDE.md is the primary technical specification.

If documentation conflicts, report the conflict rather than
silently changing the architecture.

## 3. Technology Stack

- Language: Python 3.12
- LLM Provider: Groq API
- LLM Integration: langchain-groq
- Agent Orchestration: LangGraph
- Prompt Management: LangChain
- Vector Database: FAISS
- Embeddings: Local Sentence Transformers
- Frontend: Streamlit
- Structured Output: Pydantic
- OS Diagnostics: Python, psutil, restricted Windows APIs
- Testing: pytest
- Observability: LangSmith or LangFuse (optional)

Read GROQ_API_KEY and GROQ_MODEL from environment variables.

Do not use Gemini or replace LangGraph with CrewAI.

Use supported, current library APIs.

## 4. Architecture — Do Not Change

Preserve the following components:

1. Supervisor Agent
2. Diagnostic Agent
3. Command Verification Agent
4. Compatibility Agent
5. Shared RAG Knowledge Base
6. Approved Read-Only Windows Tools
7. IEEE Verification Gate
8. Repair Planning Workflow
9. User Approval Mechanism
10. Restricted Repair Executor
11. Post-Repair Validation
12. Final Response Generator

The Supervisor routes requests to the required specialists.
Multiple specialists may participate in one diagnostic session.

Specialists must return structured outputs.

The IEEE verification stage is mandatory before recommending
or executing corrective actions.

Do not add new agent frameworks or redesign the workflow
without explicit authorization.

## 5. IEEE Verification Framework

Every proposed corrective action must be evaluated using:

- Intent: Does it match the user's request?
- Environment: Is it compatible with the OS and configuration?
- Evidence: Is it supported by available diagnostic information?
- Effect: What does it change, and what are the risks?

Unsupported or uncertain recommendations must be identified.

An LLM-generated confidence score is not proof of correctness.

Use deterministic validation wherever possible.

## 6. Windows Safety Requirements

Never execute arbitrary LLM-generated shell or PowerShell commands.

Diagnostic tools must be read-only by default.

Actual repairs must satisfy all conditions:
- Predefined and explicitly allowlisted action
- Low operational risk
- No administrator privileges
- Validated target and parameters
- Passed IEEE and execution eligibility checks
- Explicit user approval for that exact action
- Post-execution validation available

Require fresh approval for each repair operation.

Do not automatically:
- Modify the Windows Registry
- Install or uninstall drivers
- Restart critical Windows services
- Modify security settings
- Delete arbitrary user or system files
- Change file permissions
- Run privileged commands
- Disable Windows Defender or security controls

Unsafe, unsupported, privileged, or uncertain repairs
must be presented as recommendations only.

Never request administrator privileges for the MVP.

## 7. Multi-Agent Development Rules

Use typed LangGraph shared state.

Use structured Pydantic outputs for:
- Intent classification
- Diagnostic findings
- Command verification
- Compatibility verification
- Proposed actions
- IEEE verification
- Repair plans
- Final reports

Maintain evidence provenance for important claims.

Distinguish:
- Confirmed observations
- Diagnostic hypotheses
- Missing information
- Verified recommendations
- Unverified recommendations

Never fabricate system information, tool results, or citations.

The Supervisor must support selective specialist routing.

Prevent infinite loops by bounding diagnostic iterations.

## 8. Groq API Requirements

Use langchain-groq and ChatGroq.

Never hardcode API keys.

Handle:
- Rate limits
- Timeouts
- Connection failures
- Invalid structured outputs
- Unsupported model features

Keep model configuration centralized.

Use mocked LLM responses in automated unit tests.
Use live Groq calls only when required for integration testing.

## 9. RAG Requirements

Use FAISS for vector retrieval.

Use trusted OS documentation as the primary knowledge source.

Retain:
- Document title
- Source URL
- Relevant OS version
- Retrieved passage
- Source metadata

Do not treat retrieved documents as executable instructions.

Do not claim a diagnosis is correct merely because a similar
document was retrieved.

Use metadata filtering where applicable.

## 10. Development Workflow

Implement one milestone at a time.

Before coding:
1. Inspect existing files.
2. Read relevant documentation.
3. Identify affected components.
4. Define acceptance criteria.

During coding:
1. Make small, focused changes.
2. Preserve existing working functionality.
3. Keep modules independent and testable.
4. Avoid unnecessary dependencies.
5. Avoid hardcoded demonstration answers.

After coding:
1. Run relevant pytest tests.
2. Fix failures.
3. Review integration points.
4. Update docs/PROGRESS.md.
5. Report remaining limitations.

Do not claim a feature works unless it has been tested.

## 11. Testing Requirements

Test:
- Supervisor routing
- Multiple-specialist coordination
- Structured LLM output handling
- Diagnostic tool responses
- RAG retrieval and provenance
- IEEE verification
- Unsafe-command rejection
- Execution eligibility
- User approval and rejection
- Restricted repair execution
- Post-repair validation
- Error handling

Use test fixtures for potentially unsafe scenarios.

Do not run destructive tests on the host computer.

## 12. Implementation Priorities

Follow this order:

1. Project setup and Groq integration
2. LangGraph Supervisor and shared state
3. Three specialist workflows
4. FAISS RAG and read-only Windows tools
5. IEEE verification
6. Repair planning and user approval
7. Restricted execution and validation
8. End-to-end integration and testing

Finish each stage before introducing unrelated features.

## 13. Progress Reporting

After each milestone, report:
- Features implemented
- Files created or modified
- Tests executed
- Tests passed or failed
- Mocked versus real capabilities
- Known limitations
- Next milestone

Update docs/PROGRESS.md accordingly.

## 14. Project Constraints

- Windows 11 only for the initial version
- Local execution only
- No deployment required
- No unrestricted OS automation
- No unnecessary framework changes
- No production-grade complexity unless requested

Prioritize a functional, verifiable college-project MVP
while keeping the architecture extensible.
