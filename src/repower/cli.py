"""CLI entry point for repower — powered by Typer."""

from __future__ import annotations

import logging
import sys
from datetime import date

import typer

from repower.timeutil import today_jst, yesterday_jst

# This CLI prints Japanese committee names, box-drawing banners and typographic
# dashes. On a Japanese Windows console stdout defaults to cp932, which cannot
# encode any of them — the command then dies with a UnicodeEncodeError partway
# through its own output, which reads as a crash in the scrape rather than in the
# printing. Force UTF-8 and replace anything still unmappable, so output is never
# the thing that fails.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):  # already wrapped, or not a text stream
        pass

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
    jepx_year: int | None = typer.Option(None, help="JEPX year to fetch (default: current)"),
    fuel_days: int = typer.Option(7, help="Days of fuel data to fetch"),
):
    """Scrape TSO area data + market sources (recent months only)."""
    from repower.scrapers.areas import AREA_NAMES, scrape_all_areas, scrape_area
    from repower.scrapers.fuels_futures import scrape_fuels
    from repower.scrapers.jepx_spot import scrape_jepx
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
    from repower.scrapers.areas import ALL_SCRAPERS, AREA_NAMES

    try:
        sy, sm = [int(x) for x in since.split("-")]
    except Exception as e:
        raise typer.BadParameter(f"--since must be YYYY-MM, got {since!r}") from e

    # JST, not date.today(): the CI cron fires ~20:30 UTC, already the next day in JST.
    today = today_jst()
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
    target: str | None = typer.Option(None, help="Date to analyze (YYYY-MM-DD, default: yesterday)"),
    area: str = typer.Option("tepco", help="TSO area slug for the demand/supply features"),
):
    """Compute analysis features for a given date."""
    from repower.analysis.features import run_analysis

    target_date = date.fromisoformat(target) if target else yesterday_jst()
    features = run_analysis(target_date, area=area)
    typer.echo(f"Analysis for {target_date} ({area}): {len(features)} feature keys computed")


