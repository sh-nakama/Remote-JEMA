"""Persistent conditional-GET HTTP layer with ETag / Last-Modified caching.

Shared by the TSO area, JEPX, and EPRX scrapers. Cache state lives in the
``http_cache`` table, which is synced to Hugging Face, so 304 "not modified"
skips persist across the (ephemeral) daily CI runs — making the daily scrape
incremental at the file level: static past-month/year files are skipped, only
changed files (the current month/year) are re-downloaded and re-parsed.

Some TSO hosts (e.g. Kyuden behind Akamai) reject plain Python TLS with 403; an
optional ``curl_cffi`` fallback impersonates a real Chrome TLS fingerprint. That
fallback keeps one session per host for the process's lifetime, so a WAF
clearance cookie is reused by later requests instead of being re-earned per URL.

**Fallback policy:** ``allow_curl_fallback`` defaults to ``True``. It is a no-op
unless the plain request returns 403/202 or raises, so the cost of having it on is
nil, while the cost of having it off is a hard failure the day a host adds a bot
rule. A caller that genuinely wants fast, unambiguous failure opts out explicitly
with ``allow_curl_fallback=False`` and a comment saying why.

**Failures are typed** (:class:`HttpCacheError` and subclasses), so callers can
distinguish "this host is refusing us" (back off, try later) from "this document
is broken" (skip permanently) without string-matching error messages. Requests can
also carry a ``budget`` deadline, and a host that repeatedly blocks us trips a
circuit breaker so the rest of a pass fails fast instead of re-walking the ladder.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from repower.db import HttpCache, get_session, init_db
from repower.scrapers import browser_clearance

logger = logging.getLogger(__name__)

Status = Literal["ok", "not_modified", "not_found"]


class HttpCacheError(Exception):
    """Base for failures raised by this layer.

    Carries the *url* and *host* as attributes so callers can classify a failure
    without string-matching the message. Genuine server faults (5xx surviving
    retry) still raise ``httpx.HTTPStatusError`` — these types are specifically
    for "the edge is refusing us" and "this response is not usable".
    """

    def __init__(self, message: str, *, url: str) -> None:
        super().__init__(message)
        self.url = url
        self.host = _host_key(url)


class ChallengeNotClearedError(HttpCacheError):
    """A WAF JavaScript challenge (202) never cleared within the retry budget."""

    def __init__(self, url: str, attempts: int) -> None:
        super().__init__(
            f"WAF challenge not cleared after {attempts} attempt(s) for {url}", url=url
        )
        self.attempts = attempts


class BlockedError(HttpCacheError):
    """The host refused us outright (403, or a challenge with no working fallback).

    Distinct from :class:`ChallengeNotClearedError`: retrying sooner will not help,
    the client itself is being rejected.
    """

    def __init__(self, url: str, status_code: int) -> None:
        super().__init__(f"blocked with status {status_code} for {url}", url=url)
        self.status_code = status_code


class CircuitOpenError(HttpCacheError):
    """Short-circuited: this host recently blocked us repeatedly and is cooling down."""

    def __init__(self, url: str, retry_after: float) -> None:
        super().__init__(
            f"circuit open for {_host_key(url)}; retry in {retry_after:.0f}s ({url})",
            url=url,
        )
        self.retry_after = retry_after


class UnexpectedStatusError(HttpCacheError):
    """A status this layer has no handling for (e.g. 206, or a stray 3xx)."""

    def __init__(self, url: str, status_code: int) -> None:
        super().__init__(f"unexpected status {status_code} for {url}", url=url)
        self.status_code = status_code


class DeadlineExceededError(HttpCacheError):
    """The per-call time budget ran out before a usable response arrived."""

    def __init__(self, url: str, budget: float) -> None:
        super().__init__(f"time budget of {budget:.0f}s exhausted for {url}", url=url)
        self.budget = budget


# ── Failure classification ───────────────────────────────────────────────────
# Stable slugs for *why* a fetch failed. The typed exceptions above already carry
# the distinction; this maps them to short identifiers that can be persisted,
# grouped and compared — so nothing downstream ever has to string-match a message
# to decide whether a committee is blocked, challenged, or simply gone.
FETCH_KINDS: tuple[str, ...] = (
    "ok",                    # 200, body returned
    "unchanged",             # 304, cache validators still good
    "not_found",             # 404
    "blocked_403",           # host refused the client outright
    "challenge_unresolved",  # WAF 202 never cleared within the retry ladder
    "circuit_open",          # host recently blocked us repeatedly; cooling down
    "deadline_exceeded",     # per-call time budget ran out
    "unexpected_status",     # a status this layer has no handling for
    "server_error",          # 5xx/429 surviving the transient retries
    "network_error",         # DNS/TLS/connection/timeout
    "parse_error",           # fetched fine, but the body made no sense
)


def classify(exc: BaseException) -> str:
    """Map an exception raised by this layer to a stable :data:`FETCH_KINDS` slug.

    Callers use this to record *why* a URL could not be fetched. Unknown
    exceptions degrade to ``network_error`` rather than raising, since this runs
    on failure paths where a second failure would mask the original one.
    """
    if isinstance(exc, ChallengeNotClearedError):
        return "challenge_unresolved"
    if isinstance(exc, BlockedError):
        return "blocked_403"
    if isinstance(exc, CircuitOpenError):
        return "circuit_open"
    if isinstance(exc, DeadlineExceededError):
        return "deadline_exceeded"
    if isinstance(exc, UnexpectedStatusError):
        return "unexpected_status"
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 404:
            return "not_found"
        if code == 403:
            return "blocked_403"
        if code == 429 or 500 <= code < 600:
            return "server_error"
        return "unexpected_status"
    return "network_error"


# Politeness: keep at least this many seconds between consecutive requests to the
# same host so a multi-file scrape (version-probing months, EPRX product ZIPs,
# JEPX year files) drips out at a human pace instead of machine-gunning a single
# server. Keyed per host, so unrelated hosts aren't needlessly serialised and a
# host's first hit never waits.
#
# This is a *courtesy* floor, not a throttle-avoidance measure, and the two should
# not be conflated. Measured against meti.go.jp: widening the gap from 1s to 6s
# made things strictly worse (1/12 committees through instead of 4/43), because
# that WAF is stateful rather than rate-based — once it flags the client, waiting
# longer between requests does not appease it. So spacing buys good manners, and
# nothing else; the fix for a hostile host is to stop hammering it (see the
# challenge budget below), not to tiptoe.
#
# _last_request_at is shared mutable state and web_api runs the policy catch-up on
# a background thread, so it is guarded by _pace_lock. The lock covers the
# read/decide/write only — never the sleep itself — and the stored timestamp is the
# *intended* send time, so concurrent callers for one host queue up behind each
# other instead of all observing the same stale `prev` and firing together.
_MIN_HOST_INTERVAL: float = 2.0
_last_request_at: dict[str, float] = {}
_pace_lock = threading.Lock()

_DEFAULT_PORTS = {"http": "80", "https": "443"}


def _host_key(url: str) -> str:
    """Normalised per-host key: lowercased, with an explicit default port dropped.

    ``EXAMPLE.go.jp``, ``example.go.jp`` and ``example.go.jp:443`` are one server
    and must share one pacing bucket, one circuit breaker and one cookie jar.
    """
    parts = urlsplit(url)
    host = (parts.hostname or "").casefold()
    if not host:
        return ""
    port = parts.port
    if port is not None and str(port) != _DEFAULT_PORTS.get(parts.scheme.casefold(), ""):
        return f"{host}:{port}"
    return host


# Per-thread override of the pacing gap, set by :func:`host_pace` for the duration
# of a batch. Thread-local because ``web_api`` runs jobs on a background thread
# while other work may be in flight, and a batch's wider gap must not leak into it.
_pace_override = threading.local()


def min_host_interval() -> float:
    """The politeness floor between same-host requests."""
    return _MIN_HOST_INTERVAL


@contextmanager
def host_pace(interval: float):
    """Widen the inter-request gap to *interval* seconds for this block.

    For pulling a *batch* of files from one host. The floor
    (:data:`_MIN_HOST_INTERVAL`) is a politeness choice sized for one-page-per-host
    sweeps; a meeting with a dozen PDFs is a different shape of request and, as
    measured against METI, a burst that the edge starts challenging partway through.
    Clamped to the floor, so this can only ever slow requests down.
    """
    prev = getattr(_pace_override, "interval", None)
    _pace_override.interval = max(float(interval), _MIN_HOST_INTERVAL)
    try:
        yield
    finally:
        _pace_override.interval = prev


def _pace_host(url: str) -> None:
    """Sleep just long enough that consecutive requests to *url*'s host are at
    least ``_MIN_HOST_INTERVAL`` seconds apart (or the wider gap a surrounding
    :func:`host_pace` asked for). A host's first request never waits; distinct
    hosts don't block each other."""
    host = _host_key(url)
    if not host:
        return
    gap = getattr(_pace_override, "interval", None) or _MIN_HOST_INTERVAL
    with _pace_lock:
        now = time.monotonic()
        prev = _last_request_at.get(host)
        wait = 0.0 if prev is None else gap - (now - prev)
        if wait < 0:
            wait = 0.0
        # Claim our slot before releasing: the next caller paces off the moment we
        # intend to send, not off whenever we happen to wake up.
        _last_request_at[host] = now + wait
    if wait > 0:
        time.sleep(wait)


