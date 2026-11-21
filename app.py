"""Local Streamlit interface for the OSGuard Supervisor and specialists."""

import streamlit as st

from osguard.config import ConfigurationError, load_settings
from osguard.groq_client import GroqProviderUnavailable, GroqRequestError, ask_groq


st.set_page_config(page_title="OSGuard AI")
st.title("OSGuard AI")
st.caption(
    "Describe a Windows issue for structured analysis. OSGuard may collect a "
    "small set of relevant read-only measurements and documentation. The only "
    "available repair clears an explicitly approved OSGuard demo-app cache."
)


@st.cache_resource(show_spinner=False)
def _get_supervisor_graph():
    """Cache one graph/model instance instead of creating clients per rerun."""
    from osguard.graph import build_supervisor_graph
    from langgraph.checkpoint.memory import InMemorySaver

    return build_supervisor_graph(checkpointer=InMemorySaver())


def _display_label(value):
    raw = getattr(value, "value", value)
    return str(raw).replace("_", " ").title()


def _render_supervisor_result(result):
    classification = result.get("classification")
    if classification is not None:
        st.subheader("Detected request")
        st.write(f"**Issue category:** {_display_label(classification.problem_type)}")
        st.write(f"**Request type:** {_display_label(classification.intent)}")
        subsystems = classification.os_subsystems or []
        st.write(
            "**OS subsystem(s):** "
            + (", ".join(_display_label(item) for item in subsystems) or "Unknown")
        )
        selected = result.get("selected_specialists", [])
        st.write(
            "**Selected specialists:** "
            + (", ".join(_display_label(item) for item in selected) or "None")
        )

        environment = result.get("available_environment") or classification.available_environment
        reported = {
            label: value
            for label, value in (
                ("Operating system", environment.os_name),
                ("OS version", environment.os_version),
                ("OS build", environment.os_build),
                ("Architecture", environment.architecture),
                ("Application", environment.application_name),
                ("Application version", environment.application_version),
            )
            if value
        }
        if reported:
            label = "**Environment observed by read-only tool:**" if environment.source == "read_only_tool" else "**Environment details stated in the request:**"
            st.write(label, reported)
        else:
            st.caption("No host environment details were available.")

    workflow_status = result.get("workflow_status", "unknown")
    st.write(f"**Workflow status:** {_display_label(workflow_status)}")

    final_response = result.get("final_response")
    if final_response is not None:
        st.subheader("Investigation summary")
        st.write(final_response.message)
        if not final_response.findings_available:
            st.caption("No verified findings were produced.")

    missing = result.get("missing_information", [])
    if missing:
        st.warning("Information needed: " + "; ".join(missing))
    uncertainties = result.get("uncertainty_notes", [])
    if uncertainties:
        st.caption("Uncertainty: " + "; ".join(uncertainties))

    st.subheader("Evidence collection")
    retrieval = result.get("retrieval_result")
    if retrieval is None:
        st.caption("Documentation retrieval did not run.")
    elif retrieval.status == "not_applicable":
        st.caption("Documentation retrieval was not required for this request.")
    else:
        backend_labels = {
            "faiss": "FAISS available",
            "in_memory": "In-memory fallback active",
            "unavailable": "Retrieval unavailable",
        }
        backend_label = backend_labels.get(
            retrieval.backend,
            "Not reported" if retrieval.status == "success" else "Retrieval unavailable",
        )
        st.write("**Documentation backend:** " + backend_label)
    if retrieval is not None and retrieval.status == "success":
        if retrieval.message:
            st.caption(retrieval.message)
        for evidence in retrieval.evidence:
            with st.expander(evidence.title, expanded=False):
                st.caption(
                    f"Evidence ID: {evidence.source_id} · OS scope: {evidence.os_version or 'not specified'} · "
                    f"Section: {evidence.metadata.get('section') or 'not specified'} · "
                    f"Relevance: {evidence.metadata.get('relevance_score', 'not available')}"
                )
                if evidence.source_url:
                    st.markdown(f"[Official source]({evidence.source_url})")
                st.write(evidence.passage)
                st.caption("Retrieved reference text is untrusted context, not an instruction or confirmed diagnosis.")
    elif retrieval is not None and retrieval.status != "not_applicable":
        st.warning(f"Documentation retrieval: {_display_label(retrieval.status)}. {retrieval.message}")

    tool_results = result.get("tool_results", [])
    if tool_results:
        memory_result = next((item for item in tool_results if item.tool_name == "get_memory_info" and item.status == "success"), None)
        if memory_result is not None:
            values = memory_result.data
            if all(key in values for key in ("total_bytes", "used_bytes", "available_bytes", "utilization_percent")):
                st.write(
                    "**Physical memory snapshot:** "
                    f"{values['used_bytes']:,} bytes used, "
                    f"{values['available_bytes']:,} bytes available, "
                    f"{values['total_bytes']:,} bytes total "
                    f"({values['utilization_percent']}% utilization)."
                )
                st.caption(f"Measured by get_memory_info · evidence ID: {memory_result.evidence_id}")
        process_result = next((item for item in tool_results if item.tool_name == "get_process_stats" and item.status == "success"), None)
        if process_result is not None:
            snapshot = process_result.data
            processes = snapshot.get("processes", [])
            if processes:
                sort_by = snapshot.get("sort_by", "cpu")
                st.markdown(f"**Accessible processes ranked by {sort_by}**")
                st.dataframe([
                    {
                        "Process": row.get("name"),
                        "PID": row.get("pid"),
                        "Working set (bytes)": row.get("memory_bytes"),
                        "Working set (MiB)": row.get("memory_mib", row.get("memory_mb")),
                        "CPU (%)": row.get("cpu_percent"),
                    }
                    for row in processes
                ], hide_index=True, use_container_width=True)
                st.caption(snapshot.get("memory_metric_definition", "Process memory is a snapshot."))
                if snapshot.get("process_scan_cap_reached"):
                    st.warning(
                        f"Process scan stopped at its {snapshot.get('process_scan_limit')} process cap; "
                        "the table may omit larger processes."
                    )
                if sort_by == "cpu" and memory_result is not None and snapshot.get("top_memory_processes"):
                    st.markdown("**Accessible processes ranked by memory**")
                    st.dataframe([
                        {
                            "Process": row.get("name"),
                            "PID": row.get("pid"),
                            "Working set (bytes)": row.get("memory_bytes"),
                            "Working set (MiB)": row.get("memory_mib"),
                        }
                        for row in snapshot["top_memory_processes"]
                    ], hide_index=True, use_container_width=True)
        with st.expander("Raw read-only Windows checks", expanded=False):
            for tool_result in tool_results:
                st.markdown(f"**{_display_label(tool_result.tool_name)} — {_display_label(tool_result.status)}**")
                st.caption(tool_result.summary)
                if tool_result.status == "success":
                    st.write(tool_result.data)
                    st.caption(f"Measured data · evidence ID: {tool_result.evidence_id}")
                elif tool_result.error:
                    st.caption(f"Tool detail: {tool_result.error}")

    st.subheader("Specialist results")
    specialist_results = result.get("specialist_results", [])
    if not specialist_results:
        st.caption("No specialist analysis was run.")
    for specialist_result in specialist_results:
        st.markdown(
            f"**{_display_label(specialist_result.specialist)} — "
            f"{_display_label(specialist_result.status)}**"
        )
        (st.error if specialist_result.status == "failed" else st.info)(
            specialist_result.message
        )

    symptoms = result.get("diagnostic_symptoms", [])
    diagnostic_subsystems = result.get("diagnostic_subsystems", [])
    observations = result.get("diagnostic_observations", [])
    hypotheses = result.get("diagnostic_hypotheses", [])
    safe_steps = result.get("safe_diagnostic_steps", [])
    if symptoms or diagnostic_subsystems or observations or hypotheses or safe_steps:
        with st.expander("Diagnostic analysis", expanded=True):
            if symptoms:
                st.markdown("**Symptoms extracted from the request**")
                for symptom in symptoms:
                    st.write(f"• {symptom}")
            if diagnostic_subsystems:
                st.write(
                    "**Potentially affected subsystems:** "
                    + ", ".join(_display_label(item) for item in diagnostic_subsystems)
                )
            if observations:
                st.markdown("**Quoted observations**")
                for observation in observations:
                    st.write(observation.description)
                    st.caption(
                        f"Source: {_display_label(observation.source)} · "
                        f'Quote: “{observation.supporting_quote}”'
                    )
                    if observation.tool_name:
                        st.caption(f"Measured by {observation.tool_name}; evidence IDs: {', '.join(observation.evidence_ids)}")
            if hypotheses:
                st.markdown("**Hypotheses (unconfirmed)**")
                for hypothesis in hypotheses:
                    st.write(hypothesis.description)
                    st.caption(
                        f"Why uncertain: {hypothesis.uncertainty} · "
                        "This remains an unconfirmed explanation."
                    )
                    for quote in hypothesis.supporting_quotes:
                        st.caption(f'Supporting excerpt: “{quote}”')
                    if hypothesis.supporting_evidence_ids:
                        st.caption("Evidence IDs: " + ", ".join(hypothesis.supporting_evidence_ids))
            if safe_steps:
                st.markdown("**Safe information-gathering steps (not performed)**")
                for step in safe_steps:
                    st.write(f"• {step}")

    command_findings = result.get("command_verification_findings", [])
    if command_findings:
        with st.expander("Command verification", expanded=True):
            st.caption(
                "LLM-assisted static review only; OSGuard does not parse through a "
                "PowerShell runtime or execute submitted commands."
            )
            for finding in command_findings:
                st.code(finding.command_text, language="powershell")
                st.write(f"**Risk:** {_display_label(finding.risk)}")
                st.write(f"**Intent match:** {_display_label(finding.intent_match)}")
                st.write(f"**Administrator requirement:** {_display_label(finding.requires_admin)}")
                st.write(f"**Recognized parts:** {', '.join(finding.recognized_parts) or 'None'}")
                if finding.unknown_parts:
                    st.warning("Unknown parts: " + ", ".join(finding.unknown_parts))
                if finding.potential_effects:
                    st.write("**Potential effects:** " + "; ".join(finding.potential_effects))
                if finding.explanation:
                    st.write(finding.explanation)
                if finding.evidence_ids:
                    st.caption("Documentation IDs: " + ", ".join(finding.evidence_ids))
                if not finding.verified:
                    st.caption("This command was not verified as safe.")

    compatibility_findings = result.get("compatibility_findings", [])
    if compatibility_findings:
        with st.expander("Compatibility analysis", expanded=True):
            for finding in compatibility_findings:
                st.markdown(f"**{finding.component} — {_display_label(finding.result)}**")
                st.caption("Reported facts, observed OS metadata, and documented requirements are kept separate.")
                if finding.installed_version:
                    st.write(f"**Installed version ({_display_label(finding.installed_version_source)}):** {finding.installed_version}")
                if finding.installed_os:
                    st.write(f"**Observed OS:** {finding.installed_os}")
                if finding.installed_architecture:
                    st.write(f"**Observed architecture:** {finding.installed_architecture}")
                if finding.required_version:
                    st.write(f"**Required version ({_display_label(finding.requirement_source)}):** {finding.required_version}")
                if finding.required_os:
                    st.write(f"**Required OS ({_display_label(finding.requirement_source)}):** {finding.required_os}")
                if finding.required_architecture:
                    st.write(f"**Required architecture ({_display_label(finding.requirement_source)}):** {finding.required_architecture}")
                st.caption(f"Fact status: {_display_label(finding.fact_status)}")
                if finding.documented_requirement_ids:
                    st.caption("Documented requirement source IDs: " + ", ".join(finding.documented_requirement_ids))
                if finding.hypothesis:
                    st.write(f"**Hypothesis:** {finding.hypothesis}")
                if finding.missing_information:
                    st.warning("Needed: " + "; ".join(finding.missing_information))

    proposal_status = result.get("action_proposal_result")
    proposed_actions = result.get("proposed_corrective_actions", [])
    ieee_results = result.get("ieee_verification_results", [])
    ieee_summary = result.get("ieee_verification_summary")
    st.subheader("Corrective recommendations — IEEE verification")
    st.caption(
        "Information-gathering steps are shown separately above. A supported "
        "recommendation is not permission to execute it. Only the predefined "
        "OSGuard demo cache operation can become eligible for approval."
    )
    if not proposed_actions:
        if proposal_status is not None:
            st.write(proposal_status.message)
        else:
            st.caption("No corrective-action proposal was generated.")
    verification_by_id = {item.action_id: item for item in ieee_results}
    evidence_by_id = {item.source_id: item for item in result.get("retrieved_evidence", [])}
    evidence_by_id.update({
        item.evidence_id: item
        for item in result.get("tool_results", [])
        if item.evidence_id
    })
    for action in proposed_actions:
        verification = verification_by_id.get(action.action_id)
        with st.expander(action.description, expanded=True):
            if verification is None:
                st.error("No IEEE result was recorded for this proposed action.")
                continue
            badge = {
                "supported": st.info,
                "unsupported": st.error,
                "uncertain": st.warning,
            }.get(verification.overall, st.warning)
            badge(f"Recommendation status: {_display_label(verification.overall)}")
            st.write(f"**Deterministic risk:** {_display_label(verification.risk)}")
            st.write(f"**Purpose:** {action.intended_purpose}")
            st.write(f"**Target subsystem:** {_display_label(action.target_subsystem)}")
            st.write(f"**Rationale:** {action.rationale}")
            if action.parameters:
                st.write("**Proposed parameters:**", action.parameters)
            if action.required_environment_conditions:
                st.write("**Required environment conditions:**")
                for condition in action.required_environment_conditions:
                    st.write(f"- {condition}")
            st.write("**Potential effects:** " + "; ".join(action.potential_effects))
            st.write("**Risks:** " + "; ".join(action.risks))
            st.write(
                "**Administrator requirement:** "
                + _display_label(action.requires_administrator)
            )
            st.markdown("**IEEE checks**")
            for name in ("intent", "environment", "evidence", "effect"):
                check = getattr(verification, name)
                st.write(
                    f"{_display_label(name)}: {_display_label(check.result)} — {check.rationale}"
                )
                if check.reason_codes:
                    st.caption("Reason codes: " + ", ".join(check.reason_codes))
                if check.missing_information:
                    st.warning("Missing: " + "; ".join(check.missing_information))
            if action.evidence_ids:
                st.markdown("**Supporting excerpts and sources**")
                for evidence_id in action.evidence_ids:
                    st.caption(f"Evidence ID: {evidence_id}")
                    quote = action.evidence_quotes.get(evidence_id)
                    if quote:
                        st.write(quote)
                    source = evidence_by_id.get(evidence_id)
                    if source is not None and getattr(source, "source_url", None):
                        st.markdown(f"[Source: {source.title}]({source.source_url})")
            if verification.reason_codes:
                st.warning("Verification reasons: " + ", ".join(verification.reason_codes))
            if verification.missing_information:
                st.warning("More information needed: " + "; ".join(verification.missing_information))
            st.caption(verification.explanation)
    if ieee_summary is not None:
        st.caption(f"IEEE workflow: {_display_label(ieee_summary.status)} — {ieee_summary.message}")

    eligibility = result.get("repair_eligibility")
    eligibility_results = result.get("repair_eligibility_results", [])
    plan = result.get("repair_plan")
    approval = result.get("approval_state")
    execution = result.get("execution_result")
    validation = result.get("validation_result")
    st.subheader("Controlled OSGuard demo repair")
    st.caption("The registered operation changes only the disposable OSGuard demo cache. No arbitrary Windows repair is available.")
    for decision in eligibility_results:
        st.write(f"**Action {decision.action_id}:** {_display_label(decision.status)}")
        if decision.message:
            st.caption(decision.message)
        if decision.reason_codes:
            st.caption("Eligibility reasons: " + ", ".join(decision.reason_codes))
    if plan is not None:
        st.write(f"**Workflow:** {_display_label(result.get('workflow_status', 'unknown'))}")
        st.write(f"**Exact action:** {plan.executable_action_id}")
        st.write(f"**Target:** {plan.target}")
        st.write("**Validated parameters:**", plan.parameters)
        st.write(f"**Reason and intended outcome:** {plan.intended_outcome}")
        st.write("**Expected effect:** " + "; ".join(plan.expected_effects))
        st.write("**Potential risk:** " + "; ".join(plan.potential_risks))
        st.write("**Preconditions:** " + "; ".join(plan.preconditions))
        st.write(f"**Post-repair validation:** {plan.validator_id}")
        st.caption(f"Plan ID: {plan.plan_id}; fingerprint: {plan.fingerprint}")
        if eligibility:
            st.write(f"**Eligibility:** {_display_label(eligibility.status)}")
        verification = verification_by_id.get(plan.action_id)
        if verification:
            st.write("**IEEE summary:** " + ", ".join(
                f"{name}={getattr(verification, name).result}"
                for name in ("intent", "environment", "evidence", "effect")
            ))
    if approval and approval.status != "not_requested":
        st.write(f"**Approval:** {_display_label(approval.status)}")
        if approval.reason_codes:
            st.warning("Approval reasons: " + ", ".join(approval.reason_codes))
    if execution and execution.status != "not_started":
        st.write(f"**Execution:** {_display_label(execution.status)}")
        if execution.details:
            st.caption(execution.details)
        if execution.reason_codes:
            st.warning("Execution reasons: " + ", ".join(execution.reason_codes))
    if validation and validation.status != "not_started":
        status_display = st.success if validation.status == "resolved" else st.warning
        status_display(f"Post-repair outcome: {_display_label(validation.status)}")
        st.write(validation.details)
        if validation.evidence:
            st.caption("Validation evidence: " + ", ".join(validation.evidence))
        if validation.reason_codes:
            st.caption("Validation reasons: " + ", ".join(validation.reason_codes))

    for error in result.get("errors", []):
        st.error(error.message)


