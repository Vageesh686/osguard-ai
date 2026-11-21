"""IEEE checks use reproducible evidence, injected assessments, and no live services."""

from copy import deepcopy

import pytest
from langchain_core.runnables import RunnableLambda

from osguard.schemas import (
    ActionProposalOutput,
    CompatibilityFinding,
    IEEEAssessment,
    OSSubsystem,
    ProblemType,
    ProposedCorrectiveAction,
    RequestIntent,
    RetrievedEvidence,
    SpecialistName,
    SupervisorClassification,
    SystemEnvironment,
    VerificationCheck,
)
from osguard.state import make_initial_state
from osguard.verification.ieee import create_ieee_verification_node
from osguard.verification.proposals import action_id_for, create_action_proposal_node
from osguard.verification.rules import verify_action


REQUEST = (
    "Please help me fix the Runtime mismatch. Installed Runtime version 1.0. "
    "Runtime 2.0 is required for Windows 11 x64; a per-user Runtime installation "
    "does not require administrator privileges."
)
DOC_ID = "runtime-requirements#runtime-0001"
DOC_PASSAGE = (
    "Runtime 2.0 is required for Windows 11 x64. A per-user Runtime installation "
    "does not require administrator privileges."
)


def _state(*, with_documentation=True, os_known=True):
    state = make_initial_state(REQUEST)
    state["classification"] = SupervisorClassification(
        intent=RequestIntent.CHECK_COMPATIBILITY,
        problem_type=ProblemType.COMPATIBILITY,
        os_subsystems=[OSSubsystem.SOFTWARE_DEPENDENCIES],
        selected_specialists=[SpecialistName.COMPATIBILITY],
    )
    state["selected_specialists"] = [SpecialistName.COMPATIBILITY]
    state["available_environment"] = (
        SystemEnvironment(
            source="read_only_tool", os_name="Windows 11", os_version="10.0.22631",
            os_build="22631", architecture="AMD64",
        )
        if os_known else SystemEnvironment()
    )
    state["compatibility_findings"] = [
        CompatibilityFinding(
            component="Runtime",
            installed_version="1.0",
            required_version="2.0",
            installed_os="Windows 11" if os_known else None,
            installed_architecture="AMD64" if os_known else None,
            required_os="Windows 11",
            required_architecture="x64",
            result="incompatible",
            fact_status="user_reported",
            installed_version_source="user_reported",
            requirement_source="documentation" if with_documentation else "not_established",
            evidence_ids=["user_request_redacted"] + ([DOC_ID] if with_documentation else []),
            documented_requirement_ids=[DOC_ID] if with_documentation else [],
        )
    ]
    state["retrieval_result"] = {
        "status": "success" if with_documentation else "index_missing",
        "query": "Runtime requirement",
        "evidence": [],
    }
    if with_documentation:
        evidence = RetrievedEvidence(
            source_id=DOC_ID,
            title="Runtime requirements",
            source_url="https://learn.microsoft.com/runtime",
            os_version="Windows 11",
            passage=DOC_PASSAGE,
            metadata={"category": "software_dependencies"},
        )
        state["retrieved_evidence"] = [evidence]
        state["retrieval_result"] = {
            "status": "success", "query": "Runtime requirement", "evidence": [evidence]
        }
    return state


def _candidate(**updates):
    values = {
        "description": "Install or update Runtime to meet the documented requirement 2.0.",
        "intended_purpose": "Address the reported Runtime compatibility mismatch.",
        "target_subsystem": OSSubsystem.SOFTWARE_DEPENDENCIES,
        "operation": "install_or_update_dependency",
        "parameters": {"component": "Runtime", "required_version": "2.0"},
        "rationale": (
            "The Compatibility Agent found the user-reported installed version 1.0 "
            "incompatible with the documented requirement 2.0."
        ),
        "evidence_ids": ["user_request_redacted", DOC_ID],
        "evidence_quotes": {
            "user_request_redacted": "Installed Runtime version 1.0.",
            DOC_ID: DOC_PASSAGE,
        },
        "required_environment_conditions": [
            "Windows 11 x64",
            "A per-user Runtime installation does not require administrator privileges.",
        ],
        "potential_effects": [
            "Changes installed software by installing or updating the named dependency.",
            "May affect applications that depend on the installed runtime or package.",
        ],
        "risks": [
            "The installer and privilege requirements vary by package and installation scope.",
            "A version change can affect other applications; OSGuard will not perform it.",
        ],
        "requires_administrator": "no",
        "reversible": False,
        "intent_evidence_quote": "Please help me fix the Runtime mismatch.",
    }
    values.update(updates)
    return ActionProposalOutput(actions=[values]).actions[0]


def _action(candidate=None):
    candidate = candidate or _candidate()
    return ProposedCorrectiveAction(
        **candidate.model_dump(),
        action_id=action_id_for(candidate),
        risk="low",  # deliberately false; the deterministic rule must replace it
    )