def pace_host(url: str) -> None:
    """Public per-host politeness gate for callers that issue their own requests.

    Code that bypasses :func:`conditional_get` (the OCCTO existence probes) must
    still share the same per-host floor, otherwise the advertised 1 req/s is a
    fiction on exactly the tightest loops we run.
    """
    _pace_host(url)


def reset_pacing() -> None:
    """Forget all host pacing state (tests; nothing in production needs this)."""
    with _pace_lock:
        _last_request_at.clear()


# Per-host circuit breaker. Once a host has blocked/challenged us this many times
# in a row, every further request to it short-circuits for a cooldown window
# instead of paying the round-trip again to rediscover the same fact. One success
# closes the circuit immediately.
#
# This is what stops a hostile host from turning an ~85-committee pass into hours.
# It works together with _challenge_exhausted below: that caps the expensive
# challenge ladder at one walk per host, and this then stops issuing requests at
# all once the host has made its position clear.
_CIRCUIT_FAILURE_THRESHOLD = 3
_CIRCUIT_COOLDOWN: float = 300.0
_circuit_failures: dict[str, int] = {}
_circuit_open_until: dict[str, float] = {}
_circuit_lock = threading.Lock()

# Hosts whose 202 challenge ladder (see _CHALLENGE_RETRY_DELAYS) has already been
# walked to exhaustion since their last success. The ladder exists to give a *cold*
# WAF time to arm its clearance cookie, which is worth ~50s once. It is not worth
# paying per URL: a sweep of 43 METI committees used to spend the full ladder on
# each of the first three — ~165s to arrive at the same answer three times — before
# the circuit opened.
#
# So the ladder is spent at most once per host per healthy period. Afterwards that
# host still gets a real request (the plain path can return 200/304 the moment the
# WAF relents, and a success clears this flag) — it just no longer waits around
# through a full backoff to be told "no" again.
#
# Lives here, under _circuit_lock: this and the counters above are both per-host
# hostility state, cleared by the same success.
_challenge_exhausted: set[str] = set()