@app.command()
def notify(
    target: str | None = typer.Option(None, help="Date to post (YYYY-MM-DD, default: yesterday)"),
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
    from repower.analysis.features import run_analysis
    from repower.notify.webhook import notify as do_notify
    from repower.scrapers.areas import AREA_NAMES, scrape_all_areas
    from repower.scrapers.eprx import scrape_eprx, scrape_eprx_tieline
    from repower.scrapers.fuels_futures import scrape_fuels
    from repower.scrapers.jepx_spot import scrape_jepx
    from repower.scrapers.news_rss import scrape_news

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
        from repower.policy.detect import backfill_dates
        from repower.policy.detect import detect as policy_detect
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


@app.command("refresh-web")
def refresh_web(
    months_back: int = typer.Option(2, help="TSO months to re-fetch (current + N previous)"),
    lookback: int = typer.Option(6, help="Completed months to scan for entirely-missing data to recover"),
    out: str = typer.Option("web/public/data/web", help="Web snapshot output dir"),
):
    """Full data refresh for the web app: recover gaps → scrape everything → export.

    Backs the web app's interactive **Refresh** button (via ``web-api``). It first
    recovers any completed months entirely missing from the DB (parse / stale-304
    gaps), then re-scrapes every source, then regenerates the static JSON snapshots
    the frontend reads. Each source is guarded so one failure can't block the
    export of everything else.
    """
    from repower.dashboard.export_web import export_web as run_export
    from repower.scrapers.areas import AREA_NAMES, recover_missing_months, scrape_all_areas

    def _try(label: str, fn):
        try:
            typer.echo(f"   {label}: {fn()}")
        except Exception as e:  # noqa: BLE001 — a single source failure must not abort the refresh
            typer.echo(f"   {label} skipped: {e}", err=True)

    typer.echo("═══ RECOVER GAPS ═══")
    recovered = recover_missing_months(lookback=lookback)
    if recovered:
        for r in recovered:
            typer.echo(f"   recovered {AREA_NAMES.get(r['area'], r['area'])} {r['month']}: {r['rows']} rows")
    else:
        typer.echo("   no missing months found")

    typer.echo("═══ SCRAPE ═══")
    results = scrape_all_areas(months_back=months_back)
    for a, n in results.items():
        typer.echo(f"   {AREA_NAMES.get(a, a):<25} {n:>6} rows")
    from repower.scrapers.eprx import scrape_eprx, scrape_eprx_tieline
    from repower.scrapers.fuels_futures import scrape_fuels
    from repower.scrapers.jepx_spot import scrape_jepx
    from repower.scrapers.news_rss import scrape_news
    _try("JEPX rows", lambda: scrape_jepx())
    _try("fuel rows", lambda: scrape_fuels())
    _try("news items", lambda: scrape_news())
    _try("EPRX rows", lambda: scrape_eprx())
    _try("EPRX tieline rows", lambda: scrape_eprx_tieline())

    typer.echo("═══ EXPORT ═══")
    manifest = run_export(out)
    files = sum(d.get("files", 0) for d in manifest["datasets"].values())
    typer.echo(f"   exported {files} files (anchor {manifest['anchor']})")
    typer.echo(f"   sources: {manifest['sources']}")
    typer.echo("═══ DONE ═══")


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


# ── HTTP cache maintenance ───────────────────────────────────────────────────
cache_app = typer.Typer(name="cache", help="Conditional-GET HTTP cache maintenance")
app.add_typer(cache_app, name="cache")


@cache_app.command("status")
def cache_status_cmd():
    """Per-host cache summary: entries, last success, and how many are failing.

    Answers "which hosts are still succeeding?" and "when did this host last
    work?" — the questions that had to be hand-queried while diagnosing the METI
    WAF blocks.
    """
    from repower.scrapers.http_cache import cache_status

    rows = cache_status()
    if not rows:
        typer.echo("http_cache is empty")
        return
    typer.echo(f"{'HOST':38} {'ENTRIES':>7} {'FAILING':>7}  LAST SUCCESS")
    for r in rows:
        last = r["last_success"].strftime("%Y-%m-%d %H:%M") if r["last_success"] else "never"
        typer.echo(f"{r['host'][:38]:38} {r['entries']:>7} {r['failing']:>7}  {last}")
    typer.echo(f"\n{sum(r['entries'] for r in rows)} entries across {len(rows)} hosts")


@cache_app.command("prune")
def cache_prune_cmd(
    days: int = typer.Option(90, help="Drop entries not seen in this many days"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would be dropped"),
):
    """Evict stale cache entries so the HF-synced DB stops growing forever.

    Safe: a missing entry costs one unconditional re-fetch, never data.
    """
    from repower.scrapers.http_cache import cache_status, prune_cache

    if dry_run:
        from datetime import UTC, datetime, timedelta

        from repower.db import HttpCache, get_session, init_db

        init_db()
        s = get_session()
        try:
            cutoff = datetime.now(UTC) - timedelta(days=days)
            n = (
                s.query(HttpCache)
                .filter((HttpCache.last_checked.is_(None)) | (HttpCache.last_checked < cutoff))
                .count()
            )
        finally:
            s.close()
        typer.echo(f"would prune {n} entries not seen in {days} days")
        return
    before = sum(r["entries"] for r in cache_status())
    n = prune_cache(days)
    typer.echo(f"pruned {n} of {before} entries not seen in {days} days")


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


def _warn_if_stopped_early(summary: dict, retry_hint: str) -> None:
    """Explain a run that halted on the account/session rather than on its work.

    ``_require_auth_or_exit`` only gates the *start* of a run, so a cookie that
    lapses an hour in, a spent quota, or a NotebookLM that stops answering all
    surface here instead — as a plain line, since the pipeline now stops cleanly
    rather than raising.
    """
    reason = summary.get("stopped_early")
    if reason is None:
        return
    if reason == "auth_expired":
        typer.echo("WARNING: the NotebookLM session expired mid-run - stopped early. Run "
                   f"`notebooklm login`, then {retry_hint}", err=True)
    elif reason == "rate_limited":
        typer.echo(f"WARNING: NotebookLM rate limit hit - stopped early; {retry_hint} "
                   "(the cap resets over time).", err=True)
    else:
        typer.echo(f"WARNING: NotebookLM stopped responding - stopped early; {retry_hint}",
                   err=True)


def _report_deferred(count: int, noun: str) -> None:
    """Say that a pass stopped early, so a partial result doesn't read as a final one.

    Hosts like meti.go.jp only allow a handful of requests before blocking, so the
    sweeps stop short and come back later; without this the run looks complete.
    """
    if count:
        typer.echo(
            f"-- {count} {noun}(s) deferred: the host's request budget is spent. "
            "Re-run in a few minutes to continue. --"
        )


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
    _report_deferred(sum(1 for r in results if r["status"] == "deferred"), "committee")


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
    _report_deferred(sum(1 for r in results if r["deferred"]), "committee")


@policy_app.command("schedule")
def policy_schedule():
    """Refresh the upcoming-meeting snapshot from external calendars (no auth required)."""
    from repower.policy.schedule import ScheduleUnavailable, refresh_upcoming
    from repower.policy.store import list_upcoming

    try:
        refresh_upcoming()
    except ScheduleUnavailable as e:
        # A transient METI outage (network error or the overload/failover page) must
        # not wipe the stored snapshot — report it and show what's still on file.
        typer.echo(f"schedule feed unavailable: {e}", err=True)
    rows = list_upcoming()
    matched = sum(1 for r in rows if r["committee_key"])
    typer.echo(f"{'DATE':<12}{'ORG':<7}{'#':>4}  NAME")
    for r in rows:
        num = str(r["meeting_num"]) if r["meeting_num"] else "-"
        tick = "*" if r["committee_key"] else " "
        typer.echo(f"{r['date']:<12}{r['org']:<7}{num:>4}{tick} {r['name_ja'][:52]}")
    typer.echo(f"-- {len(rows)} upcoming meeting(s); {matched} matched to tracked committees (*) --")


@policy_app.command("materials")
def policy_materials(
    committee: str = typer.Option("all", help="Committee key or 'all'"),
    limit: int = typer.Option(0, help="Max material-less meetings per committee (0 = no limit)"),
):
    """Fetch materials for meetings detected without any (makes them visible in the UI)."""
    from repower.policy.detect import backfill_materials

    keys = None if committee == "all" else [committee]
    results = backfill_materials(keys, limit_per_committee=(limit or None))
    total = 0
    for r in results:
        if r["checked"]:
            typer.echo(f"{r['key']:<28}{r['source']:<6} materialised {r['materialised']}/{r['checked']}")
            total += r["materialised"]
    typer.echo(f"-- {total} meeting(s) populated with materials --")
    _report_deferred(sum(r["deferred"] for r in results), "meeting")


@policy_app.command("run")
def policy_run(
    committee: str = typer.Option("all", help="Committee key or 'all'"),
    max_per_run: int = typer.Option(5, help="Max meetings to summarise this run (rate/cost guard)"),
    breadth: bool | None = typer.Option(
        None, "--breadth/--depth-first",
        help="Breadth-first: summarise the newest pending meeting of each committee "
             "(in priority order) before going deeper — spreads a small daily quota "
             "across committees instead of draining one committee's backlog. Defaults "
             "to breadth-first for '--committee all' and depth-first for a single "
             "committee; pass --breadth/--depth-first to override.",
    ),
    meeting: int | None = typer.Option(
        None, "--meeting",
        help="Summarise exactly this meeting number of --committee and nothing else. "
             "Bypasses the pending queue, so an already-summarised meeting can be "
             "re-run (e.g. after a briefing was written from an incomplete source set).",
    ),
):
    """Summarise pending meetings via NotebookLM (requires `notebooklm login`)."""
    from repower.policy.pipeline import run

    _require_auth_or_exit()
    if meeting is not None and committee == "all":
        typer.echo("--meeting needs a specific --committee")
        raise typer.Exit(code=2)
    keys = None if committee == "all" else [committee]
    # Default: breadth-first across the whole tracked set (get the latest meeting of
    # each committee current first), depth-first when draining a single committee.
    breadth_first = (committee == "all") if breadth is None else breadth
    summary = run(keys, max_per_run=(1 if meeting is not None else max_per_run),
                  breadth_first=breadth_first, meeting_num=meeting)
    typer.echo(
        f"processed={summary['processed']} done={summary['done']} "
        f"errored={summary['errored']} blocked={summary.get('blocked', 0)} "
        f"skipped={summary.get('skipped', 0)} synthesized={summary['synthesized']}"
    )
    for host, n in sorted((summary.get("skipped_hosts") or {}).items()):
        typer.echo(f"  skipped {n} meeting(s) on {host} - its circuit breaker is open; "
                   f"they stay pending.")
    _warn_if_stopped_early(summary, "remaining meetings stay pending - retry later.")


@policy_app.command("queue")
def policy_queue(
    committee: str = typer.Option(..., help="Committee key"),
    meeting: int = typer.Option(..., help="Meeting number to move to the front of the queue"),
    clear: bool = typer.Option(False, "--clear", help="Remove it from the front instead"),
):
    """Put one meeting at the front of the summarisation queue (or take it off).

    The queue is otherwise ordered by committee priority then newest-meeting-first;
    a queued meeting outranks all of that, so this is how a specific meeting jumps
    ahead without re-prioritising its whole committee. The flag is cleared
    automatically once the meeting has been processed.
    """
    from repower.policy.store import clear_generation_request, request_generation

    if clear:
        clear_generation_request(committee, meeting, db_path=None)
        typer.echo(f"{committee} 第{meeting}回 removed from the front of the queue")
        return
    if not request_generation(committee, meeting, db_path=None):
        typer.echo(f"no such meeting: {committee} 第{meeting}回")
        raise typer.Exit(code=1)
    typer.echo(f"{committee} 第{meeting}回 queued - the next `policy run` takes it first")


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
    _warn_if_stopped_early(summary, "re-run this backfill later to continue.")


@policy_app.command("resume")
def policy_resume():
    """Finish meetings left mid-flight after a partial failure (requires auth)."""
    from repower.policy.pipeline import resume

    _require_auth_or_exit()
    summary = resume()
    typer.echo(f"resumed: done={summary['done']} errored={summary['errored']}")
    _warn_if_stopped_early(summary, "re-run `policy resume` later to finish.")


@policy_app.command("notebooks")
def policy_notebooks():
    """Audit the NotebookLM account against the DB and list untracked notebooks.

    Read-only on purpose. A notebook the DB doesn't reference is *usually* a leak
    (a `create_notebook` whose response timed out, or a superseded synthesis), but
    it can equally be one a human made in the same account — so this reports and
    never deletes. Check a candidate in the NotebookLM UI first, then remove it
    there.

    Rollover archives are flagged rather than listed as plain leaks: when a
    committee's synthesis fills up, the full notebook is deliberately left intact
    and only ``archive_watermark_meeting`` records that it happened — the
    archive's id is never stored, so it *looks* untracked. Deleting one destroys
    older meetings the DB does not duplicate.
    """
    import sqlite3

    from repower.config import DB_PATH
    from repower.policy.notebook import list_notebooks

    _require_auth_or_exit()
    con = sqlite3.connect(DB_PATH)
    try:
        known = {r[0] for r in con.execute(
            "SELECT synthesis_notebook_id FROM policy_committee "
            "WHERE synthesis_notebook_id IS NOT NULL")}
        known |= {r[0] for r in con.execute(
            "SELECT notebook_id FROM policy_meeting WHERE notebook_id IS NOT NULL")}
        rolled = {r[0] for r in con.execute(
            "SELECT committee_key FROM policy_committee "
            "WHERE archive_watermark_meeting IS NOT NULL")}
    finally:
        con.close()

    live = list_notebooks()
    untracked = [n for n in live if n.get("id") not in known]
    typer.echo(f"{len(live)} notebook(s) in the account, {len(untracked)} not referenced by the DB")
    archives = 0
    for n in sorted(untracked, key=lambda n: n.get("created_at") or ""):
        title = n.get("title") or ""
        # "<key> synthesis…" for a committee that has since rolled over is the
        # superseded notebook the rollover intentionally left behind.
        note = ""
        if "synthesis" in title and title.split(" ")[0] in rolled:
            note = "  <- rollover archive, keep"
            archives += 1
        typer.echo(f"  {n.get('created_at', '?'):<26} {n.get('id')}  {title}{note}")
    if untracked:
        typer.echo("Untracked != safe to delete - confirm each one in the NotebookLM UI first.")
    if archives:
        plural = "archive holds" if archives == 1 else "archives hold"
        typer.echo(f"{archives} rollover {plural} older meetings - deleting one loses "
                   "history the DB does not duplicate.")


@policy_app.command("status")
def policy_status():
    """Show per-committee state: enabled flag, priority, latest meeting, pending counts."""
    from collections import Counter

    from repower.policy.store import list_committees, pending_meetings, sync_committees

    sync_committees()
    pend = Counter(m["committee_key"] for m in pending_meetings())
    typer.echo(f"{'KEY':<28}{'SRC':<6}{'ON':>3}{'PRIO':>5}{'LATEST':>7}{'PENDING':>9}  {'FETCH':<22}")
    for c in list_committees():
        latest = c["latest_meeting"] if c["latest_meeting"] else "-"
        on = "y" if c["enabled"] else "-"
        tag = "*" if c["user_added"] else ""
        typer.echo(
            f"{c['committee_key'] + tag:<28}{c['source']:<6}{on:>3}{c['priority']:>5}"
            f"{str(latest):>7}{pend.get(c['committee_key'], 0):>9}  {_fetch_label(c):<22}"
        )


def _fetch_label(c: dict) -> str:
    """One-column summary of a committee's last fetch: kind + failure streak."""
    st = c.get("last_fetch_status")
    if not st:
        return "never fetched"
    if st != "error":
        return st
    n = c.get("consecutive_failures") or 0
    return f"{c.get('last_fetch_kind') or 'error'} x{n}"


# Why each failure kind happens and what actually fixes it. Printed by `doctor`
# so a failing committee comes with its remedy instead of just a slug.
#
# These are calibrated against measurement, not intuition. Notably, "back off and
# be gentler" is *not* the fix for METI's WAF: spacing requests 6s apart got fewer
# committees through than 1s did (1/12 vs 4/43), because that edge is stateful —
# once it flags the client, waiting does not un-flag it. So the remedies below say
# "come back later", not "go slower".
_FETCH_REMEDIES: dict[str, str] = {
    "blocked_403": "Host refused the client. Check curl_cffi is installed "
                   "(`pip install curl_cffi`); if it is, the impersonation profile may be stale.",
    "challenge_unresolved": "WAF JS challenge never cleared. The ladder is walked once per host "
                            "per pass, so this is the host that paid it. Widening the delays does "
                            "not help (measured); the host clears on its own — re-run later.",
    "circuit_open": "Collateral, not a fault of this committee: another committee on the same "
                    "host tripped the breaker and the rest of the pass short-circuited. Fix the "
                    "host's root failure above; these recover with it.",
    "deadline_exceeded": "The per-call time budget ran out. Raise the budget for this pass.",
    "not_found": "404 — the committee page has moved or been retired. "
                 "Fix the URL (`policy add --url ...`) or archive it (`policy archive <key>`).",
    "server_error": "The host returned 5xx/429 past the transient retries. Usually temporary.",
    "network_error": "DNS/TLS/connection failure. Check connectivity to the host.",
    "unexpected_status": "An HTTP status this layer has no handling for — inspect the detail.",
    "parse_error": "Fetched fine but the body could not be parsed — the page layout likely changed.",
}

# Kinds that are always downstream of some *other* committee's failure. They are
# reported, but summarised per host rather than itemised, and excluded from the
# "needs attention" count: a pass where one host goes hostile would otherwise
# report ~35 problems when there is one.
_COLLATERAL_KINDS = frozenset({"circuit_open"})


def _fetch_host(c: dict) -> str:
    """Host a committee's last fetch was aimed at, for grouping collateral damage.

    Prefers the URL actually fetched (which may be a sub-page) and falls back to
    the committee's configured homepage when a pass failed before issuing one.
    """
    from urllib.parse import urlsplit

    for candidate in (c.get("last_fetch_url"), c.get("url")):
        if candidate:
            host = (urlsplit(candidate).hostname or "").casefold()
            if host:
                return host
    return "?"


@policy_app.command("doctor")
def policy_doctor(
    failing_only: bool = typer.Option(True, "--failing-only/--all",
                                      help="Only show committees whose last fetch failed"),
    history: bool = typer.Option(False, "--history", help="Show recent attempts per committee"),
):
    """Diagnose per-committee fetch failures — what broke, for how long, and the fix.

    Reads the status persisted by each detection pass. The HTTP cache cannot answer
    this: a 403, an uncleared WAF challenge, an open circuit breaker and an
    exhausted budget all raise before a cache row is written, so a committee we
    can no longer fetch leaves no trace there at all.
    """
    from collections import defaultdict

    from repower.policy.store import fetch_events, list_committees, sync_committees

    sync_committees()
    rows = list_committees()

    # An archived committee is never fetched again, so whatever failure was recorded
    # on its last pass is frozen — reporting it forever would mean archiving a dead
    # committee (the remedy this command recommends) never clears the warning.
    archived = [c for c in rows if c.get("archived")]
    rows = [c for c in rows if not c.get("archived")]

    by_kind: dict[str, list[dict]] = defaultdict(list)
    unknown: list[dict] = []
    for c in rows:
        st = c.get("last_fetch_status")
        if st == "error":
            by_kind[c.get("last_fetch_kind") or "unknown"].append(c)
        elif st is None:
            # No recorded outcome yet — either a fresh install or a DB that predates
            # this tracking. That is every committee until the first pass runs, so
            # listing them in full would bury the actual failures.
            unknown.append(c)
        elif not failing_only:
            by_kind[st].append(c)

    def _stamp(v) -> str:
        return str(v)[:16] if v else "-"

    if not by_kind:
        if unknown and len(unknown) == len(rows):
            typer.echo(
                f"No fetch outcomes recorded yet for any of {len(rows)} committees.\n"
                "Run `repower policy detect` (or the catch-up job): each pass records "
                "per-committee status, and this command then explains any failures."
            )
        else:
            typer.echo("All committees fetched successfully on their last pass.")
            if unknown:
                typer.echo(f"({len(unknown)} not yet attempted.)")
        return

    # Failures first, then the informational buckets.
    order = sorted(by_kind, key=lambda k: (k in ("ok", "unchanged"), k))
    for kind in order:
        group = sorted(by_kind[kind], key=lambda c: (-(c.get("consecutive_failures") or 0), c["key"]))
        typer.echo(f"\n### {kind}  ({len(group)} committee(s))")
        remedy = _FETCH_REMEDIES.get(kind)
        if remedy:
            typer.echo(f"    → {remedy}")
        if kind in _COLLATERAL_KINDS and not history:
            # One line per host, not per committee: these all share a single cause,
            # and itemising them buries the real failure in its own fallout.
            by_host: dict[str, list[dict]] = defaultdict(list)
            for c in group:
                by_host[_fetch_host(c)].append(c)
            for host in sorted(by_host):
                members = sorted(c["key"] for c in by_host[host])
                shown = ", ".join(members[:6])
                more = f", +{len(members) - 6} more" if len(members) > 6 else ""
                typer.echo(f"    {host}  ({len(members)}): {shown}{more}")
            continue
        typer.echo(f"    {'KEY':<28}{'SRC':<6}{'TRK':<4}{'FAILS':>6}  {'LAST TRY':<17}{'LAST OK':<17}DETAIL")
        for c in group:
            trk = "yes" if c["enabled"] else "no"
            typer.echo(
                f"    {c['key']:<28}{c['source']:<6}{trk:<4}"
                f"{c.get('consecutive_failures') or 0:>6}  "
                f"{_stamp(c.get('last_fetch_at')):<17}{_stamp(c.get('last_ok_at')):<17}"
                f"{(c.get('last_fetch_detail') or '')[:70]}"
            )
            if history:
                for e in fetch_events(c["key"], limit=5):
                    typer.echo(f"        {_stamp(e['at']):<17}{e['status']:<10}{e['kind'] or ''}")

    if unknown:
        typer.echo(f"\n{len(unknown)} committee(s) have no recorded outcome yet"
                   f"{' (run `repower policy doctor --all` to list them)' if failing_only else ''}.")
        if not failing_only:
            typer.echo("    " + ", ".join(sorted(c["key"] for c in unknown)))

    n_bad = sum(
        len(v) for k, v in by_kind.items()
        if k not in ("ok", "unchanged") and k not in _COLLATERAL_KINDS
    )
    n_collateral = sum(len(v) for k, v in by_kind.items() if k in _COLLATERAL_KINDS)
    tail = f" (+{n_collateral} collateral)" if n_collateral else ""
    typer.echo(f"\n-- {n_bad}/{len(rows)} committee(s) need attention{tail} --")
    if archived:
        typer.echo(f"({len(archived)} archived committee(s) excluded: "
                   f"{', '.join(sorted(c['key'] for c in archived))})")


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
    """Disable tracking of a committee (kept in the DB, skipped by summarisation).

    Detection still scans it — use ``policy archive`` to stop fetching entirely.
    """
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
    """Disable a committee — kept in the catalog and still *detected*, but skipped
    by summarisation.

    Untracking does **not** stop the fetch passes: detection deliberately scans the
    whole catalog so a newly-discovered committee's meetings are recorded right
    away. To stop fetching a concluded committee, use ``policy archive``.
    """
    from repower.policy.store import set_committee_enabled, sync_committees

    sync_committees()
    if set_committee_enabled(committee, False):
        typer.echo(f"untracked {committee}")
    else:
        typer.echo(f"unknown committee: {committee} (run `policy list` to see keys)", err=True)
        raise typer.Exit(1)


@policy_app.command("archive")
def policy_archive(
    committee: str = typer.Argument(..., help="Committee key to archive (concluded)"),
):
    """Mark a concluded committee as archived so every fetch pass skips it.

    Detection and both backfills stop crawling its index, which is the only way to
    stop a closed committee consuming the daily budget — untracking does not, since
    detection scans the whole catalog by design. Stored meetings and materials are
    kept and still render in the dashboard.

    Naming the committee explicitly (``--committee``) still overrides the skip, so a
    one-off re-crawl works without un-archiving.
    """
    from repower.policy.store import set_committee_archived, sync_committees

    sync_committees()
    if set_committee_archived(committee, True):
        typer.echo(f"archived {committee} (fetch passes will skip it)")
    else:
        typer.echo(f"unknown committee: {committee} (run `policy list` to see keys)", err=True)
        raise typer.Exit(1)


@policy_app.command("unarchive")
def policy_unarchive(
    committee: str = typer.Argument(..., help="Committee key to un-archive (resumed)"),
):
    """Un-archive a committee so the fetch passes crawl it again."""
    from repower.policy.store import set_committee_archived, sync_committees

    sync_committees()
    if set_committee_archived(committee, False):
        typer.echo(f"unarchived {committee}")
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
    typer.echo(f"{'KEY':<28}{'SRC':<6}{'TRACK':<6}{'PRIO':>5}{'LATEST':>7}{'PEND':>6}  {'FETCH':<22}")
    for r in rows:
        latest = r["latest_meeting"] if r["latest_meeting"] else "-"
        track = "yes" if r["enabled"] else "no"
        typer.echo(
            f"{r['key']:<28}{r['source']:<6}{track:<6}{r['priority']:>5}{str(latest):>7}"
            f"{pend.get(r['key'], 0):>6}  {_fetch_label(r):<22}"
        )
    n_tracked = sum(1 for r in rows if r["enabled"])
    n_bad = sum(1 for r in rows if r.get("last_fetch_status") == "error")
    typer.echo(f"-- {n_tracked}/{len(rows)} tracked --")
    if n_bad:
        typer.echo(f"-- {n_bad} committee(s) failing to fetch; run `repower policy doctor` --")


@policy_app.command("discover")
def policy_discover():
    """Enumerate energy committees from the METI/OCCTO/EGC indexes **and** the
    energy-board backup feed into the catalog — one discovery pass over every source.

    No auth. New committees are added untracked (``enabled=0``) — track them with
    ``policy track <key>`` (or the web Manage modal) to include them in the pipeline.
    Use ``policy crosscheck`` to run only the energy-board backup diff.
    """
    from repower.policy.catalog import discover_committees

    res = discover_committees()
    typer.echo(f"catalog: {res['found']} committees listed, {res['inserted']} newly discovered")
    for src, n in sorted(res["by_source"].items()):
        typer.echo(f"  {src:<6}{n}")
    backup = res.get("backup")
    if backup is not None:
        typer.echo(
            f"  backup (energy-board): {backup['theirs']} recent · "
            f"{backup['matched']} known · {backup['added']} added"
        )


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