def _store_graph_result(workflow, result, thread_id):
    """Keep the checkpoint cursor only while an exact plan is awaiting input."""
    if result.get("__interrupt__"):
        config = {"configurable": {"thread_id": thread_id}}
        st.session_state["osguard_supervisor_result"] = dict(workflow.get_state(config).values)
        st.session_state["osguard_pending_thread_id"] = thread_id
    else:
        st.session_state["osguard_supervisor_result"] = result
        st.session_state.pop("osguard_pending_thread_id", None)


def _render_approval_controls(result):
    """Only a pending, eligible, checkpointed plan receives decision buttons."""
    plan = result.get("repair_plan")
    eligibility = result.get("repair_eligibility")
    approval = result.get("approval_state")
    thread_id = st.session_state.get("osguard_pending_thread_id")
    if not (
        plan is not None and eligibility is not None and eligibility.status == "eligible"
        and approval is not None and approval.status == "pending"
        and thread_id and approval.plan_id == plan.plan_id
        and approval.fingerprint == plan.fingerprint
    ):
        return
    st.warning("This is a real change to the disposable OSGuard demo cache. Review the exact plan above before deciding.")
    decision = None
    if st.button("APPROVE", type="primary", key=f"approve_{plan.plan_id}"):
        decision = "approve"
    if st.button("DECLINE", key=f"decline_{plan.plan_id}"):
        decision = "decline"
    if decision is None:
        return
    from langgraph.types import Command

    # Consume the UI cursor before resuming; a rerun cannot submit it again.
    st.session_state.pop("osguard_pending_thread_id", None)
    payload = {
        "decision": decision,
        "plan_id": plan.plan_id,
        "fingerprint": plan.fingerprint,
    }
    try:
        workflow = _get_supervisor_graph()
        config = {"configurable": {"thread_id": thread_id}}
        with st.spinner("Resuming the exact approval decision and validating the result..."):
            resumed = workflow.invoke(Command(resume=payload), config=config)
        _store_graph_result(workflow, resumed, thread_id)
        st.rerun()
    except Exception as exc:
        st.error(f"The approval workflow stopped ({type(exc).__name__}). No automatic retry will occur.")


