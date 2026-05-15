"""CLI entry point for repower — powered by Typer."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import typer

app = typer.Typer(name="repower", help="Tokyo power market analysis bot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@app.command()
def scrape(
    months_back: int = typer.Option(1, help="TSO months to re-fetch (current + N previous)"),
    area: str = typer.Option("all", help="Area slug (e.g. tepco, kansai) or 'all'"),
    skip_jepx: bool = typer.Option(False, help="Skip JEPX spot prices"),
    skip_fuels: bool = typer.Option(False, help="Skip fuel futures"),
    skip_news: bool = typer.Option(False, help="Skip news RSS"),
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


@app.command()
def backfill(
    since: str = typer.Option(
        "2024-04",
        help="Earliest YYYY-MM month to fetch (default 2024-04, the start of the standardised TSO publication format)",
    ),
    area: str = typer.Option("all", help="Area slug or 'all'"),
):
    """One-shot historical backfill of every month from --since to today.

    Idempotent: existing rows are upserted in place via (area, date, time) PK,
    so this is safe to re-run. Designed to be invoked once locally or via
    workflow_dispatch, then `scrape` handles incremental daily updates.
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


@app.command()
def analyze(
    target: Optional[str] = typer.Option(None, help="Date to analyze (YYYY-MM-DD, default: yesterday)"),
):
    """Compute analysis features for a given date."""
    from repower.analysis.features import run_analysis

    target_date = date.fromisoformat(target) if target else date.today() - timedelta(days=1)
    features = run_analysis(target_date)
    typer.echo(f"Analysis for {target_date}: {len(features)} feature keys computed")


@app.command()
def notify(
    target: Optional[str] = typer.Option(None, help="Date to post (YYYY-MM-DD, default: yesterday)"),
    dry_run: bool = typer.Option(False, help="Print payload without posting"),
):
    """Post analysis digest to webhook."""
    from repower.notify.webhook import notify as do_notify

    target_date = date.fromisoformat(target) if target else date.today() - timedelta(days=1)
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
    from repower.analysis.features import run_analysis
    from repower.notify.webhook import notify as do_notify

    typer.echo("\u2550\u2550\u2550 SCRAPE \u2550\u2550\u2550")
    results = scrape_all_areas(months_back=months_back)
    for a, n in results.items():
        typer.echo(f"   {AREA_NAMES.get(a, a):<25} {n:>6} rows")
    scrape_jepx()
    scrape_fuels()
    scrape_news()

    typer.echo("═══ ANALYZE ═══")
    yesterday = date.today() - timedelta(days=1)
    features = run_analysis(yesterday)

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


if __name__ == "__main__":
    app()