def _circuit_retry_after(url: str) -> float:
    """Seconds until *url*'s host is allowed again; 0.0 if it is allowed now."""
    host = _host_key(url)
    if not host:
        return 0.0
    with _circuit_lock:
        until = _circuit_open_until.get(host)
        if until is None:
            return 0.0
        remaining = until - time.monotonic()
        if remaining <= 0:
            # Cooldown elapsed: let exactly one probe through and judge by it.
            _circuit_open_until.pop(host, None)
            _circuit_failures[host] = _CIRCUIT_FAILURE_THRESHOLD - 1
            return 0.0
        return remaining


def circuit_cooldown(url: str) -> float:
    """Seconds until *url*'s host is allowed again; ``0.0`` if it is allowed now.

    Read-only, unlike :func:`_circuit_retry_after`, which consumes the single probe
    allowed once a cooldown elapses. Callers use this to *skip* work aimed at a host
    that is currently cooling down, rather than queueing thousands of requests that
    will each fail instantly — the failure mode this was written for was a run
    walking an entire committee backlog in under a second, marking every meeting
    blocked, because the breaker had opened on its third meeting.
    """
    host = _host_key(url)
    if not host:
        return 0.0
    with _circuit_lock:
        until = _circuit_open_until.get(host)
        if until is None:
            return 0.0
        return max(0.0, until - time.monotonic())


def _circuit_record_failure(url: str) -> None:
    """Count a block/challenge against *url*'s host, opening the circuit at the
    threshold."""
    host = _host_key(url)
    if not host:
        return
    with _circuit_lock:
        n = _circuit_failures.get(host, 0) + 1
        _circuit_failures[host] = n
        if n >= _CIRCUIT_FAILURE_THRESHOLD:
            _circuit_open_until[host] = time.monotonic() + _CIRCUIT_COOLDOWN
            logger.warning(
                "http_cache: %s blocked us %d times in a row; "
                "short-circuiting further requests for %.0fs",
                host,
                n,
                _CIRCUIT_COOLDOWN,
            )


def _circuit_record_success(url: str) -> None:
    """A usable response closes *url*'s host circuit."""
    host = _host_key(url)
    if not host:
        return
    with _circuit_lock:
        # Unconditional: the host is demonstrably serving us again, so it has
        # earned a fresh challenge ladder even if no failure was ever counted
        # (a ladder can exhaust without the circuit reaching its threshold).
        _challenge_exhausted.discard(host)
        if _circuit_failures.pop(host, None) is not None:
            _circuit_open_until.pop(host, None)


def _challenge_ladder_for(url: str) -> tuple[float, ...]:
    """Backoff delays to use for *url*'s next 202 challenge.

    Full ladder for a host that hasn't yet failed one, empty afterwards — see
    ``_challenge_exhausted``.
    """
    host = _host_key(url)
    if not host:
        return _CHALLENGE_RETRY_DELAYS
    with _circuit_lock:
        return () if host in _challenge_exhausted else _CHALLENGE_RETRY_DELAYS


def _mark_challenge_exhausted(url: str) -> None:
    """Record that *url*'s host ran out of challenge retries, so later URLs on
    that host don't each re-pay the ladder to learn the same thing."""
    host = _host_key(url)
    if not host:
        return
    with _circuit_lock:
        _challenge_exhausted.add(host)


def reset_circuits() -> None:
    """Forget all circuit-breaker state (tests, and manual recovery)."""
    with _circuit_lock:
        _circuit_failures.clear()
        _circuit_open_until.clear()
        _challenge_exhausted.clear()


