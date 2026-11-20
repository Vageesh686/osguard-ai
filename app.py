"""Local Streamlit interface for the OSGuard Phase 1 supervisor."""

import streamlit as st

from osguard.config import ConfigurationError, load_settings
from osguard.groq_client import GroqProviderUnavailable, GroqRequestError, ask_groq


st.set_page_config(page_title="OSGuard AI")
st.title("OSGuard AI")
st.caption(
    "Describe a Windows issue to classify it and route it to the relevant "
    "specialist workflow. Phase 1 does not run system checks or repairs."
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

    st.write(f"**Workflow status:** {_display_label(result.get('workflow_status', 'unknown'))}")

    missing = result.get("missing_information", [])
    if missing:
        st.warning("Information needed: " + "; ".join(missing))
    uncertainties = result.get("uncertainty_notes", [])
    if uncertainties:
        st.caption("Uncertainty: " + "; ".join(uncertainties))

    for specialist_result in result.get("specialist_results", []):
        st.markdown(f"**{_display_label(specialist_result.specialist)}**")
        st.info(specialist_result.message)

    final_response = result.get("final_response")
    if final_response is not None:
        st.write(final_response.message)
        if not final_response.findings_available:
            st.caption("No diagnostic findings or corrective actions were produced.")

    for error in result.get("errors", []):
        st.error(error.message)


user_request = st.text_area(
    "Describe your Windows issue",
    placeholder="For example: My Windows PC has unusually high CPU usage.",
    height=120,
)

if st.button("Classify and route", type="primary"):
    if not user_request.strip():
        st.warning("Enter a short description of the Windows issue first.")
    else:
        st.session_state.pop("osguard_supervisor_result", None)
        try:
            from osguard.state import make_initial_state

            with st.spinner("Classifying the request and selecting specialists..."):
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
