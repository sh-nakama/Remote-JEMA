"""Clear AWS WAF challenges with a headless browser.

``meti.go.jp`` and ``egc.meti.go.jp`` sit behind an AWS WAF **challenge** rule.
The edge answers HTTP 202 with ``x-amzn-waf-action: challenge`` and a page whose
``challenge.js`` runs a proof-of-work to mint an ``aws-waf-token`` cookie, then
reloads. No HTTP client can produce that token: ``curl_cffi``'s Chrome TLS
impersonation defeats *fingerprint* rules but has no JavaScript engine, so
retrying a 202 — however patiently — waits for a cookie that will never arrive.
Measured against the live host, an impersonating client is challenged exactly as
often as plain httpx once the edge has flagged the caller; a real browser is not.

So this module runs one. It offers two things, in increasing order of cost:

- :func:`cookies_for` — the token alone, cached per host, for the ordinary fast
  path to replay on its own requests.
- :func:`fetch` — the document itself, retrieved *by* the browser. This is the
  only client that can solve a challenge, so it is the last resort that actually
  works rather than one that fails more politely.

Playwright is an **optional** dependency (``pip install -e ".[browser]"`` plus
``playwright install chromium``). Without it every function here degrades to
"nothing available" and callers behave exactly as they did before.
"""

from __future__ import annotations

import atexit
import base64
import logging
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

TOKEN_COOKIE = "aws-waf-token"

# AWS WAF's challenge token carries a short immunity window (minutes by default).
# Expiring our copy slightly early costs one browser launch; expiring it late
# costs a whole pass of 202s before anything notices.
TOKEN_TTL: float = 240.0

# Wall-clock ceiling for one mint: launch, navigate, run the proof-of-work.
MINT_TIMEOUT: float = 45.0

# Ceiling for one browser-transport fetch. Generous: the first call also pays for
# the browser launch and possibly a challenge.
FETCH_TIMEOUT: float = 60.0

# Not under ``data/`` — that directory is synced to Hugging Face, and a browser
# profile is local machine state (and megabytes of it).
_DEFAULT_PROFILE_DIR = Path.home() / ".repower" / "waf-profile"

_cache: dict[str, tuple[float, dict[str, str]]] = {}
_cache_lock = threading.Lock()
# One mint at a time per host: concurrent scrapers hitting the same 202 must not
# each launch a browser to earn the same token.
_host_locks: dict[str, threading.Lock] = {}

# Playwright's sync objects belong to the thread that created them, and a
# persistent profile directory cannot be shared by two live Chromium instances.
# So the browser is per-thread, profile and all.
_local = threading.local()


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").casefold()


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/"


def _host_lock(host: str) -> threading.Lock:
    with _cache_lock:
        lock = _host_locks.get(host)
        if lock is None:
            lock = threading.Lock()
            _host_locks[host] = lock
        return lock


def _profile_dir() -> Path:
    base = os.getenv("REPOWER_BROWSER_PROFILE") or _DEFAULT_PROFILE_DIR
    return Path(base) / f"t{threading.get_ident()}"


def available() -> bool:
    """True if a browser can be used: Playwright importable and not opted out."""
    if os.getenv("REPOWER_BROWSER_CLEARANCE", "1") == "0":
        return False
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:  # noqa: BLE001 — absent or broken install is the same to us
        return False
    return True


def cookies_for(url: str, *, force: bool = False) -> dict[str, str]:
    """Cookies that clear *url*'s WAF challenge, minting them if needed.

    Returns ``{}`` when clearance is unavailable or the challenge could not be
    solved — callers treat that as "no help available" and fall through to their
    normal failure path. Never raises.
    """
    host = _host(url)
    if not host or not available():
        return {}

    if not force:
        cached = _cached(host)
        if cached is not None:
            return cached

    with _host_lock(host):
        # Another thread may have minted while we waited for the lock.
        if not force:
            cached = _cached(host)
            if cached is not None:
                return cached
        try:
            cookies = _mint(url)
        except Exception as e:  # noqa: BLE001 — a browser failure must not end the run
            logger.warning("browser clearance failed for %s: %s", host, e)
            return {}
        if not cookies:
            # Common, not alarming: the browser is often trusted where our HTTP
            # clients are not, so no challenge is raised and no token is issued.
            logger.info("no %s issued for %s", TOKEN_COOKIE, host)
            return {}
        with _cache_lock:
            _cache[host] = (time.monotonic() + TOKEN_TTL, cookies)
        logger.info("browser clearance token minted for %s", host)
        return cookies


def _cached(host: str) -> dict[str, str] | None:
    with _cache_lock:
        entry = _cache.get(host)
        if entry is None:
            return None
        expires, cookies = entry
        if expires <= time.monotonic():
            del _cache[host]
            return None
        return cookies


def invalidate(url: str) -> None:
    """Drop *url*'s cached token — call this when it stops clearing the WAF."""
    host = _host(url)
    with _cache_lock:
        _cache.pop(host, None)


