"""Minimal local API for the JEMA web frontend's interactive (dev) mode.

The deployed GitHub Pages site is read-only static JSON. Running locally, the
frontend talks to this small stdlib HTTP server (started with ``repower web-api``)
so the Policy Deep Dive **Manage** modal can WRITE the tracked set and the **Run
catch-up** button can trigger the auth-free refresh. The daily cron reads the same
SQLite DB, so a track toggle here changes what the next catch-up processes — this
is the "local is master, GitHub Pages is read-only" link.

Endpoints (all JSON):
  GET  /api/health          -> {ok, mode}
  GET  /api/policy/catalog  -> {schema, committees:[…]}   (live committees.json shape)
  POST /api/policy/track    -> {ok, key, enabled}         body: {key, enabled}
  POST /api/policy/priority -> {ok, key, priority}        body: {key, priority}
  POST /api/policy/add      -> {ok, key, name_ja, existing} body: {url} (METI /shingikai/ page; auto-tracks)
  POST /api/policy/catchup  -> 202, starts the auth-free refresh job
  POST /api/policy/job      -> 202/400/409, runs one `repower policy <cmd>` (subprocess)
                               body: {cmd, committee?, since_meeting?, max_per_run?, since_days?}
  GET  /api/policy/catchup  -> current job status (alias: /api/policy/job)
  GET  /api/policy/job      -> current job status + output tail / result
  GET  /api/policy/crosscheck -> energy-board vs our catalog (committees we may miss)
  POST /api/data/refresh    -> 202/409, full data refresh (recover gaps → scrape → export-web)
  GET  /api/data/refresh    -> current job status (shares the single-flight job slot)

The `command` jobs shell out to the same CLI the cron/skill use (detect, dates,
schedule, discover, crosscheck, run, backfill, resume, digest) — allowlisted, args
validated, single-flight. NotebookLM commands (run/backfill/resume) self-gate on
auth in the CLI and surface a clean "needs login" line in the job output.

The catch-up job runs the **auth-free** steps only (detect new meetings, backfill
dates, refresh the schedule, refresh the catalog) and reports the resulting
pending backlog. NotebookLM summarisation stays in the ``policy-catchup`` skill /
``repower policy run`` (it needs interactive auth and a daily quota).

This is a localhost dev helper — do not expose it publicly. Still, it is hardened
a little: CORS is pinned to the Vite dev origins (override with a comma-separated
``REPOWER_WEB_ORIGINS``), and setting ``REPOWER_API_TOKEN`` makes every request
require a matching ``X-API-Token`` header (unset — the default — means no auth).
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import subprocess
import sys
import threading
from collections import deque
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# CORS allowlist: the Vite dev servers (the dev proxy makes requests same-origin,
# so this only matters for direct cross-origin calls from the SPA).
_ALLOWED_ORIGINS = frozenset(
    o.strip()
    for o in os.environ.get(
        "REPOWER_WEB_ORIGINS", "http://localhost:5173,http://localhost:5199"
    ).split(",")
    if o.strip()
)

# ── Background job (single-flight) ───────────────────────────────────────────
# One job runs at a time (they share the SQLite DB and, for `run`/`backfill`, the
# single NotebookLM account). A job is either the in-process auth-free 'catchup'
# refresh or a 'command' subprocess wrapping one `repower policy <cmd>`.
_OUTPUT_MAX = 300
_JOB_TIMEOUT_S = 600  # hard cap per command subprocess; a wedged CLI must not pin the single-flight slot forever
_REFRESH_TIMEOUT_S = 1800  # data refresh scrapes every source + re-exports; give it a wider cap
# NotebookLM summarisation (run/backfill/resume) is long-running: a single meeting
# can block up to ~20 min on one report artifact (see notebook.wait_artifact), and a
# batch does several back-to-back. The run is naturally bounded by the account's
# daily generation quota, not wall-clock, so the 10-min command cap would kill it
# mid-report and surface as a spurious "error" even with valid auth. Give it a wide
# cap; the pipeline is crash-safe (Resume drains anything left mid-flight).
_NOTEBOOKLM_TIMEOUT_S = 3600
_job_lock = threading.Lock()
_job: dict = {
    "kind": None,       # 'catchup' | 'command'
    "cmd": None,        # human label (e.g. 'run', 'backfill', 'catchup')
    "argv": None,       # policy argv for command jobs
    "state": "idle",    # idle | running | done | error
    "started_at": None,
    "finished_at": None,
    "exit_code": None,  # subprocess exit code (command jobs)
    "result": None,     # structured result (catchup)
    "stages": [],       # ordered per-stage progress (catchup): running/done/error
    "output": [],       # stdout tail (command jobs)
    "error": None,
}


def _stage_start(key: str, label: str, label_ja: str) -> int:
    """Append a new 'running' stage to the live job and return its index.

    The web frontend's progress panel polls the job and renders each stage (with
    its live detail and any failure) as it advances, then summarises the outcome.
    Mutating under the lock keeps the GET handler's snapshot consistent.
    """
    with _job_lock:
        stages = _job.get("stages") or []
        stages.append({
            "key": key, "label": label, "label_ja": label_ja,
            "state": "running", "detail": None, "detail_ja": None,
        })
        _job["stages"] = stages
        return len(stages) - 1


def _stage_finish(idx: int, state: str, detail: str | None = None,
                  detail_ja: str | None = None) -> None:
    """Mark a previously-started stage done/error with a short bilingual outcome."""
    with _job_lock:
        stages = _job.get("stages") or []
        if 0 <= idx < len(stages):
            stages[idx].update(state=state, detail=detail, detail_ja=detail_ja)


def _stage_progress(idx: int, detail: str | None, detail_ja: str | None) -> None:
    """Update a still-running stage's live detail (progress within the stage)."""
    with _job_lock:
        stages = _job.get("stages") or []
        if 0 <= idx < len(stages) and stages[idx].get("state") == "running":
            stages[idx]["detail"] = detail
            stages[idx]["detail_ja"] = detail_ja


