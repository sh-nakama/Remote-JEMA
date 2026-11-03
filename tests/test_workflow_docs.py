"""The "what runs automatically" table, in the user guide and in the in-app guide, against the real workflows.

Nothing generates those tables, so a workflow that is added, rescheduled or given a new command
would leave them quietly wrong — and the table is what someone consults to decide whether a
command needs running by hand. These tests make the workflow files the thing that is right.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from repower.policy import run_gate

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
GUIDE = (ROOT / "docs" / "USER-GUIDE.md").read_text(encoding="utf-8")
CONTENT = (ROOT / "web" / "src" / "lib" / "guideContent.ts").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")

FILES = sorted(p.name for p in WORKFLOWS.glob("*.yml"))


def _crons(text: str) -> list[str]:
    return re.findall(r"^\s*-\s*cron:\s*[\"']([^\"']+)[\"']", text, re.MULTILINE)


def _jst(cron: str) -> str:
    """Clock times in JST of a cron that fires at fixed hours or hourly, at a fixed minute (all of ours do)."""
    minute, hours = cron.split()[:2]
    if hours == "*":
        return f"hourly at :{int(minute):02d}"
    return ", ".join(f"{(int(hour) + 9) % 24:02d}:{int(minute):02d}" for hour in hours.split(","))


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


def test_policy_run_signs_in_with_the_master_token():
    """Inline cookies die within minutes and bypass the library's mid-run re-mint."""
    text = (WORKFLOWS / "policy.yml").read_text(encoding="utf-8")
    steps = re.findall(r"^\s*- name: (.+)$", text, re.MULTILINE)
    assert steps.index("Mint a NotebookLM session from the master token") < steps.index("Check NotebookLM auth")
    assert "secrets.NOTEBOOKLM_AUTH_JSON" not in text
    assert text.count("secrets.NOTEBOOKLM_MASTER_TOKEN_JSON") == 1  # the mint step only, not the whole job
    assert "umask 077" in text


def test_summarising_is_gated_on_the_notebooklm_limit():
    """Clock slots cannot hold a 5-hour gap, so only the gate starts runs and each run checks again."""
    policy = (WORKFLOWS / "policy.yml").read_text(encoding="utf-8")
    assert not _crons(policy)
    assert f"- name: {run_gate.SUMMARISE_STEP}" in policy
    assert "if: steps.auth.outputs.ok == 'true' && steps.gate.outputs.due == 'true'" in policy
    assert "POLICY_RUN_ID: ${{ github.run_id }}" in policy
    gate = (WORKFLOWS / "policy-gate.yml").read_text(encoding="utf-8")
    assert f"gh workflow run {run_gate.WORKFLOW} --ref main" in gate
    assert "hf-dataset" not in gate.split("permissions:")[1]  # it must not queue behind a run it would start


def test_policy_run_starts_the_site_deploy_itself():
    """GitHub fires no workflow_run for a run GITHUB_TOKEN started, which is how the gate starts it."""
    policy = (WORKFLOWS / "policy.yml").read_text(encoding="utf-8")
    steps = re.findall(r"^\s*- name: (.+)$", policy, re.MULTILINE)
    assert steps.index("Push updated DB to Hugging Face") < steps.index("Start the site deploy")
    assert "gh workflow run web-deploy.yml --ref main -f automated=true" in policy
    assert "actions: write" in policy
    deploy = (WORKFLOWS / "web-deploy.yml").read_text(encoding="utf-8")
    assert '- "Daily Policy Summaries"' not in deploy  # would deploy twice after a run started by hand
    assert "inputs.automated != true" in deploy  # a failed pull must not replace the live site


def test_a_stale_login_fails_the_policy_run_only_after_the_push():
    """Green runs hid weeks of skipped summaries; failing any earlier would lose detection's results."""
    text = (WORKFLOWS / "policy.yml").read_text(encoding="utf-8")
    steps = re.findall(r"^\s*- name: (.+)$", text, re.MULTILINE)
    assert steps[-1] == "Mark the run failed when auth is stale"
    assert steps.index("Push updated DB to Hugging Face") < steps.index("Alert on failure") < len(steps) - 1
    assert "curl -s " not in text  # a failed alert must not pass for a sent one


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
