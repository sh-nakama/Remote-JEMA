"""The command registry, its argv builder, the run log and the ``/api/commands`` endpoint.

The central guarantee: every command the Commands pane can run is accepted by the *real*
CLI. The registry is checked against the Typer app itself, so a renamed command or flag
fails here instead of becoming a button that errors.
"""

from __future__ import annotations

import http.client
import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import typer

from repower import command_log, commands, web_api
from repower.cli import app
from repower.policy import store
from repower.web_api import _build_policy_argv, _Handler

ROOT = typer.main.get_command(app)
GUIDE = (Path(__file__).resolve().parents[1] / "docs" / "USER-GUIDE.md").read_text(encoding="utf-8")


def _db(tmp_path) -> str:
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    return db


def _known(*keys: str):
    return lambda: set(keys)


def _minimal_params(cmd: commands.Command) -> dict:
    """The smallest valid request: required parameters filled in, the rest defaulted."""
    out: dict = {}
    for p in cmd.params:
        if p.required and p.kind == "committee":
            out[p.name] = "system_review"
        elif p.required and p.kind == "int":
            out[p.name] = max(p.lo, 1)
    return out


# ── The registry against the real CLI ───────────────────────────────────────────
@pytest.mark.parametrize("cmd", commands.COMMANDS, ids=lambda c: c.id)
def test_every_command_is_accepted_by_the_real_cli(cmd):
    """Parse the generated argv with Click, without running anything."""
    argv = commands.build_argv(cmd.id, _minimal_params(cmd), _known("system_review"))
    assert argv[: len(cmd.argv)] == list(cmd.argv)
    node = ROOT  # Typer vendors its own Click, so walk the groups by duck-typing
    for part in cmd.argv:
        assert part in getattr(node, "commands", {}), f"`repower {' '.join(cmd.argv)}` is not a real CLI command"
        node = node.commands[part]
    node.make_context(cmd.id, list(argv[len(cmd.argv):]), resilient_parsing=False)  # raises on a bad flag/value


@pytest.mark.parametrize("cmd", [c for c in commands.COMMANDS if any(p.kind != "bool" for p in c.params)],
                         ids=lambda c: c.id)
def test_extreme_values_still_parse(cmd):
    """The clamped extremes of every int parameter are valid CLI input."""
    node = ROOT
    for part in cmd.argv:
        node = node.commands[part]
    for edge in ("lo", "hi"):
        params = _minimal_params(cmd)
        for p in cmd.params:
            if p.kind == "int" and p.ui:  # `meeting` is the Manage modal's field, not a form field
                params[p.name] = getattr(p, edge)
        argv = commands.build_argv(cmd.id, params, _known("system_review"))
        node.make_context(cmd.id, list(argv[len(cmd.argv):]), resilient_parsing=False)


def test_ids_are_unique_and_groups_valid():
    assert len({c.id for c in commands.COMMANDS}) == len(commands.COMMANDS)
    assert {c.group for c in commands.COMMANDS} == {commands.BACKFLOW, commands.INSPECT, commands.AUTOMATED}
    for group in (commands.BACKFLOW, commands.INSPECT, commands.AUTOMATED):
        orders = [c.order for c in commands.COMMANDS if c.group == group]
        assert len(orders) == len(set(orders)), f"{group}: two commands share a position"


# ── Safety levels and order ───────────────────────────────────────────────────────
def test_only_the_two_database_overwrites_are_dangerous_and_each_says_why():
    dangerous = {c.id for c in commands.COMMANDS if c.level == commands.DANGEROUS}
    assert dangerous == {"pull-hf", "push-hf"}
    for c in commands.COMMANDS:
        assert (c.warning is not None) == (c.level == commands.DANGEROUS), c.id
    assert commands.BY_ID["login"].level == commands.SAFE  # signs in; changes no data


def test_the_backflow_runs_pull_first_and_push_last():
    flow = sorted((c for c in commands.COMMANDS if c.group == commands.BACKFLOW), key=lambda c: c.order)
    assert flow[0].id == "pull-hf" and flow[-1].id == "push-hf"
    # the NotebookLM checks come before the steps that need a session
    ids = [c.id for c in flow]
    assert ids.index("auth") < ids.index("login") < ids.index("backfill") < ids.index("run")
    assert ids.index("resolve-citations") < ids.index("push-hf")


