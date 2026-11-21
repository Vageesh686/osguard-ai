"""Phase 5 approval and restricted demo repair in isolated disposable paths."""

import hashlib
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from osguard.graph import build_supervisor_graph
from osguard.repair.demo_cache import DEMO_PAYLOAD, DemoCacheStore
from osguard.repair.eligibility import evaluate_eligibility
from osguard.repair.executor import ExecutionLedger, execute_approved_repair
from osguard.repair.planning import fingerprint_for, plan_is_exact
from osguard.schemas import (
    ApprovalState, DemoCacheSnapshot, ExecutionValidationResult,
    DiagnosticObservation, IEEEVerificationSummary, OSSubsystem, ProblemType, RequestIntent,
    RetrievalResult, SpecialistName, SpecialistResult, SupervisorClassification,
    VerificationCheck,
)
from osguard.state import make_initial_state
from osguard.verification.proposals import action_id_for
from osguard.repair.validation import validate_demo_repair


REQUEST = "Clear the OSGuard demo cache."


@pytest.fixture
def demo_store(tmp_path):
    store = DemoCacheStore(tmp_path)
    prepared = store.prepare_fixture()
    assert prepared.status == "ready", prepared.model_dump()
    yield store


def _classification():
    return SupervisorClassification(
        intent=RequestIntent.DIAGNOSE,
        problem_type=ProblemType.STORAGE,
        os_subsystems=[OSSubsystem.UNKNOWN],
        selected_specialists=[SpecialistName.DIAGNOSTIC],
    )


def _diagnostic(_state):
    return {
        "specialist_results": [SpecialistResult(
            specialist=SpecialistName.DIAGNOSTIC, status="completed",
            message="The explicit demo request was retained; cache facts come from the read-only tool.",
        )],
        "completed_specialists": [SpecialistName.DIAGNOSTIC],
    }


def _graph(store, *, ledger=None, evidence=None, diagnostic=None, checkpointer=None):
    return build_supervisor_graph(
        classifier=lambda _request: _classification(),
        specialist_nodes={SpecialistName.DIAGNOSTIC: diagnostic or _diagnostic},
        evidence_collection_node=evidence or (lambda _state: {
            "tool_results": [store.tool_result()],
            "retrieval_result": RetrievalResult(status="index_missing", query=REQUEST),
        }),
        repair_store=store,
        execution_ledger=ledger,
        checkpointer=checkpointer if checkpointer is not None else InMemorySaver(),
    )


def _pending(store, *, ledger=None):
    graph = _graph(store, ledger=ledger)
    config = {"configurable": {"thread_id": "phase5-test-thread"}}
    response = graph.invoke(make_initial_state(REQUEST), config=config)
    assert response.get("__interrupt__"), response
    state = graph.get_state(config).values
    return graph, config, state


def _resume(graph, config, state, decision="approve", **changes):
    plan = state["repair_plan"]
    payload = {"decision": decision, "plan_id": plan.plan_id, "fingerprint": plan.fingerprint}
    payload.update(changes)
    return graph.invoke(Command(resume=payload), config=config)


def test_real_demo_cache_repair_requires_interrupt_then_resolves(demo_store):
    sibling = demo_store.project_root / "unrelated.txt"
    sibling.write_text("untouched", encoding="utf-8")
    graph, config, state = _pending(demo_store)
    plan = state["repair_plan"]

    assert plan.executable_action_id == "CLEAR_OSGUARD_DEMO_CACHE"
    assert state["repair_eligibility"].status == "eligible"
    assert state["approval_state"].status == "pending"
    assert demo_store.payload.read_bytes() == DEMO_PAYLOAD

    result = _resume(graph, config, state)

    assert result["approval_state"].status == "approved"
    assert result["execution_result"].status == "succeeded", result["execution_result"].reason_codes
    assert result["validation_result"].status == "resolved"
    assert demo_store.payload.read_bytes() == b""
    assert sibling.read_text(encoding="utf-8") == "untouched"


def test_decline_preserves_cache(demo_store):
    graph, config, state = _pending(demo_store)
    result = _resume(graph, config, state, "decline")
    assert result["approval_state"].status == "declined"
    assert result["execution_result"].status == "not_started"
    assert demo_store.payload.read_bytes() == DEMO_PAYLOAD


def test_direct_fixture_handler_changes_only_known_payload(demo_store):
    before = demo_store.inspect()
    assert before.snapshot is not None
    after = demo_store.clear(before.snapshot)
    assert after.payload_size == 0


