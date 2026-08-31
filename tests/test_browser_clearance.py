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
    # _mint returns {} when the token cookie never appears; that must not be
    # cached as if it were a valid token.
    calls = _fake_mint(monkeypatch, {})

    assert bc.cookies_for("https://www.meti.go.jp/a") == {}
    assert bc.cookies_for("https://www.meti.go.jp/b") == {}
    assert len(calls) == 2
