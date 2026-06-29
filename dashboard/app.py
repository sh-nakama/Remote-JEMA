"""Local dev entry point."""
import streamlit as st

st.set_page_config(page_title="RePower - Tokyo Market", layout="wide", page_icon="X")

# show_refresh=True so local runs get the sidebar "Refresh data" button
# (pull latest DB/Parquet from Hugging Face + clear caches). Import is after
# set_page_config by design (Streamlit requires set_page_config to run first).
from repower.dashboard import main  # noqa: E402

main(show_refresh=True)
