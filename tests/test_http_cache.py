"""Tests for the shared conditional-GET cache (repower.scrapers.http_cache).

Network-free: the low-level ``_do_get`` is monkeypatched to simulate responses,
and a temporary SQLite path holds the http_cache table.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from repower.db import HttpCache, get_session, init_db
from repower.scrapers import http_cache


def _patch(monkeypatch, responses):
    """Patch _do_get to yield *responses* in order and record the headers sent.

    Each response is ``(status_code, content, etag, last_modified)``.
    Returns the list that will capture per-call header dicts.
    """
    calls: list[dict] = []
    it = iter(responses)

    def fake_do_get(url, headers, allow_curl_fallback, timeout, deadline=None, retry_transient=True):
        calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "allow_curl_fallback": allow_curl_fallback,
                "timeout": timeout,
            }
        )
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
    statuses in order, and stub out ``time.sleep`` (recording each delay).

    Returns ``(sleeps, made, calls)``: recorded sleep durations, every Session
    constructed, and every ``get`` as ``{"session", "url", "headers"}``.

    The session registries are replaced with fresh dicts via monkeypatch (so they
    are restored afterwards) — module-level sessions would otherwise leak between
    tests, and a stale fake would be reused by the next case.
    """
    import sys
    import types

    seq = iter(status_sequence)
    made: list = []
    calls: list[dict] = []

    class _FakeResp:
        def __init__(self, status):
            self.status_code = status
            self.content = b"cleared" if status == 200 else b""
            self.headers = {"ETag": "e1", "Last-Modified": "lm1"}

    class _FakeSession:
        def __init__(self):
            self.closed = False
            made.append(self)

        def get(self, url, **kwargs):
            calls.append({"session": self, "url": url, "headers": dict(kwargs.get("headers") or {})})
            return _FakeResp(next(seq))

        def close(self):
            self.closed = True

    fake_curl = types.ModuleType("curl_cffi")
    fake_curl.requests = types.SimpleNamespace(Session=_FakeSession)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "curl_cffi", fake_curl)
    monkeypatch.setattr(http_cache, "_curl_sessions", {})
    monkeypatch.setattr(http_cache, "_curl_host_locks", {})
    monkeypatch.setattr(http_cache, "_last_request_at", {})
    monkeypatch.setattr(http_cache, "_circuit_failures", {})
    monkeypatch.setattr(http_cache, "_circuit_open_until", {})

    # A coherent fake clock: sleeping advances monotonic time. Without this the
    # host pacer would see no time pass between retries and pile up spurious
    # waits, which is an artefact of the fake rather than real behaviour.
    sleeps: list[float] = []
    now = {"t": 0.0}

    def fake_sleep(s):
        sleeps.append(s)
        now["t"] += s

    monkeypatch.setattr(http_cache.time, "sleep", fake_sleep)
    monkeypatch.setattr(http_cache.time, "monotonic", lambda: now["t"])
    return sleeps, made, calls


def test_curl_202_challenge_retries_then_succeeds(monkeypatch):
    # Two 202 WAF challenges then a 200: a short warm-up gap precedes the first
    # attempt, then the session backs off (5s, 15s) and clears.
    sleeps, _made, _calls = _fake_curl_cffi(monkeypatch, [202, 202, 200])

    result = http_cache._curl_get("http://x/f", {}, 30.0)

    assert result == (200, b"cleared", "e1", "lm1")
    assert sleeps == [2.0, 5.0, 15.0]


def test_curl_202_challenge_gives_up_after_budget(monkeypatch):
    # Persistent 202: warm-up gap, then the full backoff schedule, then give up
    # (None) so the caller surfaces the failure rather than looping forever.
    sleeps, _made, _calls = _fake_curl_cffi(monkeypatch, [202, 202, 202, 202, 202])

    result = http_cache._curl_get("http://x/f", {}, 30.0)

    assert result is None
    assert sleeps == [http_cache._CHALLENGE_INITIAL_DELAY, *http_cache._CHALLENGE_RETRY_DELAYS]


