"""Streamlit demo UI.   Run from the repo root:   streamlit run ui/app.py"""
import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import pipeline                                    # noqa: E402
from app.schemas import EnvSnapshot, Requirement            # noqa: E402
from app.stages.verify import compat                        # noqa: E402

st.set_page_config(page_title="OSGuard AI", page_icon="🛡️", layout="wide")
st.title("🛡️ OSGuard AI")
st.caption("Evidence-grounded Windows 11 troubleshooting with Intent–Environment–Evidence–Effect verification")

BADGE = {"recommend": "🟢 Recommend", "recommend_with_warning": "🟡 Recommend with warning",
         "need_more_info": "🟠 Need more info", "withhold": "🔴 Withheld"}
TIER = {"read_only": "🔍 read-only", "reversible": "↩️ reversible", "destructive": "⚠️ destructive"}

# ---------------- sidebar: environment ----------------
with st.sidebar:
    st.header("Environment")
    up = st.file_uploader("env.json from env_probe.ps1", type="json")
    if up:
        env = EnvSnapshot.model_validate_json(up.getvalue().decode("utf-8-sig"))
        st.success(f"Build {env.os_build} · admin={env.is_admin}")
    else:
        env = EnvSnapshot()
        st.info("No snapshot uploaded – environment checks will be limited.")
    with st.expander("Snapshot"):
        st.json(json.loads(env.model_dump_json()))


def show_verified(v):
    d = v.verdict
    st.markdown(f"**{BADGE[d.final]}** · {TIER[d.effect_tier]}")
    st.code(v.action.command, language="powershell" if v.action.shell != "cmd" else "bat")
    if v.action.rationale:
        st.caption(v.action.rationale)
    cols = st.columns(4)
    cols[0].metric("Intent", d.intent)
    cols[1].metric("Environment", d.environment)
    cols[2].metric("Evidence", d.evidence)
    cols[3].metric("Effect", d.effect_tier)
    with st.expander("Why"):
        for k, r in d.reasons.items():
            st.markdown(f"- **{k.title()}**: {r}")
        for r in v.requirement_results:
            st.markdown(f"- Requirement `{r.requirement.name} {r.requirement.spec}`: {r.status} – {r.detail}")


tab1, tab2, tab3 = st.tabs(["1 · Troubleshoot", "2 · Verify a command", "3 · Compatibility"])

# ---------------- tab 1 ----------------
with tab1:
    text = st.text_area("Paste the error message, log lines or describe the problem", height=180)
    if st.button("Analyse", type="primary", disabled=not text.strip()):
        with st.spinner("Classifying, retrieving documentation, diagnosing, verifying..."):
            try:
                res = pipeline.run(text, env)
            except Exception as e:                                     # noqa: BLE001
                st.error(f"Pipeline failed: {e}")
                st.stop()
        ex = res.extraction
        st.subheader("Problem")
        st.write(f"**Category:** {ex.category} · **Component:** {ex.component or '–'} · "
                 f"**Error codes:** {', '.join(ex.error_codes) or '–'}")
        st.write(f"**Goal:** {ex.user_goal}")

        st.subheader("Findings")
        cc1, cc2 = st.columns(2)
        with cc1:
            st.markdown("**Confirmed observations**")
            for c in [c for c in res.diagnosis.claims if c.kind == "observation"]:
                st.markdown(f"- {c.text}")
        with cc2:
            st.markdown("**Possible causes (hypotheses)**")
            for c in [c for c in res.diagnosis.claims if c.kind == "hypothesis"]:
                st.markdown(f"- {c.text}  \n  _sources: {', '.join(c.evidence_ids) or 'none'}_")

        st.subheader("Suggested actions")
        for v in res.verified:
            with st.container(border=True):
                show_verified(v)
        for n in res.notes:
            st.warning(n)

        with st.expander("Retrieved sources"):
            for c in res.chunks:
                st.markdown(f"**[{c.id}]** [{c.title}]({c.url})")
                st.caption(c.text[:300] + "...")

# ---------------- tab 2 ----------------
with tab2:
    st.write("Check a command from anywhere (a forum, another chatbot) before you run it.")
    cmd = st.text_area("Command", height=80, placeholder="e.g.  Remove-Item C:\\Windows\\Temp\\* -Recurse -Force")
    goal = st.text_input("What are you trying to achieve?")
    shell = st.radio("Shell", ["powershell", "cmd"], horizontal=True)
    if st.button("Verify command", disabled=not cmd.strip()):
        with st.spinner("Verifying..."):
            try:
                v = pipeline.verify_command(cmd.strip(), goal.strip(), env, shell)
                show_verified(v)
            except Exception as e:                                     # noqa: BLE001
                st.error(f"Verification failed: {e}")

# ---------------- tab 3 ----------------
with tab3:
    st.write("One requirement per line, e.g. `windows>=22000`, `powershell>=5.1`, `Python>=3.10`.")
    lines = st.text_area("Requirements", height=120, value="windows>=22000\npowershell>=5.1")
    if st.button("Check compatibility"):
        reqs = [compat.parse_requirement_line(l) for l in lines.splitlines() if l.strip()]
        for r in compat.check_requirements(reqs, env):
            icon = {"pass": "✅", "fail": "❌", "unknown": "❔"}[r.status]
            st.markdown(f"{icon} `{r.requirement.name} {r.requirement.spec}` – {r.detail}")