def test_recipes_only_name_real_commands_in_backflow_order():
    for r in commands.RECIPES:
        assert set(r.steps) <= commands.BY_ID.keys() and set(r.optional) <= set(r.steps)
        order = [commands.BY_ID[s].order for s in r.steps]
        assert order == sorted(order), f"{r.id}: steps are out of the backflow order"
        assert r.steps[-1] == "push-hf"
    full = next(r for r in commands.RECIPES if r.id == "backflow")
    assert full.steps[0] == "pull-hf" and "pull-hf" not in full.optional  # the full flow never skips the pull


def test_nothing_that_posts_outward_is_exposed():
    exposed = " ".join(" ".join(c.argv) for c in commands.COMMANDS)
    for banned in ("notify", "run-all", "init-db"):
        assert banned not in exposed
    assert "--notify" not in {a for c in commands.COMMANDS for a in c.fixed}


# ── Argument validation ──────────────────────────────────────────────────────────
def test_defaults_that_protect_the_user():
    k = _known("system_review")
    assert commands.build_argv("digest", {}, k) == ["policy", "digest", "--since-days", "7", "--dry-run"]
    assert "--dry-run" in commands.build_argv("cache-prune", {}, k)  # prune previews unless told otherwise
    assert "--dry-run" not in commands.build_argv("cache-prune", {"dry_run": False}, k)
    assert "--apply" in commands.build_argv("tag", {}, k)  # the button's purpose
    assert "--apply" not in commands.build_argv("tag", {"apply": False}, k)
    assert commands.build_argv("doctor", {}, k) == ["policy", "doctor", "--failing-only"]
    assert commands.build_argv("doctor", {"failing_only": False}, k) == ["policy", "doctor", "--all"]


def test_validation_rejects_what_the_registry_does_not_allow():
    k = _known("system_review")
    with pytest.raises(ValueError, match="unsupported"):
        commands.build_argv("rm -rf /", {}, k)
    with pytest.raises(ValueError, match="unknown committee"):
        commands.build_argv("detect", {"committee": "nope; rm -rf /"}, k)
    with pytest.raises(ValueError, match="one of"):
        commands.build_argv("login", {"browser": "firefox; calc"}, k)
    with pytest.raises(ValueError, match="integer"):
        commands.build_argv("materials", {"limit": "many"}, k)
    with pytest.raises(ValueError, match="required"):
        commands.build_argv("backfill", {"committee": "system_review"}, k)
    # clamped, not trusted
    assert commands.build_argv("resolve-citations", {"max_meetings": 10**6}, k) == [
        "policy", "resolve-citations", "--max-meetings", "50"]
    # a parameter the command does not declare is ignored — it cannot smuggle a flag in
    assert commands.build_argv("pull-hf", {"--force": True, "x": "y"}, k) == ["pull-hf"]


def test_an_optional_committee_is_omitted_unless_chosen():
    k = _known("system_review")
    assert "--committee" not in commands.build_argv("resolve-citations", {}, k)
    assert commands.build_argv("resolve-citations", {"committee": "system_review"}, k)[-2:] == [
        "--committee", "system_review"]
    assert commands.build_argv("coverage", {"committee": "all"}, k) == ["policy", "coverage"]


def test_login_defaults_to_the_bundled_browser():
    assert commands.build_argv("login", {}, _known()) == ["policy", "login", "--browser", "chromium"]
    assert commands.build_argv("login", {"browser": "msedge"}, _known())[-1] == "msedge"


def test_the_api_builder_still_validates_committees_against_the_catalog(tmp_path):
    db = _db(tmp_path)
    assert _build_policy_argv("pull-hf", {}, db) == ["pull-hf"]
    assert _build_policy_argv("materials", {"committee": "system_review", "limit": 5}, db) == [
        "policy", "materials", "--committee", "system_review", "--limit", "5"]
    with pytest.raises(ValueError):
        _build_policy_argv("materials", {"committee": "no_such_committee"}, db)


