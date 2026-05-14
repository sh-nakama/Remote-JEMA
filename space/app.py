"""
HF Space entry point for RePower Tokyo dashboard.

On cold start the DB is pulled from the private HF Dataset. A sidebar
Refresh button lets users pull the latest data without restarting the Space.
"""

import streamlit as st

st.set_page_config(page_title="RePower — Tokyo Market", layout="wide", page_icon="⚡")

# ── Cold-start DB pull ────────────────────────────────────────────────────
# Runs once per session; idempotent if file already exists.
if "db_ready" not in st.session_state:
    with st.spinner("⏳ Loading market database…"):
        try:
            from repower.hf_sync import pull_db_from_hf
            pull_db_from_hf()
            st.session_state["db_ready"] = True
        except Exception as exc:
            st.warning(
                f"⚠️ Could not fetch database from Hugging Face: {exc}\n\n"
                "Dashboard may show empty data until the next scheduled update."
            )
            st.session_state["db_ready"] = False

# ── Render dashboard ──────────────────────────────────────────────────────
from repower.dashboard import main
main(show_refresh=True)
