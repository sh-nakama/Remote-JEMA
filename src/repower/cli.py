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
    area: str = typer.Option("tepco", help="TSO area slug for the demand/supply features"),
):
    """Compute analysis features for a given date."""
    from repower.analysis.features import run_analysis

    target_date = date.fromisoformat(target) if target else yesterday_jst()
    features = run_analysis(target_date, area=area)
    typer.echo(f"Analysis for {target_date} ({area}): {len(features)} feature keys computed")


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
        typer.echo("Notification sent")
    else:
        typer.echo("Notification failed", err=True)
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
    try:
        run_analysis(yesterday)
    except Exception as e:  # noqa: BLE001 — analysis must not block the HF push of scraped data
        typer.echo(f"   analyze skipped: {e}", err=True)

    typer.echo("═══ POLICY DETECT ═══")
    try:
        from repower.policy.detect import backfill_dates, detect as policy_detect
        res = policy_detect()
        new = sum(r["new"] for r in res)
        typer.echo(f"   {new} new committee meeting(s) detected")
        # Fill meeting dates for anything still missing one. Cheap in steady state:
        # one index fetch per METI/EGC committee; OCCTO capped to the newest few.
        dated = backfill_dates(only_missing=True, occto_limit=6)
        typer.echo(f"   {sum(r['dated'] for r in dated)} meeting date(s) filled")
    except Exception as e:  # noqa: BLE001 — policy detection must not break the data pipeline
        typer.echo(f"   policy detect skipped: {e}", err=True)

    typer.echo("═══ POLICY SCHEDULE ═══")
    try:
        from repower.policy.schedule import refresh_upcoming
        n_up = refresh_upcoming()
        typer.echo(f"   {n_up} upcoming meeting(s) scheduled")
    except Exception as e:  # noqa: BLE001 — schedule scrape must not break the data pipeline
        typer.echo(f"   policy schedule skipped: {e}", err=True)

    typer.echo("═══ POLICY CATALOG ═══")
    try:
        from repower.policy.catalog import discover_committees
        cat = discover_committees()
        typer.echo(f"   {cat['inserted']} new committee(s) discovered ({cat['found']} listed)")
    except Exception as e:  # noqa: BLE001 — catalog scrape must not break the data pipeline
        typer.echo(f"   policy catalog skipped: {e}", err=True)

    typer.echo("═══ NOTIFY ═══")
    try:
        do_notify(yesterday, dry_run=dry_run)
    except Exception as e:  # noqa: BLE001 — a failed webhook post must not block the HF push
        typer.echo(f"   notify skipped: {e}", err=True)

    typer.echo("═══ DONE ═══")


@app.command()
def push_hf():
    """Push the local database to Hugging Face Dataset."""
    from repower.hf_sync import push_db_to_hf
    push_db_to_hf()
    typer.echo("Database pushed to Hugging Face")


@app.command()
def pull_hf():
    """Pull the database from Hugging Face Dataset."""
    from repower.hf_sync import pull_db_from_hf
    pull_db_from_hf()
    typer.echo("Database pulled from Hugging Face")


@app.command()
def export_web(out: str = "web/public/data/web"):
    """Export static JSON snapshots for the web frontend (served at /data/web/**)."""
    from repower.dashboard.export_web import export_web as run_export
    manifest = run_export(out)
    ds = manifest["datasets"]
    files = sum(d.get("files", 0) for d in ds.values())
    kib = sum(d.get("bytes", 0) for d in ds.values()) // 1024
    typer.echo(
        f"Exported web snapshots -> {out}  (anchor {manifest['anchor']}, "
        f"{files} files, {kib} KiB across {sorted(ds)})"
    )
    typer.echo(f"Sources: {manifest['sources']}")


@app.command("web-api")
def web_api(
    port: int = typer.Option(8787, help="Port to listen on"),
    host: str = typer.Option("127.0.0.1", help="Host to bind"),
):
    """Run the local API for the web app's interactive mode (Manage + Run catch-up).

    Start this alongside ``npm run dev`` in ``web/``; the Vite dev proxy forwards
    ``/api`` here. The deployed GitHub Pages build has no proxy and stays read-only.
    """
    from repower.web_api import serve

    serve(port=port, host=host)


@app.command()
def init_db_cmd():
    """Initialize the database (create tables)."""
    from repower.db import init_db
    init_db()
    typer.echo("Database initialized")