def _run_catchup_job(db_path: str | None) -> None:
    from repower.policy.catalog import discover_committees
    from repower.policy.detect import backfill_dates, backfill_materials, detect
    from repower.policy.schedule import refresh_upcoming
    from repower.policy.store import pending_meetings

    try:
        # 1) Detect new meetings across the tracked committees ("check for updates").
        #    This scans every committee (slow), so report live per-committee progress.
        i = _stage_start("detect", "Checked for updates", "更新を確認")
        det = detect(
            db_path=db_path,
            progress=lambda done, total, key: _stage_progress(
                i, f"{done + 1}/{total} · {key}", f"{done + 1}/{total} · {key}"
            ),
        )
        new = sum(r["new"] for r in det)
        _stage_finish(i, "done",
                      f"{new} new meeting(s)" if new else "no new meetings",
                      f"新着{new}件" if new else "新着なし")

        # 1b) Populate materials for meetings detected without any (e.g. first seen
        #     while the committee page was unavailable) so tracked committees'
        #     meetings become visible — the Deep Dive hides material-less meetings.
        i = _stage_start("materials", "Fetched meeting materials", "会合資料を取得")
        matres = backfill_materials(db_path=db_path, limit_per_committee=8)
        n_mat = sum(r["materialised"] for r in matres)
        _stage_finish(i, "done",
                      f"{n_mat} meeting(s) populated" if n_mat else "materials current",
                      f"{n_mat}件を取得" if n_mat else "対象なし")

        # 2) Backfill any missing meeting dates.
        i = _stage_start("dates", "Backfilled meeting dates", "会合日を補完")
        dated = backfill_dates(only_missing=True, occto_limit=6, db_path=db_path)
        n_dated = sum(r["dated"] for r in dated)
        _stage_finish(i, "done",
                      f"{n_dated} date(s) filled" if n_dated else "dates current",
                      f"{n_dated}件を補完" if n_dated else "対象なし")

        # 3) Refresh the upcoming-meetings schedule (optional feed — may fail on its
        #    own without failing the whole catch-up).
        i = _stage_start("schedule", "Refreshed schedule", "予定を更新")
        try:
            n_up = refresh_upcoming(db_path=db_path)
            _stage_finish(i, "done",
                          f"{n_up} upcoming" if n_up is not None else "refreshed",
                          f"予定{n_up}件" if n_up is not None else "更新済み")
        except Exception as e:  # noqa: BLE001 — schedule feed is optional
            logger.warning("catchup: schedule refresh failed: %s", e)
            n_up = None
            _stage_finish(i, "error", "feed unavailable", "取得できませんでした")

        # 4) Refresh the committee catalog from every discovery source in one pass
        #    (primary METI/OCCTO/EGC indexes + the energy-board backup feed).
        i = _stage_start("discover", "Refreshed committee catalog", "委員会カタログを更新")
        cat = discover_committees(db_path=db_path)
        n_disc = cat["inserted"]
        _stage_finish(i, "done",
                      f"{n_disc} newly discovered" if n_disc else "no new committees",
                      f"新規{n_disc}件を発見" if n_disc else "新規なし")

        pending = len(pending_meetings(only_enabled=True, db_path=db_path))
        result = {
            "new_meetings": new,
            "dated": n_dated,
            "upcoming": n_up,
            "discovered": n_disc,
            "pending": pending,
            "note": "Auth-free refresh done. Run `repower policy run` (or the "
                    "policy-catchup skill) to summarise the pending backlog via NotebookLM.",
        }
        with _job_lock:
            _job.update(state="done", finished_at=_now(), result=result, error=None)
    except Exception as e:  # noqa: BLE001
        logger.exception("catchup job failed")
        with _job_lock:
            # Name the step that was in flight so the UI can say where it failed.
            for st in _job.get("stages") or []:
                if st.get("state") == "running":
                    st.update(state="error", detail=str(e)[:120], detail_ja="失敗しました")
            _job.update(state="error", finished_at=_now(), error=str(e))


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def start_catchup(db_path: str | None) -> dict:
    """Start the auth-free refresh job if idle; return the current job state."""
    with _job_lock:
        if _job["state"] == "running":
            return dict(_job)
        _job.update(kind="catchup", cmd="catchup", argv=None, state="running",
                    started_at=_now(), finished_at=None, exit_code=None,
                    result=None, stages=[], output=[], error=None)
        snapshot = dict(_job)
    threading.Thread(target=_run_catchup_job, args=(db_path,), daemon=True).start()
    return snapshot


