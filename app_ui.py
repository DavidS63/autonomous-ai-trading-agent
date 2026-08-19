"""
Simple ChatGPT-like control panel for the Autonomous AI Trading Agent.
Run with:  streamlit run app_ui.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import streamlit as st
import yaml

st.set_page_config(
    page_title="Trading Agent Control Panel",
    page_icon="\U0001F4C8",
    layout="wide",
)

st.title("\U0001F4C8 Autonomous AI Trading Agent")
st.caption("Chat-style control panel \u00b7 Paper trading only \u00b7 Never real money")

st.sidebar.header("Controls")
mode = st.sidebar.radio(
    "What do you want to do?",
    [
        "Dry-run (safe practice)",
        "One paper cycle",
        "End-of-day review",
        "Ask a question about the last run",
    ],
)

run_button = st.sidebar.button("\u25B6 Run", type="primary")

journal_path = Path("data/trade_journal.jsonl")
perf_path = Path("data/performance.json")

col1, col2 = st.columns(2)

with col1:
    st.subheader("Last performance snapshot")
    if perf_path.exists():
        try:
            perf = json.loads(perf_path.read_text())
            st.json(perf.get("last_review", perf))
        except Exception as e:
            st.warning(f"Could not read performance file: {e}")
    else:
        st.info("No performance file yet. Run the agent at least once.")

with col2:
    st.subheader("Recent decisions (last 5)")
    if journal_path.exists():
        lines = journal_path.read_text().strip().splitlines()[-5:]
        for line in reversed(lines):
            try:
                entry = json.loads(line)
                idea = entry.get("idea", {})
                st.write(
                    f"**{entry.get('type', '?')}** \u00b7 "
                    f"{idea.get('side', '').upper()} {idea.get('symbol', '?')} "
                    f"(conf {idea.get('confidence', '?')})"
                )
            except Exception:
                pass
    else:
        st.info("No journal yet.")

st.divider()

if run_button:
    st.subheader("Agent output")
    log_box = st.empty()

    if mode == "Dry-run (safe practice)":
        cmd = [sys.executable, "main.py", "--dry-run"]
    elif mode == "One paper cycle":
        cmd = [sys.executable, "main.py"]
    elif mode == "End-of-day review":
        cmd = [sys.executable, "main.py", "--review"]
    else:
        cmd = None

    if cmd:
        with st.spinner("Agent is thinking\u2026 this can take 30\u201390 seconds"):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    cwd=str(Path(__file__).parent),
                )
                output = (result.stdout or "") + (result.stderr or "")
                log_box.code(output, language="text")
                if result.returncode == 0:
                    st.success("Cycle finished.")
                else:
                    st.error("Agent exited with an error. Scroll the log above.")
            except subprocess.TimeoutExpired:
                st.error("Timed out. Try running from PowerShell instead.")
            except Exception as e:
                st.error(f"Could not start agent: {e}")
    else:
        question = st.text_input("Ask about the last run (simple questions work best):")
        if question:
            st.info(
                "For deep questions, paste the latest journal lines to Grok in this chat. "
                "A full conversational memory layer can be added later."
            )
            if journal_path.exists():
                st.write("Here are the most recent journal entries for context:")
                st.code("\n".join(journal_path.read_text().strip().splitlines()[-8:]))

st.divider()
st.markdown(
    """
### Tips
- **Dry-run** never places orders \u2014 use it freely.
- **One paper cycle** uses your Alpaca Paper account (fake money).
- Keep the PowerShell window closed while using this panel, or use one or the other.
- To stop a long run, close this browser tab and end the process in Task Manager if needed.
"""
)
