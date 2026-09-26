"""The HF Space pulls the DB once per process, not once per visitor session.

Runs Streamlit's AppTest in a subprocess (see test_dashboard_policy.py) with the
pull stubbed out, so it is network-free and leaves the real local DB untouched.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

_RUNNER = r'''
import os

import repower.hf_sync as hf_sync
from streamlit.testing.v1 import AppTest

calls = []
hf_sync.pull_db_from_hf = lambda: calls.append(1)

for _visitor in range(2):
    at = AppTest.from_file(os.environ["SPACE_APP"], default_timeout=60)
    at.run()
    assert not at.exception, at.exception
assert len(calls) == 1, f"pulled {len(calls)} times for 2 sessions"
print("SPACE_OK")
'''


def test_space_pulls_once_per_process_not_per_session(tmp_path):
    runner = tmp_path / "runner.py"
    runner.write_text(_RUNNER, encoding="utf-8")
    env = dict(os.environ)
    env["REPOWER_DB_PATH"] = str(tmp_path / "t.db")
    env["SPACE_APP"] = str(_ROOT / "space" / "app.py")
    env["PYTHONPATH"] = str(_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.run(
        [sys.executable, str(runner)], env=env, capture_output=True, text=True, timeout=180,
    )
    assert "SPACE_OK" in proc.stdout, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