def test_plan_contains_exact_registered_target_and_fingerprint(demo_store):
    _, _, state = _pending(demo_store)
    plan = state["repair_plan"]
    action = state["proposed_corrective_actions"][0]
    assert plan.target == str(demo_store.cache_dir)
    assert plan.parameters == {"cache_id": "osguard_demo"}
    assert plan.requires_user_approval is True
    assert plan.validator_id == "demo_cache_empty_and_owned"
    assert plan.fingerprint == fingerprint_for(plan)
    assert plan_is_exact(plan, action, demo_store)


def test_plan_rejects_unknown_executable_identifier(demo_store):
    _, _, state = _pending(demo_store)
    plan = state["repair_plan"].model_copy(update={"executable_action_id": "UNKNOWN_REPAIR"})
    action = state["proposed_corrective_actions"][0]
    assert not plan_is_exact(plan, action, demo_store)
    changed = {**state, "repair_plan": plan, "approval_state": state["approval_state"].model_copy(update={"status": "approved"})}
    result = execute_approved_repair(changed, demo_store, ExecutionLedger())
    assert result.status == "blocked"
    assert result.reason_codes == ["unknown_action"]
    assert demo_store.payload.read_bytes() == DEMO_PAYLOAD


def test_unknown_or_unsupported_operations_remain_recommendation_only(demo_store):
    _, _, state = _pending(demo_store)
    original = state["proposed_corrective_actions"][0]
    verification = state["ieee_verification_results"][0]
    for operation in ("delete_files", "install_or_update_dependency", "invented_repair"):
        action = original.model_copy(update={"operation": operation})
        decision, _ = evaluate_eligibility(state, action, verification, demo_store)
        assert decision.status == "ineligible"
        assert decision.reason_codes == ["recommendation_only"]


def test_missing_ieee_or_failed_ieee_check_blocks_plan(demo_store):
    _, _, state = _pending(demo_store)
    action = state["proposed_corrective_actions"][0]
    verification = state["ieee_verification_results"][0]
    missing, _ = evaluate_eligibility(state, action, None, demo_store)
    assert missing.reason_codes == ["ieee_missing"]
    failed = verification.model_copy(update={"overall": "unsupported"})
    denied, _ = evaluate_eligibility(state, action, failed, demo_store)
    assert denied.reason_codes == ["ieee_not_supported"]
    check = VerificationCheck(result="fail", rationale="Fixture concern.")
    failed_check = verification.model_copy(update={"effect": check})
    denied, _ = evaluate_eligibility(state, action, failed_check, demo_store)
    assert denied.reason_codes == ["ieee_check_failed"]


def test_missing_or_changed_evidence_blocks_plan(demo_store):
    _, _, state = _pending(demo_store)
    action = state["proposed_corrective_actions"][0]
    verification = state["ieee_verification_results"][0]
    changed = {**state, "tool_results": []}
    denied, _ = evaluate_eligibility(changed, action, verification, demo_store)
    assert denied.status == "ineligible"
    assert denied.reason_codes == ["ieee_recheck_failed"]


@pytest.mark.parametrize("changes", [
    {"risk": "high"},
    {"requires_administrator": "yes"},
])
def test_high_risk_or_admin_action_is_ineligible(demo_store, changes):
    _, _, state = _pending(demo_store)
    action = state["proposed_corrective_actions"][0].model_copy(update=changes)
    action = action.model_copy(update={"action_id": action_id_for(action)})
    decision, _ = evaluate_eligibility(state, action, state["ieee_verification_results"][0], demo_store)
    assert decision.reason_codes == ["risk_or_privilege"]


def test_modified_action_parameters_and_target_are_ineligible(demo_store):
    _, _, state = _pending(demo_store)
    action = state["proposed_corrective_actions"][0]
    verification = state["ieee_verification_results"][0]
    changed_action = action.model_copy(update={"parameters": {"cache_id": "other"}})
    changed_action = changed_action.model_copy(update={"action_id": action_id_for(changed_action)})
    decision, _ = evaluate_eligibility(state, changed_action, verification, demo_store)
    assert decision.reason_codes == ["invalid_parameters"]
    changed_plan = state["repair_plan"].model_copy(update={"target": str(demo_store.cache_dir / ".." / "other")})
    decision, _ = evaluate_eligibility(state, action, verification, demo_store, changed_plan)
    assert decision.reason_codes == ["plan_modified"]


