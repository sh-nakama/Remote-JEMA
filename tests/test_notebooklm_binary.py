"""Finding the ``notebooklm`` program, and telling "not installed" apart from "not logged in".

The bug these pin: ``repower web-api`` started without its virtualenv activated has no
``Scripts`` folder on PATH, so the bare name ``notebooklm`` was not found — and the auth check
swallowed that and reported "auth is missing/stale, run `notebooklm login`", advice that cannot
work when the program itself cannot be found. Both the Manage page's run and the Commands
pane's sign-in failed, and the first one blamed the login.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from repower.cli import app
from repower.policy import notebook as nb

runner = CliRunner()


@pytest.fixture
def exe_dir(tmp_path, monkeypatch):
    """A fake interpreter folder holding a fake console script, with PATH and the env override empty."""
    monkeypatch.delenv("NOTEBOOKLM_BIN", raising=False)
    monkeypatch.setattr(nb.shutil, "which", lambda name: None)
    monkeypatch.setattr(nb.sys, "executable", str(tmp_path / "python.exe"))
    return tmp_path


def test_finds_the_script_next_to_the_running_python_when_path_lacks_it(exe_dir):
    (exe_dir / "notebooklm.exe").write_text("")
    assert nb.find_binary() == str(exe_dir / "notebooklm.exe")
    assert nb.binary_problem() is None


def test_posix_style_script_name_is_found_too(exe_dir):
    (exe_dir / "notebooklm").write_text("")
    assert nb.find_binary() == str(exe_dir / "notebooklm")


def test_path_wins_over_the_interpreter_folder(exe_dir, monkeypatch):
    (exe_dir / "notebooklm.exe").write_text("")
    monkeypatch.setattr(nb.shutil, "which", lambda name: "/usr/local/bin/notebooklm")
    assert nb.find_binary() == "/usr/local/bin/notebooklm"


def test_the_env_override_is_honoured_by_full_path_or_by_name(exe_dir, monkeypatch):
    custom = exe_dir / "tools" / "nblm.exe"
    custom.parent.mkdir()
    custom.write_text("")
    monkeypatch.setenv("NOTEBOOKLM_BIN", str(custom))
    assert nb.find_binary() == str(custom)
    monkeypatch.setenv("NOTEBOOKLM_BIN", "nblm")
    monkeypatch.setattr(nb.shutil, "which", lambda name: "/opt/nblm" if name == "nblm" else None)
    assert nb.find_binary() == "/opt/nblm"


def test_a_wrong_override_is_not_silently_replaced_by_another_copy(exe_dir, monkeypatch):
    (exe_dir / "notebooklm.exe").write_text("")
    monkeypatch.setenv("NOTEBOOKLM_BIN", str(exe_dir / "does-not-exist.exe"))
    assert nb.find_binary() is None  # the user said which one to use; honour it or say so
    assert "does-not-exist.exe" in nb.binary_problem()


def test_the_explanation_says_where_it_looked_and_how_to_fix_it(exe_dir):
    msg = nb.binary_problem()
    assert str(exe_dir) in msg and "PATH" in msg
    assert "NOTEBOOKLM_BIN" in msg and "notebooklm-py" in msg
    assert "login" not in msg.replace("notebooklm login", "")  # it must not send anyone to log in


def test_running_a_missing_program_raises_the_accurate_error_not_a_login_one(exe_dir, monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(nb.subprocess, "run", boom)
    with pytest.raises(nb.NotebookLMError, match="was not found") as e:
        nb._run(["auth", "check"], timeout=5)
    assert not isinstance(e.value, nb.NotebookLMAuthError)


def test_require_auth_blames_the_missing_program_when_the_check_cannot_pass(exe_dir, monkeypatch):
    monkeypatch.setattr(nb, "auth_ok", lambda **k: False)
    with pytest.raises(nb.NotebookLMAuthError, match="was not found"):
        nb.require_auth()


# ── the CLI the buttons run ──────────────────────────────────────────────────────────
def test_policy_auth_reports_a_missing_program_rather_than_a_stale_login(exe_dir):
    r = runner.invoke(app, ["policy", "auth"])
    assert r.exit_code == 2
    assert "was not found" in r.output and "missing/stale" not in r.output


def test_policy_login_reports_a_missing_program_and_does_not_open_anything(exe_dir, monkeypatch):
    monkeypatch.delenv("NOTEBOOKLM_AUTH_JSON", raising=False)
    monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("must not launch anything"))
    r = runner.invoke(app, ["policy", "login"])
    assert r.exit_code == 2 and "was not found" in r.output


def test_a_genuinely_stale_login_is_still_reported_as_one(exe_dir, monkeypatch):
    (exe_dir / "notebooklm.exe").write_text("")
    monkeypatch.setattr(nb, "auth_ok", lambda **k: False)
    r = runner.invoke(app, ["policy", "auth"])
    assert r.exit_code == 2 and "missing/stale" in r.output and "was not found" not in r.output


def test_policy_login_launches_the_resolved_executable_not_the_bare_name(exe_dir, monkeypatch):
    (exe_dir / "notebooklm.exe").write_text("")
    monkeypatch.delenv("NOTEBOOKLM_AUTH_JSON", raising=False)
    seen: list[list[str]] = []

    class Done:
        returncode = 0

    monkeypatch.setattr("subprocess.run", lambda cmd, **k: (seen.append(cmd), Done())[1])
    monkeypatch.setattr(nb, "auth_ok", lambda **k: True)
    r = runner.invoke(app, ["policy", "login", "--browser", "chrome"])
    assert r.exit_code == 0, r.output
    assert seen[0][:2] == [str(exe_dir / "notebooklm.exe"), "login"] and seen[0][2:4] == ["--browser", "chrome"]
