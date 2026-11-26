"""Presentation-only Streamlit views for the existing OSGuard graph."""

from __future__ import annotations

from collections import OrderedDict
import re

import streamlit as st


PAGES = ("Home", "Troubleshoot", "Results", "Knowledge Base", "Settings")
EXAMPLES = (
    ("Performance & Memory", "Why is my Windows PC using so much memory?"),
    ("Storage & Files", "Why is my Windows drive running out of space?"),
    ("Windows Services", "Is the Windows Search service running?"),
    ("Applications", "Why does my application keep crashing?"),
    ("Devices & Drivers", "Are there reported device or driver problems on this PC?"),
    ("Networking", "Why is my Wi-Fi connection not working?"),
)

CSS = """
<style>
  :root { color-scheme: dark; }
  .stApp, [data-testid="stAppViewContainer"] { background: #0B1120; color: #F8FAFC; }
  [data-testid="stSidebar"] { background: #111A2E; border-right: 1px solid #293850; }
  .stApp p, .stApp span, .stApp label, .stApp li,
  .stApp [data-testid="stMarkdownContainer"],
  [data-testid="stSidebar"] p, [data-testid="stSidebar"] span,
  [data-testid="stSidebar"] label { color: #FFFFFF !important; }
  .stApp [data-testid="stCaptionContainer"] *, .osg-muted { color: #E2E8F0 !important; }
  .stApp [data-testid="stButton"] button,
  .stApp .stButton button { background-color: #1E293B !important;
      color: #FFFFFF !important; border: 1px solid #64748B !important; }
  .stApp [data-testid="stButton"] button *, .stApp .stButton button * {
      color: #FFFFFF !important; }
  .stApp [data-testid="stButton"] button:hover,
  .stApp .stButton button:hover { background-color: #334155 !important; }
  .stApp [data-testid="stButton"] button:disabled,
  .stApp .stButton button:disabled { background-color: #1E293B !important;
      color: #CBD5E1 !important; }
  .stApp [data-testid="stAlert"], .stApp [data-baseweb="notification"] {
      background-color: #172238 !important; color: #FFFFFF !important; }
  .stApp [data-testid="stAlert"] > div,
  .stApp [data-baseweb="notification"] > div { background-color: #172238 !important; }
  .stApp [data-testid="stAlert"] *, .stApp [data-baseweb="notification"] * {
      color: #FFFFFF !important; }
  [data-testid="stHeader"] { background: transparent; }
  .block-container { max-width: 1220px; padding-top: 1.8rem; padding-bottom: 2.5rem; }
  h1, h2, h3 { color: #F8FAFC !important; letter-spacing: -.025em; }
  h1 { font-size: clamp(1.9rem, 3vw, 2.7rem) !important; }
  h2 { font-size: 1.4rem !important; }
  h3 { font-size: 1.1rem !important; }
  [data-testid="stVerticalBlockBorderWrapper"] > div {
      background: #172238; border: 1px solid #2D405B !important; border-radius: 15px !important;
  }
  [data-testid="stMetric"] { background: #172238; border: 1px solid #2D405B;
      border-radius: 14px; padding: 12px 14px; }
  [data-testid="stMetricValue"] { color: #F8FAFC; font-size: 1.5rem; }
  [data-testid="stMetricLabel"] { color: #FFFFFF; }
  [data-testid="stTextArea"] textarea { background: #111A2E; color: #F8FAFC;
      border: 1px solid #405270; border-radius: 11px; }
  [data-testid="stTextArea"] textarea::placeholder { color: #E2E8F0; opacity: 1; }
  .stButton > button { min-height: 2.6rem; border-radius: 10px; }
  .stApp [data-testid="stButton"] button[kind="primary"],
  .stApp .stButton button[kind="primary"] { background-color: #1D4ED8 !important;
      color: #FFFFFF !important; border: 0 !important; font-weight: 650; }
  .osg-kicker { color: #38BDF8; font-weight: 700; letter-spacing: .1em;
      text-transform: uppercase; font-size: .76rem; }
  .osg-brand { color: #F8FAFC; font-size: 1.35rem; font-weight: 800; }
  .osg-muted { color: #94A3B8; font-size: .9rem; }
  .osg-rule { border-top: 1px solid #2D405B; margin: 1.15rem 0; }
  @media (max-width: 700px) { .block-container { padding: 1rem .8rem 2rem; } }
</style>
"""