def test_model_safe_claim_cannot_authorize_file_deletion(demo_store):
    _, _, state = _pending(demo_store)
    action = state["proposed_corrective_actions"][0].model_copy(update={"operation": "delete_files", "risk": "low"})
    action = action.model_copy(update={"action_id": action_id_for(action)})
    fake_ieee = state["ieee_verification_results"][0].model_copy(update={"action_id": action.action_id, "overall": "supported", "risk": "low"})
    decision, _ = evaluate_eligibility(state, action, fake_ieee, demo_store)
    assert decision.reason_codes == ["recommendation_only"]


def test_missing_approval_and_missing_ieee_block_direct_executor(demo_store):
    _, _, state = _pending(demo_store)
    ledger = ExecutionLedger()
    no_approval = execute_approved_repair(state, demo_store, ledger)
    assert no_approval.status == "blocked"
    assert no_approval.reason_codes == ["approval_missing_or_mismatched"]
    approved = {**state, "approval_state": state["approval_state"].model_copy(update={"status": "approved"})}
    no_ieee = {**approved, "ieee_verification_results": []}
    result = execute_approved_repair(no_ieee, demo_store, ledger)
    assert result.status == "blocked"
    assert result.reason_codes == ["ieee_missing"]
    assert demo_store.payload.read_bytes() == DEMO_PAYLOAD


def test_approved_plan_mutation_and_path_traversal_block_executor(demo_store):
    _, _, state = _pending(demo_store)
    approved = {**state, "approval_state": state["approval_state"].model_copy(update={"status": "approved"})}
    for changes in (
        {"parameters": {"cache_id": "other"}},
        {"target": str(demo_store.cache_dir / ".." / "outside")},
    ):
        modified = {**approved, "repair_plan": state["repair_plan"].model_copy(update=changes)}
        result = execute_approved_repair(modified, demo_store, ExecutionLedger())
        assert result.status == "blocked"
        assert result.reason_codes == ["plan_modified"]
    assert demo_store.payload.read_bytes() == DEMO_PAYLOAD


@pytest.mark.parametrize("overrides", [
    {"plan_id": "plan-" + "0" * 32},
    {"fingerprint": "0" * 64},
    {"decision": "invalid"},
    {"fingerprint": ""},
])
def test_stale_or_invalid_approval_expires_without_execution(demo_store, overrides):
    graph, config, state = _pending(demo_store)
    result = _resume(graph, config, state, **overrides)
    assert result["approval_state"].status == "expired"
    assert result["execution_result"].status == "not_started"
    assert demo_store.payload.read_bytes() == DEMO_PAYLOAD


def test_missing_resume_fields_expire_approval(demo_store):
    graph, config, _ = _pending(demo_store)
    result = graph.invoke(Command(resume={"decision": "approve"}), config=config)
    assert result["approval_state"].status == "expired"
    assert result["execution_result"].status == "not_started"


def test_duplicate_executor_submission_never_repeats_repair(demo_store, monkeypatch):
    ledger = ExecutionLedger()
    calls = []
    original = demo_store.clear

    def counted(snapshot):
        calls.append(snapshot)
        return original(snapshot)

    monkeypatch.setattr(demo_store, "clear", counted)
    graph, config, state = _pending(demo_store, ledger=ledger)
    completed = _resume(graph, config, state)
    assert completed["validation_result"].status == "resolved"
    duplicate = execute_approved_repair(completed, demo_store, ledger)
    assert duplicate.status == "already_executed"
    assert duplicate.reason_codes == ["duplicate_plan_submission"]
    assert len(calls) == 1


def test_repeated_langgraph_resume_does_not_reexecute(demo_store, monkeypatch):
    calls = []
    original = demo_store.clear

    def counted(snapshot):
        calls.append(snapshot)
        return original(snapshot)

    monkeypatch.setattr(demo_store, "clear", counted)
    graph, config, state = _pending(demo_store)
    _resume(graph, config, state)
    # A completed checkpoint has no pending approval to replay.
    plan = state["repair_plan"]
    graph.invoke(Command(resume={
        "decision": "approve", "plan_id": plan.plan_id,
        "fingerprint": plan.fingerprint,
    }), config=config)
    assert len(calls) == 1


def test_permission_failure_is_recorded_and_not_retried(demo_store, monkeypatch):
    calls = []

    def denied(_snapshot):
        calls.append(1)
        raise PermissionError("Fixture-denied access")

    monkeypatch.setattr(demo_store, "clear", denied)
    ledger = ExecutionLedger()
    graph, config, state = _pending(demo_store, ledger=ledger)
    result = _resume(graph, config, state)
    assert result["execution_result"].status == "failed"
    assert result["validation_result"].status == "failed"
    assert demo_store.payload.read_bytes() == DEMO_PAYLOAD
    assert execute_approved_repair(result, demo_store, ledger).status == "already_executed"
    assert len(calls) == 1


