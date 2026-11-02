"""Webhook posters must never log the webhook URL: its path is the secret."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from typer.testing import CliRunner

from repower import cli
from repower.db import PolicyMeeting
from repower.notify import webhook
from repower.policy import digest, store

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


def test_a_run_digest_lists_only_what_finished_since_then(policy_db):
    start = datetime(2026, 11, 3, 1, 0, tzinfo=UTC)
    assert digest.build_run_digest(start, db_path=policy_db) is None  # nothing finished: nothing to post

    def done(key, num, *, at, redo=False):
        store.record_meeting(key, num, None, db_path=policy_db)
        with store.session_scope(policy_db) as s:
            m = s.query(PolicyMeeting).filter_by(committee_key=key, meeting_num=num).one()
            m.state, m.summarised_at = "done", at
            m.resummarised_at = at if redo else None

    done("santeii", 117, at=start - timedelta(minutes=1))  # an earlier run's
    done("santeii", 118, at=start + timedelta(minutes=5))
    done("doji_shijo", 12, at=start + timedelta(minutes=9), redo=True)

    out = digest.build_run_digest(start, db_path=policy_db)
    assert out.splitlines() == [
        "**Policy summaries finished: 2**",
        "- Procurement Price Calculation Committee (FIT/FIP) 第118回",
        "- Study Group on a Simultaneous Market 第12回 (redone)",
    ]


def test_digest_since_posts_nothing_when_nothing_finished(monkeypatch):
    posted = []
    monkeypatch.setattr(digest, "build_run_digest", lambda since: None)
    monkeypatch.setattr(digest, "post_digest", posted.append)
    result = CliRunner().invoke(cli.app, ["policy", "digest", "--since", "2026-11-03T01:00:00+00:00"])
    assert result.exit_code == 0, result.output
    assert posted == [] and "nothing to post" in result.output
    assert CliRunner().invoke(cli.app, ["policy", "digest", "--since", "yesterday"]).exit_code != 0


def test_cli_silences_httpx_request_log():
    import repower.cli  # noqa: F401 — configures logging on import

    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