@st.cache_resource(show_spinner=False)
def _get_supervisor_graph():
    """Cache the graph, its Groq client, and approval checkpointer."""
    from langgraph.checkpoint.memory import InMemorySaver
    from osguard.graph import build_supervisor_graph

    return build_supervisor_graph(checkpointer=InMemorySaver())


def _label(value: object) -> str:
    return str(getattr(value, "value", value)).replace("_", " ").title()


def _unique(values) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _public(value: object) -> str:
    """Describe the restricted owned-cache operation accurately in reports."""
    text = str(value or "")
    text = re.sub(r"\bCLEAR_OSGUARD_DEMO_CACHE\b", "OSGuard Workspace Cleanup", text, flags=re.I)
    text = re.sub(r"\b(?:OSGuard[ -])?demo(?:[ -]app)?[ -]cache\b",
                  "OSGuard workspace files", text, flags=re.I)
    text = re.sub(r"\bdemo\b", "workspace", text, flags=re.I)
    text = re.sub(r"\bfixture\b", "temporary", text, flags=re.I)
    text = re.sub(r"\btool:[A-Za-z0-9_.:-]+\b", "Windows observation", text, flags=re.I)
    text = re.sub(r"\b(?:get|inspect|list|check)_[a-z][a-z0-9_]+\b",
                  "Windows check", text, flags=re.I)
    return text


def _plain_guidance(value: object) -> str | None:
    """Keep raw command syntax out of the short public report."""
    text = _public(value)
    command_markers = (
        "get-", "set-", "remove-", "start-", "stop-", "restart-", "invoke-",
        "powershell", "cmd.exe", "ipconfig", "netsh", "sfc /", "dism /",
        "reg.exe", "pnputil", "`",
    )
    return None if any(marker in text.casefold() for marker in command_markers) else text


def _bytes(value: object) -> str:
    try:
        number = float(value)
    except (ValueError, TypeError):
        return "Unavailable"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(number) < 1024 or unit == "TiB":
            return f"{number:,.0f} {unit}" if unit == "B" else f"{number:,.1f} {unit}"
        number /= 1024
    return "Unavailable"


def _tool(result: dict, name: str):
    return next((item for item in result.get("tool_results", [])
                 if item.tool_name == name and item.status == "success"), None)


def _status(result: dict) -> tuple[str, str]:
    classification = result.get("classification")
    if classification and classification.needs_clarification:
        return "More information needed", "warning"
    if result.get("workflow_status") == "awaiting_approval":
        return "Awaiting your decision", "warning"
    specialists = result.get("specialist_results", [])
    if result.get("errors") or any(item.status == "failed" for item in specialists):
        return ("Completed with limitations", "warning") if any(
            item.status == "completed" for item in specialists
        ) else ("Analysis incomplete", "error")
    if result.get("final_response") and specialists:
        return "Analysis complete", "success"
    return "Analysis incomplete", "warning"


def _finding(result: dict) -> str:
    status, _ = _status(result)
    if status == "Analysis incomplete":
        return "Analysis could not be completed. Please try again."
    classification = result.get("classification")
    if classification and classification.needs_clarification:
        return _public(classification.clarification_question or "Please describe the main symptom.")
    response = result.get("final_response")
    if response and response.findings_available:
        direct = response.message.split("Classified as", 1)[0].strip()
        if (direct and not direct.startswith("Reported problem:")
                and not re.fullmatch(r"(?:RAM|memory) (?:utilization|usage):\s*\d+(?:\.\d+)?%[.!?]?", direct, re.I)):
            return _public(direct)
    request = str(result.get("user_request") or "").casefold()
    processes = _tool(result, "get_process_stats")
    if processes and any(phrase in request for phrase in ("most ram", "most memory", "top process")):
        rows = processes.data.get("processes", [])
        if processes.data.get("sort_by") == "memory" and rows:
            top = rows[0]
            if top.get("name") and top.get("memory_mib") is not None:
                scope = "inspected" if processes.data.get("process_scan_cap_reached") else "accessible"
                return (f"Among {scope} processes, {top['name']} had the largest measured working set "
                        f"({top['memory_mib']:,.1f} MiB). This snapshot does not show total usage by application.")
    memory = _tool(result, "get_memory_info")
    if memory and memory.data.get("utilization_percent") is not None:
        available = memory.data.get("available_bytes")
        remaining = f", with {_bytes(available)} available" if available is not None else ""
        return (f"Windows reported {memory.data['utilization_percent']}% memory utilization{remaining}. "
                "This snapshot alone does not establish the cause or a memory trend.")
    commands = result.get("command_verification_findings", [])
    if commands:
        return (f"Submitted command review: {_label(commands[0].risk).lower()} risk; "
                f"intent match {_label(commands[0].intent_match).lower()}.")
    compatibility = result.get("compatibility_findings", [])
    if compatibility:
        item = compatibility[0]
        return f"{item.component}: {_label(item.result)} based on the available information."
    return "No confirmed system finding is available yet."


