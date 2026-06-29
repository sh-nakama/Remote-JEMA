"""CLI entry point for repower — powered by Typer."""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import typer

from repower.timeutil import yesterday_jst

app = typer.Typer(name="repower", help="Tokyo power market analysis bot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@app.command()
def scrape(
    months_back: int = typer.Option(1, help="TSO months to re-fetch (current + N previous)"),
    area: str = typer.Option("all", help="Area slug (e.g. tepco, kansai) or 'all'"),
    skip_jepx: bool = typer.Option(False, help="Skip JEPX spot prices"),
    skip_fuels: bool = typer.Option(False, help="Skip fuel futures"),
    skip_news: bool = typer.Option(False, help="Skip news RSS"),
    skip_eprx: bool = typer.Option(False, help="Skip EPRX balancing + tieline data"),
    jepx_year: Optional[int] = typer.Option(None, help="JEPX year to fetch (default: current)"),
    fuel_days: int = typer.Option(7, help="Days of fuel data to fetch"),
):
    """Scrape TSO area data + market sources (recent months only)."""
    from repower.scrapers.areas import scrape_all_areas, scrape_area, AREA_NAMES
    from repower.scrapers.jepx_spot import scrape_jepx
    from repower.scrapers.fuels_futures import scrape_fuels
    from repower.scrapers.news_rss import scrape_news

    typer.echo("\u2500\u2500 TSO area supply/demand \u2500\u2500")
    if area == "all":
        results = scrape_all_areas(months_back=months_back)
        for a, n in results.items():
            typer.echo(f"   {AREA_NAMES.get(a, a):<25} {n:>6} rows")
    else:
        n = scrape_area(area, months_back=months_back)
        typer.echo(f"   {AREA_NAMES.get(area, area):<25} {n:>6} rows")

    if not skip_jepx:
        typer.echo("\u2500\u2500 JEPX spot prices \u2500\u2500")
        n = scrape_jepx(year=jepx_year)
        typer.echo(f"   {n} rows upserted")

    if not skip_fuels:
        typer.echo("\u2500\u2500 Fuel prices \u2500\u2500")
        n = scrape_fuels(days_back=fuel_days)
        typer.echo(f"   {n} rows upserted")

    if not skip_news:
        typer.echo("\u2500\u2500 News RSS \u2500\u2500")
        n = scrape_news()
        typer.echo(f"   {n} new items")

    if not skip_eprx:
        from repower.scrapers.eprx import scrape_eprx, scrape_eprx_tieline
        typer.echo("\u2500\u2500 EPRX balancing \u2500\u2500")
        n = scrape_eprx()
        typer.echo(f"   {n} rows upserted")
        typer.echo("\u2500\u2500 EPRX tieline \u2500\u2500")
        n = scrape_eprx_tieline()
        typer.echo(f"   {n} rows upserted")


@app.command()
def backfill(
    since: str = typer.Option(
        "2024-04",
        help="Earliest YYYY-MM month to fetch (default 2024-04, the start of the standardised TSO publication format)",
    ),
    area: str = typer.Option("all", help="Area slug or 'all'"),
    jepx_since: int = typer.Option(
        2024,
        help="Earliest JEPX year to backfill (one CSV per year). Set to 0 to skip JEPX.",
    ),
    eprx_since: int = typer.Option(
        2025,
        help="Earliest JFY to backfill EPRX balancing + tieline. Set to 0 to skip EPRX.",
    ),
):
    """One-shot historical backfill of every month from --since to today.

    Idempotent: existing rows are upserted in place via (area, date, time) PK,
    so this is safe to re-run. Designed to be invoked once locally or via
    workflow_dispatch, then `scrape` handles incremental daily updates.

    Also backfills JEPX per-area spot prices from --jepx-since through the
    current year (skip with --jepx-since 0).
    """
    from datetime import date as _date
    from repower.scrapers.areas import ALL_SCRAPERS, AREA_NAMES

    try:
        sy, sm = [int(x) for x in since.split("-")]
    except Exception as e:
        raise typer.BadParameter(f"--since must be YYYY-MM, got {since!r}") from e

    today = _date.today()
    months = (today.year - sy) * 12 + (today.month - sm)
    if months < 0:
        raise typer.BadParameter(f"--since {since} is in the future")

    typer.echo(f"\u2550\u2550\u2550 BACKFILL  {since} \u2192 {today:%Y-%m}  ({months + 1} months) \u2550\u2550\u2550")
    targets = [cls for cls in ALL_SCRAPERS if area in ("all", cls.AREA)]
    if not targets:
        raise typer.BadParameter(f"Unknown area: {area}")

    grand = 0
    for cls in targets:
        s = cls()
        try:
            n = s.scrape(months_back=months)
        except Exception as e:  # noqa: BLE001
            typer.echo(f"   {AREA_NAMES.get(s.AREA, s.AREA):<25} CRASHED: {e}", err=True)
            n = 0
        typer.echo(f"   {AREA_NAMES.get(s.AREA, s.AREA):<25} {n:>7} rows upserted")
        grand += n
    typer.echo(f"\u2550\u2550\u2550 TOTAL {grand} rows \u2550\u2550\u2550")

    if jepx_since and jepx_since > 0:
        from repower.scrapers.jepx_spot import scrape_jepx_years
        typer.echo(f"\u2550\u2550\u2550 JEPX BACKFILL  {jepx_since} \u2192 {today.year} \u2550\u2550\u2550")
        results = scrape_jepx_years(jepx_since, today.year)
        for y, n in results.items():
            typer.echo(f"   JEPX {y}                  {n:>7} rows upserted")
        typer.echo(f"\u2550\u2550\u2550 JEPX TOTAL {sum(results.values())} rows \u2550\u2550\u2550")

    if eprx_since and eprx_since > 0:
        from repower.scrapers.eprx import _current_jfy, scrape_eprx_range
        typer.echo(f"\u2550\u2550\u2550 EPRX BACKFILL  JFY {eprx_since} \u2192 {_current_jfy()} \u2550\u2550\u2550")
        n = scrape_eprx_range(eprx_since)
        typer.echo(f"   EPRX TOTAL {n} rows upserted")


@app.command()
def analyze(
    target: Optional[str] = typer.Option(None, help="Date to analyze (YYYY-MM-DD, default: yesterday)"),
):
    """Compute analysis features for a given date."""
    from repower.analysis.features import run_analysis

    target_date = date.fromisoformat(target) if target else yesterday_jst()
    features = run_analysis(target_date)
    typer.echo(f"Analysis for {target_date}: {len(features)} feature keys computed")


@app.command()
def notify(
    target: Optional[str] = typer.Option(None, help="Date to post (YYYY-MM-DD, default: yesterday)"),
    dry_run: bool = typer.Option(False, help="Print payload without posting"),
):
    """Post analysis digest to webhook."""
    from repower.notify.webhook import notify as do_notify

    target_date = date.fromisoformat(target) if target else yesterday_jst()
    ok = do_notify(target_date, dry_run=dry_run)
    if ok:
        typer.echo("✓ Notification sent")
    else:
        typer.echo("✗ Notification failed", err=True)
        raise typer.Exit(code=1)


@app.command()
def run_all(
    months_back: int = typer.Option(2, help="TSO months to fetch (covers publication lag)"),
    dry_run: bool = typer.Option(False, help="Skip webhook post"),
):
    """Run full pipeline: scrape \u2192 analyze \u2192 notify."""
    from repower.scrapers.areas import scrape_all_areas, AREA_NAMES
    from repower.scrapers.jepx_spot import scrape_jepx
    from repower.scrapers.fuels_futures import scrape_fuels
    from repower.scrapers.news_rss import scrape_news
    from repower.scrapers.eprx import scrape_eprx, scrape_eprx_tieline
    from repower.analysis.features import run_analysis
    from repower.notify.webhook import notify as do_notify

    typer.echo("\u2550\u2550\u2550 SCRAPE \u2550\u2550\u2550")
    results = scrape_all_areas(months_back=months_back)
    for a, n in results.items():
        typer.echo(f"   {AREA_NAMES.get(a, a):<25} {n:>6} rows")
    scrape_jepx()
    scrape_fuels()
    scrape_news()
    scrape_eprx()
    scrape_eprx_tieline()

    typer.echo("═══ ANALYZE ═══")
    yesterday = yesterday_jst()
    run_analysis(yesterday)

    typer.echo("═══ POLICY DETECT ═══")
    try:
        from repower.policy.detect import detect as policy_detect
        res = policy_detect()
        new = sum(r["new"] for r in res)
        typer.echo(f"   {new} new committee meeting(s) detected")
    except Exception as e:  # noqa: BLE001 — policy detection must not break the data pipeline
        typer.echo(f"   policy detect skipped: {e}", err=True)

    typer.echo("═══ NOTIFY ═══")
    do_notify(yesterday, dry_run=dry_run)

    typer.echo("═══ DONE ═══")


@app.command()
def push_hf():
    """Push the local database to Hugging Face Dataset."""
    from repower.hf_sync import push_db_to_hf
    push_db_to_hf()
    typer.echo("✓ Database pushed to Hugging Face")


@app.command()
def pull_hf():
    """Pull the database from Hugging Face Dataset."""
    from repower.hf_sync import pull_db_from_hf
    pull_db_from_hf()
    typer.echo("✓ Database pulled from Hugging Face")


@app.command()
def init_db_cmd():
    """Initialize the database (create tables)."""
    from repower.db import init_db
    init_db()
    typer.echo("✓ Database initialized")


# ── Policy observer ──────────────────────────────────────────────────────────
policy_app = typer.Typer(name="policy", help="Japanese energy-policy committee observer")
app.add_typer(policy_app, name="policy")


@policy_app.command("detect")
def policy_detect(
    committee: str = typer.Option("all", help="Committee key or 'all'"),
    window: int = typer.Option(8, help="Enumerate materials for the newest N new meetings"),
    dry_run: bool = typer.Option(False, help="Report new meetings without writing to the DB"),
):
    """Detect new committee meetings (no NotebookLM auth required)."""
    from repower.policy.detect import detect

    keys = None if committee == "all" else [committee]
    results = detect(keys, enumerate_window=window, dry_run=dry_run)
    typer.echo(f"{'KEY':<28}{'SRC':<6}{'STATUS':<10}{'ONLINE':>7}{'KNOWN':>7}{'NEW':>5}")
    for r in results:
        typer.echo(
            f"{r['key']:<28}{r['source']:<6}{r['status']:<10}"
            f"{str(r['latest_online'] or '-'):>7}{str(r['known_latest'] or '-'):>7}{r['new']:>5}"
        )
    typer.echo(f"── {sum(r['new'] for r in results)} new meeting(s) total ──")


@policy_app.command("run")
def policy_run(
    committee: str = typer.Option("all", help="Committee key or 'all'"),
    max_per_run: int = typer.Option(5, help="Max meetings to summarise this run (rate/cost guard)"),
):
    """Summarise pending meetings via NotebookLM (requires `notebooklm login`)."""
    from repower.policy.pipeline import run

    keys = None if committee == "all" else [committee]
    summary = run(keys, max_per_run=max_per_run)
    typer.echo(
        f"processed={summary['processed']} done={summary['done']} "
        f"errored={summary['errored']} synthesized={summary['synthesized']}"
    )


@policy_app.command("backfill")
def policy_backfill(
    committee: str = typer.Option(..., help="Committee key (backfill one at a time)"),
    since_meeting: int = typer.Option(..., help="Earliest meeting number to summarise"),
    max_per_run: int = typer.Option(10, help="Max meetings to summarise this run"),
):
    """Throttled historical backfill for one committee (newest-first), requires auth."""
    from repower.policy.detect import detect
    from repower.policy.pipeline import run

    detect([committee], backfill_to=since_meeting)
    summary = run([committee], max_per_run=max_per_run)
    typer.echo(
        f"backfilled {committee}: done={summary['done']} errored={summary['errored']} "
        f"synthesized={summary['synthesized']}"
    )


@policy_app.command("resume")
def policy_resume():
    """Finish meetings left mid-flight after a partial failure (requires auth)."""
    from repower.policy.pipeline import resume

    summary = resume()
    typer.echo(f"resumed: done={summary['done']} errored={summary['errored']}")


@policy_app.command("status")
def policy_status():
    """Show per-committee state: latest summarised meeting and pending counts."""
    from collections import Counter

    from repower.policy.committees import COMMITTEES
    from repower.policy.store import get_committee, pending_meetings, sync_committees

    sync_committees()
    pend = Counter(m["committee_key"] for m in pending_meetings())
    typer.echo(f"{'KEY':<28}{'SRC':<6}{'LATEST':>7}{'PENDING':>9}")
    for c in COMMITTEES:
        row = get_committee(c.key)
        latest = row.latest_meeting if row and row.latest_meeting else "-"
        typer.echo(f"{c.key:<28}{c.source:<6}{str(latest):>7}{pend.get(c.key, 0):>9}")


@policy_app.command("digest")
def policy_digest(
    since_days: int = typer.Option(7, help="Window of recently summarised meetings to include"),
    dry_run: bool = typer.Option(False, help="Print the digest without posting to the webhook"),
):
    """Assemble a digest of recently summarised meetings (for the weekly run)."""
    from repower.policy.digest import build_digest, post_digest

    md = build_digest(since_days=since_days)
    typer.echo(md)
    if not dry_run:
        ok = post_digest(md)
        typer.echo("✓ Digest posted" if ok else "(no webhook configured / post failed)")


if __name__ == "__main__":
    app()