# ── Policy observer ──────────────────────────────────────────────────────────
policy_app = typer.Typer(name="policy", help="Japanese energy-policy committee observer")
app.add_typer(policy_app, name="policy")


def _require_auth_or_exit() -> None:
    """Clean pre-check for NotebookLM auth: print a plain message and exit (no
    traceback) when the session is missing/stale, so operators and the catch-up
    loop get an actionable line instead of a stack trace."""
    from repower.policy.notebook import auth_ok

    if not auth_ok():
        typer.echo("NotebookLM auth is missing/stale.", err=True)
        typer.echo("Run `notebooklm login` locally (or refresh the NOTEBOOKLM_AUTH_JSON "
                   "secret), then retry.", err=True)
        raise typer.Exit(code=2)


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


@policy_app.command("dates")
def policy_dates(
    committee: str = typer.Option("all", help="Committee key or 'all'"),
    all_meetings: bool = typer.Option(
        False, "--all", help="Re-read dates for every meeting (default: only those missing a date)"
    ),
    occto_limit: int = typer.Option(
        0, help="Cap OCCTO subpage fetches per committee (0 = no cap)"
    ),
):
    """Backfill meeting dates from the committees' official pages (no auth required)."""
    from repower.policy.detect import backfill_dates

    keys = None if committee == "all" else [committee]
    results = backfill_dates(
        keys,
        only_missing=not all_meetings,
        occto_limit=(occto_limit or None),
    )
    typer.echo(f"{'KEY':<28}{'SRC':<6}{'DATED':>6}")
    for r in results:
        typer.echo(f"{r['key']:<28}{r['source']:<6}{r['dated']:>6}")
    typer.echo(f"-- {sum(r['dated'] for r in results)} meeting date(s) set --")


@policy_app.command("schedule")
def policy_schedule():
    """Refresh the upcoming-meeting snapshot from external calendars (no auth required)."""
    from repower.policy.schedule import fetch_upcoming
    from repower.policy.store import replace_upcoming

    rows = fetch_upcoming()
    written = replace_upcoming(rows)
    matched = sum(1 for r in rows if r.committee_key)
    typer.echo(f"{'DATE':<12}{'ORG':<7}{'#':>4}  NAME")
    for r in rows:
        num = str(r.meeting_num) if r.meeting_num else "-"
        tick = "*" if r.committee_key else " "
        typer.echo(f"{r.date.isoformat():<12}{r.org:<7}{num:>4}{tick} {r.name_ja[:52]}")
    typer.echo(f"-- {written} upcoming meeting(s); {matched} matched to tracked committees (*) --")


@policy_app.command("run")
def policy_run(
    committee: str = typer.Option("all", help="Committee key or 'all'"),
    max_per_run: int = typer.Option(5, help="Max meetings to summarise this run (rate/cost guard)"),
):
    """Summarise pending meetings via NotebookLM (requires `notebooklm login`)."""
    from repower.policy.pipeline import run

    _require_auth_or_exit()
    keys = None if committee == "all" else [committee]
    summary = run(keys, max_per_run=max_per_run)
    typer.echo(
        f"processed={summary['processed']} done={summary['done']} "
        f"errored={summary['errored']} synthesized={summary['synthesized']}"
    )
    if summary.get("rate_limited"):
        typer.echo("WARNING: NotebookLM rate limit hit - run stopped early; remaining meetings "
                   "stay pending (retry later; the cap resets over time).")


@policy_app.command("backfill")
def policy_backfill(
    committee: str = typer.Option(..., help="Committee key (backfill one at a time)"),
    since_meeting: int = typer.Option(..., help="Earliest meeting number to summarise"),
    max_per_run: int = typer.Option(10, help="Max meetings to summarise this run"),
):
    """Throttled historical backfill for one committee (newest-first), requires auth."""
    from repower.policy.detect import backfill_dates, detect
    from repower.policy.pipeline import run

    detect([committee], backfill_to=since_meeting)  # auth-free; prime the worklist first
    backfill_dates([committee], only_missing=True)  # auth-free; fill meeting dates too
    _require_auth_or_exit()
    summary = run([committee], max_per_run=max_per_run)
    typer.echo(
        f"backfilled {committee}: done={summary['done']} errored={summary['errored']} "
        f"synthesized={summary['synthesized']}"
    )
    if summary.get("rate_limited"):
        typer.echo("WARNING: NotebookLM rate limit hit - re-run this backfill later to continue "
                   "(meetings left are still pending; the cap resets over time).")