def _metric_cards(result: dict) -> None:
    cards: list[tuple[str, str]] = []
    memory = _tool(result, "get_memory_info")
    if memory:
        for key, title in (("total_bytes", "Total RAM"), ("used_bytes", "Used RAM"),
                           ("available_bytes", "Available RAM")):
            if memory.data.get(key) is not None:
                cards.append((title, _bytes(memory.data[key])))
        if memory.data.get("utilization_percent") is not None:
            cards.append(("Memory utilization", f"{memory.data['utilization_percent']}%"))
    processes = _tool(result, "get_process_stats")
    if processes and processes.data.get("system_cpu_percent") is not None:
        cards.append(("Current CPU utilization", f"{processes.data['system_cpu_percent']}%"))
    disk = _tool(result, "get_disk_info")
    if disk:
        for volume in disk.data.get("volumes", [])[:2]:
            cards.append((f"{volume.get('mountpoint') or 'Local volume'} available",
                          _bytes(volume.get("free_bytes"))))
    if cards:
        st.subheader("System observations")
        for offset in range(0, len(cards), 4):
            columns = st.columns(len(cards[offset:offset + 4]))
            for column, (title, value) in zip(columns, cards[offset:offset + 4]):
                with column:
                    st.metric(title, value)


TABLES = (
    ("get_process_stats", "Processes measured", "processes",
     (("name", "Process"), ("pid", "PID"), ("cpu_percent", "CPU (%)"), ("memory_mib", "Working set (MiB)"))),
    ("get_disk_info", "Local volumes", "volumes",
     (("mountpoint", "Volume"), ("filesystem", "File system"), ("used_percent", "Used (%)"), ("free_bytes", "Available (bytes)"))),
    ("get_service_status", "Service status", None,
     (("display_name", "Service"), ("status", "State"), ("start_type", "Startup"))),
    ("list_services", "Windows services", "services",
     (("display_name", "Service"), ("status", "State"), ("start_type", "Startup"))),
    ("inspect_problem_devices", "Devices reporting problems", "devices",
     (("name", "Device"), ("device_class", "Class"), ("status", "State"), ("problem_code", "Problem code"))),
    ("inspect_device_status", "Device status", "devices",
     (("name", "Device"), ("device_class", "Class"), ("status", "State"), ("problem_code", "Problem code"))),
    ("inspect_device_drivers", "Driver information", "drivers",
     (("name", "Device"), ("provider", "Provider"), ("driver_version", "Version"), ("driver_date", "Date"))),
    ("inspect_network_adapters", "Network adapters", "adapters",
     (("name", "Adapter"), ("status", "State"), ("speed_mbps", "Speed (Mbps)"))),
    ("get_network_configuration", "Network configuration", "interfaces",
     (("name", "Adapter"), ("ipv4", "IPv4"), ("default_gateway", "Gateway"))),
    ("inspect_dns_configuration", "DNS configuration", "interfaces",
     (("name", "Adapter"), ("dns_servers", "DNS servers"))),
    ("inspect_failed_updates", "Failed Windows updates", "updates",
     (("title", "Update"), ("installed_at", "Date"), ("status", "Result"), ("hresult", "Error code"))),
    ("get_windows_update_history", "Recent Windows updates", "updates",
     (("title", "Update"), ("installed_at", "Date"), ("status", "Result"), ("hresult", "Error code"))),
    ("inspect_installed_software", "Installed applications", "applications",
     (("name", "Application"), ("version", "Version"), ("publisher", "Publisher"))),
    ("inspect_application_process", "Application processes", "processes",
     (("name", "Process"), ("pid", "PID"), ("memory_mib", "Working set (MiB)"))),
    ("inspect_application_errors", "Application errors", "events",
     (("created_at", "Date"), ("provider", "Source"), ("message", "Details"))),
)


