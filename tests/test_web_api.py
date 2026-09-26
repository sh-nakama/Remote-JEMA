"""Tests for the local web-api policy-command allowlist / argv builder.

The job runner shells out to `repower policy <cmd>`, so the argv builder is the
security boundary: it must reject unknown commands, validate committee keys against
the catalog, require mandatory args, and clamp numeric ones.
"""

from __future__ import annotations

import http.client
import io
import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from repower import web_api
from repower.policy import store
from repower.scrapers import browser_clearance
from repower.web_api import _build_policy_argv, _Handler


def _db(tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    return db


def test_auth_free_and_run_defaults(tmp_path):
    db = _db(tmp_path)
    assert _build_policy_argv("detect", {}, db) == ["policy", "detect", "--committee", "all"]
    assert _build_policy_argv("discover", {}, db) == ["policy", "discover"]
    assert _build_policy_argv("crosscheck", {}, db) == ["policy", "crosscheck"]
    assert _build_policy_argv("run", {}, db) == ["policy", "run", "--committee", "all", "--max-per-run", "5"]
    # digest is forced dry-run so a UI click never posts to the webhook
    assert _build_policy_argv("digest", {}, db) == ["policy", "digest", "--since-days", "7", "--dry-run"]


def test_committee_validated_against_catalog(tmp_path):
    db = _db(tmp_path)
    assert _build_policy_argv("run", {"committee": "system_review"}, db) == [
        "policy", "run", "--committee", "system_review", "--max-per-run", "5",
    ]
    with pytest.raises(ValueError):
        _build_policy_argv("run", {"committee": "no_such_committee"}, db)


def test_backfill_requires_committee_and_since(tmp_path):
    db = _db(tmp_path)
    assert _build_policy_argv(
        "backfill", {"committee": "system_review", "since_meeting": 50}, db
    ) == ["policy", "backfill", "--committee", "system_review", "--since-meeting", "50", "--max-per-run", "10"]
    with pytest.raises(ValueError):  # since_meeting required
        _build_policy_argv("backfill", {"committee": "system_review"}, db)
    with pytest.raises(ValueError):  # committee required (no 'all' for backfill)
        _build_policy_argv("backfill", {"since_meeting": 5}, db)


def test_numeric_args_clamped_and_unknown_cmd_rejected(tmp_path):
    db = _db(tmp_path)
    assert _build_policy_argv("run", {"max_per_run": 999}, db)[-1] == "20"  # clamped to 20
    assert _build_policy_argv("run", {"max_per_run": 0}, db)[-1] == "1"  # clamped to >=1
    with pytest.raises(ValueError):
        _build_policy_argv("rm -rf /", {}, db)
    with pytest.raises(ValueError):
        _build_policy_argv("run", {"committee": "system_review", "max_per_run": "abc"}, db)


def test_single_meeting_run_is_targeted_and_validated(tmp_path):
    """"Run now" must reach exactly one meeting of one real committee — never the
    whole tracked set — so the meeting number and the key are both validated."""
    db = _db(tmp_path)
    assert _build_policy_argv("run", {"committee": "system_review", "meeting": 114}, db) == [
        "policy", "run", "--committee", "system_review", "--meeting", "114",
    ]
    # A meeting number without a real committee must not silently widen to 'all'.
    with pytest.raises(ValueError):
        _build_policy_argv("run", {"meeting": 3}, db)
    with pytest.raises(ValueError):
        _build_policy_argv("run", {"committee": "system_review", "meeting": "not-a-number"}, db)
    # "Latest only" is the ordinary run with a budget of one.
    assert _build_policy_argv("run", {"committee": "system_review", "max_per_run": 1}, db) == [
        "policy", "run", "--committee", "system_review", "--max-per-run", "1",
    ]


# ── Access guard: without a token, only this machine's own pages get in ───────────
def _bare_handler(headers: dict[str, str], peer: str = "127.0.0.1") -> _Handler:
    h = object.__new__(_Handler)  # skip __init__, which would serve a socket
    h.client_address = (peer, 50000)
    h.headers = http.client.HTTPMessage()
    for k, v in headers.items():
        h.headers[k] = v
    return h


@pytest.mark.parametrize("headers", [
    {"Host": "127.0.0.1:8787"},  # curl / the CLI
    {"Host": "127.0.0.1:8787", "Origin": "http://localhost:5173", "Sec-Fetch-Site": "same-origin"},
    {"Host": "127.0.0.1:8787", "Origin": "http://127.0.0.1:5200"},  # Vite moved off its port
    {"Host": "localhost:8787", "Sec-Fetch-Site": "none"},  # typed into the address bar
])
def test_local_requests_are_allowed(headers):
    assert _bare_handler(headers)._local_refusal() is None


@pytest.mark.parametrize(("headers", "peer", "reason"), [
    ({"Host": "127.0.0.1:8787", "Origin": "https://evil.example"}, "127.0.0.1", "cross-origin"),
    ({"Host": "127.0.0.1:8787", "Origin": "null"}, "127.0.0.1", "cross-origin"),
    ({"Host": "127.0.0.1:8787", "Sec-Fetch-Site": "cross-site"}, "127.0.0.1", "cross-site"),
    ({"Host": "127.0.0.1:8787", "Sec-Fetch-Site": "same-site"}, "127.0.0.1", "cross-site"),
    ({"Host": "rebound.evil.example:8787"}, "127.0.0.1", "Host"),
    ({}, "127.0.0.1", "Host"),
    ({"Host": "127.0.0.1:8787"}, "192.168.1.20", "remote client"),
])
def test_foreign_requests_are_refused(headers, peer, reason):
    assert reason in (_bare_handler(headers, peer)._local_refusal() or "")


@pytest.mark.parametrize(("length", "drained"), [(60, True), (web_api._REFUSED_BODY_MAX + 1, False)])
def test_refusal_drains_the_body_it_leaves_unread(length, drained):
    """Unread request bytes turn the close into a reset that can eat the 403."""
    h = _bare_handler({"Host": "127.0.0.1:8787", "Content-Length": str(length)})
    h.rfile, h.wfile = io.BytesIO(b"x" * length), io.BytesIO()
    h.request_version, h.command, h.requestline, h.close_connection = "HTTP/1.1", "POST", "", False
    h._refuse(403, "forbidden")
    assert (h.rfile.tell() == length) is drained
    assert h.close_connection is not drained
    assert h.wfile.getvalue().split(b" ", 2)[1] == b"403"


@pytest.fixture
def api(tmp_path, monkeypatch):
    """A real web-api on an ephemeral loopback port, over a tmp DB."""
    monkeypatch.delenv("REPOWER_API_TOKEN", raising=False)
    db = _db(tmp_path)
    monkeypatch.setattr(_Handler, "db_path", db)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def post(path: str, body: dict, **headers: str) -> int:
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
        conn.request("POST", path, json.dumps(body), {k.replace("_", "-"): v for k, v in headers.items()})
        status = conn.getresponse().status
        conn.close()
        return status

    yield post, db
    httpd.shutdown()
    httpd.server_close()


def _enabled(db: str, key: str) -> bool:
    return next(r["enabled"] for r in store.list_committees(db_path=db) if r["key"] == key)


def test_cross_site_post_is_refused_before_it_can_write(api):
    post, db = api
    # A no-cors text/plain POST from a foreign page: CORS would only hide the answer.
    assert post("/api/policy/track", {"key": "system_review", "enabled": False},
                Origin="https://evil.example", Content_Type="text/plain") == 403
    assert _enabled(db, "system_review") is True

    assert post("/api/policy/track", {"key": "system_review", "enabled": False},
                Origin="http://localhost:5173") == 200
    assert _enabled(db, "system_review") is False


def test_token_mode_requires_the_token(api, monkeypatch):
    post, db = api
    monkeypatch.setenv("REPOWER_API_TOKEN", "s3cret")
    assert post("/api/policy/track", {"key": "system_review", "enabled": False}) == 401
    assert post("/api/policy/track", {"key": "system_review", "enabled": False},
                X_API_Token="s3cret") == 200
    assert _enabled(db, "system_review") is False


# ── Headless browsers are per thread; web-api's threads must close their own ───────
class _FakeBrowser:
    """Stands in for the Playwright context a METI token mint leaves in thread-local state."""

    def __init__(self):
        self.closed = threading.Event()

    def close(self):
        self.closed.set()


def test_a_browser_launched_during_a_request_is_closed_with_it(api, monkeypatch):
    post, _ = api
    browser = _FakeBrowser()

    def mint_then_track(key, enabled, db_path=None):
        browser_clearance._local.context = browser
        return True

    monkeypatch.setattr(store, "set_committee_enabled", mint_then_track)
    assert post("/api/policy/track", {"key": "system_review", "enabled": True}) == 200
    # Closed after the response is written, so wait rather than assert at once.
    assert browser.closed.wait(5)


def test_a_failing_catchup_job_still_closes_its_browser(tmp_path, monkeypatch):
    browser = _FakeBrowser()

    def mint_then_fail(**_):
        browser_clearance._local.context = browser
        raise RuntimeError("METI unreachable")

    monkeypatch.setattr("repower.policy.detect.detect", mint_then_fail)
    job = threading.Thread(target=web_api._run_catchup_job, args=(_db(tmp_path),))
    job.start()
    job.join(30)
    assert browser.closed.is_set()