def test_curl_reuses_one_session_per_host(monkeypatch):
    """Two fetches from the same host must share a session, so a WAF clearance
    cookie earned by the first is replayed by the second instead of being
    re-earned (minutes of challenge backoff) per URL."""
    _sleeps, made, calls = _fake_curl_cffi(monkeypatch, [200, 200])

    http_cache._curl_get("https://meti.example/a", {}, 30.0)
    http_cache._curl_get("https://meti.example/b", {}, 30.0)

    assert len(made) == 1, "a second Session means the cleared cookie jar was thrown away"
    assert calls[0]["session"] is calls[1]["session"]


def test_curl_sessions_are_per_host(monkeypatch):
    # Distinct hosts must not share a cookie jar (cookies are per-domain, and one
    # hostile host shouldn't disturb another).
    _sleeps, made, calls = _fake_curl_cffi(monkeypatch, [200, 200])

    http_cache._curl_get("https://a.example/1", {}, 30.0)
    http_cache._curl_get("https://b.example/1", {}, 30.0)

    assert len(made) == 2
    assert calls[0]["session"] is not calls[1]["session"]


def test_curl_drops_session_after_exhausted_challenge(monkeypatch):
    """Once the challenge budget is spent the cookies have demonstrably failed to
    clear, so the jar must be discarded rather than carried into the next call."""
    _sleeps, made, _calls = _fake_curl_cffi(monkeypatch, [202, 202, 202, 202, 200])

    assert http_cache._curl_get("https://meti.example/a", {}, 30.0) is None
    assert made[0].closed is True
    assert http_cache._curl_sessions == {}

    # The next call starts from a fresh session rather than the poisoned one.
    assert http_cache._curl_get("https://meti.example/b", {}, 30.0) is not None
    assert len(made) == 2


def test_curl_does_not_send_our_default_user_agent(monkeypatch):
    """impersonate="chrome" supplies a UA matching the TLS fingerprint it
    presents. Overriding it with our own (older, different-platform) string is
    the exact mismatch a WAF fingerprints on, so the curl path must not carry it."""
    _sleeps, _made, calls = _fake_curl_cffi(monkeypatch, [200])

    http_cache._curl_get("https://meti.example/a", {"Accept-Language": "ja"}, 30.0)

    assert "User-Agent" not in calls[0]["headers"]
    assert calls[0]["headers"]["Accept-Language"] == "ja"


def test_curl_forwards_a_caller_supplied_user_agent(monkeypatch):
    # Suppressing the *default* UA must not silence a caller that deliberately
    # set one.
    _sleeps, _made, calls = _fake_curl_cffi(monkeypatch, [200])

    http_cache._curl_get("https://meti.example/a", {"User-Agent": "custom/1.0"}, 30.0)

    assert calls[0]["headers"]["User-Agent"] == "custom/1.0"


def test_httpx_path_still_sends_the_default_user_agent(monkeypatch):
    # The default UA is transport-specific, not dropped altogether: plain httpx
    # (which has no impersonation to supply one) must still send it.
    sent: dict = {}

    class _Resp:
        status_code = 200
        content = b"body"
        headers: dict = {}

    def fake_get(url, **kwargs):
        sent.update(kwargs.get("headers") or {})
        return _Resp()

    monkeypatch.setattr(http_cache.httpx, "get", fake_get)
    monkeypatch.setattr(http_cache, "_pace_host", lambda url: None)

    http_cache._do_get("https://a.example/1", {"Accept-Language": "ja"}, False, 30.0)

    assert sent["User-Agent"] == http_cache._DEFAULT_UA
    assert sent["Accept-Language"] == "ja"


def test_caller_user_agent_overrides_the_default_on_the_httpx_path(monkeypatch):
    sent: dict = {}

    class _Resp:
        status_code = 200
        content = b"body"
        headers: dict = {}

    def fake_get(url, **kwargs):
        sent.update(kwargs.get("headers") or {})
        return _Resp()

    monkeypatch.setattr(http_cache.httpx, "get", fake_get)
    monkeypatch.setattr(http_cache, "_pace_host", lambda url: None)

    http_cache._do_get("https://a.example/1", {"User-Agent": "custom/1.0"}, False, 30.0)

    assert sent["User-Agent"] == "custom/1.0"


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




