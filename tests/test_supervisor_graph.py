"""Offline Supervisor and LangGraph integration tests for Phase 2."""

from langchain_core.runnables import RunnableLambda

from osguard.graph import build_supervisor_graph
from osguard.schemas import (
    CommandVerificationFinding,
    CommandVerificationOutput,
    CompatibilityAgentOutput,
    CompatibilityFinding,
    DiagnosticAgentOutput,
    DiagnosticHypothesis,
    DiagnosticObservation,
    OSSubsystem,
    ProblemType,
    RequestIntent,
    SpecialistName,
    SpecialistResult,
    SupervisorClassification,
    SystemEnvironment,
    WorkflowError,
)
from osguard.state import make_initial_state


SPECIALISTS = (
    SpecialistName.DIAGNOSTIC,
    SpecialistName.COMMAND_VERIFICATION,
    SpecialistName.COMPATIBILITY,
)
NO_EVIDENCE = lambda _state: {}


def _classification(selected, *, intent=RequestIntent.DIAGNOSE, problem=ProblemType.UNKNOWN):
    return SupervisorClassification(
        intent=intent,
        problem_type=problem,
        os_subsystems=[OSSubsystem.UNKNOWN],
        selected_specialists=selected,
    )


def _stub_nodes(calls, updates=None):
    updates = updates or {}
    nodes = {}
    for specialist in SPECIALISTS:
        def node(state, specialist=specialist):
            calls.append(specialist)
            configured = updates.get(specialist)
            if callable(configured):
                return configured(state)
            if configured is not None:
                return configured
            return {
                "specialist_results": [
                    SpecialistResult(
                        specialist=specialist,
                        status="completed",
                        message=f"{specialist.value} fixture output",
                    )
                ],
                "completed_specialists": [specialist],
            }

        nodes[specialist] = node
    return nodes


def _run_with_stubs(request, classification, *, updates=None, model_factory=None):
    calls = []
    graph = build_supervisor_graph(
        classifier=lambda _request: classification,
        model_factory=model_factory,
        specialist_nodes=_stub_nodes(calls, updates),
        evidence_collection_node=NO_EVIDENCE,
    )
    return graph.invoke(make_initial_state(request)), calls


def _specialist_names(result):
    return [item.value for item in result["selected_specialists"]]


def test_high_cpu_request_routes_to_diagnostic_agent_without_live_groq():
    classification = _classification(
        [SpecialistName.DIAGNOSTIC],
        intent=RequestIntent.DIAGNOSE,
        problem=ProblemType.PERFORMANCE,
    )

    def forbidden_model_factory(**_kwargs):
        raise AssertionError("Mocked graph tests must not create a Groq model")

    result, calls = _run_with_stubs(
        "My Windows PC has high CPU usage.",
        classification,
        model_factory=forbidden_model_factory,
    )

    assert _specialist_names(result) == ["diagnostic"]
    assert calls == [SpecialistName.DIAGNOSTIC]
    assert result["workflow_status"] == "specialists_completed"
    assert result["specialist_results"][0].status == "completed"


def test_powershell_safety_request_routes_to_command_verification_agent():
    classification = _classification(
        [SpecialistName.COMMAND_VERIFICATION],
        intent=RequestIntent.VERIFY_COMMAND,
        problem=ProblemType.COMMAND_SAFETY,
    )
    result, calls = _run_with_stubs("Is this PowerShell command safe?", classification)

    assert _specialist_names(result) == ["command_verification"]
    assert calls == [SpecialistName.COMMAND_VERIFICATION]
    assert result["workflow_status"] == "specialists_completed"


def test_missing_software_dependency_routes_to_compatibility_agent():
    classification = _classification(
        [SpecialistName.COMPATIBILITY],
        intent=RequestIntent.CHECK_COMPATIBILITY,
        problem=ProblemType.COMPATIBILITY,
    )
    result, calls = _run_with_stubs(
        "An application says a required runtime is missing.", classification
    )

    assert _specialist_names(result) == ["compatibility"]
    assert calls == [SpecialistName.COMPATIBILITY]
    assert result["workflow_status"] == "specialists_completed"


def test_crash_after_windows_update_routes_to_diagnostic_and_compatibility():
    classification = _classification(
        [SpecialistName.DIAGNOSTIC, SpecialistName.COMPATIBILITY],
        intent=RequestIntent.DIAGNOSE,
        problem=ProblemType.SOFTWARE_FAILURE,
    )

    result, calls = _run_with_stubs(
        "The application crashes after a Windows update.", classification
    )

    assert _specialist_names(result) == ["diagnostic", "compatibility"]
    assert calls == [SpecialistName.DIAGNOSTIC, SpecialistName.COMPATIBILITY]
    assert [item.specialist for item in result["specialist_results"]] == calls
    assert result["workflow_status"] == "specialists_completed"


