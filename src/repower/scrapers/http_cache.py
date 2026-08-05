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
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from repower.db import HttpCache, get_session, init_db

logger = logging.getLogger(__name__)

Status = Literal["ok", "not_modified", "not_found"]

# Politeness: keep at least this many seconds between consecutive requests to the
# same host so a multi-file scrape (version-probing months, EPRX product ZIPs,
# JEPX year files) drips out at a human pace instead of machine-gunning a single
# server. Keyed per host, so unrelated hosts aren't needlessly serialised and a
# host's first hit never waits.
_MIN_HOST_INTERVAL: float = 1.0
_last_request_at: dict[str, float] = {}


def _pace_host(url: str) -> None:
    """Sleep just long enough that consecutive requests to *url*'s host are at
    least ``_MIN_HOST_INTERVAL`` seconds apart. A host's first request never
    waits; distinct hosts don't block each other."""
    host = urlsplit(url).netloc
    if not host:
        return
    prev = _last_request_at.get(host)
    if prev is not None:
        wait = _MIN_HOST_INTERVAL - (time.monotonic() - prev)
        if wait > 0:
            time.sleep(wait)
    _last_request_at[host] = time.monotonic()


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

# Sent on the plain-httpx path only. The curl_cffi path deliberately does NOT get
# this header: ``impersonate="chrome"`` already supplies the User-Agent matching
# the TLS/HTTP2 fingerprint it presents, and overriding it with a different
# (older, different-platform) string is exactly the inconsistency a WAF looks for.
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

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
    allow_curl_fallback: bool = False,
    force: bool = False,
    timeout: float = 30.0,
) -> tuple[Status, bytes | None]:
    """GET *url* with persistent conditional-GET caching.

    Returns ``("ok", content)`` on 200, ``("not_modified", None)`` on 304, and
    ``("not_found", None)`` on 404. Raises on other/unexpected HTTP errors so
    callers can log and try the next URL. ETag/Last-Modified are stored per URL,
    so the next run sends ``If-None-Match`` / ``If-Modified-Since`` and the
    server returns 304 for unchanged files (skipping both download and parse).

    Set ``force=True`` to bypass the cache and always re-download.
    """
    init_db(db_path)
    session = get_session(db_path)
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
            url, req_headers, allow_curl_fallback, timeout
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
        raise RuntimeError(f"unexpected status {status_code} for {url}")
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
    session.commit()


def _do_get(url: str, headers: dict, allow_curl_fallback: bool, timeout: float):
    """Return ``(status_code, content|None, etag, last_modified)``. Raises on
    unexpected HTTP/network errors (after trying the curl fallback if allowed)."""
    _pace_host(url)  # space consecutive same-host requests to a human pace
    # The default UA belongs to this transport only — the curl fallback gets the
    # headers untouched so impersonation supplies a UA matching its fingerprint.
    httpx_headers = {"User-Agent": _DEFAULT_UA, **headers}
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True, headers=httpx_headers)
    except Exception:
        if allow_curl_fallback:
            r = _curl_get(url, headers, timeout)
            if r is not None:
                return r
        raise
    # 403 = plain bot block; 202 = AWS WAF JavaScript challenge (meti.go.jp sits
    # behind CloudFront + WAF and answers plain HTTP stacks with either). Both
    # yield to the browser-impersonating fallback.
    if resp.status_code in (403, 202) and allow_curl_fallback:
        r = _curl_get(url, headers, timeout)
        if r is not None:
            return r
    if resp.status_code in (200, 304, 404):
        body = resp.content if resp.status_code == 200 else None
        return (resp.status_code, body, resp.headers.get("ETag"), resp.headers.get("Last-Modified"))
    resp.raise_for_status()  # 4xx/5xx → raise for the caller to handle
    # Any other status (2xx like 206, or 3xx) is unexpected for these static
    # file endpoints — treat as an error rather than a complete body.
    raise httpx.HTTPStatusError(
        f"unexpected status {resp.status_code}", request=resp.request, response=resp
    )


def _curl_get(url: str, headers: dict, timeout: float):
    """curl_cffi Chrome-impersonation fallback. Returns the same 4-tuple, or
    None if curl_cffi is unavailable or the request did not yield a usable
    status. Conditional headers are forwarded so 304s still work for Kyuden.

    No User-Agent is added here: ``impersonate="chrome"`` supplies one consistent
    with the TLS/HTTP2 fingerprint it presents. A caller that set its own UA in
    *headers* still has it honoured.

    The host's session is reused across calls (see ``_curl_sessions``), so a
    WAF/Akamai clearance cookie earned once is replayed by the host's later URLs
    rather than being re-earned per URL. Within a call, a 202 is retried with the
    lengthening ``_CHALLENGE_RETRY_DELAYS`` backoff; if the budget is exhausted the
    cookie jar has failed to clear, so it is discarded rather than carried forward.
    """
    try:
        from curl_cffi import requests as cr  # type: ignore
    except Exception:
        return None

    host = urlsplit(url).netloc
    # Held for the whole call: curl_cffi sessions aren't documented as
    # thread-safe, and serialising a host's fallback requests is desirable anyway.
    with _curl_host_lock(host):
        session = _curl_session_for(host, cr)
        if session is None:
            return None
        # Don't slam the fallback request in the same instant as the httpx 202 — a
        # short warm-up gap keeps the initial fallback from re-tripping the challenge.
        time.sleep(_CHALLENGE_INITIAL_DELAY)
        for attempt in range(len(_CHALLENGE_RETRY_DELAYS) + 1):
            try:
                r = session.get(url, impersonate="chrome", timeout=timeout, headers=headers or {})
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
            if r.status_code == 202 and attempt < len(_CHALLENGE_RETRY_DELAYS):
                delay = _CHALLENGE_RETRY_DELAYS[attempt]
                logger.info(
                    "curl_cffi %s -> 202 challenge; backing off %.0fs then retrying (%d/%d)",
                    url,
                    delay,
                    attempt + 1,
                    len(_CHALLENGE_RETRY_DELAYS),
                )
                time.sleep(delay)
                continue
            # Out of retries (or an unusable status): these cookies aren't working.
            reset_curl_sessions(host)
            return None
