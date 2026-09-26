"""The Space sync must fail when Hugging Face can't build or start the new revision."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "sync_space.py"
_spec = importlib.util.spec_from_file_location("sync_space", _PATH)
assert _spec and _spec.loader
sync_space = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_space)


def _run(stages: list[str], **kw):
    """Feed a stage sequence (the last one repeats) through a fake clock that advances per poll."""
    seen, now = [], [0.0]

    def stage_of():
        s = stages[min(len(seen), len(stages) - 1)]
        seen.append(s)
        return s

    sync_space.wait_for_build(stage_of, clock=lambda: now[0],
                              sleep=lambda s: now.__setitem__(0, now[0] + s), **kw)
    return seen


def test_returns_once_the_rebuild_is_running():
    stages = ["RUNNING", "BUILDING", "APP_STARTING", "RUNNING"]
    assert _run(stages) == stages


@pytest.mark.parametrize("bad", ["BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR", "NO_APP_FILE"])
def test_fails_when_the_space_breaks(bad):
    with pytest.raises(SystemExit, match=bad):
        _run(["BUILDING", bad])


def test_fails_when_the_build_never_finishes():
    with pytest.raises(SystemExit, match="still BUILDING"):
        _run(["BUILDING"], timeout=100, poll=20)


def test_gives_up_quietly_when_no_rebuild_starts(capsys):
    _run(["RUNNING"], no_build_grace=60, poll=20)
    assert "No rebuild observed" in capsys.readouterr().out


def test_does_not_wait_on_a_paused_space():
    assert _run(["PAUSED", "BUILDING"]) == ["PAUSED"]


def test_deploy_dir_carries_the_pins(tmp_path):
    root = tmp_path / "repo"
    for rel in ("space/app.py", "src/repower/__init__.py", "Dockerfile", "pyproject.toml", "constraints.txt"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x")
    sync_space.build_deploy_dir(root, tmp_path / "deploy")
    assert {p.name for p in (tmp_path / "deploy").iterdir()} == {
        "app.py", "src", "Dockerfile", "pyproject.toml", "constraints.txt"}