def test_unclear_request_returns_missing_information_without_routing():
    classification = SupervisorClassification(
        intent=RequestIntent.UNCLEAR,
        problem_type=ProblemType.UNKNOWN,
        os_subsystems=[OSSubsystem.UNKNOWN],
        needs_clarification=True,
        clarification_question="What Windows issue are you seeing?",
        missing_information=["The main symptom"],
    )

    result, calls = _run_with_stubs("help", classification)

    assert result["selected_specialists"] == []
    assert result["missing_information"] == ["The main symptom"]
    assert result["workflow_status"] == "needs_clarification"
    assert "What Windows issue are you seeing?" in result["final_response"].message
    assert result["specialist_results"] == []
    assert calls == []


def test_environment_claims_not_stated_by_user_are_discarded():
    classification = _classification([SpecialistName.DIAGNOSTIC])
    classification = classification.model_copy(
        update={
            "available_environment": SystemEnvironment(
                source="read_only_tool",
                os_name="Windows",
                os_version="11",
                architecture="x64",
            )
        }
    )

    result, _calls = _run_with_stubs("My computer feels slow.", classification)

    assert result["available_environment"].source == "unknown"
    assert result["available_environment"].os_name is None
    assert result["available_environment"].os_version is None
    assert result["available_environment"].architecture is None


def test_invalid_supervisor_output_becomes_controlled_error():
    calls = []
    graph = build_supervisor_graph(
        classifier=lambda _request: {
            "intent": "not-a-supported-intent",
            "selected_specialists": [],
        },
        specialist_nodes=_stub_nodes(calls),
        evidence_collection_node=NO_EVIDENCE,
    )

    result = graph.invoke(make_initial_state("Windows is broken"))

    assert result["workflow_status"] == "classification_error"
    assert result["errors"][0].code == "invalid_llm_output"
    assert result["selected_specialists"] == []
    assert result["specialist_results"] == []
    assert result["final_response"].findings_available is False
    assert calls == []


def test_shared_state_aggregation_preserves_existing_and_new_findings():
    classification = _classification([SpecialistName.DIAGNOSTIC])
    existing = DiagnosticObservation(
        description="Previously retained user report",
        source="user_report",
        supporting_quote="prior observation",
        evidence_ids=["prior"],
    )
    added = DiagnosticObservation(
        description="Newly retained user report",
        source="user_report",
        supporting_quote="new observation",
        evidence_ids=["new"],
    )
    calls = []
    graph = build_supervisor_graph(
        classifier=lambda _request: classification,
        specialist_nodes=_stub_nodes(
            calls,
            {
                SpecialistName.DIAGNOSTIC: {
                    "diagnostic_observations": [added],
                    "specialist_results": [
                        SpecialistResult(
                            specialist=SpecialistName.DIAGNOSTIC,
                            status="completed",
                            message="fixture findings",
                        )
                    ],
                    "completed_specialists": [SpecialistName.DIAGNOSTIC],
                }
            },
        ),
        evidence_collection_node=NO_EVIDENCE,
    )
    initial = make_initial_state("A Windows issue")
    initial["diagnostic_observations"] = [existing]
    result = graph.invoke(initial)

    assert [item.description for item in result["diagnostic_observations"]] == [
        "Previously retained user report",
        "Newly retained user report",
    ]
    assert result["final_response"].findings_available is True


def test_partial_specialist_failure_retains_successful_findings():
    classification = _classification(
        [SpecialistName.DIAGNOSTIC, SpecialistName.COMPATIBILITY]
    )
    updates = {
        SpecialistName.DIAGNOSTIC: {
            "diagnostic_symptoms": ["user-reported crash"],
            "specialist_results": [
                SpecialistResult(
                    specialist=SpecialistName.DIAGNOSTIC,
                    status="completed",
                    message="diagnostic fixture completed",
                )
            ],
            "completed_specialists": [SpecialistName.DIAGNOSTIC],
        },
        SpecialistName.COMPATIBILITY: {
            "specialist_results": [
                SpecialistResult(
                    specialist=SpecialistName.COMPATIBILITY,
                    status="failed",
                    message="compatibility fixture failed",
                )
            ],
            "completed_specialists": [SpecialistName.COMPATIBILITY],
            "errors": [
                WorkflowError(
                    stage="compatibility_agent",
                    code="provider_unavailable",
                    message="Compatibility fixture failed.",
                )
            ],
        },
    }
    result, calls = _run_with_stubs("The app crashes.", classification, updates=updates)

    assert calls == [SpecialistName.DIAGNOSTIC, SpecialistName.COMPATIBILITY]
    assert result["workflow_status"] == "partial_failure"
    assert result["diagnostic_symptoms"] == ["user-reported crash"]
    assert [item.status for item in result["specialist_results"]] == [
        "completed",
        "failed",
    ]
    assert result["errors"][0].code == "provider_unavailable"
    assert result["final_response"].findings_available is True


