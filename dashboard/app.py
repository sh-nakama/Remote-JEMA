"""Local dev entry point."""
import streamlit as st

st.set_page_config(page_title="RePower - Tokyo Market", layout="wide", page_icon="X")

from repower.dashboard import main
main()
