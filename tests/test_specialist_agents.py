"""Deterministic specialist tests; all model responses are local fixtures."""

import os
import subprocess

import pytest
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
    OSSubsystem,
    SpecialistName,
)
from osguard.state import make_initial_state


class FakeStructuredModel:
    """Runnable test double for a LangChain model's structured output path."""

    def __init__(self, result):
        self.result = result
        self.prompts = []
        self.schemas = []

    def with_structured_output(self, schema):
        self.schemas.append(schema)

        def respond(prompt):
            self.prompts.append(prompt.to_string())
            return self.result

        return RunnableLambda(respond)


def _agent_result(agent_factory, request, result, specialist):
    model = FakeStructuredModel(result)
    node = agent_factory(model_provider=lambda: model)
    update = node(make_initial_state(request))
    assert update["specialist_results"][0].specialist == specialist
    return update, model


def test_diagnostic_agent_reports_symptoms_grounded_facts_hypotheses_and_safe_steps():
    request = (
        "My Windows PC has high CPU usage after startup. "
        "The error says: service failed to start."
    )
    output = DiagnosticAgentOutput(
        reported_symptoms=["high CPU usage after startup"],
        potentially_affected_subsystems=[OSSubsystem.PROCESS_CPU],
        observations=[
            DiagnosticObservation(
                description="The user reported a service startup error.",
                source="user_report",
                supporting_quote="service failed to start",
            )
        ],
        hypotheses=[
            DiagnosticHypothesis(
                description="A startup service may be related to the reported CPU use.",
                supporting_quotes=["high CPU usage after startup"],
                uncertainty="The request contains no process measurements.",
            )
        ],
        missing_information=["Which process uses the CPU?"],
        safe_diagnostic_steps=["Open Task Manager and note the busiest process."],
    )

    update, _model = _agent_result(
        create_diagnostic_agent,
        request,
        output,
        SpecialistName.DIAGNOSTIC,
    )

    assert update["diagnostic_symptoms"] == ["high CPU usage after startup"]
    assert update["diagnostic_observations"][0].supporting_quote == "service failed to start"
    assert update["diagnostic_observations"][0].evidence_ids == ["user_request_redacted"]
    assert update["diagnostic_hypotheses"][0].supporting_quotes == [
        "high CPU usage after startup"
    ]
    assert update["missing_information"] == ["Which process uses the CPU?"]
    assert update["safe_diagnostic_steps"] == [
        "Open Task Manager and note the busiest process."
    ]


def test_diagnostic_agent_rejects_fabricated_quotes_and_system_changing_steps():
    request = "The app crashes after login."
    output = DiagnosticAgentOutput(
        reported_symptoms=["The disk is full"],
        observations=[
            DiagnosticObservation(
                description="A measured disk level was found.",
                source="user_report",
                supporting_quote="Disk usage is 99%",
            )
        ],
        hypotheses=[
            DiagnosticHypothesis(
                description="The graphics driver caused the crash.",
                supporting_quotes=["The graphics driver failed"],
                uncertainty="No supplied text supports this claim.",
            )
        ],
        safe_diagnostic_steps=[
            "Open the application and copy the error message.",
            "Restart the Windows service.",
        ],
    )

    update, _model = _agent_result(
        create_diagnostic_agent,
        request,
        output,
        SpecialistName.DIAGNOSTIC,
    )

    assert update["diagnostic_symptoms"] == []
    assert update["diagnostic_observations"] == []
    assert update["diagnostic_hypotheses"] == []
    assert update["safe_diagnostic_steps"] == [
        "Open the application and copy the error message."
    ]
    assert any("omitted" in item for item in update["uncertainty_notes"])


def test_diagnostic_agent_redacts_sensitive_request_before_model_call():
    request = r"My PC is slow; username: alice, log: C:\Users\alice\private.log"
    model = FakeStructuredModel(DiagnosticAgentOutput())
    node = create_diagnostic_agent(model_provider=lambda: model)

    node(make_initial_state(request))

    prompt = model.prompts[0]
    assert "alice" not in prompt
    assert "private.log" not in prompt
    assert "<REDACTED>" in prompt
    assert "<PATH>" in prompt