# ── httpx-level fakes: the failure/fallback paths inside _do_get ─────────────
def _fake_httpx(monkeypatch, responses):
    """Patch ``httpx.get`` to yield *responses* in order.

    Each entry is either an ``Exception`` (raised) or ``(status, headers, body)``.
    Returns the list recording each call's url/headers.
    """
    calls: list[dict] = []
    it = iter(responses)

    class _Resp:
        def __init__(self, status, headers, body):
            self.status_code = status
            self.headers = headers or {}
            self.content = body or b""
            self.request = httpx.Request("GET", "http://x/f")

        def raise_for_status(self):
            if 400 <= self.status_code < 600:
                raise httpx.HTTPStatusError(
                    f"status {self.status_code}", request=self.request, response=self
                )

    def fake_get(url, **kwargs):
        calls.append({"url": url, "headers": dict(kwargs.get("headers") or {})})
        nxt = next(it)
        if isinstance(nxt, Exception):
            raise nxt
        return _Resp(*nxt)

    monkeypatch.setattr(http_cache.httpx, "get", fake_get)
    monkeypatch.setattr(http_cache, "_last_request_at", {})
    monkeypatch.setattr(http_cache, "_circuit_failures", {})
    monkeypatch.setattr(http_cache, "_circuit_open_until", {})
    return calls


def _no_curl(monkeypatch):
    """Make the curl fallback unavailable, isolating the plain-httpx path."""
    monkeypatch.setattr(http_cache, "_curl_get", lambda *a, **k: None)


def test_403_falls_back_to_curl(monkeypatch):
    """The Kyuden case: a plain 403 must hand off to the impersonating fallback."""
    _fake_httpx(monkeypatch, [(403, {}, b"")])
    seen = {}

    def fake_curl(url, headers, timeout, deadline=None):
        seen["url"] = url
        return (200, b"via-curl", "e", "lm")

    monkeypatch.setattr(http_cache, "_curl_get", fake_curl)

    assert http_cache._do_get("http://x/f", {}, True, 30.0) == (200, b"via-curl", "e", "lm")
    assert seen["url"] == "http://x/f"


def test_403_without_fallback_raises_blocked(monkeypatch):
    # Typed, so a caller can tell "refused" from "this document is broken".
    _fake_httpx(monkeypatch, [(403, {}, b"")])
    _no_curl(monkeypatch)

    with pytest.raises(http_cache.BlockedError) as ei:
        http_cache._do_get("http://x/f", {}, True, 30.0)
    assert ei.value.status_code == 403
    assert ei.value.host == "x"


def test_202_exhausted_raises_challenge_not_cleared(monkeypatch):
    _fake_httpx(monkeypatch, [(202, {}, b"")])
    _no_curl(monkeypatch)

    with pytest.raises(http_cache.ChallengeNotClearedError):
        http_cache._do_get("http://x/f", {}, True, 30.0)


def test_network_error_falls_back_to_curl(monkeypatch):
    _fake_httpx(monkeypatch, [httpx.ConnectError("boom")])
    monkeypatch.setattr(
        http_cache, "_curl_get", lambda *a, **k: (200, b"rescued", None, None)
    )

    assert http_cache._do_get("http://x/f", {}, True, 30.0)[1] == b"rescued"


def test_network_error_reraises_when_fallback_fails(monkeypatch):
    # The fallback returning None must not swallow the original error.
    _fake_httpx(monkeypatch, [httpx.ConnectError("boom")])
    _no_curl(monkeypatch)

    with pytest.raises(httpx.ConnectError):
        http_cache._do_get("http://x/f", {}, True, 30.0)


def test_5xx_retries_then_succeeds(monkeypatch):
    """A transient blip must not lose the file for the whole run."""
    _fake_httpx(monkeypatch, [(503, {}, b""), (200, {"ETag": "e"}, b"ok")])
    _no_curl(monkeypatch)
    _fake_clock(monkeypatch)

    status, body, etag, _lm = http_cache._do_get("http://x/f", {}, True, 30.0)
    assert (status, body, etag) == (200, b"ok", "e")


def test_5xx_exhausts_retries_and_raises(monkeypatch):
    _fake_httpx(monkeypatch, [(500, {}, b"")] * (http_cache._TRANSIENT_MAX_RETRIES + 1))
    _no_curl(monkeypatch)
    _fake_clock(monkeypatch)

    with pytest.raises(httpx.HTTPStatusError):
        http_cache._do_get("http://x/f", {}, True, 30.0)