def test_handler_refuses_mismatched_target_and_repeated_clear(demo_store):
    before = demo_store.inspect().snapshot
    assert before is not None
    unsafe = before.model_copy(update={"target": str(demo_store.project_root / "outside")})
    with pytest.raises(Exception, match="target"):
        demo_store.clear(unsafe)
    demo_store.clear(before)
    with pytest.raises(Exception, match="pre-state"):
        demo_store.clear(before)


def test_symlinked_cache_target_is_rejected(demo_store, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    demo_store.payload.unlink()
    demo_store.marker.unlink()
    demo_store.cache_dir.rmdir()
    try:
        demo_store.cache_dir.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Directory symlink unavailable: {exc}")
    inspection = demo_store.inspect()
    assert inspection.status == "unsafe"
    assert inspection.reason_code == "reparse_point"


def test_junction_guard_rejects_target_before_file_access(demo_store, monkeypatch):
    original = Path.is_junction
    monkeypatch.setattr(Path, "is_junction", lambda path: path == demo_store.cache_dir or original(path))
    inspection = demo_store.inspect()
    assert inspection.status == "unsafe"
    assert inspection.reason_code == "reparse_point"
    assert demo_store.payload.read_bytes() == DEMO_PAYLOAD


def test_symlink_guard_rejects_payload_before_file_access(demo_store, monkeypatch):
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == demo_store.payload or original(path))
    inspection = demo_store.inspect()
    assert inspection.status == "unsafe"
    assert inspection.reason_code == "reparse_point"
    assert demo_store.payload.read_bytes() == DEMO_PAYLOAD


def test_unknown_cache_entry_blocks_repair(demo_store):
    (demo_store.cache_dir / "unexpected.txt").write_text("not owned", encoding="utf-8")
    inspection = demo_store.inspect()
    assert inspection.status == "unsafe"
    assert inspection.reason_code == "unexpected_contents"


def test_action_changed_after_approval_blocks_executor(demo_store):
    _, _, state = _pending(demo_store)
    changed_action = state["proposed_corrective_actions"][0].model_copy(
        update={"parameters": {"cache_id": "other"}}
    )
    approved = {
        **state,
        "approval_state": state["approval_state"].model_copy(update={"status": "approved"}),
        "proposed_corrective_actions": [changed_action],
    }
    result = execute_approved_repair(approved, demo_store, ExecutionLedger())
    assert result.status == "blocked"
    assert demo_store.payload.read_bytes() == DEMO_PAYLOAD


def test_successful_handler_return_without_state_change_is_unresolved(demo_store, monkeypatch):
    before = demo_store.inspect().snapshot
    assert before is not None
    monkeypatch.setattr(demo_store, "clear", lambda _snapshot: before)
    graph, config, state = _pending(demo_store)
    result = _resume(graph, config, state)
    assert result["execution_result"].status == "succeeded"
    assert result["validation_result"].status == "unresolved"
    assert demo_store.payload.read_bytes() == DEMO_PAYLOAD


def test_missing_postrepair_measurement_is_unverifiable(demo_store):
    _, _, state = _pending(demo_store)
    execution = ExecutionValidationResult(
        status="succeeded", action_id=state["repair_plan"].action_id,
        plan_id=state["repair_plan"].plan_id,
        before_snapshot=state["repair_plan"].pre_state,
    )
    outcome = validate_demo_repair({**state, "execution_result": execution}, demo_store)
    assert outcome.status == "unverifiable"
    assert outcome.reason_codes == ["validation_evidence_missing"]


def test_malformed_agent_output_prevents_demo_action(demo_store):
    def failed_agent(_state):
        return {
            "specialist_results": [SpecialistResult(
                specialist=SpecialistName.DIAGNOSTIC, status="failed",
                message="Malformed fixture output was rejected.",
            )],
            "completed_specialists": [SpecialistName.DIAGNOSTIC],
        }

    graph = _graph(demo_store, diagnostic=failed_agent)
    result = graph.invoke(
        make_initial_state(REQUEST),
        config={"configurable": {"thread_id": "malformed-agent"}},
    )
    assert result["proposed_corrective_actions"] == []
    assert result["repair_plan"] is None
    assert result["execution_result"].status == "not_started"
    assert demo_store.payload.read_bytes() == DEMO_PAYLOAD