def _tables(result: dict) -> None:
    shown = False
    for name, title, key, fields in TABLES:
        item = _tool(result, name)
        if item is None:
            continue
        records = item.data.get(key, []) if key else [item.data]
        rows = [{label: ", ".join(map(str, row[field])) if isinstance(row.get(field), list)
                 else row.get(field) for field, label in fields if row.get(field) is not None}
                for row in records if isinstance(row, dict)]
        if not rows:
            continue
        if not shown and not any(_tool(result, tool) for tool in
                                 ("get_memory_info", "get_process_stats", "get_disk_info")):
            st.subheader("System observations")
        shown = True
        st.markdown(f"**{title}**")
        st.dataframe(rows, hide_index=True, use_container_width=True)
        if any(item.data.get(key) for key in ("display_truncated", "scan_cap_reached", "entries_skipped")):
            st.caption("Only the available portion of this inventory is shown.")


def _findings(result: dict, main_finding: str = "") -> None:
    observations = result.get("diagnostic_observations", [])
    measured = _unique([_public(item.description) for item in observations
                        if item.source == "read_only_tool" and _public(item.description) != main_finding])
    reported = _unique([_public(item.description) for item in observations
                        if item.source != "read_only_tool" and _public(item.description) != main_finding])
    if measured or reported:
        st.subheader("What we found")
        for line in measured[:6]:
            st.write("• " + line)
        for line in reported[:3]:
            st.write("• Reported: " + line)
    hypotheses = _unique([_public(item.description) for item in result.get("diagnostic_hypotheses", [])])
    if hypotheses:
        st.subheader("Possible explanations")
        st.caption("These possibilities are not confirmed causes.")
        for line in hypotheses[:4]:
            st.write("• " + line)
    commands = result.get("command_verification_findings", [])
    if commands:
        st.subheader("Command review")
        st.caption("Submitted commands were reviewed without running them.")
        for item in commands[:4]:
            st.write(f"Risk: {_label(item.risk)} · Intent match: {_label(item.intent_match)} · Administrator access: {_label(item.requires_admin)}")
            if not item.verified:
                st.caption("The submitted command has not been verified as safe to run.")
    compatibility = result.get("compatibility_findings", [])
    if compatibility:
        st.subheader("Compatibility review")
        for item in compatibility[:4]:
            st.write(f"{item.component}: {_label(item.result)}")
            if item.installed_version:
                st.caption(f"Installed version: {item.installed_version}")
            if item.required_version:
                st.caption(f"Required version: {item.required_version}")
    steps = _unique([line for item in result.get("safe_diagnostic_steps", [])
                     if (line := _plain_guidance(item)) is not None])
    actions = result.get("proposed_corrective_actions", [])
    decisions = {item.action_id: item for item in result.get("ieee_verification_results", [])}
    if steps or actions:
        st.subheader("Recommended next steps")
        for line in steps[:4]:
            st.write("• " + line)
        for item in actions[:4]:
            decision = decisions.get(item.action_id)
            st.write(f"• {_public(item.description)} — safety review: {_label(decision.overall) if decision else 'Not completed'}.")
            if decision is None or decision.overall != "supported":
                st.caption("More evidence or manual review is required. OSGuard has not performed this action.")
    missing = _unique([_public(item) for item in result.get("missing_information", [])])
    uncertain = _unique([_public(item) for item in result.get("uncertainty_notes", [])])
    if missing or uncertain:
        with st.expander("Information still needed", expanded=False):
            for line in _unique(missing + uncertain)[:6]:
                st.write("• " + line)