with st.expander("OSGuard disposable demo cache"):
    st.caption("Creates only OSGuard-owned disposable fixture data under this project's data/demo_app/cache directory. Use this to demonstrate the single approved repair.")
    if st.button("Prepare disposable demo cache"):
        from osguard.repair.demo_cache import DemoCacheStore

        inspection = DemoCacheStore().prepare_fixture()
        if inspection.status == "ready":
            st.success(inspection.message)
        else:
            st.error(inspection.message or inspection.reason_code)


with st.expander("Documentation knowledge base"):
    st.caption(
        "Initialize the allowlisted Microsoft documentation before analysis. "
        "On this device the in-memory fallback loads and embeds pages once per app process."
    )
    prepared = st.session_state.get("osguard_kb_initialization")
    ready = prepared is not None and prepared.backend in {"faiss", "in_memory"}
    if st.button("Initialize documentation", disabled=ready):
        from osguard.rag.retriever import search_documentation

        with st.spinner("Loading the documentation knowledge base..."):
            prepared = search_documentation("Windows troubleshooting", top_k=1)
        st.session_state["osguard_kb_initialization"] = prepared
    if prepared is not None:
        if ready or prepared.backend in {"faiss", "in_memory"}:
            label = "FAISS" if prepared.backend == "faiss" else "In-memory fallback"
            st.success(f"{label} knowledge base is ready for this app process.")
        else:
            st.warning(f"Documentation retrieval unavailable: {prepared.message}")