@policy_app.command("resume")
def policy_resume():
    """Finish meetings left mid-flight after a partial failure (requires auth)."""
    from repower.policy.pipeline import resume

    _require_auth_or_exit()
    summary = resume()
    typer.echo(f"resumed: done={summary['done']} errored={summary['errored']}")
    if summary.get("rate_limited"):
        typer.echo("WARNING: NotebookLM rate limit hit - re-run `policy resume` later to finish.")


@policy_app.command("status")
def policy_status():
    """Show per-committee state: enabled flag, priority, latest meeting, pending counts."""
    from collections import Counter

    from repower.policy.store import list_committees, pending_meetings, sync_committees

    sync_committees()
    pend = Counter(m["committee_key"] for m in pending_meetings())
    typer.echo(f"{'KEY':<28}{'SRC':<6}{'ON':>3}{'PRIO':>5}{'LATEST':>7}{'PENDING':>9}")
    for c in list_committees():
        latest = c["latest_meeting"] if c["latest_meeting"] else "-"
        on = "y" if c["enabled"] else "-"
        tag = "*" if c["user_added"] else ""
        typer.echo(
            f"{c['committee_key'] + tag:<28}{c['source']:<6}{on:>3}{c['priority']:>5}"
            f"{str(latest):>7}{pend.get(c['committee_key'], 0):>9}"
        )


@policy_app.command("add")
def policy_add(
    key: str = typer.Option(..., help="Unique committee key (ascii id, e.g. ccs_jigyo)"),
    name_ja: str = typer.Option(..., help="Japanese committee name"),
    url: str = typer.Option(..., help="Committee homepage URL"),
    source: str = typer.Option("METI", help="METI | OCCTO | EGC"),
    name_en: str = typer.Option("", help="English name (optional)"),
    priority: int = typer.Option(100, help="Summarisation priority (lower = first)"),
):
    """Add (or update) a tracked committee from the terminal."""
    from repower.policy.store import add_committee

    src = source.upper()
    if src not in {"METI", "OCCTO", "EGC"}:
        typer.echo("source must be one of METI / OCCTO / EGC", err=True)
        raise typer.Exit(code=2)
    created = add_committee(key=key, name_ja=name_ja, name_en=name_en or key,
                            url=url, source=src, priority=priority)
    # ASCII-only echo (cp932 consoles choke on Japanese names).
    typer.echo(f"{'added' if created else 'updated'} committee '{key}' ({src}, priority={priority})")


@policy_app.command("enable")
def policy_enable(key: str = typer.Argument(..., help="Committee key to start tracking")):
    """Enable tracking of a committee (detection + summarisation)."""
    from repower.policy.store import set_committee_enabled

    set_committee_enabled(key, True)
    typer.echo(f"enabled '{key}'")


@policy_app.command("disable")
def policy_disable(key: str = typer.Argument(..., help="Committee key to stop tracking")):
    """Disable tracking of a committee (kept in the DB, skipped by detect/run)."""
    from repower.policy.store import set_committee_enabled

    set_committee_enabled(key, False)
    typer.echo(f"disabled '{key}'")


@policy_app.command("track")
def policy_track(
    committee: str = typer.Argument(..., help="Committee key to start tracking"),
):
    """Enable a committee so the daily detect/summarise pipeline processes it."""
    from repower.policy.store import set_committee_enabled, sync_committees

    sync_committees()
    if set_committee_enabled(committee, True):
        typer.echo(f"tracking {committee}")
    else:
        typer.echo(f"unknown committee: {committee} (run `policy list` to see keys)", err=True)
        raise typer.Exit(1)


@policy_app.command("untrack")
def policy_untrack(
    committee: str = typer.Argument(..., help="Committee key to stop tracking"),
):
    """Disable a committee — kept in the catalog but skipped by detect/summarise."""
    from repower.policy.store import set_committee_enabled, sync_committees

    sync_committees()
    if set_committee_enabled(committee, False):
        typer.echo(f"untracked {committee}")
    else:
        typer.echo(f"unknown committee: {committee} (run `policy list` to see keys)", err=True)
        raise typer.Exit(1)


