"""Phase 4 graph coverage uses only local evidence and injected model functions."""

from osguard.graph import build_supervisor_graph
from osguard.schemas import (
    ActionProposalOutput,
    CommandVerificationFinding,
    CompatibilityFinding,
    IEEEAssessment,
    OSSubsystem,
    ProblemType,
    RequestIntent,
    SpecialistName,
    SpecialistResult,
    SupervisorClassification,
    SystemEnvironment,
    ToolExecutionResult,
    VerificationCheck,
    WorkflowError,
    RetrievedEvidence,
    RetrievalResult,
)
from osguard.state import make_initial_state
from osguard.verification.proposals import action_id_for


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


def _evidence_update():
    evidence = RetrievedEvidence(
        source_id=DOC_ID,
        title="Runtime requirements",
        source_url="https://learn.microsoft.com/runtime",
        os_version="Windows 11",
        passage=DOC_PASSAGE,
        metadata={"category": "software_dependencies"},
    )
    return {
        "retrieval_result": RetrievalResult(status="success", query="Runtime", evidence=[evidence]),
        "retrieved_evidence": [evidence],
        "available_environment": SystemEnvironment(
            source="read_only_tool", os_name="Windows 11", os_version="10.0.22631",
            os_build="22631", architecture="AMD64",
        ),
    }


def _classification(specialists=None):
    specialists = specialists or [SpecialistName.COMPATIBILITY]
    return SupervisorClassification(
        intent=RequestIntent.CHECK_COMPATIBILITY,
        problem_type=ProblemType.COMPATIBILITY,
        os_subsystems=[OSSubsystem.SOFTWARE_DEPENDENCIES],
        selected_specialists=specialists,
    )


def _finding():
    return CompatibilityFinding(
        component="Runtime",
        installed_version="1.0",
        required_version="2.0",
        installed_os="Windows 11",
        installed_architecture="AMD64",
        required_os="Windows 11",
        required_architecture="x64",
        result="incompatible",
        fact_status="user_reported",
        installed_version_source="user_reported",
        requirement_source="documentation",
        evidence_ids=["user_request_redacted", DOC_ID],
        documented_requirement_ids=[DOC_ID],
    )


def _candidate(operation="install_or_update_dependency"):
    return {
        "description": "Install or update Runtime to meet the documented requirement 2.0.",
        "intended_purpose": "Address the reported Runtime compatibility mismatch.",
        "target_subsystem": OSSubsystem.SOFTWARE_DEPENDENCIES,
        "operation": operation,
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


def _assessment(_state, action):
    check = lambda label: VerificationCheck(
        result="pass", rationale=f"Mocked {label} assessment.", evidence_ids=action.evidence_ids
    )
    return IEEEAssessment(
        intent=check("intent"), environment=check("environment"),
        evidence=check("evidence"), effect=check("effect"), risk="low",
    )


def _compatibility_node(_state):
    return {
        "compatibility_findings": [_finding()],
        "specialist_results": [SpecialistResult(
            specialist=SpecialistName.COMPATIBILITY,
            status="completed",
            message="Compatibility fixture completed.",
        )],
        "completed_specialists": [SpecialistName.COMPATIBILITY],
    }


def _graph(*, specialists=None, compatibility_node=_compatibility_node,
           evidence_node=None, proposer=None, assessor=_assessment, other_nodes=None):
    specialists = specialists or [SpecialistName.COMPATIBILITY]
    nodes = {SpecialistName.COMPATIBILITY: compatibility_node}
    nodes.update(other_nodes or {})
    return build_supervisor_graph(
        classifier=lambda _request: _classification(specialists),
        specialist_nodes=nodes,
        evidence_collection_node=evidence_node or (lambda _state: _evidence_update()),
        action_proposer=proposer or (lambda _state: ActionProposalOutput(actions=[_candidate()])),
        ieee_assessor=assessor,
    )


def test_supervisor_to_ieee_to_final_response_is_integrated():
    result = _graph().invoke(make_initial_state(REQUEST))

    assert result["workflow_status"] == "specialists_completed"
    assert result["action_proposal_result"].status == "proposed"
    assert len(result["proposed_corrective_actions"]) == 1
    assert len(result["ieee_verification_results"]) == 1
    assert result["ieee_verification_results"][0].overall == "supported"
    assert "1 supported" in result["final_response"].message
    assert "do not authorize execution" in result["final_response"].message
    assert result["repair_eligibility"].status == "not_evaluated"
    assert result["execution_result"].status == "not_started"


def test_graph_edges_require_proposal_and_ieee_before_final_response():
    graph = _graph()
    edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}

    assert ("aggregate_findings", "propose_corrective_actions") in edges
    assert ("propose_corrective_actions", "ieee_verification") in edges
    assert ("ieee_verification", "final_response") in edges
    assert ("aggregate_findings", "final_response") not in edges