user_request = st.text_area(
    "Describe your Windows issue",
    placeholder=(
        "For example: My Windows PC has unusually high CPU usage, or paste a "
        "PowerShell command or application error."
    ),
    height=120,
)

if st.button("Analyze and route", type="primary"):
    if not user_request.strip():
        st.warning("Enter a short description of the Windows issue first.")
    else:
        st.session_state.pop("osguard_supervisor_result", None)
        st.session_state.pop("osguard_pending_thread_id", None)
        try:
            from uuid import uuid4
            from osguard.state import make_initial_state

            with st.spinner("Classifying the request, collecting relevant read-only evidence, and running selected specialists..."):
                workflow = _get_supervisor_graph()
                thread_id = uuid4().hex
                result = workflow.invoke(
                    make_initial_state(user_request),
                    config={"configurable": {"thread_id": thread_id}},
                )
            _store_graph_result(workflow, result, thread_id)
        except Exception as exc:
            if "Application Control policy has blocked this file" in str(exc):
                st.error(
                    "Windows Application Control blocked a required native dependency. "
                    "No system checks, commands, or repairs were run."
                )
            else:
                st.error(
                    "The Supervisor could not start or complete classification "
                    f"({type(exc).__name__}). No system actions were run."
                )

if "osguard_supervisor_result" in st.session_state:
    current_result = st.session_state["osguard_supervisor_result"]
    _render_supervisor_result(current_result)
    _render_approval_controls(current_result)

with st.expander("Groq connection check"):
    st.caption("Sends a fixed test prompt to Groq; it does not inspect Windows.")
    if st.button("Check Groq connection"):
        try:
            settings = load_settings()
        except ConfigurationError as exc:
            st.error(str(exc))
        else:
            with st.spinner(f"Contacting Groq with model {settings.model}..."):
                try:
                    answer = ask_groq(
                        "Reply with exactly: OSGuard Groq connection is working.",
                        settings=settings,
                    )
                except (GroqProviderUnavailable, GroqRequestError) as exc:
                    st.error(str(exc))
                else:
                    st.success("Groq returned a response.")
                    st.write(answer)