def _pass_assessment(state, action):
    evidence_ids = [item for item in action.evidence_ids if item]
    check = lambda label: VerificationCheck(
        result="pass", rationale=f"Structured assessment: {label} is supported.", evidence_ids=evidence_ids
    )
    return IEEEAssessment(
        intent=check("intent"),
        environment=check("environment"),
        evidence=check("evidence"),
        effect=check("effect"),
        risk="low",  # model risk is ignored
        explanation="Fixture assessment.",
    )


def test_aligned_documented_recommendation_passes_all_ieee_checks_but_stays_high_risk():
    state = _state()
    action = _action()

    result = verify_action(state, action, _pass_assessment(state, action))

    assert result.overall == "supported"
    assert [result.intent.result, result.environment.result, result.evidence.result, result.effect.result] == [
        "pass", "pass", "pass", "pass"
    ]
    assert result.risk == "high"
    assert result.action_id == action.action_id
    assert set(result.supporting_evidence_ids) == {"user_request_redacted", DOC_ID}
    assert "not execution authorization" in result.explanation
    assert state["repair_eligibility"].status == "not_evaluated"
    assert state["execution_result"].status == "not_started"


def test_action_contradicting_user_scope_fails_intent_even_if_model_says_pass():
    state = _state()
    state["user_request"] = "Only explain the Runtime mismatch; do not change anything."
    action = _action()

    result = verify_action(state, action, _pass_assessment(state, action))

    assert result.intent.result == "fail"
    assert "action_contradicts_user_scope" in result.reason_codes
    assert result.overall == "unsupported"


def test_missing_documentation_evidence_is_unknown_not_a_pass():
    state = _state(with_documentation=False)
    candidate = _candidate(
        evidence_ids=["user_request_redacted"],
        evidence_quotes={"user_request_redacted": "Installed Runtime version 1.0."},
        required_environment_conditions=["Windows 11 x64"],
        requires_administrator="unknown",
    )
    action = _action(candidate)

    result = verify_action(state, action, _pass_assessment(state, action))

    assert result.evidence.result == "unknown"
    assert "documented_requirement_missing" in result.evidence.reason_codes
    assert result.overall == "uncertain"


def test_fabricated_evidence_id_fails_closed():
    state = _state()
    candidate = _candidate(
        evidence_ids=["user_request_redacted", DOC_ID, "fake-source-123"],
        evidence_quotes={
            "user_request_redacted": "Installed Runtime version 1.0.",
            DOC_ID: DOC_PASSAGE,
            "fake-source-123": "Runtime 2.0 is officially required.",
        },
    )

    action = _action(candidate)
    assessment = _pass_assessment(state, action)
    assessment = assessment.model_copy(update={
        name: getattr(assessment, name).model_copy(update={"evidence_ids": ["user_request_redacted", DOC_ID]})
        for name in ("intent", "environment", "evidence", "effect")
    })
    result = verify_action(state, action, assessment)

    assert result.evidence.result == "fail"
    assert "invalid_evidence_id" in result.evidence.reason_codes
    assert result.overall == "unsupported"


def test_real_source_id_with_unrelated_passage_does_not_support_claim():
    state = _state()
    state["retrieved_evidence"] = [
        RetrievedEvidence(
            source_id=DOC_ID, title="Unrelated", source_url="https://learn.microsoft.com/other",
            passage="This page documents Windows display brightness and power plans.",
        )
    ]
    candidate = _candidate(
        evidence_quotes={
            "user_request_redacted": "Installed Runtime version 1.0.",
            DOC_ID: "This page documents Windows display brightness and power plans.",
        }
    )
    action = _action(candidate)

    result = verify_action(state, action, _pass_assessment(state, action))

    assert result.evidence.result == "fail"
    assert "documented_requirement_does_not_support_action" in result.evidence.reason_codes


def test_unknown_windows_version_keeps_environment_and_overall_uncertain():
    state = _state(os_known=False)
    action = _action()

    result = verify_action(state, action, _pass_assessment(state, action))

    assert result.environment.result == "unknown"
    assert "environment_prerequisite_unknown" in result.environment.reason_codes
    assert result.overall == "uncertain"


def test_documented_os_mismatch_fails_environment_check():
    state = _state()
    state["available_environment"] = SystemEnvironment(
        source="read_only_tool", os_name="Windows 10", os_version="10.0.19045",
        os_build="19045", architecture="AMD64",
    )
    action = _action()

    result = verify_action(state, action, _pass_assessment(state, action))

    assert result.environment.result == "fail"
    assert "os_requirement_mismatch" in result.environment.reason_codes
    assert result.overall == "unsupported"


