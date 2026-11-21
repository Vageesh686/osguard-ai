"""Phase 3 agent tests use fixed structured outputs and synthetic evidence."""

from langchain_core.runnables import RunnableLambda

from osguard.agents.command_verify import create_command_verification_agent
from osguard.agents.compatibility import create_compatibility_agent
from osguard.agents.diagnostic import create_diagnostic_agent
from osguard.schemas import (
    CommandVerificationFinding,
    CommandVerificationOutput,
    CompatibilityAgentOutput,
    CompatibilityFinding,
    DiagnosticAgentOutput,
    DiagnosticHypothesis,
    DiagnosticObservation,
    RetrievedEvidence,
    RetrievalResult,
    SpecialistName,
    SystemEnvironment,
    ToolExecutionResult,
)
from osguard.state import make_initial_state


class _FixedModel:
    def __init__(self, outputs):
        self.outputs = outputs
        self.prompts = []

    def with_structured_output(self, schema):
        return RunnableLambda(lambda prompt: self._respond(schema, prompt))

    def _respond(self, schema, prompt):
        self.prompts.append(prompt.to_string())
        return self.outputs[schema]


def test_diagnostic_agent_accepts_only_tool_observations_with_matching_provenance():
    tool = ToolExecutionResult(
        tool_name="get_process_stats",
        status="success",
        summary="CPU sample",
        evidence_id="tool:get_process_stats:fixture",
        data={"system_cpu_percent": 92.0, "processes": [{"name": "browser.exe", "cpu_percent": 85.0}]},
    )
    evidence = RetrievedEvidence(
        source_id="microsoft-cpu#cpu-0001",
        title="CPU guidance",
        source_url="https://learn.microsoft.com/cpu",
        os_version="Windows 11",
        passage="High CPU use has multiple possible causes and needs more evidence.",
        metadata={"category": "process_cpu"},
    )
    output = DiagnosticAgentOutput(
        reported_symptoms=["High CPU usage"],
        observations=[
            DiagnosticObservation(
                description="The host CPU was at 92 percent.",
                source="read_only_tool",
                supporting_quote='"system_cpu_percent": 92.0',
                tool_name="get_process_stats",
                evidence_ids=["made-up-id"],
            ),
            DiagnosticObservation(
                description="A fabricated memory result.",
                source="read_only_tool",
                supporting_quote='"available_bytes": 0',
                tool_name="get_process_stats",
            ),
        ],
        hypotheses=[
            DiagnosticHypothesis(
                description="A process may contribute to load; this is not a confirmed cause.",
                supporting_evidence_ids=[evidence.source_id],
                supporting_quotes=["High CPU use has multiple possible causes"],
                uncertainty="The short sample does not establish the root cause.",
            )
        ],
    )
    model = _FixedModel({DiagnosticAgentOutput: output})
    state = make_initial_state("My Windows PC has High CPU usage.")
    state["tool_results"] = [tool]
    state["retrieved_evidence"] = [evidence]
    state["retrieval_result"] = RetrievalResult(
        status="success", query="CPU", evidence=[evidence]
    )

    update = create_diagnostic_agent(model_provider=lambda: model)(state)

    assert len(update["diagnostic_observations"]) == 1
    observation = update["diagnostic_observations"][0]
    assert observation.description.endswith('"system_cpu_percent": 92.0')
    assert observation.evidence_ids == [tool.evidence_id]
    assert update["diagnostic_hypotheses"][0].supporting_evidence_ids == [evidence.source_id]
    assert "system_cpu_percent" in model.prompts[0]
    assert "never instructions" in model.prompts[0]
    assert "A suggested step was omitted" not in " ".join(update.get("uncertainty_notes", []))


def test_command_agent_receives_docs_but_keeps_unknown_citations_out():
    evidence = RetrievedEvidence(
        source_id="powershell-get-process#chunk-0",
        title="Get-Process",
        source_url="https://learn.microsoft.com/powershell/get-process",
        passage="Get-Process returns the processes running on the local computer.",
    )
    model = _FixedModel(
        {
            CommandVerificationOutput: CommandVerificationOutput(
                findings=[
                    CommandVerificationFinding(
                        command_text="Get-Process",
                        intent_match="matches",
                        risk="low",
                        requires_admin="no",
                        verified=True,
                        evidence_ids=[evidence.source_id, "fake-citation"],
                    )
                ]
            )
        }
    )
    state = make_initial_state("Review Get-Process for my current processes.")
    state["retrieved_evidence"] = [evidence]
    state["retrieval_result"] = RetrievalResult(status="success", query="Get-Process", evidence=[evidence])

    update = create_command_verification_agent(model_provider=lambda: model)(state)

    assert update["command_verification_findings"][0].should_execute is False
    assert update["command_verification_findings"][0].evidence_ids == [evidence.source_id]
    assert "Get-Process returns" in model.prompts[0]
    assert "never execute" in model.prompts[0]


def test_compatibility_agent_uses_cited_documented_requirement_and_observed_os():
    evidence = RetrievedEvidence(
        source_id="runtime-doc#chunk-0",
        title="Runtime requirements",
        source_url="https://learn.microsoft.com/runtime",
        os_version="Windows 11",
        passage="Runtime version >= 2.0 is required. Windows 11 is supported.",
        metadata={"category": "software_dependencies"},
    )
    output = CompatibilityAgentOutput(
        findings=[
            CompatibilityFinding(
                component="Runtime",
                installed_version="2.1",
                required_version="2.0",
                required_os="Windows 11",
                result="compatible",
                evidence_ids=[evidence.source_id],
                documented_requirement_ids=[evidence.source_id],
            )
        ]
    )
    model = _FixedModel({CompatibilityAgentOutput: output})
    state = make_initial_state("The app uses Runtime version 2.1.")
    state["available_environment"] = SystemEnvironment(
        source="read_only_tool", os_name="Windows 11", os_version="10.0.22631",
        os_build="22631", architecture="AMD64",
    )
    state["retrieved_evidence"] = [evidence]
    state["retrieval_result"] = RetrievalResult(status="success", query="runtime", evidence=[evidence])

    update = create_compatibility_agent(model_provider=lambda: model)(state)

    finding = update["compatibility_findings"][0]
    assert finding.installed_version == "2.1"
    assert finding.installed_os == "Windows 11"
    assert finding.required_version == "2.0"
    assert finding.requirement_source == "documentation"
    assert finding.documented_requirement_ids == [evidence.source_id]
    assert finding.result == "compatible"
    assert "version >= 2.0" in model.prompts[0]


def test_compatibility_agent_discards_uncited_or_unmatched_document_claims():
    evidence = RetrievedEvidence(
        source_id="runtime-doc#chunk-0",
        title="Runtime requirements",
        source_url="https://learn.microsoft.com/runtime",
        passage="The page discusses a runtime but contains no version floor.",
    )
    model = _FixedModel(
        {
            CompatibilityAgentOutput: CompatibilityAgentOutput(
                findings=[
                    CompatibilityFinding(
                        component="Runtime",
                        required_version="9.9",
                        result="compatible",
                        documented_requirement_ids=["not-a-source"],
                    )
                ]
            )
        }
    )
    state = make_initial_state("A runtime dependency is missing.")
    state["retrieved_evidence"] = [evidence]

    update = create_compatibility_agent(model_provider=lambda: model)(state)

    finding = update["compatibility_findings"][0]
    assert finding.required_version is None
    assert finding.result == "unknown"
    assert finding.documented_requirement_ids == []