# ── Policy CLI command jobs (subprocess) ─────────────────────────────────────
def _build_policy_argv(cmd: str, params: dict, db_path: str | None) -> list[str]:
    """Validate a UI request into a safe ``policy`` CLI argv (allowlist; no shell).

    Committee keys are checked against the catalog and numeric args are clamped, so
    the request can't inject arbitrary arguments.
    """
    def _committee(*, required: bool = False, allow_all: bool = True) -> str | None:
        c = (params.get("committee") or "").strip()
        if not c or c == "all":
            if required:
                raise ValueError("committee is required")
            return "all" if allow_all else None
        from repower.policy.store import list_committees
        if c not in {r["key"] for r in list_committees(db_path=db_path)}:
            raise ValueError(f"unknown committee: {c}")
        return c

    def _int(name: str, default, lo: int, hi: int, *, required: bool = False) -> int:
        raw = params.get(name, default)
        if raw is None or raw == "":
            if required:
                raise ValueError(f"{name} is required")
            raw = default
        try:
            return max(lo, min(hi, int(raw)))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be an integer") from exc

    if cmd in ("detect", "dates"):
        return ["policy", cmd, "--committee", _committee()]
    if cmd in ("schedule", "discover", "crosscheck", "resume", "status"):
        return ["policy", cmd]
    if cmd == "run":
        argv = ["policy", "run", "--committee", _committee(),
                "--max-per-run", str(_int("max_per_run", 5, 1, 20))]
        if params.get("breadth"):
            argv.append("--breadth")  # spread a small quota across committees (newest of each first)
        return argv
    if cmd == "backfill":
        return ["policy", "backfill",
                "--committee", _committee(required=True, allow_all=False),
                "--since-meeting", str(_int("since_meeting", None, 1, 100000, required=True)),
                "--max-per-run", str(_int("max_per_run", 10, 1, 30))]
    if cmd == "digest":  # --dry-run: never post to the webhook from a UI click
        return ["policy", "digest", "--since-days", str(_int("since_days", 7, 1, 90)), "--dry-run"]
    raise ValueError(f"unsupported command: {cmd}")


def _run_command_job(argv: list[str], timeout: int = _JOB_TIMEOUT_S) -> None:
    tail: deque[str] = deque(maxlen=_OUTPUT_MAX)
    timed_out = threading.Event()
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "repower.cli", *argv],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, encoding="utf-8", errors="replace",
            # Force the child to emit UTF-8 too: on non-UTF-8 consoles (e.g. a
            # Japanese cp932 Windows locale) the CLI's box-drawing/→ output would
            # otherwise raise UnicodeEncodeError mid-run and abort the job.
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        )

        # The stdout iteration below blocks for as long as the CLI runs, so the
        # timeout has to come from the side: kill the process and flag it.
        def _kill_on_timeout() -> None:
            timed_out.set()
            proc.kill()

        timer = threading.Timer(timeout, _kill_on_timeout)
        timer.daemon = True
        timer.start()
        try:
            for line in proc.stdout or []:
                tail.append(line.rstrip("\n"))
                with _job_lock:
                    _job["output"] = list(tail)
            code = proc.wait(timeout=timeout)
        finally:
            timer.cancel()
        if timed_out.is_set():
            with _job_lock:
                _job.update(state="error", finished_at=_now(), exit_code=code,
                            error=f"job killed after {timeout}s timeout",
                            output=list(tail))
        else:
            with _job_lock:
                _job.update(state="done" if code == 0 else "error",
                            finished_at=_now(), exit_code=code, output=list(tail))
    except Exception as e:  # noqa: BLE001
        logger.exception("command job failed")
        with _job_lock:
            _job.update(state="error", finished_at=_now(), error=str(e), output=list(tail))


