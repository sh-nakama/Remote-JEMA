"""Tests for the shared conditional-GET cache (repower.scrapers.http_cache).

Network-free: the low-level ``_do_get`` is monkeypatched to simulate responses,
and a temporary SQLite path holds the http_cache table.
"""

from __future__ import annotations

from repower.db import HttpCache, get_session, init_db
from repower.scrapers import http_cache


def _patch(monkeypatch, responses):
    """Patch _do_get to yield *responses* in order and record the headers sent.

    Each response is ``(status_code, content, etag, last_modified)``.
    Returns the list that will capture per-call header dicts.
    """
    calls: list[dict] = []
    it = iter(responses)

    def fake_do_get(url, headers, allow_curl_fallback, timeout):
        calls.append({"url": url, "headers": dict(headers)})
        return next(it)

    monkeypatch.setattr(http_cache, "_do_get", fake_do_get)
    return calls


def _cache_entry(db, url):
    s = get_session(db)
    try:
        return s.get(HttpCache, url)
    finally:
        s.close()


def test_first_fetch_stores_validators(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db)
    calls = _patch(monkeypatch, [(200, b"hello", "etag1", "Mon, 01 Jan 2026")])

    status, content = http_cache.conditional_get("http://x/f", db_path=db)

    assert status == "ok"
    assert content == b"hello"
    # No conditional headers on the first fetch (nothing cached yet).
    assert "If-None-Match" not in calls[0]["headers"]
    entry = _cache_entry(db, "http://x/f")
    assert entry.etag == "etag1"
    assert entry.last_status == 200


def test_second_fetch_sends_conditional_and_304(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch(monkeypatch, [(200, b"hello", "etag1", "Mon, 01 Jan 2026")])
    http_cache.conditional_get("http://x/f", db_path=db)

    calls = _patch(monkeypatch, [(304, None, None, None)])
    status, content = http_cache.conditional_get("http://x/f", db_path=db)

    assert status == "not_modified"
    assert content is None
    # The cached validators must be sent on the second request.
    assert calls[0]["headers"].get("If-None-Match") == "etag1"
    assert calls[0]["headers"].get("If-Modified-Since") == "Mon, 01 Jan 2026"
    # A 304 with no body validators must preserve the previously stored ETag.
    entry = _cache_entry(db, "http://x/f")
    assert entry.etag == "etag1"
    assert entry.last_status == 304


def test_404_returns_not_found(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch(monkeypatch, [(404, None, None, None)])

    status, content = http_cache.conditional_get("http://x/missing", db_path=db)

    assert status == "not_found"
    assert content is None
    # 404s are not persisted (no validators to 304 on; avoids table bloat).
    assert _cache_entry(db, "http://x/missing") is None


def test_force_bypasses_cache(tmp_path, monkeypatch):
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch(monkeypatch, [(200, b"a", "etag1", None)])
    http_cache.conditional_get("http://x/f", db_path=db)

    calls = _patch(monkeypatch, [(200, b"b", "etag2", None)])
    status, content = http_cache.conditional_get("http://x/f", db_path=db, force=True)

    assert status == "ok"
    assert content == b"b"
    # force=True must NOT send conditional headers even though a cache entry exists.
    assert "If-None-Match" not in calls[0]["headers"]
    # And the new validator overwrites the old.
    assert _cache_entry(db, "http://x/f").etag == "etag2"


def test_invalidate_forces_refetch(tmp_path, monkeypatch):
    """A bad 200 body that the caller rejects must not poison the cache: after
    invalidate(), the next request re-fetches (200) instead of 304-skipping."""
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch(monkeypatch, [(200, b"corrupt", "etag1", None)])
    http_cache.conditional_get("http://x/f", db_path=db)

    # Caller decided the body was unusable.
    http_cache.invalidate("http://x/f", db_path=db)
    assert _cache_entry(db, "http://x/f") is None

    calls = _patch(monkeypatch, [(200, b"good", "etag2", None)])
    status, content = http_cache.conditional_get("http://x/f", db_path=db)

    assert status == "ok"
    assert content == b"good"
    # No conditional header → a fresh fetch, not a 304-skip.
    assert "If-None-Match" not in calls[0]["headers"]


def _fake_curl_cffi(monkeypatch, status_sequence):
    """Install a fake ``curl_cffi`` module whose Session.get yields the given
    statuses in order, and stub out ``time.sleep`` (recording each delay)."""
    import sys
    import types

    seq = iter(status_sequence)

    class _FakeResp:
        def __init__(self, status):
            self.status_code = status
            self.content = b"cleared" if status == 200 else b""
            self.headers = {"ETag": "e1", "Last-Modified": "lm1"}

    class _FakeSession:
        def get(self, url, **kwargs):
            return _FakeResp(next(seq))

    fake_curl = types.ModuleType("curl_cffi")
    fake_curl.requests = types.SimpleNamespace(Session=_FakeSession)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "curl_cffi", fake_curl)

    sleeps: list[float] = []
    monkeypatch.setattr(http_cache.time, "sleep", lambda s: sleeps.append(s))
    return sleeps


def test_curl_202_challenge_retries_then_succeeds(monkeypatch):
    # Two 202 WAF challenges then a 200: a short warm-up gap precedes the first
    # attempt, then the persistent session backs off (5s, 15s) and clears.
    sleeps = _fake_curl_cffi(monkeypatch, [202, 202, 200])

    result = http_cache._curl_get("http://x/f", {}, 30.0)

    assert result == (200, b"cleared", "e1", "lm1")
    assert sleeps == [2.0, 5.0, 15.0]


def test_curl_202_challenge_gives_up_after_budget(monkeypatch):
    # Persistent 202: warm-up gap, then the full backoff schedule, then give up
    # (None) so the caller surfaces the failure rather than looping forever.
    sleeps = _fake_curl_cffi(monkeypatch, [202, 202, 202, 202, 202])

    result = http_cache._curl_get("http://x/f", {}, 30.0)

    assert result is None
    assert sleeps == [http_cache._CHALLENGE_INITIAL_DELAY, *http_cache._CHALLENGE_RETRY_DELAYS]


def _fake_clock(monkeypatch):
    """Freeze ``time.monotonic``/``time.sleep`` so pacing is deterministic: sleep
    advances the fake clock. Returns the recorded sleep durations."""
    clock = {"t": 1000.0}
    sleeps: list[float] = []
    monkeypatch.setattr(http_cache.time, "monotonic", lambda: clock["t"])

    def _sleep(s):
        sleeps.append(s)
        clock["t"] += s

    monkeypatch.setattr(http_cache.time, "sleep", _sleep)
    return sleeps


def test_pace_host_spaces_consecutive_same_host_requests(monkeypatch):
    # Back-to-back hits on one host: the first is immediate, the second waits the
    # full politeness interval so we don't machine-gun a single server.
    sleeps = _fake_clock(monkeypatch)
    http_cache._last_request_at.clear()

    http_cache._pace_host("https://a.example/1")
    http_cache._pace_host("https://a.example/2")

    assert sleeps == [http_cache._MIN_HOST_INTERVAL]


def test_pace_host_does_not_serialise_distinct_hosts(monkeypatch):
    # Different hosts don't block each other — no wait for either first hit.
    sleeps = _fake_clock(monkeypatch)
    http_cache._last_request_at.clear()

    http_cache._pace_host("https://a.example/1")
    http_cache._pace_host("https://b.example/1")

    assert sleeps == []


