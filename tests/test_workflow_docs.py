"""The "what runs automatically" table, in the user guide and in the in-app guide, against the real workflows.

Nothing generates those tables, so a workflow that is added, rescheduled or given a new command
would leave them quietly wrong — and the table is what someone consults to decide whether a
command needs running by hand. These tests make the workflow files the thing that is right.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
GUIDE = (ROOT / "docs" / "USER-GUIDE.md").read_text(encoding="utf-8")
CONTENT = (ROOT / "web" / "src" / "lib" / "guideContent.ts").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")

FILES = sorted(p.name for p in WORKFLOWS.glob("*.yml"))


def _crons(text: str) -> list[str]:
    return re.findall(r"^\s*-\s*cron:\s*[\"']([^\"']+)[\"']", text, re.MULTILINE)


def _jst(cron: str) -> str:
    """Clock time in JST of a cron that fires at a fixed hour and minute (all of ours do)."""
    minute, hour = cron.split()[:2]
    return f"{(int(hour) + 9) % 24:02d}:{int(minute):02d}"


def _commands(text: str) -> list[str]:
    """The ``repower`` commands a workflow invokes, without their options: ``policy run``, ``pull-hf``…"""
    found: list[str] = []
    for m in re.finditer(r"python -m repower\.cli ((?:[a-z][a-z-]*[ \t]*)+)", text):
        words = m.group(1).split()
        found.append(" ".join(words[:2]) if words[0] in {"policy", "cache"} else words[0])
    return found


def _guide_row(file: str) -> str:
    rows = [ln for ln in GUIDE.splitlines() if ln.startswith("| `") and f"`{file}`" in ln.split("|")[1]]
    assert rows, f"{file} has no row in USER-GUIDE.md's 'What runs automatically' table"
    return rows[0]


def _app_entry(file: str) -> str:
    start = CONTENT.find(f"file: '{file}'")
    assert start >= 0, f"{file} has no entry in AUTOMATED_RUNS (web/src/lib/guideContent.ts)"
    end = CONTENT.find("file: '", start + 1)
    return CONTENT[start : end if end > 0 else CONTENT.find("]\n", start)]


def test_there_are_workflows_to_check():
    assert len(FILES) >= 8


@pytest.mark.parametrize("file", FILES)
def test_every_workflow_has_a_row_in_the_user_guide(file):
    _guide_row(file)


@pytest.mark.parametrize("file", FILES)
def test_every_workflow_has_an_entry_in_the_in_app_guide(file):
    _app_entry(file)


@pytest.mark.parametrize("file", FILES)
def test_the_schedule_in_the_guide_is_the_schedule_in_the_workflow(file):
    row = _guide_row(file)
    entry = _app_entry(file)
    crons = _crons((WORKFLOWS / file).read_text(encoding="utf-8"))
    if not crons:
        assert "cron: null" in entry
        return
    for cron in crons:
        assert f"`{cron}`" in row, f"{file}: cron {cron} missing from USER-GUIDE.md"
        assert f"→ {_jst(cron)} JST" in row, f"{file}: JST time for {cron} should be {_jst(cron)}"
        assert f"cron: '{cron}'" in entry and f"jst: '{_jst(cron)}'" in entry, f"{file}: in-app entry out of date"


@pytest.mark.parametrize("file", FILES)
def test_every_command_a_workflow_runs_is_listed_in_its_row(file):
    row = _guide_row(file)
    for cmd in _commands((WORKFLOWS / file).read_text(encoding="utf-8")):
        assert f"`repower {cmd}" in row, f"{file} runs `repower {cmd}` but its USER-GUIDE.md row does not say so"


def test_the_guide_lists_no_workflow_that_does_not_exist():
    named = set()
    for ln in GUIDE.splitlines():
        m = re.match(r"\| `([\w-]+\.yml)` — ", ln)
        if m:
            named.add(m.group(1))
    assert named == set(FILES)
    in_app = set(re.findall(r"file: '([\w-]+\.yml)'", CONTENT))
    assert in_app == set(FILES)


def test_writes_dataset_flag_matches_whether_the_workflow_pushes():
    for file in FILES:
        pushes = "repower.cli push-hf" in (WORKFLOWS / file).read_text(encoding="utf-8")
        assert f"writes: {str(pushes).lower()}" in _app_entry(file), f"{file}: 'writes' should be {pushes}"
        last = _guide_row(file).strip().strip("|").split("|")[-1].strip()
        want = "Yes" if pushes else "No"
        assert last.startswith(want), f"{file}: the 'Writes the dataset' column says {last!r}, expected {want}"


@pytest.mark.parametrize("file", FILES)
def test_the_readme_mentions_every_workflow(file):
    assert f"`{file}`" in README, f"{file} is not described in README.md's 'CI workflows' section"
