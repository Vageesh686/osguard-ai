"""Local Streamlit interface for the OSGuard Supervisor and specialists."""

import streamlit as st

from osguard.config import ConfigurationError, load_settings
from osguard.groq_client import GroqProviderUnavailable, GroqRequestError, ask_groq


st.set_page_config(page_title="OSGuard AI")
st.title("OSGuard AI")
st.caption(
    "Describe a Windows issue for structured analysis. OSGuard uses only the "
    "request and any text you provide; it does not inspect or change your system."
)


@st.cache_resource(show_spinner=False)
def _get_supervisor_graph():
    """Cache one graph/model instance instead of creating clients per rerun."""
    from osguard.graph import build_supervisor_graph

    return build_supervisor_graph()


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

        environment = classification.available_environment
        reported = {
            label: value
            for label, value in (
                ("Operating system", environment.os_name),
                ("OS version", environment.os_version),
                ("Architecture", environment.architecture),
                ("Application", environment.application_name),
                ("Application version", environment.application_version),
            )
            if value
        }
        if reported:
            st.write("**Environment details stated in the request:**", reported)
        else:
            st.caption("The host environment was not inspected.")

    workflow_status = result.get("workflow_status", "unknown")
    st.write(f"**Workflow status:** {_display_label(workflow_status)}")

    missing = result.get("missing_information", [])
    if missing:
        st.warning("Information needed: " + "; ".join(missing))
    uncertainties = result.get("uncertainty_notes", [])
    if uncertainties:
        st.caption("Uncertainty: " + "; ".join(uncertainties))

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
            if hypotheses:
                st.markdown("**Hypotheses (unconfirmed)**")
                for hypothesis in hypotheses:
                    st.write(hypothesis.description)
                    st.caption(
                        f"Why uncertain: {hypothesis.uncertainty} · "
                        "Evidence is limited to the supplied request."
                    )
                    for quote in hypothesis.supporting_quotes:
                        st.caption(f'User-provided support: “{quote}”')
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
                if not finding.verified:
                    st.caption("This command was not verified as safe.")

    compatibility_findings = result.get("compatibility_findings", [])
    if compatibility_findings:
        with st.expander("Compatibility analysis", expanded=True):
            for finding in compatibility_findings:
                st.markdown(f"**{finding.component} — {_display_label(finding.result)}**")
                st.caption("Any comparison is based only on values reported in the request.")
                if finding.installed_version:
                    st.write(f"**Installed version (user-reported):** {finding.installed_version}")
                if finding.required_version:
                    st.write(f"**Required version (user-reported):** {finding.required_version}")
                if finding.required_os:
                    st.write(f"**Required OS (user-reported):** {finding.required_os}")
                if finding.required_architecture:
                    st.write(f"**Required architecture (user-reported):** {finding.required_architecture}")
                st.caption(f"Fact status: {_display_label(finding.fact_status)}")
                if finding.hypothesis:
                    st.write(f"**Hypothesis:** {finding.hypothesis}")
                if finding.missing_information:
                    st.warning("Needed: " + "; ".join(finding.missing_information))

    final_response = result.get("final_response")
    if final_response is not None:
        st.write(final_response.message)
        if not final_response.findings_available:
            st.caption("No verified findings were produced.")

    for error in result.get("errors", []):
        st.error(error.message)


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
        try:
            from osguard.state import make_initial_state

            with st.spinner("Classifying the request and running selected specialists..."):
                workflow = _get_supervisor_graph()
                result = workflow.invoke(make_initial_state(user_request))
            st.session_state["osguard_supervisor_result"] = result
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
    _render_supervisor_result(st.session_state["osguard_supervisor_result"])

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
