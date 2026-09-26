"""Webhook posters must never log the webhook URL: its path is the secret."""

from __future__ import annotations

import logging

import httpx
import pytest

from repower.notify import webhook
from repower.policy import digest

SECRET = "https://discord.com/api/webhooks/123/SECRET-TOKEN"


def _failing_post(exc_or_status):
    def post(url, **_):
        req = httpx.Request("POST", url)
        if isinstance(exc_or_status, int):
            return httpx.Response(exc_or_status, request=req)
        raise exc_or_status("boom " + url, request=req)
    return post


@pytest.mark.parametrize("failure", [404, httpx.ConnectError])
def test_failed_posts_do_not_log_the_url(monkeypatch, caplog, failure):
    monkeypatch.setattr(httpx, "post", _failing_post(failure))
    monkeypatch.setattr(digest, "WEBHOOK_URL", SECRET)

    with caplog.at_level(logging.DEBUG):
        assert webhook.post_webhook({}, webhook_url=SECRET) is False
        assert digest.post_digest("x") is False

    assert len(caplog.records) == 2
    assert "SECRET-TOKEN" not in caplog.text


def test_cli_silences_httpx_request_log():
    import repower.cli  # noqa: F401 — configures logging on import

    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