def test_normal_diagnostic_request_stays_recommendation_only(demo_store):
    graph = _graph(demo_store)
    result = graph.invoke(
        make_initial_state("Please explain why caches can be full."),
        config={"configurable": {"thread_id": "explanation-only"}},
    )
    assert result["proposed_corrective_actions"] == []
    assert result["repair_plan"] is None
    assert result["execution_result"].status == "not_started"


def test_exact_demo_request_works_with_default_local_route_without_groq_or_faiss(demo_store):
    graph = build_supervisor_graph(
        repair_store=demo_store,
        checkpointer=InMemorySaver(),
        retriever=lambda _query: pytest.fail("FAISS must not run for the fixed local demo"),
        windows_tools={"get_disk_info": lambda: pytest.fail("Host disk inspection must not run")},
    )
    config = {"configurable": {"thread_id": "local-demo"}}
    paused = graph.invoke(make_initial_state(REQUEST), config=config)
    assert paused.get("__interrupt__")
    state = graph.get_state(config).values
    assert state["retrieval_result"].status == "not_applicable"
    assert [item.tool_name for item in state["tool_results"]] == ["inspect_osguard_demo_cache"]
    finished = _resume(graph, config, state)
    assert finished["validation_result"].status == "resolved"


def test_diagnostic_observation_survives_approval_and_validation(demo_store):
    def with_observation(state):
        result = _diagnostic(state)
        result["diagnostic_observations"] = [DiagnosticObservation(
            description="The user requested clearing the OSGuard demo cache.",
            source="user_report", supporting_quote=REQUEST,
        )]
        return result

    graph = _graph(demo_store, diagnostic=with_observation)
    config = {"configurable": {"thread_id": "preserve-findings"}}
    graph.invoke(make_initial_state(REQUEST), config=config)
    paused = graph.get_state(config).values
    finished = _resume(graph, config, paused)
    assert finished["validation_result"].status == "resolved"
    assert finished["diagnostic_observations"] == paused["diagnostic_observations"]
    assert finished["tool_results"] == paused["tool_results"]


def test_cache_change_during_approval_expires_plan(demo_store):
    graph, config, state = _pending(demo_store)
    demo_store.payload.write_bytes(b"")
    result = _resume(graph, config, state)
    assert result["approval_state"].status == "expired"
    assert result["execution_result"].status == "not_started"


def test_no_checkpoint_never_exposes_executable_approval_path(demo_store):
    graph = build_supervisor_graph(
        classifier=lambda _request: _classification(),
        specialist_nodes={SpecialistName.DIAGNOSTIC: _diagnostic},
        evidence_collection_node=lambda _state: {"tool_results": [demo_store.tool_result()]},
        repair_store=demo_store,
    )
    result = graph.invoke(make_initial_state(REQUEST))
    assert result["repair_eligibility"].status == "eligible"
    assert result["approval_state"].status == "not_requested"
    assert result["execution_result"].status == "not_started"
    assert demo_store.payload.read_bytes() == DEMO_PAYLOAD


def test_partial_other_specialist_failure_preserves_demo_evidence(demo_store):
    classification = _classification().model_copy(update={
        "selected_specialists": [SpecialistName.DIAGNOSTIC, SpecialistName.COMPATIBILITY]
    })

    def failed_compatibility(_state):
        return {
            "specialist_results": [SpecialistResult(
                specialist=SpecialistName.COMPATIBILITY, status="failed",
                message="Fixture compatibility output failed validation.",
            )],
            "completed_specialists": [SpecialistName.COMPATIBILITY],
        }

    graph = build_supervisor_graph(
        classifier=lambda _request: classification,
        specialist_nodes={
            SpecialistName.DIAGNOSTIC: _diagnostic,
            SpecialistName.COMPATIBILITY: failed_compatibility,
        },
        evidence_collection_node=lambda _state: {"tool_results": [demo_store.tool_result()]},
        repair_store=demo_store,
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "partial-specialist"}}
    paused = graph.invoke(make_initial_state(REQUEST), config=config)
    assert paused.get("__interrupt__")
    state = graph.get_state(config).values
    assert len(state["specialist_results"]) == 2
    assert state["repair_eligibility"].status == "eligible"
    finished = _resume(graph, config, state)
    assert len(finished["specialist_results"]) == 2
    assert finished["validation_result"].status == "resolved"