class _Deadline:
    """Per-call time budget, shared by the retry ladders so they can't stack.

    ``None`` budget means unbounded, preserving the previous behaviour for callers
    that don't opt in.
    """

    __slots__ = ("budget", "started")

    def __init__(self, budget: float | None) -> None:
        self.budget = budget
        self.started = time.monotonic()

    def remaining(self) -> float | None:
        if self.budget is None:
            return None
        return self.budget - (time.monotonic() - self.started)

    def expired(self) -> bool:
        rem = self.remaining()
        return rem is not None and rem <= 0

    def allows(self, sleep_for: float) -> bool:
        """True if sleeping *sleep_for* would still leave time to act afterwards."""
        rem = self.remaining()
        return rem is None or sleep_for < rem

    def clamp_timeout(self, timeout: float) -> float:
        """Never let a single request outlive the budget."""
        rem = self.remaining()
        if rem is None:
            return timeout
        return max(0.1, min(timeout, rem))

    def check(self, url: str) -> None:
        if self.expired():
            raise DeadlineExceededError(url, self.budget or 0.0)


# 202 = WAF/Akamai JavaScript challenge (meti.go.jp / egc.meti.go.jp sit behind
# CloudFront + WAF). The edge serves the challenge first and only arms the
# clearance cookie a moment later, so a single retry often still sees 202. We
# retry a few times with a lengthening, deliberately un-aggressive backoff
# (seconds, not milliseconds) to stay a polite client while giving the WAF time
# to arm the cookie on the host's curl_cffi session.
_CHALLENGE_RETRY_DELAYS: tuple[float, ...] = (5.0, 15.0, 30.0)
# Firing the impersonating fallback in the same instant as the plain-httpx 202
# just trips the challenge again — the edge reads the back-to-back hit as bot
# traffic. Pause briefly first so the initial fallback request lands at a human
# pace instead of milliseconds after the block.
_CHALLENGE_INITIAL_DELAY: float = 2.0

# Transient-failure retries (429 / 5xx) on the plain-httpx path. Deliberately
# short and few: unlike the WAF ladder these are for a server having a moment, and
# every one competes with the rest of the pass for the run's time budget.
_TRANSIENT_MAX_RETRIES = 3
_TRANSIENT_BASE_DELAY: float = 1.0
# Jitter spreads retries so a batch of URLs failing together doesn't resynchronise
# into a thundering herd on the recovering server.
_TRANSIENT_JITTER: float = 0.25
# Ceiling for any single wait, including a server-supplied Retry-After. A server
# is allowed to ask for an hour; we are not willing to hold the run that long.
_RETRY_AFTER_CAP: float = 60.0