# ── The catalog sent to the browser ───────────────────────────────────────────────
def test_catalog_is_json_and_leaks_no_cli_flags():
    cat = commands.catalog()
    text = json.dumps(cat, ensure_ascii=False)
    assert '"--' not in text.replace("repower ", "")  # the browser never builds argv
    by = {c["id"]: c for c in cat["commands"]}
    assert by["pull-hf"]["warning"] and by["detect"]["warning"] is None
    assert all(p["name"] != "meeting" for p in by["run"]["params"])  # the Manage modal's field, not a form field
    assert by["backfill"]["needsNotebooklm"] and not by["detect"]["needsNotebooklm"]
    assert by["tag"]["params"][0] == {"name": "apply", "kind": "bool", "label": ["Apply (otherwise dry run)",
                                                                                  "適用（外すとドライラン）"],
                                      "required": False, "default": True}


def test_the_user_guide_documents_every_command():
    """docs/USER-GUIDE.md is the long-form reference; a command with no entry there is undocumented."""
    for c in commands.COMMANDS:
        assert f"repower {' '.join(c.argv)}" in GUIDE, f"`repower {' '.join(c.argv)}` is missing from USER-GUIDE.md"


# ── The run log and the pull/push guards ────────────────────────────────────────────
def _t(hours_ago: float, now: datetime) -> datetime:
    return now - timedelta(hours=hours_ago)


def test_a_pull_warns_about_the_local_work_it_would_discard(tmp_path):
    log, now = tmp_path / "runs.json", datetime(2026, 10, 3, 12, tzinfo=UTC)
    command_log.record("pull-hf", True, at=_t(10, now), path=log)
    command_log.record("resolve-citations", True, at=_t(5, now), path=log)
    command_log.record("detect", True, at=_t(4, now), path=log)
    command_log.record("backfill", False, at=_t(3, now), path=log)  # failed: changed nothing worth warning about
    command_log.record("status", True, at=_t(2, now), path=log)  # read-only
    g = command_log.guards(now=now, path=log)
    assert [u["cmd"] for u in g["unpushed"]] == ["resolve-citations", "detect"]
    assert g["pullAgeHours"] == 10.0 and g["pullStale"] is False


def test_a_push_resets_the_unpushed_list_and_a_pull_does_too(tmp_path):
    log, now = tmp_path / "runs.json", datetime(2026, 10, 3, 12, tzinfo=UTC)
    command_log.record("pull-hf", True, at=_t(10, now), path=log)
    command_log.record("resolve-citations", True, at=_t(5, now), path=log)
    command_log.record("push-hf", True, at=_t(4, now), path=log)
    assert command_log.guards(now=now, path=log)["unpushed"] == []
    command_log.record("detect", True, at=_t(1, now), path=log)
    assert [u["cmd"] for u in command_log.guards(now=now, path=log)["unpushed"]] == ["detect"]


def test_a_push_is_flagged_when_this_copy_was_never_pulled_or_is_old(tmp_path):
    log, now = tmp_path / "runs.json", datetime(2026, 10, 3, 12, tzinfo=UTC)
    g = command_log.guards(now=now, path=log)  # no log at all
    assert g["pullStale"] is True and g["pullAgeHours"] is None and g["lastPull"] is None
    command_log.record("pull-hf", True, at=_t(30, now), path=log)
    assert command_log.guards(now=now, path=log)["pullStale"] is True
    command_log.record("pull-hf", True, at=_t(1, now), path=log)
    assert command_log.guards(now=now, path=log)["pullStale"] is False


def test_a_failed_pull_does_not_count_as_a_pull(tmp_path):
    log, now = tmp_path / "runs.json", datetime(2026, 10, 3, 12, tzinfo=UTC)
    command_log.record("pull-hf", False, at=_t(1, now), path=log)
    assert command_log.guards(now=now, path=log)["lastPull"] is None


