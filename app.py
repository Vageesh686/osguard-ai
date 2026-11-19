"""Minimal local UI for verifying the configured Groq connection."""

import streamlit as st

from osguard.config import ConfigurationError, load_settings
from osguard.groq_client import GroqProviderUnavailable, GroqRequestError, ask_groq


st.set_page_config(page_title="OSGuard AI")
st.title("OSGuard AI")
st.subheader("Groq connection check")
st.caption(
    "This foundation screen checks the configured LLM provider only. "
    "It does not inspect Windows, diagnose issues, or recommend system changes."
)

if st.button("Check Groq connection", type="primary"):
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