def test_missing_prerequisite_and_privilege_details_remain_unknown():
    state = _state()
    candidate = _candidate(required_environment_conditions=[], requires_administrator="unknown")
    result = verify_action(state, _action(candidate), _pass_assessment(state, _action(candidate)))

    assert result.environment.result == "unknown"
    assert "environment_prerequisite_unknown" in result.environment.reason_codes
    assert result.missing_information


def test_administrator_required_action_is_a_recommendation_only_and_never_eligible():
    state = _state()
    doc = "Runtime 2.0 is required for Windows 11 x64. Installation requires administrator privileges."
    state["retrieved_evidence"] = [state["retrieved_evidence"][0].model_copy(update={"passage": doc})]
    candidate = _candidate(
        evidence_quotes={
            "user_request_redacted": "Installed Runtime version 1.0.",
            DOC_ID: doc,
        },
        required_environment_conditions=[
            "Windows 11 x64", "Installation requires administrator privileges."
        ],
        requires_administrator="yes",
    )
    action = _action(candidate)

    result = verify_action(state, action, _pass_assessment(state, action))

    assert result.overall == "supported"
    assert result.environment.result == "pass"
    assert result.risk == "high"
    assert state["repair_eligibility"].status == "not_evaluated"
    assert state["execution_result"].status == "not_started"


@pytest.mark.parametrize(
    ("operation", "expected_code"),
    [
        ("modify_registry", "registry_modification_prohibited"),
        ("delete_files", "arbitrary_file_deletion_prohibited"),
        ("modify_security_settings", "security_configuration_change_prohibited"),
        ("install_driver", "driver_installation_prohibited"),
        ("restart_service", "service_modification_prohibited"),
    ],
)
def test_prohibited_operations_fail_deterministically_even_when_llm_says_safe(operation, expected_code):
    state = _state()
    candidate = _candidate(operation=operation, target_subsystem=OSSubsystem.SYSTEM_CONFIGURATION)
    action = _action(candidate)

    result = verify_action(state, action, _pass_assessment(state, action))

    assert result.effect.result == "fail"
    assert expected_code in result.effect.reason_codes
    assert result.risk == "high"
    assert result.overall == "unsupported"


def test_unknown_command_operation_fails_closed_and_never_executes():
    state = _state()
    state["classification"] = state["classification"].model_copy(
        update={"intent": RequestIntent.VERIFY_COMMAND, "problem_type": ProblemType.COMMAND_SAFETY}
    )
    candidate = _candidate(operation="run_powershell")
    action = _action(candidate)

    result = verify_action(state, action, _pass_assessment(state, action))

    assert result.intent.result == "fail"
    assert result.effect.result == "fail"
    assert "command_execution_prohibited" in result.reason_codes
    assert state["execution_result"].status == "not_started"


def test_model_claiming_low_risk_cannot_override_deterministic_policy():
    state = _state()
    action = _action(_candidate(operation="modify_registry"))
    assessment = _pass_assessment(state, action).model_copy(update={"risk": "low"})

    result = verify_action(state, action, assessment)

    assert result.effect.result == "fail"
    assert result.risk == "high"
    assert result.overall == "unsupported"


def test_action_id_is_stable_unique_and_content_bound():
    first = _candidate()
    same = _candidate()
    changed = _candidate(parameters={"component": "Runtime", "required_version": "2.1"})

    assert action_id_for(first) == action_id_for(same)
    assert action_id_for(first) != action_id_for(changed)
    assert action_id_for(first).startswith("act-")


def test_modified_action_cannot_reuse_another_actions_id():
    state = _state()
    action = _action().model_copy(update={"description": "Install a different package."})

    result = verify_action(state, action, _pass_assessment(state, action))

    assert result.evidence.result == "fail"
    assert "action_id_mismatch" in result.evidence.reason_codes
    assert result.overall == "unsupported"


def test_proposal_node_uses_injected_proposer_and_caps_action_set():
    state = _state()
    calls = []

    def proposer(received):
        calls.append(received)
        return ActionProposalOutput(actions=[_candidate()])

    update = create_action_proposal_node(proposer=proposer)(state)

    assert calls == [state]
    assert update["action_proposal_result"].status == "proposed"
    assert len(update["proposed_corrective_actions"]) == 1
    assert update["proposed_corrective_actions"][0].risk == "high"


def test_default_proposer_uses_injected_model_structured_output_without_live_groq():
    class FixedModel:
        def __init__(self):
            self.schemas = []

        def with_structured_output(self, schema):
            self.schemas.append(schema)
            return RunnableLambda(lambda _prompt: ActionProposalOutput(actions=[_candidate()]))

    model = FixedModel()
    update = create_action_proposal_node(model_provider=lambda: model)(_state())

    assert model.schemas == [ActionProposalOutput]
    assert update["action_proposal_result"].status == "proposed"
    assert update["proposed_corrective_actions"][0].risk == "high"