# Sent on the plain-httpx path only. The curl_cffi path deliberately does NOT get
# this header: ``impersonate="chrome"`` already supplies the User-Agent matching
# the TLS/HTTP2 fingerprint it presents, and overriding it with a different
# (older, different-platform) string is exactly the inconsistency a WAF looks for.
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# The rest of a browser's navigation headers. A lone User-Agent is a tell — and
# more concretely, AWS WAF only serves its challenge *page* to a request whose
# Accept admits text/html; with httpx's default ``*/*`` the 202 comes back with an
# empty body, so the client cannot even see what it is being asked to do.
# Accept-Encoding is deliberately absent: httpx sets it from the codecs it can
# actually decode, and advertising one we can't is worse than not looking like a
# browser.
_BROWSER_HEADERS: dict[str, str] = {
    "User-Agent": _DEFAULT_UA,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# AWS WAF names the action it took. ``challenge`` means a JavaScript proof-of-work
# stands between us and the page — see repower.scrapers.browser_clearance.
_WAF_ACTION_HEADER = "x-amzn-waf-action"
_WAF_CHALLENGE_ACTION = "challenge"

# One httpx client per host for the process's lifetime. Previously every request
# went through module-level ``httpx.get``, i.e. a fresh client: a new TLS
# handshake each time and, worse, a cookie jar that was discarded before the next
# request could use it — so no clearance or session cookie could ever accumulate.
_http_clients: dict[str, httpx.Client] = {}
_http_client_lock = threading.Lock()


def _http_client(url: str) -> httpx.Client:
    """The persistent client for *url*'s host, created on first use.

    Per host so one server's cookies and connections stay its own, and so a
    wedged client can be discarded without disturbing the others.
    """
    host = _host_key(url)
    with _http_client_lock:
        client = _http_clients.get(host)
        if client is None:
            client = httpx.Client(follow_redirects=True)
            _http_clients[host] = client
        return client


def reset_http_clients() -> None:
    """Close and forget every per-host client (tests, and manual recovery)."""
    with _http_client_lock:
        clients = list(_http_clients.values())
        _http_clients.clear()
    for client in clients:
        _close_quietly(client)


def _is_waf_challenge(resp: Any) -> bool:
    """True if *resp* is an AWS WAF JavaScript challenge rather than a plain block."""
    action = resp.headers.get(_WAF_ACTION_HEADER) or ""
    return action.strip().casefold() == _WAF_CHALLENGE_ACTION


# One curl_cffi session per host, reused for the process's lifetime, so a WAF
# clearance cookie earned on one URL is replayed on the host's later URLs instead
# of being re-earned (minutes of challenge backoff) per URL. Keyed per host both
# because cookies are per-domain and so one hostile host can't disturb another.
#
# curl_cffi sessions are not documented as thread-safe and web_api runs the
# policy catch-up on a background thread, so each host's session is used under
# its own lock, held for the whole of _curl_get. Same-host fallback requests are
# thereby serialised (which politeness wants anyway); distinct hosts don't block
# each other. _curl_state_lock guards only the two registries below — never a
# network call — so it is never held while a request or backoff sleep is running.
_curl_sessions: dict[str, Any] = {}
_curl_host_locks: dict[str, threading.Lock] = {}
_curl_state_lock = threading.Lock()


def _curl_host_lock(host: str) -> threading.Lock:
    """Return (creating if needed) the lock serialising *host*'s curl session."""
    with _curl_state_lock:
        lock = _curl_host_locks.get(host)
        if lock is None:
            lock = threading.Lock()
            _curl_host_locks[host] = lock
        return lock


def _close_quietly(session: Any) -> None:
    close = getattr(session, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception as e:  # noqa: BLE001
        logger.debug("curl_cffi session close failed: %s", e)


def _curl_session_for(host: str, cr: Any) -> Any | None:
    """Return *host*'s cached curl_cffi session, creating it on first use.

    Returns None if the session cannot be constructed, so the caller can fall
    through to its normal failure path.
    """
    with _curl_state_lock:
        session = _curl_sessions.get(host)
    if session is not None:
        return session
    try:
        session = cr.Session()
    except Exception as e:  # noqa: BLE001
        logger.debug("curl_cffi session init failed for %s: %s", host, e)
        return None
    with _curl_state_lock:
        # Another thread may have raced us here; keep whichever landed first so
        # every caller for this host shares one cookie jar.
        existing = _curl_sessions.setdefault(host, session)
    if existing is not session:
        _close_quietly(session)
    return existing


def reset_curl_sessions(host: str | None = None) -> None:
    """Discard cached curl_cffi session(s), for *host* or all hosts.

    Called when a host's challenge budget is exhausted — at that point its cookie
    jar has demonstrably failed to clear, so keeping it only carries the bad state
    into the next attempt. Also the escape hatch for a session wedged some other
    way (and for tests, which must not share sessions between cases).
    """
    with _curl_state_lock:
        if host is None:
            sessions = list(_curl_sessions.values())
            _curl_sessions.clear()
        else:
            popped = _curl_sessions.pop(host, None)
            sessions = [popped] if popped is not None else []
    for s in sessions:
        _close_quietly(s)


def conditional_get(
    url: str,
    *,
    db_path: str | None = None,
    headers: dict | None = None,
    allow_curl_fallback: bool = True,
    force: bool = False,
    timeout: float = 30.0,
    budget: float | None = None,
    retry_transient: bool = True,
) -> tuple[Status, bytes | None]:
    """GET *url* with persistent conditional-GET caching.

    Returns ``("ok", content)`` on 200, ``("not_modified", None)`` on 304, and
    ``("not_found", None)`` on 404. Raises on other/unexpected HTTP errors so
    callers can log and try the next URL. ETag/Last-Modified are stored per URL,
    so the next run sends ``If-None-Match`` / ``If-Modified-Since`` and the
    server returns 304 for unchanged files (skipping both download and parse).

    Set ``force=True`` to bypass the cache and always re-download.

    ``budget`` caps the total wall-clock time for this URL across every retry and
    backoff, raising :class:`DeadlineExceededError` rather than mechanically
    walking the full ladder. ``None`` (default) is unbounded.

    ``retry_transient=False`` opts out of the 429/5xx retries for callers that
    prefer to fail fast.

    Failures are typed (see :class:`HttpCacheError` and its subclasses) so callers
    can tell "this host is refusing us" from "this document is broken".
    """
    init_db(db_path)
    session = get_session(db_path)
    deadline = _Deadline(budget)
    try:
        # No default User-Agent here: it is transport-specific and is added by
        # _do_get for the plain-httpx request only. A caller-supplied UA does
        # travel on both paths, overriding the default.
        req_headers = dict(headers or {})
        if not force:
            entry = session.get(HttpCache, url)
            if entry is not None:
                if entry.etag:
                    req_headers["If-None-Match"] = entry.etag
                if entry.last_modified:
                    req_headers["If-Modified-Since"] = entry.last_modified

        status_code, content, etag, last_modified = _do_get(
            url, req_headers, allow_curl_fallback, timeout, deadline, retry_transient
        )

        if status_code == 304:
            _store(session, url, etag, last_modified, 304)
            return ("not_modified", None)
        if status_code == 404:
            # Don't persist 404s: version-probing hits many non-existent URLs and
            # a 404 carries no validator to 304 on, so caching it only bloats the
            # synced table. Re-probe every run (a month may appear later).
            return ("not_found", None)
        if status_code == 200:
            _store(session, url, etag, last_modified, 200)
            return ("ok", content)
        raise UnexpectedStatusError(url, status_code)
    except Exception as exc:  # noqa: BLE001 — record, then re-raise unchanged
        _store_error(session, url, classify(exc), str(exc))
        raise
    finally:
        session.close()


def invalidate(url: str, db_path: str | None = None) -> None:
    """Drop any cached entry for *url* so the next request re-fetches (200).

    Call this when a 200 body turns out to be unusable (corrupt ZIP, non-archive
    bytes, unparseable/empty CSV). Without it, the validators stored on the bad
    200 would make the next run 304-skip the file permanently, silently losing
    that month/year until the upstream file changes again.
    """
    init_db(db_path)
    session = get_session(db_path)
    try:
        entry = session.get(HttpCache, url)
        if entry is not None:
            session.delete(entry)
            session.commit()
    finally:
        session.close()


def prune_cache(older_than_days: float = 90, db_path: str | None = None) -> int:
    """Drop cache entries not seen in *older_than_days*. Returns rows deleted.

    Safe by construction: a missing entry costs exactly one unconditional
    re-fetch, never lost data. Without this the table only grows — superseded
    month/year files, retired EPRX products, committee pages that will never
    change — and it is pushed to and pulled from Hugging Face on every run.

    Rows with no ``last_checked`` at all are treated as stale: they predate the
    timestamping and carry no evidence of being current.
    """
    init_db(db_path)
    session = get_session(db_path)
    try:
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        stale = (
            session.query(HttpCache)
            .filter(
                (HttpCache.last_checked.is_(None)) | (HttpCache.last_checked < cutoff)
            )
            .all()
        )
        for entry in stale:
            session.delete(entry)
        session.commit()
        if stale:
            logger.info(
                "http_cache: pruned %d entries not seen in %d days", len(stale), older_than_days
            )
        return len(stale)
    finally:
        session.close()


def cache_status(db_path: str | None = None) -> list[dict]:
    """Per-host cache summary, newest activity first.

    Turns ``last_checked`` — written on every request and, until now, never read
    — into the observability we lacked while diagnosing the METI WAF blocks:
    which hosts are still succeeding, when each was last seen, and how many of
    its entries last came back as something other than 200.

    ``errors`` counts entries currently carrying an unresolved failure and
    ``error_kinds`` breaks those down by :data:`FETCH_KINDS` slug — the states
    that never reach ``last_status`` because they raise before the row is stored.

    Each row: ``{host, entries, last_success, last_checked, failing, errors,
    error_kinds}``.
    """
    init_db(db_path)
    session = get_session(db_path)
    try:
        hosts: dict[str, dict] = {}
        for entry in session.query(HttpCache).all():
            host = _host_key(str(entry.url)) or "(unknown)"
            row = hosts.setdefault(
                host,
                {
                    "host": host,
                    "entries": 0,
                    "last_success": None,
                    "last_checked": None,
                    "failing": 0,
                    "errors": 0,
                    "error_kinds": {},
                },
            )
            row["entries"] += 1
            checked = entry.last_checked
            if checked is not None:
                if row["last_checked"] is None or checked > row["last_checked"]:
                    row["last_checked"] = checked
                if entry.last_status in (200, 304) and (
                    row["last_success"] is None or checked > row["last_success"]
                ):
                    row["last_success"] = checked
            if entry.last_status not in (200, 304):
                row["failing"] += 1
            if entry.last_error_kind:
                row["errors"] += 1
                kinds = row["error_kinds"]
                kinds[entry.last_error_kind] = kinds.get(entry.last_error_kind, 0) + 1
        return sorted(
            hosts.values(),
            key=lambda r: (r["last_checked"] is not None, r["last_checked"]),
            reverse=True,
        )
    finally:
        session.close()


def _store(session, url: str, etag, last_modified, status: int) -> None:
    """Persist cache validators. On 304 keep prior validators (the response may
    omit them); on 200/404 replace them with whatever the response carried so a
    server that drops ETags can't trigger a stale false-304 next time."""
    entry = session.get(HttpCache, url)
    if entry is None:
        entry = HttpCache(url=url)
        session.add(entry)
    if status == 304:
        if etag is not None:
            entry.etag = etag
        if last_modified is not None:
            entry.last_modified = last_modified
    else:
        entry.etag = etag
        entry.last_modified = last_modified
    entry.last_status = status
    entry.last_checked = datetime.now(UTC)
    # A success clears any recorded failure, so `last_error_kind` always answers
    # "why is this URL currently unfetchable?" rather than "did it ever fail?".
    entry.last_error_kind = None
    entry.last_error_at = None
    entry.last_error_detail = None
    session.commit()


def _store_error(session, url: str, kind: str, detail: str) -> None:
    """Record *why* a URL could not be fetched, without disturbing the cache state.

    Two invariants make this safe to call on every failure path:

    - ``etag``/``last_modified`` are left untouched. Clearing them on a 403 would
      make the next successful fetch re-download a file that never changed.
    - ``last_checked`` is left untouched. :func:`prune_cache` keys on it, so
      bumping it here would keep permanently-dead URLs alive forever in a table
      that is synced to Hugging Face.

    Best-effort: a failure to record a failure must never replace the original
    exception the caller is about to see.
    """
    try:
        entry = session.get(HttpCache, url)
        if entry is None:
            # No validators to protect yet; the row exists purely to carry the
            # error. last_checked stays NULL so prune_cache treats it as stale.
            entry = HttpCache(url=url)
            session.add(entry)
        entry.last_error_kind = kind
        entry.last_error_at = datetime.now(UTC)
        entry.last_error_detail = detail[:500]
        session.commit()
    except Exception as e:  # noqa: BLE001
        logger.debug("http_cache: could not record error for %s: %s", url, e)
        session.rollback()


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a ``Retry-After`` header in either form the RFC allows.

    Returns seconds, or None if absent/unparseable. Both delta-seconds ("120")
    and the HTTP-date form ("Wed, 21 Oct 2015 07:28:00 GMT") are accepted.
    """
    if not value:
        return None
    raw = value.strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _transient_delay(resp: httpx.Response, attempt: int) -> float:
    """How long to wait before retrying a 429/5xx.

    A server-supplied ``Retry-After`` wins (capped, so a hostile or mistaken
    header can't park the run for an hour); otherwise exponential backoff with
    jitter to avoid synchronising retries across a batch of URLs.
    """
    advised = _parse_retry_after(resp.headers.get("Retry-After"))
    if advised is not None:
        return min(advised, _RETRY_AFTER_CAP)
    base = _TRANSIENT_BASE_DELAY * (2**attempt)
    return min(base, _RETRY_AFTER_CAP) * (1.0 + random.random() * _TRANSIENT_JITTER)


def _do_get(
    url: str,
    headers: dict,
    allow_curl_fallback: bool,
    timeout: float,
    deadline: _Deadline | None = None,
    retry_transient: bool = True,
):
    """Return ``(status_code, content|None, etag, last_modified)``. Raises on
    unexpected HTTP/network errors (after trying the curl fallback if allowed).

    429 and 5xx are retried within the deadline (honouring ``Retry-After``); a
    host that keeps blocking us trips its circuit breaker and subsequent calls
    fail immediately instead of re-walking the ladder.
    """
    deadline = deadline or _Deadline(None)

    waiting = _circuit_retry_after(url)
    if waiting > 0:
        raise CircuitOpenError(url, waiting)

    last_resp: httpx.Response | None = None
    for attempt in range(_TRANSIENT_MAX_RETRIES + 1):
        deadline.check(url)
        _pace_host(url)  # space consecutive same-host requests to a human pace
        # The default UA belongs to this transport only — the curl fallback gets the
        # headers untouched so impersonation supplies a UA matching its fingerprint.
        httpx_headers = {**_BROWSER_HEADERS, **headers}
        try:
            resp = _http_client(url).get(
                url,
                timeout=deadline.clamp_timeout(timeout),
                headers=httpx_headers,
            )
        except Exception:
            if allow_curl_fallback:
                r = _curl_get(url, headers, timeout, deadline)
                if r is not None:
                    _circuit_record_success(url)
                    return r
            raise
        last_resp = resp
        # 403 = plain bot block; 202 = AWS WAF JavaScript challenge (meti.go.jp sits
        # behind CloudFront + WAF and answers plain HTTP stacks with either). Both
        # yield to the browser-impersonating fallback.
        if resp.status_code in (403, 202):
            # An AWS WAF *challenge* is a JavaScript proof-of-work, so no amount of
            # waiting will clear it and the backoff ladder is dead time; only a
            # browser-minted token helps, which _curl_get goes and fetches.
            js_challenge = _is_waf_challenge(resp)
            # Snapshot before the fallback: it marks the host exhausted on failure,
            # so asking afterwards would report 1 attempt even for the full ladder.
            # This number reaches last_error_detail, so it has to be the truth.
            attempts = 1 if js_challenge else len(_challenge_ladder_for(url)) + 1
            if allow_curl_fallback:
                r = _curl_get(url, headers, timeout, deadline, js_challenge=js_challenge)
                if r is not None:
                    _circuit_record_success(url)
                    return r
            if js_challenge:
                # Last resort, and the only one that can actually work: a real
                # browser runs the proof-of-work. Costly, so it is reached only
                # after the cheap transports have been refused.
                r = browser_clearance.fetch(url, httpx_headers)
                if r is not None and r[0] in (200, 304, 404):
                    _circuit_record_success(url)
                    return r
            # Fallback unavailable, or it could not clear the block either.
            _circuit_record_failure(url)
            if resp.status_code == 202:
                raise ChallengeNotClearedError(url, attempts)
            raise BlockedError(url, resp.status_code)
        if resp.status_code in (200, 304, 404):
            _circuit_record_success(url)
            body = resp.content if resp.status_code == 200 else None
            return (
                resp.status_code,
                body,
                resp.headers.get("ETag"),
                resp.headers.get("Last-Modified"),
            )
        # 429/5xx are transient by definition: a single blip would otherwise lose
        # this month/year file until some later run happens to succeed.
        transient = resp.status_code == 429 or 500 <= resp.status_code < 600
        if transient and retry_transient and attempt < _TRANSIENT_MAX_RETRIES:
            delay = _transient_delay(resp, attempt)
            if deadline.allows(delay):
                logger.info(
                    "http_cache %s -> %s; retrying in %.1fs (%d/%d)",
                    url,
                    resp.status_code,
                    delay,
                    attempt + 1,
                    _TRANSIENT_MAX_RETRIES,
                )
                time.sleep(delay)
                continue
            deadline.check(url)
        break

    if last_resp is None:
        # Unreachable: every path to the break assigns last_resp first. Guard
        # rather than assert, since `python -O` strips asserts and this would then
        # fail as an opaque AttributeError.
        raise UnexpectedStatusError(url, 0)
    last_resp.raise_for_status()  # 4xx/5xx → raise for the caller to handle
    # Any other status (2xx like 206, or 3xx) is unexpected for these static
    # file endpoints — treat as an error rather than a complete body.
    raise UnexpectedStatusError(url, last_resp.status_code)


def _apply_clearance(session: Any, url: str) -> bool:
    """Put a browser-minted WAF token on *session*'s cookie jar.

    Returns True if one was applied. Best-effort: clearance is an optimisation,
    so a browser that won't start must not turn into a fetch failure.
    """
    try:
        cookies = browser_clearance.cookies_for(url)
        if not cookies:
            return False
        for name, value in cookies.items():
            session.cookies.set(name, value, domain=_host_key(url))
    except Exception as e:  # noqa: BLE001
        logger.debug("could not apply clearance cookies for %s: %s", url, e)
        return False
    return True


def _curl_get(
    url: str,
    headers: dict,
    timeout: float,
    deadline: _Deadline | None = None,
    js_challenge: bool = False,
):
    """curl_cffi Chrome-impersonation fallback. Returns the same 4-tuple, or
    None if curl_cffi is unavailable or the request did not yield a usable
    status. Conditional headers are forwarded so 304s still work for Kyuden.

    No User-Agent is added here: ``impersonate="chrome"`` supplies one consistent
    with the TLS/HTTP2 fingerprint it presents. A caller that set its own UA in
    *headers* still has it honoured.

    The host's session is reused across calls (see ``_curl_sessions``), so a
    WAF/Akamai clearance cookie earned once is replayed by the host's later URLs
    rather than being re-earned per URL.

    ``js_challenge`` says the block was an AWS WAF challenge. That changes the
    strategy completely: impersonation alone cannot solve a proof-of-work, so
    instead of backing off we ask :mod:`repower.scrapers.browser_clearance` for a
    browser-minted token and make a single attempt carrying it. Otherwise (a
    fingerprint-style 403, or a 202 from some other edge) the lengthening
    ``_CHALLENGE_RETRY_DELAYS`` ladder still applies, once per host — see
    ``_challenge_exhausted``.

    Retries are paced like any other request, and the whole ladder is bounded by
    *deadline* so a hostile host can't consume the run.
    """
    try:
        from curl_cffi import requests as cr  # type: ignore
    except Exception:
        return None

    deadline = deadline or _Deadline(None)
    host = _host_key(url)
    # Held for the whole call: curl_cffi sessions aren't documented as
    # thread-safe, and serialising a host's fallback requests is desirable anyway.
    with _curl_host_lock(host):
        session = _curl_session_for(host, cr)
        if session is None:
            return None
        if js_challenge:
            _apply_clearance(session, url)
        # Don't slam the fallback request in the same instant as the httpx 202 — a
        # short warm-up gap keeps the initial fallback from re-tripping the challenge.
        if not deadline.allows(_CHALLENGE_INITIAL_DELAY):
            return None
        time.sleep(_CHALLENGE_INITIAL_DELAY)
        # Empty for a JS challenge (waiting cannot mint a token), and once this
        # host has already failed a ladder: one real attempt is still made (the
        # WAF may have relented), but without the long backoff.
        delays = () if js_challenge else _challenge_ladder_for(url)
        for attempt in range(len(delays) + 1):
            if deadline.expired():
                # Out of time: the jar hasn't cleared, so don't carry it forward.
                reset_curl_sessions(host)
                return None
            # Retries go through the same politeness gate as any other request —
            # this is the host that is least tolerant of unpaced bursts.
            _pace_host(url)
            try:
                r = session.get(
                    url,
                    impersonate="chrome",
                    timeout=deadline.clamp_timeout(timeout),
                    headers=headers or {},
                )
            except Exception as e:  # noqa: BLE001
                logger.debug("curl_cffi fallback failed for %s: %s", url, e)
                # The session may be wedged; don't hand it to the next caller.
                reset_curl_sessions(host)
                return None
            if r.status_code in (200, 304, 404):
                logger.info("curl_cffi %s -> %s", url, r.status_code)
                body = r.content if r.status_code == 200 else None
                return (r.status_code, body, r.headers.get("ETag"), r.headers.get("Last-Modified"))
            # 202 = WAF challenge not yet cleared. Wait (respectfully) for the cookie
            # to arm on this session, then retry — unless we've exhausted the budget.
            if r.status_code == 202 and attempt < len(delays):
                delay = delays[attempt]
                if not deadline.allows(delay):
                    _mark_challenge_exhausted(url)
                    reset_curl_sessions(host)
                    return None
                logger.info(
                    "curl_cffi %s -> 202 challenge; backing off %.0fs then retrying (%d/%d)",
                    url,
                    delay,
                    attempt + 1,
                    len(delays),
                )
                time.sleep(delay)
                continue
            # Out of retries (or an unusable status): these cookies aren't working.
            if r.status_code == 202:
                if js_challenge:
                    # The token we carried (if any) did not clear the challenge, so
                    # don't hand the same one to the next URL — re-mint instead.
                    browser_clearance.invalidate(url)
                _mark_challenge_exhausted(url)
            reset_curl_sessions(host)
            return None