def test_invalid_specialist_response_is_contained_and_other_agent_runs():
    from langchain_core.runnables import RunnableLambda

    class InvalidStructuredModel:
        def with_structured_output(self, _schema):
            return RunnableLambda(lambda _prompt: {"unexpected": "not in the schema"})

    classification = _classification(
        [SpecialistName.DIAGNOSTIC, SpecialistName.COMPATIBILITY]
    )
    compatibility_calls = []

    def compatibility_node(_state):
        compatibility_calls.append(True)
        return {
            "compatibility_findings": [],
            "specialist_results": [
                SpecialistResult(
                    specialist=SpecialistName.COMPATIBILITY,
                    status="completed",
                    message="compatibility fixture completed",
                )
            ],
            "completed_specialists": [SpecialistName.COMPATIBILITY],
        }

    graph = build_supervisor_graph(
        classifier=lambda _request: classification,
        model=InvalidStructuredModel(),
        specialist_nodes={SpecialistName.COMPATIBILITY: compatibility_node},
        evidence_collection_node=NO_EVIDENCE,
    )
    result = graph.invoke(make_initial_state("My computer has high CPU usage."))

    assert result["workflow_status"] == "partial_failure"
    assert result["errors"][0].code == "invalid_llm_output"
    assert [item.status for item in result["specialist_results"]] == [
        "failed",
        "completed",
    ]
    assert compatibility_calls == [True]


def test_supervisor_to_all_real_specialist_nodes_with_mocked_structured_model():
    responses = {
        DiagnosticAgentOutput: DiagnosticAgentOutput(
            reported_symptoms=["high CPU usage"],
            observations=[
                DiagnosticObservation(
                    description="The user reports high CPU usage.",
                    source="user_report",
                    supporting_quote="high CPU usage",
                )
            ],
            hypotheses=[
                DiagnosticHypothesis(
                    description="A background process may be contributing.",
                    supporting_quotes=["high CPU usage"],
                    uncertainty="No process measurements were supplied.",
                )
            ],
            safe_diagnostic_steps=["Open Task Manager and note the busiest process."],
        ),
        CommandVerificationOutput: CommandVerificationOutput(
            findings=[
                CommandVerificationFinding(
                    command_text="Get-Process",
                    intent_match="matches",
                    risk="low",
                    requires_admin="no",
                    verified=True,
                )
            ]
        ),
        CompatibilityAgentOutput: CompatibilityAgentOutput(
            findings=[
                CompatibilityFinding(
                    component="Runtime",
                    installed_version="2.1",
                    required_version="2.0",
                    result="compatible",
                )
            ]
        ),
    }

    class FakeStructuredModel:
        def __init__(self):
            self.schemas = []

        def with_structured_output(self, schema):
            self.schemas.append(schema)
            return RunnableLambda(lambda _prompt: responses[schema])

    model = FakeStructuredModel()
    classification = _classification(
        list(SPECIALISTS),
        intent=RequestIntent.DIAGNOSE,
        problem=ProblemType.SOFTWARE_FAILURE,
    )
    graph = build_supervisor_graph(
        classifier=lambda _request: classification,
        model=model,
        evidence_collection_node=NO_EVIDENCE,
    )
    request = (
        "My PC has high CPU usage. Get-Process. "
        "Installed Runtime is 2.1; the app requires Runtime >= 2.0."
    )

    result = graph.invoke(make_initial_state(request))

    assert model.schemas == [
        DiagnosticAgentOutput,
        CommandVerificationOutput,
        CompatibilityAgentOutput,
    ]
    assert result["workflow_status"] == "specialists_completed"
    assert result["diagnostic_symptoms"] == ["high CPU usage"]
    assert len(result["diagnostic_observations"]) == 1
    assert result["diagnostic_hypotheses"][0].description.startswith("A background")
    assert result["command_verification_findings"][0].should_execute is False
    assert result["compatibility_findings"][0].result == "compatible"
    assert len(result["specialist_results"]) == 3
    assert result["final_response"].findings_available is True