def test_command_agent_recognizes_read_only_command_and_never_executes(monkeypatch):
    request = "Get-Process -Name notepad"
    finding = CommandVerificationFinding(
        command_text=request,
        user_intent="Review the process query",
        intent_match="matches",
        recognized_parts=["-Name"],
        risk="low",
        requires_admin="no",
        verified=True,
    )
    output = CommandVerificationOutput(findings=[finding])

    def forbidden(*_args, **_kwargs):
        pytest.fail("Command verification must never launch a process or shell")

    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    update, _model = _agent_result(
        create_command_verification_agent,
        request,
        output,
        SpecialistName.COMMAND_VERIFICATION,
    )

    reviewed = update["command_verification_findings"][0]
    assert "get-process" in [part.casefold() for part in reviewed.recognized_parts]
    assert reviewed.risk == "low"
    assert reviewed.requires_admin == "no"
    assert reviewed.verified is True
    assert reviewed.should_execute is False


def test_command_agent_marks_unknown_command_unverified():
    request = "Invoke-UnknownWidget -Target node1"
    output = CommandVerificationOutput(
        findings=[
            CommandVerificationFinding(
                command_text=request,
                recognized_parts=["Invoke-UnknownWidget"],
                risk="low",
                requires_admin="no",
                verified=True,
            )
        ]
    )

    update, _model = _agent_result(
        create_command_verification_agent,
        request,
        output,
        SpecialistName.COMMAND_VERIFICATION,
    )

    reviewed = update["command_verification_findings"][0]
    assert "invoke-unknownwidget" in reviewed.unknown_parts
    assert reviewed.risk == "unknown"
    assert reviewed.requires_admin == "unknown"
    assert reviewed.verified is False
    assert reviewed.should_execute is False


def test_command_agent_flags_destructive_operation_even_if_model_calls_it_low_risk():
    request = r"Remove-Item C:\temp\cache -Recurse -Force"
    redacted_command = "Remove-Item <PATH>"
    output = CommandVerificationOutput(
        findings=[
            CommandVerificationFinding(
                command_text=redacted_command,
                risk="low",
                requires_admin="no",
                verified=True,
            )
        ]
    )

    update, _model = _agent_result(
        create_command_verification_agent,
        request,
        output,
        SpecialistName.COMMAND_VERIFICATION,
    )

    reviewed = update["command_verification_findings"][0]
    assert reviewed.risk == "high"
    assert reviewed.verified is False
    assert reviewed.should_execute is False
    assert any("modify or remove" in effect for effect in reviewed.potential_effects)


def test_command_agent_preserves_intent_mismatch_and_admin_requirement():
    request = "Get-Service"
    output = CommandVerificationOutput(
        findings=[
            CommandVerificationFinding(
                command_text=request,
                user_intent="Change a service configuration",
                intent_match="does_not_match",
                risk="low",
                requires_admin="yes",
                verified=True,
            )
        ]
    )

    update, _model = _agent_result(
        create_command_verification_agent,
        request,
        output,
        SpecialistName.COMMAND_VERIFICATION,
    )

    reviewed = update["command_verification_findings"][0]
    assert reviewed.intent_match == "does_not_match"
    assert reviewed.requires_admin == "yes"
    assert reviewed.verified is False
    assert reviewed.should_execute is False


def test_command_agent_requests_missing_command_without_calling_model():
    def forbidden_model_provider():
        pytest.fail("No command input should not call a model")

    node = create_command_verification_agent(model_provider=forbidden_model_provider)
    update = node(make_initial_state("Is this command safe?"))

    assert update.get("command_verification_findings", []) == []
    assert any("exact PowerShell command" in item for item in update["missing_information"])
    assert update["specialist_results"][0].status == "completed"