def _components(result: dict) -> None:
    tools = result.get("tool_results", [])
    specialists = result.get("specialist_results", [])
    retrieval = result.get("retrieval_result")
    safety = result.get("ieee_verification_summary")
    cards = (
        ("Windows System Analysis", "Authorized read-only Windows diagnostics.",
         "Completed" if any(item.status == "success" for item in tools) else "Unavailable" if tools else "Not needed"),
        ("AI Diagnostic Analysis", "Review of available observations and possible causes.",
         "Completed" if any(item.specialist == "diagnostic" and item.status == "completed" for item in specialists) else
         "Unavailable" if any(item.specialist == "diagnostic" for item in specialists) else "Not needed"),
        ("Microsoft Knowledge Base", "Trusted Microsoft guidance when needed.",
         "Completed" if retrieval and retrieval.status == "success" and retrieval.evidence else
         "Not needed" if retrieval is None or retrieval.status == "not_applicable" else "Unavailable"),
        ("Safety Verification", "Review of proposed corrective actions.",
         "Completed" if safety and safety.status == "completed" and result.get("ieee_verification_results") else
         "Not needed" if not result.get("proposed_corrective_actions") else "Not completed"),
    )
    st.subheader("How OSGuard Analyzed Your Issue")
    for offset in (0, 2):
        for column, (title, detail, state) in zip(st.columns(2), cards[offset:offset + 2]):
            with column:
                with st.container(border=True):
                    st.markdown(f"**{title}**")
                    st.caption(detail)
                    st.write(state)


def _sources(result: dict) -> None:
    retrieval = result.get("retrieval_result")
    evidence = retrieval.evidence if retrieval and retrieval.status == "success" else []
    st.subheader("Microsoft documentation")
    if not evidence:
        if retrieval is None or retrieval.status == "not_applicable":
            st.caption("Documentation was not needed for this analysis.")
        else:
            st.warning("Microsoft documentation is temporarily unavailable for this analysis.")
        return
    grouped: OrderedDict[str, list] = OrderedDict()
    for item in evidence:
        grouped.setdefault(item.source_url or item.source_id, []).append(item)
    for url, passages in grouped.items():
        with st.container(border=True):
            st.markdown(f"**{passages[0].title}**")
            if url.startswith("https://learn.microsoft.com/"):
                st.markdown(f"[Read on Microsoft Learn]({url})")
            st.caption(f"{len(passages)} supporting passage{'s' if len(passages) != 1 else ''}")
            sections = _unique([item.metadata.get("section", "") for item in passages])
            if sections:
                st.caption("Sections: " + ", ".join(sections[:4]))
            st.caption("Open the official source for the full guidance.")


def _store_graph_result(workflow, result: dict, thread_id: str) -> None:
    """Keep the checkpoint cursor only while the exact plan is interrupted."""
    if result.get("__interrupt__"):
        config = {"configurable": {"thread_id": thread_id}}
        st.session_state["osguard_supervisor_result"] = dict(workflow.get_state(config).values)
        st.session_state["osguard_pending_thread_id"] = thread_id
        st.session_state["osguard_workspace_status"] = "pending"
    else:
        st.session_state["osguard_supervisor_result"] = result
        st.session_state.pop("osguard_pending_thread_id", None)
        validation = result.get("validation_result")
        if validation and validation.status == "resolved":
            st.session_state["osguard_workspace_status"] = "completed"
        elif st.session_state.get("osguard_workspace_status") == "pending":
            try:
                from osguard.repair.demo_cache import DemoCacheStore

                st.session_state["osguard_workspace_status"] = DemoCacheStore().inspect().status
            except Exception:
                st.session_state["osguard_workspace_status"] = "failed"