def start_command(cmd: str, params: dict, db_path: str | None) -> tuple[int, dict]:
    """Start a policy CLI command as a background subprocess (single-flight).

    Returns ``(http_status, body)``: 202 started, 400 bad request, 409 busy.
    """
    try:
        argv = _build_policy_argv(cmd, params, db_path)
    except ValueError as e:
        return 400, {"error": str(e)}
    with _job_lock:
        if _job["state"] == "running":
            return 409, {"error": "a job is already running", "job": dict(_job)}
        _job.update(kind="command", cmd=cmd, argv=argv, state="running",
                    started_at=_now(), finished_at=None, exit_code=None,
                    result=None, stages=[], output=[], error=None)
        snap = dict(_job)
    # Long-running NotebookLM commands need a much wider cap than the default so the
    # killer timer doesn't abort them mid-report (see _NOTEBOOKLM_TIMEOUT_S).
    timeout = _NOTEBOOKLM_TIMEOUT_S if cmd in ("run", "backfill", "resume") else _JOB_TIMEOUT_S
    threading.Thread(target=_run_command_job, args=(argv,),
                     kwargs={"timeout": timeout}, daemon=True).start()
    return 202, snap


def start_refresh(db_path: str | None) -> tuple[int, dict]:
    """Start a full data refresh (recover gaps → scrape every source → export-web)
    as a single-flight background subprocess. Shares the ``_job`` slot with the
    policy jobs, so it's 409 while any job runs. Returns ``(202 started | 409 busy,
    job)``. ``db_path`` is unused (the subprocess uses the default DB) but kept for
    a uniform call signature with the other job starters.
    """
    with _job_lock:
        if _job["state"] == "running":
            return 409, {"error": "a job is already running", "job": dict(_job)}
        argv = ["refresh-web"]
        _job.update(kind="command", cmd="refresh-web", argv=argv, state="running",
                    started_at=_now(), finished_at=None, exit_code=None,
                    result=None, stages=[], output=[], error=None)
        snap = dict(_job)
    threading.Thread(
        target=_run_command_job, args=(argv,),
        kwargs={"timeout": _REFRESH_TIMEOUT_S}, daemon=True,
    ).start()
    return 202, snap


