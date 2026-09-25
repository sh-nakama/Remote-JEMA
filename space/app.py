"""HF Space entry point for RePower Tokyo dashboard (Docker SDK).

The DB is pulled from the private HF Dataset once per process and re-checked
hourly — not once per visitor. The sidebar Refresh button pulls on demand.
"""

import streamlit as st

st.set_page_config(page_title="RePower — Tokyo Market", layout="wide", page_icon="⚡")


@st.cache_resource(ttl=3600, show_spinner="⏳ Loading market database…")
def _pull_db() -> str | None:
    """Pull the DB for the whole process; returns the failure text, if any."""
    try:
        from repower.hf_sync import pull_db_from_hf
        pull_db_from_hf()
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return None


if (error := _pull_db()) is not None:
    st.warning(
        f"⚠️ Could not fetch database from Hugging Face: {error}\n\n"
        "Dashboard may show empty data until the next scheduled update."
    )

# ── Render dashboard ──────────────────────────────────────────────────────
from repower.dashboard import main  # noqa: E402 — must follow set_page_config

main(show_refresh=True)