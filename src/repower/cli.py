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
    months_back: int = typer.Option(1, help="TEPCO months to re-fetch (current + N previous)"),
    jepx_year: Optional[int] = typer.Option(None, help="JEPX year to fetch (default: current)"),
    fuel_days: int = typer.Option(7, help="Days of fuel data to fetch"),
):
    """Scrape all data sources."""
    from repower.scrapers.tepco_area import scrape_tepco
    from repower.scrapers.jepx_spot import scrape_jepx
    from repower.scrapers.fuels_futures import scrape_fuels
    from repower.scrapers.news_rss import scrape_news

    typer.echo("── TEPCO area supply/demand ──")
    n = scrape_tepco(months_back=months_back)
    typer.echo(f"   {n} rows upserted")

    typer.echo("── JEPX spot prices ──")
    n = scrape_jepx(year=jepx_year)
    typer.echo(f"   {n} rows upserted")

    typer.echo("── Fuel prices ──")
    n = scrape_fuels(days_back=fuel_days)
    typer.echo(f"   {n} rows upserted")

    typer.echo("── News RSS ──")
    n = scrape_news()
    typer.echo(f"   {n} new items")


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