@policy_app.command("priority")
def policy_priority(
    committee: str = typer.Argument(..., help="Committee key"),
    priority: int = typer.Argument(..., help="Queue priority (lower = summarised first)"),
):
    """Set a committee's summarisation priority — its catch-up queue position.

    Lower runs first (system_review=1, emissions_trading=2, chousei_jukyu=3, others
    default 100). Persisted across syncs, so it's how a committee jumps the queue
    permanently.
    """
    from repower.policy.store import set_committee_priority, sync_committees

    sync_committees()
    if priority < 1:
        typer.echo("priority must be >= 1", err=True)
        raise typer.Exit(1)
    if set_committee_priority(committee, priority):
        typer.echo(f"{committee} priority = {priority}")
    else:
        typer.echo(f"unknown committee: {committee} (run `policy list` to see keys)", err=True)
        raise typer.Exit(1)


@policy_app.command("list")
def policy_list():
    """List every catalog committee and whether it is tracked (enabled)."""
    from collections import Counter

    from repower.policy.store import list_committees, pending_meetings, sync_committees

    sync_committees()
    pend = Counter(m["committee_key"] for m in pending_meetings())
    rows = list_committees()
    typer.echo(f"{'KEY':<28}{'SRC':<6}{'TRACK':<6}{'PRIO':>5}{'LATEST':>7}{'PEND':>6}")
    for r in rows:
        latest = r["latest_meeting"] if r["latest_meeting"] else "-"
        track = "yes" if r["enabled"] else "no"
        typer.echo(
            f"{r['key']:<28}{r['source']:<6}{track:<6}{r['priority']:>5}{str(latest):>7}{pend.get(r['key'], 0):>6}"
        )
    n_tracked = sum(1 for r in rows if r["enabled"])
    typer.echo(f"-- {n_tracked}/{len(rows)} tracked --")


@policy_app.command("discover")
def policy_discover():
    """Enumerate energy committees from the METI/OCCTO/EGC indexes into the catalog.

    No auth. New committees are added untracked (``enabled=0``) — track them with
    ``policy track <key>`` (or the web Manage modal) to include them in the pipeline.
    """
    from repower.policy.catalog import discover_committees

    res = discover_committees()
    typer.echo(f"catalog: {res['found']} committees listed, {res['inserted']} newly discovered")
    for src, n in sorted(res["by_source"].items()):
        typer.echo(f"  {src:<6}{n}")


@policy_app.command("crosscheck")
def policy_crosscheck(
    notify: bool = typer.Option(False, help="Post the missing-committees report to the webhook"),
):
    """Cross-check energy-board.xvps.jp's recent committees against our catalog.

    Finds energy committees the aggregator surfaces that our catalog didn't contain
    (by METI path) — committees we were failing to track — and *accumulates* them
    into the catalog as discovered / untracked rows, so they appear in the Manage
    modal and ``committees.json`` ready to track. Intended to run monthly (only the
    site's recent feed is visible). No auth. Track a result with ``policy track <key>``.
    """
    import sys

    from repower.policy.energy_board import cross_check

    # Committee names are Japanese; a piped/redirected Windows console defaults to a
    # non-UTF-8 encoding and would crash on echo. Force UTF-8 (no-op on the Linux CI).
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    res = cross_check()
    missing = res["missing"]
    typer.echo(
        f"energy-board: {res['theirs']} recent committees · {res['matched']} already in our catalog · "
        f"{res['added']} added to catalog (untracked)"
    )
    for m in missing:
        typer.echo(f"  ADDED  {(m['council'] or '')[:46]:<46} {m['dir']}")
    if missing:
        typer.echo("  → track any of these with `repower policy track <key>` or the web Manage modal.")
    if notify and missing:
        from repower.policy.digest import post_digest

        lines = [
            "# Committee cross-check — energy-board.xvps.jp",
            "",
            f"{len(missing)} energy committee(s) on energy-board were **not in our catalog** and "
            "have been added as untracked — track them in the Manage modal or with "
            "`repower policy track <key>`:",
            "",
        ]
        lines += [f"- {m['council']} (`{m['dir']}`) — {m['url']}" for m in missing]
        posted = post_digest("\n".join(lines))
        typer.echo("posted to webhook" if posted else "webhook not configured / post failed")


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
        typer.echo("Digest posted" if ok else "(no webhook configured / post failed)")


if __name__ == "__main__":
    app()