def _render_approval_controls(result: dict) -> None:
    """Only an eligible checkpointed plan receives decision controls."""
    plan = result.get("repair_plan")
    eligibility = result.get("repair_eligibility")
    approval = result.get("approval_state")
    thread_id = st.session_state.get("osguard_pending_thread_id")
    if not (plan and eligibility and eligibility.status == "eligible"
            and approval and approval.status == "pending" and thread_id
            and approval.plan_id == plan.plan_id and approval.fingerprint == plan.fingerprint):
        return
    st.subheader("Approval Required")
    with st.container(border=True):
        st.markdown("**OSGuard Workspace Cleanup**")
        st.write("Remove temporary files created and owned by OSGuard within its application workspace.")
        st.write("Affected resource: one known OSGuard-owned cache entry in this app's workspace.")
        st.write(f"Current entry size: {_bytes(plan.pre_state.payload_size)}")
        st.write("What changes: the known cache entry is cleared; its ownership marker remains.")
        for risk in _unique([_public(value) for value in plan.potential_risks])[:3]:
            st.caption("Consideration: " + risk)
        st.caption("This does not repair Windows or clear other applications' caches.")
        left, right = st.columns(2)
        with left:
            approve = st.button("Approve", type="primary", key=f"approve_{plan.plan_id}")
        with right:
            decline = st.button("Decline", key=f"decline_{plan.plan_id}")
    decision = "approve" if approve else "decline" if decline else None
    if decision is None:
        return
    from langgraph.types import Command

    # Consume the cursor before resuming so a rerun cannot submit it again.
    st.session_state.pop("osguard_pending_thread_id", None)
    payload = {"decision": decision, "plan_id": plan.plan_id, "fingerprint": plan.fingerprint}
    try:
        workflow = _get_supervisor_graph()
        config = {"configurable": {"thread_id": thread_id}}
        with st.spinner("Recording your decision and checking the outcome..."):
            resumed = workflow.invoke(Command(resume=payload), config=config)
        _store_graph_result(workflow, resumed, thread_id)
        st.session_state.pop("osguard_approval_error", None)
        st.rerun()
    except Exception:
        st.session_state["osguard_approval_error"] = (
            "The approval workflow could not be completed. No automatic retry will occur."
        )
        st.error(st.session_state["osguard_approval_error"])


def _render_supervisor_result(result: dict) -> None:
    """Use the saved graph state; rendering never calls Groq or Windows tools."""
    status, severity = _status(result)
    classification = result.get("classification")
    st.title("Your analysis")
    {"success": st.success, "warning": st.warning, "error": st.error}[severity](status)
    st.caption("Issue category: " + (_label(classification.problem_type) if classification else "Not determined"))
    with st.container(border=True):
        st.markdown('<div class="osg-kicker">Main finding</div>', unsafe_allow_html=True)
        main_finding = _finding(result)
        st.markdown("### " + main_finding)
    response = result.get("final_response")
    if response and not response.findings_available:
        st.caption("No confirmed finding was produced from the available information.")
    if status == "Analysis incomplete":
        st.info("Revise the issue description and try again from Troubleshoot.")
    _metric_cards(result)
    _tables(result)
    _findings(result, main_finding)
    _components(result)
    _sources(result)
    approval = result.get("approval_state")
    validation = result.get("validation_result")
    if approval and approval.status == "declined":
        st.info("Workspace cleanup was declined. No change was made.")
    elif validation and validation.status == "resolved":
        st.success("OSGuard workspace cleanup completed and was confirmed by a fresh check.")
    elif validation and validation.status not in {"not_started", "resolved"}:
        st.warning("The workspace cleanup outcome could not be confirmed as complete.")
    _render_approval_controls(result)
    if st.session_state.get("osguard_approval_error"):
        st.error(st.session_state["osguard_approval_error"])
    if result.get("errors"):
        st.warning("Some parts of the analysis could not be completed. Available findings are shown above.")


def _run_analysis(request: str) -> None:
    if not request.strip():
        st.warning("Describe the Windows issue before starting an analysis.")
        return
    try:
        from uuid import uuid4
        from osguard.state import make_initial_state

        with st.spinner("Analyzing your issue with the available Windows information..."):
            workflow = _get_supervisor_graph()
            thread_id = uuid4().hex
            result = workflow.invoke(make_initial_state(request), config={"configurable": {"thread_id": thread_id}})
        _store_graph_result(workflow, result, thread_id)
        st.session_state.pop("osguard_analysis_error", None)
        st.session_state["osguard_draft"] = request
        st.session_state["osguard_next_page"] = "Results"
        st.rerun()
    except Exception as exc:
        st.session_state["osguard_analysis_error"] = (
            "Windows security controls blocked a required component. Analysis could not be completed."
            if "Application Control policy has blocked this file" in str(exc)
            else "Analysis could not be completed. Please try again."
        )
        st.error(st.session_state["osguard_analysis_error"])


def _input() -> None:
    st.subheader("What can we help you troubleshoot?")
    issue = st.text_area(
        "Describe your Windows issue",
        value=st.session_state.get("osguard_draft", ""),
        placeholder="Describe what's happening on your Windows PC...",
        height=125,
        key="osguard_issue_input",
        on_change=lambda: st.session_state.__setitem__(
            "osguard_draft", st.session_state["osguard_issue_input"]
        ),
    )
    if st.button("Analyze Issue", type="primary", use_container_width=True):
        _run_analysis(issue)