def test_the_log_survives_garbage_and_never_raises(tmp_path):
    log = tmp_path / "runs.json"
    log.write_text("{not json", encoding="utf-8")
    assert command_log.guards(path=log)["unpushed"] == []
    command_log.record("detect", True, path=log)  # overwrites the garbage cleanly
    assert [u["cmd"] for u in command_log.guards(path=log)["unpushed"]] == ["detect"]
    blocked = tmp_path / "a-file"
    blocked.write_text("x")
    command_log.record("detect", True, path=blocked / "nested" / "runs.json")  # parent is a file: swallowed


def test_the_log_keeps_only_recent_runs(tmp_path):
    log = tmp_path / "runs.json"
    for _ in range(command_log.KEEP + 10):
        command_log.record("detect", True, path=log)
    assert len(json.loads(log.read_text(encoding="utf-8"))) == command_log.KEEP


def test_refresh_web_counts_as_unpushed_local_work(tmp_path):
    log = tmp_path / "runs.json"
    command_log.record("refresh-web", True, path=log)
    assert [u["cmd"] for u in command_log.guards(path=log)["unpushed"]] == ["refresh-web"]


# ── The job runner records outcomes and protects the DB across a pull ─────────────────
class _FakeProc:
    def __init__(self, code: int):
        self.stdout = iter(["line one\n"])
        self._code = code

    def wait(self, timeout=None):
        return self._code

    def kill(self):  # pragma: no cover - only on timeout
        pass


@pytest.mark.parametrize(("code", "ok"), [(0, True), (1, False)])
def test_a_pull_drops_pooled_connections_before_and_after_and_is_logged(monkeypatch, code, ok):
    calls: list[str] = []
    monkeypatch.setattr(web_api, "dispose_engines", lambda: calls.append("dispose"))
    monkeypatch.setattr(web_api.subprocess, "Popen", lambda *a, **k: (calls.append("spawn"), _FakeProc(code))[1])
    logged: list[tuple[str, bool]] = []
    monkeypatch.setattr(web_api.command_log, "record", lambda cmd, ok_: logged.append((cmd, ok_)))
    with web_api._job_lock:
        web_api._job.update(state="running", cmd="pull-hf")
    web_api._run_command_job(["pull-hf"], timeout=5, cmd_id="pull-hf")
    assert calls == ["dispose", "spawn", "dispose"]  # nothing may hold the old file while it is replaced
    assert logged == [("pull-hf", ok)]


def test_other_commands_do_not_touch_the_engines(monkeypatch):
    monkeypatch.setattr(web_api, "dispose_engines", lambda: pytest.fail("only a pull replaces the DB"))
    monkeypatch.setattr(web_api.subprocess, "Popen", lambda *a, **k: _FakeProc(0))
    monkeypatch.setattr(web_api.command_log, "record", lambda *a: None)
    with web_api._job_lock:
        web_api._job.update(state="running", cmd="detect")
    web_api._run_command_job(["policy", "detect"], timeout=5, cmd_id="detect")


# ── GET /api/commands ──────────────────────────────────────────────────────────────────
@pytest.fixture
def get(tmp_path, monkeypatch):
    monkeypatch.delenv("REPOWER_API_TOKEN", raising=False)
    monkeypatch.setattr(_Handler, "db_path", _db(tmp_path))
    monkeypatch.setattr(command_log, "PATH", tmp_path / "runs.json")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def fetch(path: str, headers: dict | None = None) -> tuple[int, dict]:
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
        conn.request("GET", path, headers=headers or {})
        r = conn.getresponse()
        body = json.loads(r.read())
        conn.close()
        return r.status, body

    yield fetch
    httpd.shutdown()
    httpd.server_close()


def test_api_serves_the_registry_guards_and_committees(get):
    status, body = get("/api/commands")
    assert status == 200 and body["schema"] == 1
    assert {c["id"] for c in body["commands"]} == set(commands.BY_ID)
    assert body["recipes"][0]["steps"][0] == "pull-hf"
    assert body["guards"]["pullStale"] is True and body["guards"]["unpushed"] == []
    assert any(c["key"] == "system_review" for c in body["committees"])


def test_api_commands_is_refused_to_a_foreign_page(get):
    status, _ = get("/api/commands", {"Origin": "https://evil.example"})
    assert status == 403
