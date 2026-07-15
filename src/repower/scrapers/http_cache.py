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
from datetime import datetime, timezone
from typing import Literal, Optional

import httpx

from repower.db import HttpCache, get_session, init_db

logger = logging.getLogger(__name__)

Status = Literal["ok", "not_modified", "not_found"]

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
) -> tuple[Status, Optional[bytes]]:
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
    entry.last_checked = datetime.now(timezone.utc)
    session.commit()


def _do_get(url: str, headers: dict, allow_curl_fallback: bool, timeout: float):
    """Return ``(status_code, content|None, etag, last_modified)``. Raises on
    unexpected HTTP/network errors (after trying the curl fallback if allowed)."""
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
    status. Conditional headers are forwarded so 304s still work for Kyuden."""
    try:
        from curl_cffi import requests as cr  # type: ignore
    except Exception:
        return None
    try:
        r = cr.get(url, impersonate="chrome", timeout=timeout, headers=headers or {})
    except Exception as e:  # noqa: BLE001
        logger.debug("curl_cffi fallback failed for %s: %s", url, e)
        return None
    if r.status_code in (200, 304, 404):
        logger.info("curl_cffi %s -> %s", url, r.status_code)
        body = r.content if r.status_code == 200 else None
        return (r.status_code, body, r.headers.get("ETag"), r.headers.get("Last-Modified"))
    return None