def reset() -> None:
    """Forget every cached token (tests, and manual recovery)."""
    with _cache_lock:
        _cache.clear()


# ── Browser lifecycle ────────────────────────────────────────────────────────
def _context():
    """This thread's persistent browser context, launched on first use.

    Kept open for the process: a launch costs seconds, and the profile is where
    a hard-won clearance token lives.
    """
    context = getattr(_local, "context", None)
    if context is not None:
        return context
    from playwright.sync_api import sync_playwright

    profile = _profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    playwright = sync_playwright().start()
    context = playwright.chromium.launch_persistent_context(
        str(profile),
        headless=True,
        locale="ja-JP",
        # challenge.js inspects navigator.webdriver among other signals.
        args=["--disable-blink-features=AutomationControlled"],
    )
    _local.playwright = playwright
    _local.context = context
    atexit.register(close)
    return context


def close() -> None:
    """Shut down this thread's browser, if it has one. Safe to call repeatedly."""
    for attr, shutdown in (("context", "close"), ("playwright", "stop")):
        obj = getattr(_local, attr, None)
        setattr(_local, attr, None)
        if obj is None:
            continue
        try:
            getattr(obj, shutdown)()
        except Exception as e:  # noqa: BLE001
            logger.debug("browser %s.%s failed: %s", attr, shutdown, e)
    _local.page = None


def _page(url: str):
    """A page whose document is on *url*'s origin.

    The origin matters: :func:`fetch` runs ``fetch()`` *inside* the document, so
    the request inherits the page's cookies, referer and the browser's own TLS
    stack — which is the entire point. Navigating also triggers (and thereby
    solves) any challenge before the real request is made.
    """
    context = _context()
    page = getattr(_local, "page", None)
    if page is None or page.is_closed():
        page = context.new_page()
        _local.page = page
    origin = _origin(url)
    if not page.url.startswith(origin):
        response = page.goto(origin, wait_until="domcontentloaded", timeout=FETCH_TIMEOUT * 1000)
        if response is not None and _is_challenge(response):
            _await_clearance(context, page, url)
    return page


def _is_challenge(response) -> bool:
    """True if *response* is the AWS WAF challenge interstitial."""
    action = response.header_value("x-amzn-waf-action") or ""
    return response.status == 202 or action.strip().casefold() == "challenge"


def _await_clearance(context, page, url: str) -> bool:
    """Give challenge.js time to finish its proof-of-work and set the token."""
    deadline = time.monotonic() + MINT_TIMEOUT
    while time.monotonic() < deadline:
        if any(c["name"] == TOKEN_COOKIE for c in context.cookies(url)):
            return True
        page.wait_for_timeout(500)
    logger.warning("challenge for %s did not resolve in %.0fs", _host(url), MINT_TIMEOUT)
    return False


# Returns the body base64-encoded: page.evaluate marshals JSON, which cannot
# carry raw bytes, and these documents are PDFs as often as HTML.
_FETCH_JS = """
async ({url, headers}) => {
  const r = await fetch(url, {credentials: 'include', headers});
  const bytes = new Uint8Array(await r.arrayBuffer());
  let binary = '';
  const CHUNK = 0x8000;  // apply() blows the stack on a whole PDF
  for (let i = 0; i < bytes.length; i += CHUNK) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  return {
    status: r.status,
    body: btoa(binary),
    etag: r.headers.get('etag'),
    lastModified: r.headers.get('last-modified'),
  };
}
"""


def fetch(
    url: str, headers: dict | None = None
) -> tuple[int, bytes | None, str | None, str | None] | None:
    """Fetch *url* with the browser, returning ``_do_get``'s 4-tuple.

    ``None`` if the browser is unavailable or the attempt failed, so the caller
    can fall through to its normal failure path. Never raises.
    """
    if not available():
        return None
    try:
        page = _page(url)
        result = page.evaluate(_FETCH_JS, {"url": url, "headers": dict(headers or {})})
    except Exception as e:  # noqa: BLE001 — a browser failure must not end the run
        logger.warning("browser fetch failed for %s: %s", url, e)
        close()  # the context may be wedged; the next call gets a fresh one
        return None
    status = int(result["status"])
    body = base64.b64decode(result["body"]) if status == 200 else None
    logger.info("browser fetch %s -> %s", url, status)
    return (status, body, result.get("etag"), result.get("lastModified"))


def _mint(url: str) -> dict[str, str]:
    """Return the browser's cookies for *url*, solving a challenge if one is set.

    ``{}`` when no token was issued — the browser is often trusted where our HTTP
    clients are not, and an unchallenged visit has no token to hand out.
    """
    context = _context()
    _page(url)  # navigating is what triggers, and clears, the challenge
    jar = {c["name"]: c["value"] for c in context.cookies(url)}
    return jar if TOKEN_COOKIE in jar else {}

