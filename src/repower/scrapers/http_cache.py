"""Persistent conditional-GET HTTP layer with ETag / Last-Modified caching.

Shared by the TSO area, JEPX, and EPRX scrapers. Cache state lives in the
``http_cache`` table, which is synced to Hugging Face, so 304 "not modified"
skips persist across the (ephemeral) daily CI runs — making the daily scrape
incremental at the file level: static past-month/year files are skipped, only
changed files (the current month/year) are re-downloaded and re-parsed.

Some TSO hosts (e.g. Kyuden behind Akamai) reject plain Python TLS with 403; an
optional ``curl_cffi`` fallback impersonates a real Chrome TLS fingerprint.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Literal
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
# to arm the cookie on our persistent curl_cffi session.
_CHALLENGE_RETRY_DELAYS: tuple[float, ...] = (5.0, 15.0, 30.0)
# Firing the impersonating fallback in the same instant as the plain-httpx 202
# just trips the challenge again — the edge reads the back-to-back hit as bot
# traffic. Pause briefly first so the initial fallback request lands at a human
# pace instead of milliseconds after the block.
_CHALLENGE_INITIAL_DELAY: float = 2.0

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


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
        req_headers = {"User-Agent": _DEFAULT_UA, **(headers or {})}
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
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True, headers=headers)
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

    A persistent ``Session`` is used so a WAF/Akamai 202 challenge cookie set on
    the first attempt is replayed on the next; a 202 is retried with the
    lengthening ``_CHALLENGE_RETRY_DELAYS`` backoff before giving up."""
    try:
        from curl_cffi import requests as cr  # type: ignore
    except Exception:
        return None
    try:
        session = cr.Session()
    except Exception as e:  # noqa: BLE001
        logger.debug("curl_cffi session init failed for %s: %s", url, e)
        return None
    # Don't slam the fallback request in the same instant as the httpx 202 — a
    # short warm-up gap keeps the initial fallback from re-tripping the challenge.
    time.sleep(_CHALLENGE_INITIAL_DELAY)
    for attempt in range(len(_CHALLENGE_RETRY_DELAYS) + 1):
        try:
            r = session.get(url, impersonate="chrome", timeout=timeout, headers=headers or {})
        except Exception as e:  # noqa: BLE001
            logger.debug("curl_cffi fallback failed for %s: %s", url, e)
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
        return None
    return None