def test_no_documentation_or_missing_dependency_skips_action_model():
    state = _state(with_documentation=False)
    calls = []
    update = create_action_proposal_node(proposer=lambda received: calls.append(received)) (state)

    assert update["action_proposal_result"].status == "no_action"
    assert update.get("proposed_corrective_actions", []) == []
    assert calls == []

    state = _state()
    state["compatibility_findings"] = [
        CompatibilityFinding(component="Runtime", result="unknown", missing_information=["Required version"])
    ]
    update = create_action_proposal_node(proposer=lambda received: calls.append(received))(state)
    assert update["action_proposal_result"].status == "no_action"
    assert calls == []


def test_command_safety_route_never_calls_corrective_action_proposer():
    state = _state()
    state["classification"] = state["classification"].model_copy(update={
        "intent": RequestIntent.VERIFY_COMMAND,
        "problem_type": ProblemType.COMMAND_SAFETY,
    })
    calls = []
    update = create_action_proposal_node(proposer=lambda received: calls.append(received))(state)

    assert update["action_proposal_result"].status == "no_action"
    assert update.get("proposed_corrective_actions", []) == []
    assert calls == []


def test_malformed_proposal_output_is_a_controlled_failure():
    state = _state()
    update = create_action_proposal_node(proposer=lambda _state: {"actions": [{"operation": "delete"}] })(state)

    assert update["action_proposal_result"].status == "failed"
    assert update["errors"][0].stage == "action_proposal"
    assert update["errors"][0].code == "invalid_llm_output"
    assert update.get("proposed_corrective_actions", []) == []


def test_malformed_ieee_model_output_leaves_checks_uncertain_and_one_result():
    state = _state()
    action = _action()
    state["proposed_corrective_actions"] = [action]

    node = create_ieee_verification_node(assessor=lambda *_args: {"intent": "pass"})
    update = node(state)

    assert len(update["ieee_verification_results"]) == 1
    result = update["ieee_verification_results"][0]
    assert result.action_id == action.action_id
    assert result.overall == "uncertain"
    assert update["ieee_verification_summary"].status == "partial_failure"
    assert update["errors"][0].code == "invalid_llm_output"


def test_default_ieee_assessor_uses_injected_model_structured_output_without_live_groq():
    class FixedModel:
        def __init__(self, assessment):
            self.assessment = assessment
            self.schemas = []

        def with_structured_output(self, schema):
            self.schemas.append(schema)
            return RunnableLambda(lambda _prompt: self.assessment)

    state = _state()
    action = _action()
    state["proposed_corrective_actions"] = [action]
    model = FixedModel(_pass_assessment(state, action))

    update = create_ieee_verification_node(model_provider=lambda: model)(state)

    assert model.schemas == [IEEEAssessment]
    assert update["ieee_verification_results"][0].overall == "supported"


def test_missing_action_has_explicit_no_action_ieee_status():
    update = create_ieee_verification_node(assessor=lambda *_args: pytest.fail("No action should be assessed"))(
        make_initial_state("My PC is slow.")
    )

    assert update["ieee_verification_results"] == []
    assert update["ieee_verification_summary"].status == "no_actions"


def test_multiple_actions_receive_exactly_one_result_and_unsupported_action_stays_unsupported():
    state = _state()
    supported = _action()
    unsafe = _action(_candidate(operation="modify_registry"))
    state["proposed_corrective_actions"] = [supported, unsafe, supported]

    update = create_ieee_verification_node(assessor=_pass_assessment)(state)

    results = update["ieee_verification_results"]
    assert len(results) == 2
    assert len({item.action_id for item in results}) == 2
    assert {item.action_id: item.overall for item in results} == {
        supported.action_id: "supported",
        unsafe.action_id: "unsupported",
    }


def test_assessment_with_fabricated_citation_is_rejected():
    state = _state()
    action = _action()

    def assessor(_state, _action):
        assessment = _pass_assessment(state, action)
        return assessment.model_copy(update={
            "evidence": assessment.evidence.model_copy(update={"evidence_ids": ["fake-doc"]})
        })

    result = create_ieee_verification_node(assessor=assessor)(
        {**state, "proposed_corrective_actions": [action]}
    )["ieee_verification_results"][0]

    assert result.evidence.result == "fail"
    assert "invalid_llm_evidence_reference" in result.reason_codes


def test_partial_evidence_failure_retains_valid_ieee_results():
    state = _state()
    supported = _action()
    unsafe = _action(_candidate(operation="delete_files"))
    state["proposed_corrective_actions"] = [supported, unsafe]

    update = create_ieee_verification_node(assessor=_pass_assessment)(state)

    assert len(update["ieee_verification_results"]) == 2
    assert update["ieee_verification_summary"].status == "completed"
    assert {item.overall for item in update["ieee_verification_results"]} == {"supported", "unsupported"}

