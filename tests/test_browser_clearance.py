"""Tests for the headless-browser WAF clearance helper.

Network- and browser-free: ``_mint`` (the only part that launches Chromium) is
monkeypatched, so what is exercised here is the caching and degradation logic
that decides *whether* a browser is launched at all.
"""

from __future__ import annotations

from repower.scrapers import browser_clearance as bc


def _fake_mint(monkeypatch, cookies):
    """Patch minting to return *cookies* and count how often it ran."""
    calls: list[str] = []

    def mint(url):
        calls.append(url)
        return dict(cookies)

    monkeypatch.setattr(bc, "_mint", mint)
    monkeypatch.setattr(bc, "available", lambda: True)
    monkeypatch.setattr(bc, "_cache", {})
    return calls


def test_token_is_minted_once_per_host(monkeypatch):
    # A pass over one committee is dozens of URLs; each browser launch costs
    # seconds, and the token is valid for all of them.
    calls = _fake_mint(monkeypatch, {bc.TOKEN_COOKIE: "tok"})

    first = bc.cookies_for("https://www.meti.go.jp/a")
    second = bc.cookies_for("https://www.meti.go.jp/b")

    assert first == second == {bc.TOKEN_COOKIE: "tok"}
    assert len(calls) == 1


def test_invalidate_forces_a_fresh_mint(monkeypatch):
    # Called when the token demonstrably failed to clear the challenge, so
    # replaying it would just reproduce the failure.
    calls = _fake_mint(monkeypatch, {bc.TOKEN_COOKIE: "tok"})

    bc.cookies_for("https://www.meti.go.jp/a")
    bc.invalidate("https://www.meti.go.jp/a")
    bc.cookies_for("https://www.meti.go.jp/b")

    assert len(calls) == 2


def test_expired_token_is_re_minted(monkeypatch):
    calls = _fake_mint(monkeypatch, {bc.TOKEN_COOKIE: "tok"})
    monkeypatch.setattr(bc, "TOKEN_TTL", -1.0)

    bc.cookies_for("https://www.meti.go.jp/a")
    bc.cookies_for("https://www.meti.go.jp/b")

    assert len(calls) == 2


def test_no_playwright_means_no_cookies_and_no_launch(monkeypatch):
    # The whole feature is optional: without it callers must behave exactly as
    # they did before, not fail.
    calls = _fake_mint(monkeypatch, {bc.TOKEN_COOKIE: "tok"})
    monkeypatch.setattr(bc, "available", lambda: False)

    assert bc.cookies_for("https://www.meti.go.jp/a") == {}
    assert calls == []


def test_opt_out_env_var_disables_clearance(monkeypatch):
    monkeypatch.setenv("REPOWER_BROWSER_CLEARANCE", "0")
    assert bc.available() is False


def test_a_broken_browser_never_raises(monkeypatch):
    monkeypatch.setattr(bc, "available", lambda: True)
    monkeypatch.setattr(bc, "_cache", {})

    def boom(url):
        raise RuntimeError("chromium is not installed")

    monkeypatch.setattr(bc, "_mint", boom)

    assert bc.cookies_for("https://www.meti.go.jp/a") == {}


def test_a_challenge_that_never_solves_yields_nothing(monkeypatch):
    # _mint returns {} when the token cookie never appears. That is cached, but
    # briefly and never as if it were a valid token — see EMPTY_TTL below. The
    # caching matters because the ordinary fast path now asks before *every*
    # request, and an uncached "no" costs a browser round trip each time.
    calls = _fake_mint(monkeypatch, {})

    assert bc.cookies_for("https://www.meti.go.jp/a") == {}
    assert bc.cookies_for("https://www.meti.go.jp/b") == {}
    assert len(calls) == 1


def test_absent_token_is_cached_for_less_time_than_a_real_one(monkeypatch):
    # "Not guarded right now" is the state we want to leave quickly: the host may
    # start challenging a moment later, and then a token is what we need.
    assert bc.EMPTY_TTL < bc.TOKEN_TTL

    calls = _fake_mint(monkeypatch, {})
    monkeypatch.setattr(bc, "EMPTY_TTL", -1.0)

    bc.cookies_for("https://www.meti.go.jp/a")
    bc.cookies_for("https://www.meti.go.jp/b")

    assert len(calls) == 2


# ── Headless User-Agent ──────────────────────────────────────────────────────
class _FakePage:
    def __init__(self, ua):
        self._ua = ua

    def evaluate(self, script):
        return self._ua


class _FakeContext:
    def __init__(self, sent=None, fail=False):
        self.sent = sent if sent is not None else []
        self.fail = fail

    def new_cdp_session(self, page):
        if self.fail:
            raise RuntimeError("no CDP here")
        return self

    def send(self, method, params):
        self.sent.append((method, params))


_HEADLESS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) HeadlessChrome/151.0.7922.34 Safari/537.36"
)


def test_headless_user_agent_is_hidden_before_the_first_navigation():
    # Measured live: with "HeadlessChrome/" in the UA, meti.go.jp answers 403 with
    # no x-amzn-waf-action — a block, so challenge.js never runs and no token can
    # ever be minted. De-headlessed, the same navigation is challenged (202) and
    # the token appears. This is the difference between this module working and
    # silently doing nothing.
    ctx = _FakeContext()
    bc._hide_headless_ua(ctx, _FakePage(_HEADLESS_UA))

    assert len(ctx.sent) == 1
    method, params = ctx.sent[0]
    assert method == "Emulation.setUserAgentOverride"
    assert "HeadlessChrome" not in params["userAgent"]
    # Version comes from the real browser rather than a hardcoded string, so this
    # cannot drift out of date.
    assert "Chrome/151.0.7922.34" in params["userAgent"]


def test_a_normal_user_agent_is_left_alone():
    # Nothing to hide when Playwright is driving real Chrome (channel="chrome"),
    # and overriding would only risk disagreeing with the actual engine.
    real = _HEADLESS_UA.replace("HeadlessChrome/", "Chrome/")
    ctx = _FakeContext()

    bc._hide_headless_ua(ctx, _FakePage(real))

    assert ctx.sent == []


def test_a_failed_override_does_not_sink_the_launch():
    # Best-effort: worst case we keep the default UA and get blocked, which is
    # the old behaviour — not a crash in the middle of a scrape.
    ctx = _FakeContext(fail=True)

    bc._hide_headless_ua(ctx, _FakePage(_HEADLESS_UA))  # must not raise

    assert ctx.sent == []
