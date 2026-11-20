"""Offline supervisor routing tests using injected structured classifications."""

from osguard.graph import build_supervisor_graph
from osguard.schemas import (
    OSSubsystem,
    ProblemType,
    RequestIntent,
    SpecialistName,
    SupervisorClassification,
    SystemEnvironment,
)
from osguard.state import make_initial_state


def _run_with_classification(request, classification):
    graph = build_supervisor_graph(classifier=lambda _request: classification)
    return graph.invoke(make_initial_state(request))


def _specialist_names(result):
    return [item.value for item in result["selected_specialists"]]


def test_high_cpu_request_routes_to_diagnostic_agent():
    classification = SupervisorClassification(
        intent=RequestIntent.DIAGNOSE,
        problem_type=ProblemType.PERFORMANCE,
        os_subsystems=[OSSubsystem.PROCESS_CPU],
        selected_specialists=[SpecialistName.DIAGNOSTIC],
    )

    result = _run_with_classification(
        "My Windows PC has high CPU usage.", classification
    )

    assert _specialist_names(result) == ["diagnostic"]
    assert result["workflow_status"] == "specialists_not_implemented"
    assert result["specialist_results"][0].status == "not_implemented"
    assert result["diagnostic_observations"] == []
    assert result["final_response"].findings_available is False


def test_powershell_safety_request_routes_to_command_verification():
    classification = SupervisorClassification(
        intent=RequestIntent.VERIFY_COMMAND,
        problem_type=ProblemType.COMMAND_SAFETY,
        os_subsystems=[OSSubsystem.COMMAND_SAFETY],
        selected_specialists=[SpecialistName.COMMAND_VERIFICATION],
    )

    result = _run_with_classification(
        "Is this PowerShell command safe?", classification
    )

    assert _specialist_names(result) == ["command_verification"]
    assert result["command_verification_findings"] == []
    assert "No command was parsed" in result["specialist_results"][0].message


def test_missing_software_dependency_routes_to_compatibility_agent():
    classification = SupervisorClassification(
        intent=RequestIntent.CHECK_COMPATIBILITY,
        problem_type=ProblemType.COMPATIBILITY,
        os_subsystems=[OSSubsystem.SOFTWARE_DEPENDENCIES],
        selected_specialists=[SpecialistName.COMPATIBILITY],
    )

    result = _run_with_classification(
        "An application says a required runtime is missing.", classification
    )

    assert _specialist_names(result) == ["compatibility"]
    assert result["compatibility_findings"] == []
    assert "No dependency requirements" in result["specialist_results"][0].message


def test_crash_after_windows_update_routes_to_diagnostic_and_compatibility():
    classification = SupervisorClassification(
        intent=RequestIntent.DIAGNOSE,
        problem_type=ProblemType.SOFTWARE_FAILURE,
        os_subsystems=[OSSubsystem.SOFTWARE_DEPENDENCIES, OSSubsystem.SYSTEM_CONFIGURATION],
        selected_specialists=[
            SpecialistName.DIAGNOSTIC,
            SpecialistName.COMPATIBILITY,
        ],
    )

    result = _run_with_classification(
        "The application crashes after a Windows update.", classification
    )

    assert _specialist_names(result) == ["diagnostic", "compatibility"]
    assert [item.specialist for item in result["specialist_results"]] == [
        SpecialistName.DIAGNOSTIC,
        SpecialistName.COMPATIBILITY,
    ]
    assert result["diagnostic_observations"] == []
    assert result["compatibility_findings"] == []


def test_unclear_request_returns_missing_information_without_routing():
    classification = SupervisorClassification(
        intent=RequestIntent.UNCLEAR,
        problem_type=ProblemType.UNKNOWN,
        os_subsystems=[OSSubsystem.UNKNOWN],
        needs_clarification=True,
        clarification_question="What Windows issue are you seeing?",
        missing_information=["The main symptom"],
    )

    result = _run_with_classification("help", classification)

    assert result["selected_specialists"] == []
    assert result["missing_information"] == ["The main symptom"]
    assert result["workflow_status"] == "needs_clarification"
    assert "What Windows issue are you seeing?" in result["final_response"].message
    assert result["specialist_results"] == []


def test_environment_claims_not_stated_by_user_are_discarded():
    classification = SupervisorClassification(
        intent=RequestIntent.DIAGNOSE,
        problem_type=ProblemType.PERFORMANCE,
        os_subsystems=[OSSubsystem.PROCESS_CPU],
        selected_specialists=[SpecialistName.DIAGNOSTIC],
        available_environment=SystemEnvironment(
            source="read_only_tool",
            os_name="Windows",
            os_version="11",
            architecture="x64",
        ),
    )

    result = _run_with_classification("My computer feels slow.", classification)

    assert result["available_environment"].source == "unknown"
    assert result["available_environment"].os_name is None
    assert result["available_environment"].os_version is None
    assert result["available_environment"].architecture is None


def test_invalid_llm_output_becomes_controlled_classification_error():
    graph = build_supervisor_graph(
        classifier=lambda _request: {
            "intent": "not-a-supported-intent",
            "selected_specialists": [],
        }
    )

    result = graph.invoke(make_initial_state("Windows is broken"))

    assert result["workflow_status"] == "classification_error"
    assert result["errors"][0].code == "invalid_llm_output"
    assert result["selected_specialists"] == []
    assert result["specialist_results"] == []
    assert result["final_response"].findings_available is False