def test_compatibility_agent_compares_only_explicit_versions_and_constraint():
    request = "Installed Runtime is 2.1; the app requires Runtime >= 2.0."
    output = CompatibilityAgentOutput(
        findings=[
            CompatibilityFinding(
                component="Runtime",
                installed_version="2.1",
                required_version="2.0",
                result="incompatible",
            )
        ]
    )

    update, _model = _agent_result(
        create_compatibility_agent,
        request,
        output,
        SpecialistName.COMPATIBILITY,
    )

    finding = update["compatibility_findings"][0]
    assert finding.installed_version == "2.1"
    assert finding.required_version == "2.0"
    assert finding.result == "compatible"
    assert finding.fact_status == "user_reported"


def test_compatibility_agent_reports_explicit_version_mismatch():
    request = "Installed Runtime is 1.5; the app requires Runtime >= 2.0."
    output = CompatibilityAgentOutput(
        findings=[
            CompatibilityFinding(
                component="Runtime",
                installed_version="1.5",
                required_version="2.0",
                result="compatible",
            )
        ]
    )

    update, _model = _agent_result(
        create_compatibility_agent,
        request,
        output,
        SpecialistName.COMPATIBILITY,
    )

    finding = update["compatibility_findings"][0]
    assert finding.installed_version == "1.5"
    assert finding.required_version == "2.0"
    assert finding.result == "incompatible"


def test_compatibility_agent_reports_missing_dependency_and_unknown_requirement():
    request = "The installer says a runtime dependency is missing, but gives no version."
    output = CompatibilityAgentOutput(
        findings=[
            CompatibilityFinding(
                component="runtime dependency",
                required_version="9.9",
                required_os="Windows 11",
                result="compatible",
            )
        ]
    )

    update, _model = _agent_result(
        create_compatibility_agent,
        request,
        output,
        SpecialistName.COMPATIBILITY,
    )

    finding = update["compatibility_findings"][0]
    assert finding.installed_version is None
    assert finding.required_version is None
    assert finding.required_os is None
    assert finding.result == "unknown"
    assert finding.fact_status == "not_established"
    assert any("installed application/runtime version" in item for item in finding.missing_information)
    assert any("exact documented dependency" in item for item in finding.missing_information)


def test_compatibility_agent_requests_missing_os_and_architecture_context():
    request = "Installed Runtime is 2.1 and the app requires Runtime >= 2.0."
    output = CompatibilityAgentOutput(
        findings=[
            CompatibilityFinding(
                component="Runtime",
                installed_version="2.1",
                required_version="2.0",
                result="compatible",
            )
        ]
    )

    update, _model = _agent_result(
        create_compatibility_agent,
        request,
        output,
        SpecialistName.COMPATIBILITY,
    )

    finding = update["compatibility_findings"][0]
    assert finding.result == "compatible"
    assert any("Windows version/build" in item for item in finding.missing_information)
    assert any("system architecture" in item for item in finding.missing_information)


def test_compatibility_agent_rejects_unsupported_compatibility_claims():
    request = "MyApp crashes when I open it."
    output = CompatibilityAgentOutput(
        findings=[
            CompatibilityFinding(
                component="MyApp",
                installed_version="9.9",
                required_version="1.0",
                required_os="Windows 11",
                required_architecture="x64",
                result="compatible",
            )
        ]
    )

    update, _model = _agent_result(
        create_compatibility_agent,
        request,
        output,
        SpecialistName.COMPATIBILITY,
    )

    finding = update["compatibility_findings"][0]
    assert finding.installed_version is None
    assert finding.required_version is None
    assert finding.required_os is None
    assert finding.required_architecture is None
    assert finding.result == "unknown"
    assert finding.fact_status == "not_established"


def test_invalid_structured_response_is_a_controlled_specialist_failure():
    model = FakeStructuredModel({"unexpected": "extra fields are forbidden"})
    node = create_diagnostic_agent(model_provider=lambda: model)

    update = node(make_initial_state("My PC feels slow."))

    assert update["specialist_results"][0].status == "failed"
    assert update["errors"][0].code == "invalid_llm_output"
    assert update["completed_specialists"] == [SpecialistName.DIAGNOSTIC]

