"""Smoke tests of the CLI: every command the workflows run, with all I/O stubbed.

A broken command otherwise surfaces only as a failed cron in production.
"""

from __future__ import annotations

import ast
import importlib
import pathlib
import re
import shlex
from datetime import date

import httpx
import pytest
import typer
import yaml
from typer.core import TyperGroup
from typer.testing import CliRunner

from repower import cli

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = date(2026, 9, 27)
FRESH = {"source": "eprx_balancing", "latest": date(2026, 9, 26), "age": 1, "limit": 3,
         "stale": False}
CROSSCHECK = {"theirs": 5, "matched": 4, "added": 1, "missing": [
    {"council": "次世代電力系統ワーキンググループ", "dir": "shoene_shinene/wg", "url": "https://x/wg"},
]}


class Stubs:
    """Call log of the stubbed stages: names in call order, plus each one's last arguments."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.args: dict[str, tuple[tuple, dict]] = {}

    def stub(self, name, result=None, fail=False):
        def fn(*args, **kwargs):
            self.calls.append(name)
            self.args[name] = (args, kwargs)
            if fail:
                raise RuntimeError(f"{name} down")
            return result(*args, **kwargs) if callable(result) else result
        return fn


@pytest.fixture
def stubs(monkeypatch):
    """Stub every stage the workflow commands reach, and fail on any real network call."""
    s = Stubs()

    class _Area:
        AREA = "tepco"

        def scrape(self, months_back):
            return s.stub("area_backfill", 5)(months_back=months_back)

    detected = [{"key": "doji_shijo", "source": "meti", "status": "ok", "latest_online": 24,
                 "known_latest": 22, "new": 2}]
    summary = {"processed": 1, "done": 1, "errored": 0, "synthesized": 1}
    manifest = {"datasets": {"prices": {"files": 3, "bytes": 4096}}, "anchor": "2026-09-26",
                "sources": {"db": "ok"}}
    patches = {
        "repower.scrapers.areas.scrape_all_areas": s.stub("areas", {"tepco": 3}),
        "repower.scrapers.jepx_spot.scrape_jepx": s.stub("jepx"),
        "repower.scrapers.fuels_futures.scrape_fuels": s.stub("fuels"),
        "repower.scrapers.news_rss.scrape_news": s.stub("news"),
        "repower.scrapers.eprx.scrape_eprx": s.stub("eprx"),
        "repower.scrapers.eprx.scrape_eprx_tieline": s.stub("tieline"),
        "repower.analysis.features.run_analysis": s.stub("analyze", fail=True),
        "repower.policy.detect.detect": s.stub("detect", detected),
        "repower.policy.detect.backfill_dates": s.stub("dates", [{"dated": 1}]),
        "repower.policy.tagging.retag": s.stub(
            "tags", {"meetings": [{}, {}], "committees": [{}], "checked": {"meetings": 9, "committees": 3}}),
        "repower.policy.schedule.refresh_upcoming": s.stub("schedule", 4),
        "repower.policy.catalog.discover_committees": s.stub("catalog", {"inserted": 0, "found": 9}),
        "repower.notify.webhook.notify": s.stub("notify", lambda day, dry_run: s.calls.append(f"dry_run={dry_run}")),
        "repower.hf_sync.pull_db_from_hf": s.stub("pull"),
        "repower.hf_sync.push_db_to_hf": s.stub("push"),
        "repower.freshness.source_ages": s.stub("freshness", [FRESH]),
        "repower.scrapers.http_cache.cache_status": s.stub("cache_status", [{"entries": 10}]),
        "repower.scrapers.http_cache.prune_cache": s.stub("prune", 2),
        "repower.dashboard.export_web.export_web": s.stub("export", manifest),
        "repower.scrapers.areas.ALL_SCRAPERS": [_Area],
        "repower.scrapers.jepx_spot.scrape_jepx_years": s.stub("jepx_years", lambda a, b: {a: 1}),
        "repower.scrapers.eprx._current_jfy": lambda: 2026,
        "repower.scrapers.eprx.scrape_eprx_range": s.stub("eprx_range", 7),
        "repower.policy.notebook.auth_ok": s.stub("auth", True),
        "repower.policy.pipeline.run": s.stub("run", summary),
        "repower.policy.pipeline.resume": s.stub("resume", {"done": 0, "errored": 0}),
        "repower.policy.digest.build_digest": s.stub("digest", "# Weekly digest"),
        "repower.policy.digest.post_digest": s.stub("post", True),
        "repower.policy.energy_board.cross_check": s.stub("crosscheck", CROSSCHECK),
    }
    for target, fn in patches.items():
        monkeypatch.setattr(target, fn)
    monkeypatch.setattr(cli, "today_jst", lambda: TODAY)

    def no_network(*args, **kwargs):
        raise AssertionError("unstubbed network call from a CLI test")

    monkeypatch.setattr(httpx.Client, "send", no_network)
    monkeypatch.setattr("repower.scrapers.http_cache._do_get", no_network)
    return s


def test_run_all_runs_every_stage_and_survives_a_failing_one(stubs):
    result = CliRunner().invoke(cli.app, ["run-all", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert stubs.calls == ["areas", "jepx", "fuels", "news", "eprx", "tieline", "analyze",
                           "detect", "dates", "tags", "schedule", "catalog", "notify", "dry_run=True"]
    assert "analyze skipped: analyze down" in result.output
    assert "policy tags: 2 meeting(s), 1 committee(s) updated" in result.output
    assert "2 new committee meeting(s) detected" in result.output
    assert result.output.rstrip().endswith("═══ DONE ═══")


# Stand-ins for the workflows' ${{ expressions }} and $ENV references.
_WORKFLOW_VALUES = {
    "SINCE": "2026-01",
    "AREA": "all",
    "COMMITTEE": "all",
    "MAX_PER_RUN": "8",
    "steps.window.outputs.since": "2026-03",
    "steps.window.outputs.jepx_since": "2025",
}


def _workflow_invocations() -> list[list[str]]:
    """The argv of every `python -m repower.cli ...` line in the workflows, deduplicated."""
    found: dict[tuple[str, ...], None] = {}
    for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for job in yaml.safe_load(wf.read_text(encoding="utf-8"))["jobs"].values():
            for step in job.get("steps", []):
                for line in str(step.get("run", "")).splitlines():
                    m = re.match(r"\s*python -m repower\.cli\s+(.*)", line)
                    if not m:
                        continue
                    args = re.sub(r"\$\{\{\s*(.+?)\s*\}\}", lambda v: _WORKFLOW_VALUES[v[1]], m[1])
                    args = re.sub(r"\$(\w+)", lambda v: _WORKFLOW_VALUES[v[1]], args)
                    found[tuple(shlex.split(args))] = None
    return [list(argv) for argv in found]


_INVOCATIONS = _workflow_invocations()


def test_the_workflow_scan_finds_the_cron_commands():
    names = {" ".join(a[:2]) if a[0] in ("policy", "cache") else a[0] for a in _INVOCATIONS}
    assert {"pull-hf", "push-hf", "run-all", "check-freshness", "export-web", "policy run"} <= names


@pytest.mark.parametrize("argv", _INVOCATIONS, ids=" ".join)
def test_every_workflow_invocation_runs(stubs, argv):
    result = CliRunner().invoke(cli.app, argv)

    assert result.exit_code == 0, result.output
    assert stubs.calls, "exited without reaching the command's implementation"


def test_a_failing_tagger_does_not_fail_the_scrape(stubs, monkeypatch):
    """Tags are derived data: a bug there must not cost the day's scrape or the HF push."""
    monkeypatch.setattr("repower.policy.tagging.retag", stubs.stub("tags", fail=True))

    result = CliRunner().invoke(cli.app, ["run-all", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "policy tags skipped: tags down" in result.output
    assert result.output.rstrip().endswith("═══ DONE ═══")


@pytest.mark.parametrize("argv", [["policy", "detect"], ["policy", "run"], ["policy", "resume"]], ids=" ".join)
def test_policy_commands_refresh_tags_after_writing(stubs, argv):
    result = CliRunner().invoke(cli.app, argv)

    assert result.exit_code == 0, result.output
    assert stubs.calls[-1] == "tags"


def test_policy_detect_dry_run_does_not_tag(stubs):
    result = CliRunner().invoke(cli.app, ["policy", "detect", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert "tags" not in stubs.calls


def test_check_freshness_exits_1_when_a_source_is_stale(stubs, monkeypatch):
    stale = {**FRESH, "source": "jepx_spot", "age": 9, "stale": True}
    monkeypatch.setattr("repower.freshness.source_ages", lambda: [FRESH, stale])

    result = CliRunner().invoke(cli.app, ["check-freshness"])

    assert result.exit_code == 1
    assert "Stale market data: jepx_spot" in result.output


@pytest.mark.parametrize("argv", [["policy", "run"], ["policy", "resume"]], ids=" ".join)
def test_summarising_commands_stop_without_notebooklm_auth(stubs, monkeypatch, argv):
    monkeypatch.setattr("repower.policy.notebook.auth_ok", lambda: False)

    result = CliRunner().invoke(cli.app, argv)

    assert result.exit_code == 2
    assert "notebooklm login" in result.output
    assert "run" not in stubs.calls and "resume" not in stubs.calls


@pytest.mark.parametrize(("committee", "keys", "breadth_first"), [
    ("all", None, True),
    ("doji_shijo", ["doji_shijo"], False),
])
def test_policy_run_passes_the_queue_options(stubs, committee, keys, breadth_first):
    argv = ["policy", "run", "--committee", committee, "--max-per-run", "8"]
    result = CliRunner().invoke(cli.app, argv)

    assert result.exit_code == 0, result.output
    assert stubs.args["run"] == (
        (keys,), {"max_per_run": 8, "breadth_first": breadth_first, "meeting_num": None})


def test_policy_run_meeting_needs_a_committee(stubs):
    result = CliRunner().invoke(cli.app, ["policy", "run", "--meeting", "3"])

    assert result.exit_code == 2
    assert "run" not in stubs.calls


def test_backfill_spans_since_to_today_for_every_source(stubs):
    # The weekly re-validation's arguments; TODAY is 2026-09-27, six months after 2026-03.
    argv = ["backfill", "--since", "2026-03", "--jepx-since", "2025", "--eprx-since", "2025"]
    result = CliRunner().invoke(cli.app, argv)

    assert result.exit_code == 0, result.output
    assert stubs.args["area_backfill"] == ((), {"months_back": 6})
    assert stubs.args["jepx_years"] == ((2025, 2026), {})
    assert stubs.args["eprx_range"] == ((2025,), {})


@pytest.mark.parametrize("since", ["2026/03", "2027-01"])
def test_backfill_rejects_a_malformed_or_future_since(stubs, since):
    result = CliRunner().invoke(cli.app, ["backfill", "--since", since])

    assert result.exit_code == 2
    assert "area_backfill" not in stubs.calls


def test_crosscheck_posts_new_committees_only_with_notify(stubs, monkeypatch):
    assert CliRunner().invoke(cli.app, ["policy", "crosscheck"]).exit_code == 0
    assert "post" not in stubs.calls

    result = CliRunner().invoke(cli.app, ["policy", "crosscheck", "--notify"])
    assert result.exit_code == 0, result.output
    assert "次世代電力系統ワーキンググループ" in stubs.args["post"][0][0]

    stubs.calls.clear()
    monkeypatch.setattr("repower.policy.energy_board.cross_check",
                        lambda: {**CROSSCHECK, "added": 0, "missing": []})
    assert CliRunner().invoke(cli.app, ["policy", "crosscheck", "--notify"]).exit_code == 0
    assert "post" not in stubs.calls


def test_digest_posts_unless_dry_run(stubs):
    result = CliRunner().invoke(cli.app, ["policy", "digest", "--since-days", "7"])
    assert result.exit_code == 0, result.output
    assert stubs.args["digest"] == ((), {"since_days": 7})
    assert stubs.args["post"] == (("# Weekly digest",), {})

    stubs.calls.clear()
    assert CliRunner().invoke(cli.app, ["policy", "digest", "--dry-run"]).exit_code == 0
    assert "post" not in stubs.calls


def test_cache_prune_and_export_pass_their_arguments(stubs):
    assert CliRunner().invoke(cli.app, ["cache", "prune", "--days", "90"]).exit_code == 0
    assert stubs.args["prune"] == ((90,), {})

    result = CliRunner().invoke(cli.app, ["export-web", "--out", "web/public/data/web"])
    assert result.exit_code == 0, result.output
    assert stubs.args["export"] == (("web/public/data/web",), {})


def test_every_import_in_the_cli_resolves():
    """Commands import what they use when they run, so a rename breaks only that command."""
    tree = ast.parse((ROOT / "src" / "repower" / "cli.py").read_text(encoding="utf-8"))
    missing = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ImportFrom) and node.module and node.level == 0):
            continue
        mod = importlib.import_module(node.module)
        for alias in node.names:
            if hasattr(mod, alias.name):
                continue
            try:
                importlib.import_module(f"{node.module}.{alias.name}")
            except ImportError:
                missing.append(f"{node.module}.{alias.name}")
    assert not missing


def _command_paths(group: TyperGroup, prefix: tuple[str, ...] = ()):
    for name, cmd in group.commands.items():
        if isinstance(cmd, TyperGroup):  # typer vendors click, so not a click.Group
            yield from _command_paths(cmd, (*prefix, name))
        else:
            yield (*prefix, name)


def test_every_command_renders_its_help():
    root = typer.main.get_command(cli.app)
    assert isinstance(root, TyperGroup)
    paths = list(_command_paths(root))
    assert len(paths) > 30
    for path in paths:
        result = CliRunner().invoke(cli.app, [*path, "--help"])
        assert result.exit_code == 0, (path, result.output)
