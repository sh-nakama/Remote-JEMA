"""Smoke test of the `run-all` entry point every daily cron runs, with all network stages stubbed."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from repower import cli


@pytest.fixture
def stages(monkeypatch):
    """Stub every stage `run-all` imports; record the call order."""
    calls: list[str] = []

    def stub(name, result=None, fail=False):
        def fn(*args, **kwargs):
            calls.append(name)
            if fail:
                raise RuntimeError(f"{name} down")
            return result(*args, **kwargs) if callable(result) else result
        return fn

    patches = {
        "repower.scrapers.areas.scrape_all_areas": stub("areas", {"tepco": 3}),
        "repower.scrapers.jepx_spot.scrape_jepx": stub("jepx"),
        "repower.scrapers.fuels_futures.scrape_fuels": stub("fuels"),
        "repower.scrapers.news_rss.scrape_news": stub("news"),
        "repower.scrapers.eprx.scrape_eprx": stub("eprx"),
        "repower.scrapers.eprx.scrape_eprx_tieline": stub("tieline"),
        "repower.analysis.features.run_analysis": stub("analyze", fail=True),
        "repower.policy.detect.detect": stub("detect", [{"new": 2}]),
        "repower.policy.detect.backfill_dates": stub("dates", [{"dated": 1}]),
        "repower.policy.schedule.refresh_upcoming": stub("schedule", 4),
        "repower.policy.catalog.discover_committees": stub("catalog", {"inserted": 0, "found": 9}),
        "repower.notify.webhook.notify": stub("notify", lambda day, dry_run: calls.append(f"dry_run={dry_run}")),
    }
    for target, fn in patches.items():
        monkeypatch.setattr(target, fn)
    return calls


def test_run_all_runs_every_stage_and_survives_a_failing_one(stages):
    result = CliRunner().invoke(cli.app, ["run-all", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert stages == ["areas", "jepx", "fuels", "news", "eprx", "tieline", "analyze",
                      "detect", "dates", "schedule", "catalog", "notify", "dry_run=True"]
    assert "analyze skipped: analyze down" in result.output
    assert "2 new committee meeting(s) detected" in result.output
    assert result.output.rstrip().endswith("═══ DONE ═══")