def test_5xx_not_retried_when_caller_opts_out(monkeypatch):
    calls = _fake_httpx(monkeypatch, [(500, {}, b"")])
    _no_curl(monkeypatch)

    with pytest.raises(httpx.HTTPStatusError):
        http_cache._do_get("http://x/f", {}, True, 30.0, None, False)
    assert len(calls) == 1, "retry_transient=False must fail fast"


def test_429_honours_retry_after_seconds(monkeypatch):
    _fake_httpx(monkeypatch, [(429, {"Retry-After": "7"}, b""), (200, {}, b"ok")])
    _no_curl(monkeypatch)
    sleeps = _fake_clock(monkeypatch)

    http_cache._do_get("http://x/f", {}, True, 30.0)
    assert 7.0 in sleeps, f"server-advised delay ignored; slept {sleeps}"


def test_retry_after_cap_bounds_a_hostile_header(monkeypatch):
    # A server may ask for an hour; we are not willing to hold the run that long.
    _fake_httpx(monkeypatch, [(429, {"Retry-After": "99999"}, b""), (200, {}, b"ok")])
    _no_curl(monkeypatch)
    sleeps = _fake_clock(monkeypatch)

    http_cache._do_get("http://x/f", {}, True, 30.0)
    assert max(sleeps) <= http_cache._RETRY_AFTER_CAP


def test_retry_after_accepts_http_date():
    from email.utils import format_datetime

    when = datetime.now(UTC) + timedelta(seconds=30)
    parsed = http_cache._parse_retry_after(format_datetime(when))
    assert parsed is not None and 20 <= parsed <= 40


def test_retry_after_ignores_garbage():
    assert http_cache._parse_retry_after("later please") is None
    assert http_cache._parse_retry_after(None) is None


def test_unexpected_status_is_typed(monkeypatch):
    _fake_httpx(monkeypatch, [(206, {}, b"partial")])
    _no_curl(monkeypatch)

    with pytest.raises(http_cache.UnexpectedStatusError) as ei:
        http_cache._do_get("http://x/f", {}, True, 30.0)
    assert ei.value.status_code == 206


def test_force_still_stores_validators(tmp_path, monkeypatch):
    """force=True bypasses the read side, but the write side must still happen —
    the whole policy package relies on it."""
    db = str(tmp_path / "t.db")
    init_db(db)
    _patch(monkeypatch, [(200, b"a", "etag-forced", "lm-forced")])

    http_cache.conditional_get("http://x/f", db_path=db, force=True)

    entry = _cache_entry(db, "http://x/f")
    assert entry.etag == "etag-forced"
    assert entry.last_modified == "lm-forced"


def test_curl_fallback_is_on_by_default(tmp_path, monkeypatch):
    """JEPX/EPRX relied on the default; it must now carry the fallback."""
    db = str(tmp_path / "t.db")
    init_db(db)
    calls = _patch(monkeypatch, [(200, b"a", None, None)])

    http_cache.conditional_get("http://x/f", db_path=db)

    assert calls[0]["allow_curl_fallback"] is True

# ── Circuit breaker, deadline, host normalisation ───────────────────────────
def test_circuit_opens_after_repeated_blocks(monkeypatch):
    """A hostile host must stop costing the full ladder once it has proven itself
    hostile — otherwise one bad host consumes an entire ~85-committee pass."""
    _fake_httpx(monkeypatch, [(403, {}, b"")] * http_cache._CIRCUIT_FAILURE_THRESHOLD)
    _no_curl(monkeypatch)
    _fake_clock(monkeypatch)

    for _ in range(http_cache._CIRCUIT_FAILURE_THRESHOLD):
        with pytest.raises(http_cache.BlockedError):
            http_cache._do_get("http://hostile/f", {}, True, 30.0)

    # The next call must short-circuit *without* issuing a request (the fake
    # response list is exhausted, so any real attempt would raise StopIteration).
    with pytest.raises(http_cache.CircuitOpenError) as ei:
        http_cache._do_get("http://hostile/other", {}, True, 30.0)
    assert ei.value.retry_after > 0