def test_multiple_actions_and_partial_specialist_failure_preserve_results():
    def diagnostic_failure(_state):
        return {
            "specialist_results": [SpecialistResult(
                specialist=SpecialistName.DIAGNOSTIC, status="failed", message="fixture failed"
            )],
            "completed_specialists": [SpecialistName.DIAGNOSTIC],
            "errors": [WorkflowError(stage="diagnostic_agent", code="fixture_failure", message="fixture")],
        }

    def propose(_state):
        return ActionProposalOutput(actions=[_candidate(), _candidate("modify_registry")])

    result = _graph(
        specialists=[SpecialistName.DIAGNOSTIC, SpecialistName.COMPATIBILITY],
        proposer=propose,
        other_nodes={SpecialistName.DIAGNOSTIC: diagnostic_failure},
    ).invoke(make_initial_state(REQUEST))

    assert result["workflow_status"] == "partial_failure"
    assert len(result["specialist_results"]) == 2
    assert len(result["ieee_verification_results"]) == 2
    statuses = {item.overall for item in result["ieee_verification_results"]}
    assert statuses == {"supported", "unsupported"}
    assert "successful results were retained" in result["final_response"].message


def test_missing_faiss_and_read_only_tool_failure_produce_no_action_and_no_fake_evidence():
    proposer_calls = []
    missing = {
        "retrieval_result": RetrievalResult(status="index_missing", query="Runtime"),
        "retrieved_evidence": [],
        "tool_results": [ToolExecutionResult(
            tool_name="get_system_info", status="permission_denied", summary="Denied."
        )],
    }
    result = _graph(
        evidence_node=lambda _state: missing,
        proposer=lambda state: proposer_calls.append(state),
    ).invoke(make_initial_state(REQUEST))

    assert result["retrieval_result"].status == "index_missing"
    assert result["retrieved_evidence"] == []
    assert result["tool_results"][0].status == "permission_denied"
    assert result["action_proposal_result"].status == "no_action"
    assert result["proposed_corrective_actions"] == []
    assert result["ieee_verification_summary"].status == "no_actions"
    assert result["ieee_verification_results"] == []
    assert proposer_calls == []


def test_command_review_is_never_converted_into_a_proposed_or_executed_action():
    calls = []

    def command_node(_state):
        return {
            "command_verification_findings": [CommandVerificationFinding(
                command_text="Remove-Item C:\\Temp\\* -Recurse",
                user_intent="list files",
                intent_match="does_not_match",
                risk="high",
                should_execute=False,
            )],
            "specialist_results": [SpecialistResult(
                specialist=SpecialistName.COMMAND_VERIFICATION,
                status="completed", message="Static review only.",
            )],
            "completed_specialists": [SpecialistName.COMMAND_VERIFICATION],
        }

    classification = SupervisorClassification(
        intent=RequestIntent.VERIFY_COMMAND,
        problem_type=ProblemType.COMMAND_SAFETY,
        os_subsystems=[OSSubsystem.COMMAND_SAFETY],
        selected_specialists=[SpecialistName.COMMAND_VERIFICATION],
    )
    graph = build_supervisor_graph(
        classifier=lambda _request: classification,
        specialist_nodes={SpecialistName.COMMAND_VERIFICATION: command_node},
        evidence_collection_node=lambda _state: {},
        action_proposer=lambda state: calls.append(state),
        ieee_assessor=_assessment,
    )
    result = graph.invoke(make_initial_state("List files; is Remove-Item safe?"))

    assert result["command_verification_findings"][0].should_execute is False
    assert result["proposed_corrective_actions"] == []
    assert result["ieee_verification_results"] == []
    assert result["repair_eligibility"].status == "not_evaluated"
    assert result["execution_result"].status == "not_started"
    assert calls == []