def _home() -> None:
    st.markdown('<div class="osg-kicker">OSGuard AI</div>', unsafe_allow_html=True)
    st.title("Intelligent Windows Troubleshooting")
    st.write("Understand Windows problems through AI-assisted diagnostics, real system information, and trusted Microsoft guidance.")
    _input()
    st.markdown('<div class="osg-rule"></div>', unsafe_allow_html=True)
    st.subheader("Explore common issues")
    for offset in (0, 3):
        for column, (title, prompt) in zip(st.columns(3), EXAMPLES[offset:offset + 3]):
            with column:
                if st.button(title, key=f"shortcut_{title}", use_container_width=True):
                    st.session_state["osguard_draft"] = prompt
                    st.session_state["osguard_next_input"] = prompt
                    st.rerun()
    if st.session_state.get("osguard_supervisor_result"):
        st.info("Your latest analysis is available on the Results page.")


def _troubleshoot() -> None:
    st.title("Troubleshoot a Windows issue")
    st.write("Describe what happened, when it began, and any error message you saw. OSGuard will use only relevant approved checks.")
    _input()
    st.caption("System checks are read-only. Supported workspace changes require separate approval.")


def _knowledge_status():
    """Check once per session and use the backend's lock for one initialization."""
    if "osguard_kb_status" in st.session_state:
        return st.session_state["osguard_kb_status"]
    from osguard.rag.knowledge_base import KnowledgeBaseStatus, inspect_knowledge_base, initialize_knowledge_base

    try:
        observed = inspect_knowledge_base()
        if not observed.retrieval_verified and (
            observed.state in {
            "faiss_ready", "fallback_active", "index_missing", "index_incomplete",
            "index_corrupt", "embedding_mismatch",
            } or (observed.state == "faiss_unavailable" and observed.fallback_allowed)
        ):
            with st.spinner("Preparing trusted Microsoft guidance..."):
                observed = initialize_knowledge_base()
    except Exception:
        observed = KnowledgeBaseStatus("initialization_failed", "unavailable", "Documentation preparation failed.", "")
    st.session_state["osguard_kb_status"] = observed
    return observed


def _knowledge_page() -> None:
    st.title("Microsoft Knowledge Base")
    st.write("OSGuard uses trusted Microsoft guidance when a question needs documentation.")
    status = _knowledge_status()
    ready = status.retrieval_verified and status.state in {"faiss_ready", "fallback_active"}
    if ready:
        st.success("Documentation is ready for retrieval.")
    else:
        st.warning("Microsoft documentation is temporarily unavailable.")
        if st.button("Retry documentation preparation"):
            st.session_state.pop("osguard_kb_status", None)
            retried = _knowledge_status()
            if retried.retrieval_verified and retried.state in {"faiss_ready", "fallback_active"}:
                st.rerun()
            else:
                st.error("Documentation could not be prepared. You can still describe an issue for analysis.")
    result = st.session_state.get("osguard_supervisor_result")
    if result:
        _sources(result)
    else:
        st.caption("Sources used in your analysis will appear here after an issue is reviewed.")


def _prepare_workspace_once() -> None:
    """Prepare only a safely missing owned workspace, once per UI session."""
    if st.session_state.get("osguard_workspace_checked"):
        return
    st.session_state["osguard_workspace_checked"] = True
    result = st.session_state.get("osguard_supervisor_result") or {}
    validation = result.get("validation_result")
    approval = result.get("approval_state")
    if (st.session_state.get("osguard_workspace_status") == "completed"
            or (validation and validation.status == "resolved")):
        st.session_state["osguard_workspace_status"] = "completed"
        return
    pending = bool(st.session_state.get("osguard_pending_thread_id")
                   or (approval and approval.status == "pending"))
    try:
        from osguard.repair.demo_cache import DemoCacheStore

        store = DemoCacheStore()
        inspection = store.inspect()
        if inspection.status == "missing" and not pending:
            inspection = store.prepare_fixture()
        st.session_state["osguard_workspace_status"] = (
            "pending" if pending else inspection.status
        )
    except Exception:
        st.session_state["osguard_workspace_status"] = "failed"


