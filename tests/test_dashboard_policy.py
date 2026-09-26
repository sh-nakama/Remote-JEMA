"""Smoke test: the Policy dashboard view (with the committee manager) renders
without raising, against an isolated temp DB.

Runs Streamlit's AppTest in a subprocess so ``REPOWER_DB_PATH`` is picked up at
import time (config/db resolve the path once, at import), keeping the real local
DB untouched. Rendering is network-free — discovery/detection only fire on button
clicks, which this test does not perform.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_RUNNER = r'''
import os

from streamlit.testing.v1 import AppTest


def _script():
    import streamlit as st
    from repower.policy.store import add_committee, sync_committees

    sync_committees()
    # A user-added committee exercises the registry + removal UI path.
    add_committee(
        key="ut_new", name_ja="テスト委員会", name_en="Test Committee",
        url="https://www.meti.go.jp/shingikai/x/ut_new/", source="METI",
    )
    from repower.dashboard.app_main import main

    st.session_state["top_view"] = "Policy"
    main()


at = AppTest.from_function(_script)
at.run(timeout=60)
# The Policy view (header + committee manager + generate buttons) must render
# without raising. A stray exception in any of those paths fails here.
assert not at.exception, at.exception
assert at.header, "policy header not rendered"
keys = [b.key or "" for b in at.button]
if os.environ.get("SPACE_ID"):
    # The hosted copy is read-only: no committee manager, no Generate buttons.
    assert not [k for k in keys if k.startswith("policy_")], keys
    assert any("閲覧専用" in c.value or "read-only" in c.value for c in at.caption), "read-only note missing"
else:
    assert "policy_apply_committee_edits" in keys, keys
print("APPTEST_OK")
'''


@pytest.mark.parametrize("hosted", [False, True], ids=["local", "hf-space"])
def test_policy_view_renders(tmp_path, hosted):
    runner = tmp_path / "runner.py"
    runner.write_text(_RUNNER, encoding="utf-8")

    env = dict(os.environ)
    env.pop("SPACE_ID", None)
    if hosted:
        env["SPACE_ID"] = "someone/space"
    env["REPOWER_DB_PATH"] = str(tmp_path / "t.db")
    src = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.run(
        [sys.executable, str(runner)],
        env=env, capture_output=True, text=True, timeout=180,
    )
    assert "APPTEST_OK" in proc.stdout, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