def test_circuit_is_per_host(monkeypatch):
    _fake_httpx(monkeypatch, [(403, {}, b"")] * http_cache._CIRCUIT_FAILURE_THRESHOLD
                + [(200, {}, b"fine")])
    _no_curl(monkeypatch)
    _fake_clock(monkeypatch)

    for _ in range(http_cache._CIRCUIT_FAILURE_THRESHOLD):
        with pytest.raises(http_cache.BlockedError):
            http_cache._do_get("http://hostile/f", {}, True, 30.0)

    # A different host is unaffected.
    assert http_cache._do_get("http://friendly/f", {}, True, 30.0)[0] == 200


def test_circuit_closes_after_success(monkeypatch):
    _fake_httpx(monkeypatch, [(403, {}, b""), (200, {}, b"ok"), (403, {}, b"")])
    _no_curl(monkeypatch)
    _fake_clock(monkeypatch)

    with pytest.raises(http_cache.BlockedError):
        http_cache._do_get("http://h/f", {}, True, 30.0)
    assert http_cache._do_get("http://h/f", {}, True, 30.0)[0] == 200
    # Success reset the counter, so one more failure must not re-open the circuit.
    with pytest.raises(http_cache.BlockedError):
        http_cache._do_get("http://h/f", {}, True, 30.0)


def test_circuit_reopens_for_a_probe_after_cooldown(monkeypatch):
    _fake_httpx(monkeypatch, [(403, {}, b"")] * http_cache._CIRCUIT_FAILURE_THRESHOLD
                + [(200, {}, b"recovered")])
    _no_curl(monkeypatch)
    now = {"t": 0.0}
    monkeypatch.setattr(http_cache.time, "monotonic", lambda: now["t"])
    monkeypatch.setattr(http_cache.time, "sleep", lambda s: now.__setitem__("t", now["t"] + s))

    for _ in range(http_cache._CIRCUIT_FAILURE_THRESHOLD):
        with pytest.raises(http_cache.BlockedError):
            http_cache._do_get("http://h/f", {}, True, 30.0)

    now["t"] += http_cache._CIRCUIT_COOLDOWN + 1
    assert http_cache._do_get("http://h/f", {}, True, 30.0)[0] == 200


def test_deadline_stops_the_challenge_ladder(monkeypatch):
    """The point of the budget: give up early rather than mechanically walking
    the full 2 + 50s ladder."""
    sleeps, _made, _calls = _fake_curl_cffi(monkeypatch, [202, 202, 202, 202, 202])

    result = http_cache._curl_get("http://x/f", {}, 30.0, http_cache._Deadline(10.0))

    assert result is None
    assert sum(sleeps) <= 10.0, f"budget overrun: slept {sum(sleeps)}s"
    assert sleeps != [2.0, 5.0, 15.0, 30.0], "budget did not curtail the ladder"


def test_deadline_expired_raises_before_requesting(monkeypatch):
    calls = _fake_httpx(monkeypatch, [(200, {}, b"never")])
    _no_curl(monkeypatch)
    d = http_cache._Deadline(0.0)

    with pytest.raises(http_cache.DeadlineExceededError):
        http_cache._do_get("http://x/f", {}, True, 30.0, d)
    assert calls == [], "a spent budget must not issue the request"


def test_unbounded_budget_is_the_default(monkeypatch):
    d = http_cache._Deadline(None)
    assert d.remaining() is None
    assert not d.expired()
    assert d.allows(9999.0)
    assert d.clamp_timeout(30.0) == 30.0


def test_host_key_normalises_case_and_default_port():
    # One server must not become three pacing/circuit/cookie buckets.
    assert http_cache._host_key("https://EXAMPLE.go.jp/a") == "example.go.jp"
    assert http_cache._host_key("https://example.go.jp:443/a") == "example.go.jp"
    assert http_cache._host_key("http://example.go.jp:80/a") == "example.go.jp"
    # A non-default port is a genuinely different endpoint.
    assert http_cache._host_key("https://example.go.jp:8443/a") == "example.go.jp:8443"


def test_pacing_treats_normalised_hosts_as_one(monkeypatch):
    sleeps = _fake_clock(monkeypatch)
    monkeypatch.setattr(http_cache, "_last_request_at", {})

    http_cache._pace_host("https://A.example/1")
    http_cache._pace_host("https://a.example:443/2")

    assert sleeps == [http_cache._MIN_HOST_INTERVAL], "case/port variants dodged the pacer"