def _settings() -> None:
    st.title("Settings & availability")
    result = st.session_state.get("osguard_supervisor_result")
    environment = result.get("available_environment") if result else None
    st.subheader("This Windows PC")
    if environment and environment.source == "read_only_tool":
        st.write("Windows version: " + (environment.os_name or "Unavailable"))
        st.write("Build: " + (environment.os_build or "Unavailable"))
        st.write("Architecture: " + (environment.architecture or "Unavailable"))
    else:
        st.caption("System details will appear after a read-only system check succeeds.")
    st.subheader("Application availability")
    status = _knowledge_status()
    st.write("Microsoft guidance: " + (
        "Ready" if status.retrieval_verified and status.state in {"faiss_ready", "fallback_active"}
        else "Unavailable"
    ))
    st.write("Windows system analysis: " + (
        "Available" if result and any(item.status == "success" for item in result.get("tool_results", []))
        else "Not confirmed" if result else "Not checked"
    ))
    st.write("AI analysis: " + (
        "Available" if result and any(item.status == "completed" for item in result.get("specialist_results", []))
        else "Not confirmed" if result else "Not checked"
    ))
    st.markdown('<div class="osg-rule"></div>', unsafe_allow_html=True)
    st.subheader("Workspace Maintenance")
    st.write("Manage temporary files created and owned by OSGuard within its application workspace.")
    st.caption("This does not clean Windows, optimize your PC, or remove other applications' files.")
    if st.button("Check workspace files"):
        from osguard.repair.demo_cache import DemoCacheStore

        st.session_state["osguard_workspace_status"] = DemoCacheStore().inspect().status
    workspace_status = st.session_state.get("osguard_workspace_status")
    if workspace_status == "ready":
        st.write("OSGuard Temporary Files: Ready")
    elif workspace_status == "pending":
        st.write("OSGuard Temporary Files: Cleanup awaiting your decision")
    elif workspace_status in {"completed", "empty"}:
        st.caption("OSGuard Temporary Files are cleared and will not be recreated in this session.")
    elif workspace_status in {"unsafe", "failed", "unsupported_os"}:
        st.warning("OSGuard Temporary Files could not be prepared safely.")
    elif workspace_status == "missing":
        st.caption("OSGuard Temporary Files are not prepared.")
    if st.button("Review workspace cleanup"):
        # The backend recognizes this fixed request; it still enforces IEEE and approval.
        _run_analysis("Clear the OSGuard demo cache")


def _sidebar() -> str:
    next_page = st.session_state.pop("osguard_next_page", None)
    if next_page in PAGES:
        st.session_state["osguard_page"] = next_page
    st.session_state.setdefault("osguard_page", "Home")
    with st.sidebar:
        st.markdown('<div class="osg-brand">◇ OSGuard AI</div><div class="osg-muted">Intelligent Windows Troubleshooting</div>', unsafe_allow_html=True)
        st.markdown('<div class="osg-rule"></div>', unsafe_allow_html=True)
        page = st.radio("Navigation", PAGES, key="osguard_page", label_visibility="collapsed")
        st.markdown('<div class="osg-rule"></div>', unsafe_allow_html=True)
        st.caption("Read-only system analysis")
        st.caption("Your approval is required for supported changes")
    return page


def main() -> None:
    st.set_page_config(
        page_title="OSGuard AI | Windows Troubleshooting",
        page_icon="🛡️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(CSS, unsafe_allow_html=True)
    if "osguard_next_input" in st.session_state:
        st.session_state["osguard_issue_input"] = st.session_state.pop("osguard_next_input")
    _prepare_workspace_once()
    _knowledge_status()
    page = _sidebar()
    if page == "Home":
        _home()
    elif page == "Troubleshoot":
        _troubleshoot()
    elif page == "Results":
        result = st.session_state.get("osguard_supervisor_result")
        if result:
            _render_supervisor_result(result)
        else:
            st.title("Your analysis")
            st.info("No analysis is available yet. Describe an issue on Home to get started.")
    elif page == "Knowledge Base":
        _knowledge_page()
    else:
        _settings()
    if st.session_state.get("osguard_analysis_error") and page in {"Home", "Troubleshoot"}:
        st.error(st.session_state["osguard_analysis_error"])