# ── HTTP handler ─────────────────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    db_path: str | None = None

    def _send(self, code: int, obj: object) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        origin = self.headers.get("Origin")
        if origin in _ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-API-Token")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _read_json(self) -> dict:
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return {}
            return json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, TypeError):
            return {}

    def do_OPTIONS(self) -> None:  # noqa: N802 — CORS preflight (no auth: preflights can't carry custom headers)
        self._send(200, {})

    def _check_auth(self) -> bool:
        """Optional shared secret: with REPOWER_API_TOKEN set, every GET/POST must
        carry a matching X-API-Token header. Unset (the default) means no auth."""
        token = os.environ.get("REPOWER_API_TOKEN")
        if not token:
            return True
        if hmac.compare_digest(self.headers.get("X-API-Token") or "", token):
            return True
        self._send(401, {"error": "missing or invalid X-API-Token"})
        return False

    def _guard(self, route) -> None:
        """Run one routed handler; anything that escapes still gets a JSON answer.

        http.server catches only ``TimeoutError`` around ``do_*``, so any other
        exception escaping a handler (a cold-start lazy import failing mid-chain,
        JSON encoding, a client hanging up mid-write) tears the connection down
        with **no response at all** — which the Vite dev proxy surfaces to the SPA
        as an opaque 500. Answer with structured JSON instead; if the socket is
        already gone there is nobody left to answer, so give up quietly.
        """
        try:
            route()
        except Exception as e:  # noqa: BLE001 — last resort, see docstring
            logger.exception("web-api: unhandled error on %s %s", self.command, self.path)
            try:
                self._send(500, {"error": str(e)})
            except OSError:
                pass  # client already disconnected

    def do_GET(self) -> None:  # noqa: N802
        if self._check_auth():
            self._guard(self._route_get)

    def do_POST(self) -> None:  # noqa: N802
        if self._check_auth():
            self._guard(self._route_post)

    def _route_get(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            return self._send(200, {"ok": True, "mode": "local"})
        if path == "/api/policy/catalog":
            from repower.dashboard.export_web import build_policy_catalog
            return self._send(200, {"schema": 1, "committees": build_policy_catalog(self.db_path)})
        if path == "/api/policy/deepdive":
            # Live Policy Deep Dive payload straight from the DB, so the local master
            # reflects tracking/backfill without a re-export. Same shape the static
            # committees.json + meetings.json carry.
            try:
                # Import inside the guard: this is the once-per-process cold path
                # (pandas/streamlit via repower.dashboard, seconds of imports on the
                # first request) — a transient failure here must fall back like any
                # other error instead of killing the connection.
                from repower.dashboard.export_web import build_policy_snapshot
                return self._send(200, {"schema": 1, **build_policy_snapshot(self.db_path)})
            except Exception as e:  # noqa: BLE001 — never 500 the UI; fall back to empty
                logger.exception("deepdive snapshot failed; serving empty fallback")
                return self._send(200, {"schema": 1, "committees": [], "meetings": [], "upcoming": [], "error": str(e)})
        if path in ("/api/policy/catchup", "/api/policy/job", "/api/data/refresh"):
            with _job_lock:
                return self._send(200, dict(_job))
        if path == "/api/policy/crosscheck":
            try:
                from repower.policy.energy_board import cross_check
                return self._send(200, cross_check(db_path=self.db_path))
            except Exception as e:  # noqa: BLE001 — third-party site; never 500 the UI
                logger.exception("crosscheck failed; serving empty fallback")
                return self._send(200, {"theirs": 0, "matched": 0, "missing": [], "error": str(e)})
        return self._send(404, {"error": "not found"})

    def _route_post(self) -> None:
        path = urlparse(self.path).path
        body = self._read_json()
        if path == "/api/policy/track":
            from repower.policy.store import set_committee_enabled
            key = body.get("key")
            enabled = bool(body.get("enabled"))
            if not key:
                return self._send(400, {"error": "key required"})
            ok = set_committee_enabled(key, enabled, db_path=self.db_path)
            return self._send(200 if ok else 404, {"ok": ok, "key": key, "enabled": enabled})
        if path == "/api/policy/priority":
            from repower.policy.store import set_committee_priority
            key = body.get("key")
            try:
                pr = int(body.get("priority"))
            except (TypeError, ValueError):
                return self._send(400, {"error": "priority must be an integer"})
            if not key:
                return self._send(400, {"error": "key required"})
            if pr < 1:
                return self._send(400, {"error": "priority must be >= 1"})
            ok = set_committee_priority(key, pr, db_path=self.db_path)
            return self._send(200 if ok else 404, {"ok": ok, "key": key, "priority": pr})
        if path == "/api/policy/add":
            # Manual add-by-URL: the escape hatch for committees the org indexes
            # never list (e.g. WGs nested under a 小委員会). Auto-tracks the row.
            from repower.policy.catalog import add_committee_by_url
            url = (body.get("url") or "").strip()
            if not url:
                return self._send(400, {"error": "url required"})
            try:
                return self._send(200, add_committee_by_url(url, db_path=self.db_path))
            except ValueError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:  # noqa: BLE001 — network fetch; never 500 the UI
                return self._send(400, {"error": f"could not add committee: {e}"})
        if path == "/api/policy/catchup":
            return self._send(202, start_catchup(self.db_path))
        if path == "/api/data/refresh":
            status, out = start_refresh(self.db_path)
            return self._send(status, out)
        if path == "/api/policy/job":
            cmd = (body.get("cmd") or "").strip()
            status, out = start_command(cmd, body, self.db_path)
            return self._send(status, out)
        return self._send(404, {"error": "not found"})

    def log_message(self, *args) -> None:  # keep the console quiet
        return


def serve(port: int = 8787, host: str = "127.0.0.1", db_path: str | None = None) -> None:
    """Run the local web API until interrupted."""
    _Handler.db_path = db_path
    httpd = ThreadingHTTPServer((host, port), _Handler)
    logger.info("JEMA web-api listening on http://%s:%d", host, port)
    print(f"JEMA web-api on http://{host}:{port} (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