def test_pace_host_is_threadsafe(monkeypatch):
    """Concurrent callers must *queue*, not all observe the same stale timestamp.

    web_api runs policy catch-up on a background thread, so this is reachable.
    The distinguishing property is not that everyone sleeps, but that each waiter
    queues behind the previous *intended send time* — so the waits grow. If the
    slot were claimed at "now" instead, every thread would compute the same ~1s
    wait and they would all fire at once, silently defeating the pacing.
    """
    import threading

    monkeypatch.setattr(http_cache, "_last_request_at", {})
    slept: list[float] = []
    lock = threading.Lock()

    def record(s):
        with lock:
            slept.append(s)

    monkeypatch.setattr(http_cache.time, "sleep", record)

    threads = [
        threading.Thread(target=http_cache._pace_host, args=("https://h.example/x",))
        for _ in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 8 requests, one free first hit → 7 must wait.
    assert len(slept) == 7, f"pacing lost under concurrency: {slept}"
    # …and the last waiter must be queued well behind the first, i.e. roughly
    # 7 × the interval. All-equal waits would mean they were never serialised.
    expected_last = 6 * http_cache._MIN_HOST_INTERVAL
    assert max(slept) >= expected_last, (
        f"waits did not accumulate ({sorted(slept)}) — callers were not queued "
        "behind each other's intended send time"
    )

# ── Eviction and observability ──────────────────────────────────────────────
def _seed(db, url, status, checked):
    s = get_session(db)
    try:
        s.add(HttpCache(url=url, etag="e", last_modified="lm",
                        last_status=status, last_checked=checked))
        s.commit()
    finally:
        s.close()


def test_prune_drops_only_stale_entries(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    now = datetime.now(UTC)
    _seed(db, "http://h/fresh", 200, now - timedelta(days=1))
    _seed(db, "http://h/stale", 200, now - timedelta(days=200))

    assert http_cache.prune_cache(90, db_path=db) == 1
    assert _cache_entry(db, "http://h/fresh") is not None
    assert _cache_entry(db, "http://h/stale") is None


def test_prune_drops_untimestamped_entries(tmp_path):
    # No last_checked means no evidence of currency — treat as stale.
    db = str(tmp_path / "t.db")
    init_db(db)
    _seed(db, "http://h/old", 200, None)

    assert http_cache.prune_cache(90, db_path=db) == 1


def test_prune_is_safe_to_repeat(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    _seed(db, "http://h/fresh", 200, datetime.now(UTC))

    assert http_cache.prune_cache(90, db_path=db) == 0
    assert http_cache.prune_cache(90, db_path=db) == 0


def test_cache_status_groups_by_host_and_counts_failures(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    now = datetime.now(UTC)
    _seed(db, "https://a.example/1", 200, now)
    _seed(db, "https://A.example:443/2", 304, now)   # same host, normalised
    _seed(db, "https://a.example/3", 500, now)
    _seed(db, "https://b.example/1", 200, now - timedelta(days=5))

    rows = {r["host"]: r for r in http_cache.cache_status(db_path=db)}

    assert rows["a.example"]["entries"] == 3, "case/port variants split the host"
    assert rows["a.example"]["failing"] == 1
    assert rows["a.example"]["last_success"] is not None
    assert rows["b.example"]["entries"] == 1

def test_prune_cutoff_is_timezone_correct(tmp_path):
    """`last_checked` is a naive SQLite column compared against an aware
    `datetime.now(UTC)`. Test at *hour* granularity: a JST/UTC (9h) mix-up would
    delete the 10h-old row or spare the 30h-old one, while a day-granularity test
    would not notice.
    """
    db = str(tmp_path / "tz.db")
    init_db(db)
    now = datetime.now(UTC)
    for label, age_h in [("age_2h", 2), ("age_8h", 8), ("age_10h", 10), ("age_30h", 30)]:
        _seed(db, f"http://h/{label}", 200, now - timedelta(hours=age_h))

    deleted = http_cache.prune_cache(0.5, db_path=db)  # 12 hours

    s = get_session(db)
    try:
        remaining = sorted(r.url.split("/")[-1] for r in s.query(HttpCache).all())
    finally:
        s.close()
    assert deleted == 1
    assert remaining == ["age_10h", "age_2h", "age_8h"]