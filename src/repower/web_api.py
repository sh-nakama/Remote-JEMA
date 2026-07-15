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

The `command` jobs shell out to the same CLI the cron/skill use (detect, dates,
schedule, discover, crosscheck, run, backfill, resume, digest) — allowlisted, args
validated, single-flight. NotebookLM commands (run/backfill/resume) self-gate on
auth in the CLI and surface a clean "needs login" line in the job output.

The catch-up job runs the **auth-free** steps only (detect new meetings, backfill
dates, refresh the schedule, refresh the catalog) and reports the resulting
pending backlog. NotebookLM summarisation stays in the ``policy-catchup`` skill /
``repower policy run`` (it needs interactive auth and a daily quota). CORS is open
because this is a localhost dev helper — do not expose it publicly.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── Background job (single-flight) ───────────────────────────────────────────
# One job runs at a time (they share the SQLite DB and, for `run`/`backfill`, the
# single NotebookLM account). A job is either the in-process auth-free 'catchup'
# refresh or a 'command' subprocess wrapping one `repower policy <cmd>`.
_OUTPUT_MAX = 300
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
    "output": [],       # stdout tail (command jobs)
    "error": None,
}


def _run_catchup_job(db_path: str | None) -> None:
    from repower.policy.catalog import discover_committees
    from repower.policy.detect import backfill_dates, detect
    from repower.policy.schedule import refresh_upcoming
    from repower.policy.store import pending_meetings

    try:
        det = detect(db_path=db_path)
        new = sum(r["new"] for r in det)
        dated = backfill_dates(only_missing=True, occto_limit=6, db_path=db_path)
        n_dated = sum(r["dated"] for r in dated)
        try:
            n_up = refresh_upcoming(db_path=db_path)
        except Exception as e:  # noqa: BLE001 — schedule feed is optional
            logger.warning("catchup: schedule refresh failed: %s", e)
            n_up = None
        cat = discover_committees(db_path=db_path)
        pending = len(pending_meetings(only_enabled=True, db_path=db_path))
        result = {
            "new_meetings": new,
            "dated": n_dated,
            "upcoming": n_up,
            "discovered": cat["inserted"],
            "pending": pending,
            "note": "Auth-free refresh done. Run `repower policy run` (or the "
                    "policy-catchup skill) to summarise the pending backlog via NotebookLM.",
        }
        with _job_lock:
            _job.update(state="done", finished_at=_now(), result=result, error=None)
    except Exception as e:  # noqa: BLE001
        logger.exception("catchup job failed")
        with _job_lock:
            _job.update(state="error", finished_at=_now(), error=str(e))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def start_catchup(db_path: str | None) -> dict:
    """Start the auth-free refresh job if idle; return the current job state."""
    with _job_lock:
        if _job["state"] == "running":
            return dict(_job)
        _job.update(kind="catchup", cmd="catchup", argv=None, state="running",
                    started_at=_now(), finished_at=None, exit_code=None,
                    result=None, output=[], error=None)
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
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be an integer")

    if cmd in ("detect", "dates"):
        return ["policy", cmd, "--committee", _committee()]
    if cmd in ("schedule", "discover", "crosscheck", "resume", "status"):
        return ["policy", cmd]
    if cmd == "run":
        return ["policy", "run", "--committee", _committee(),
                "--max-per-run", str(_int("max_per_run", 5, 1, 20))]
    if cmd == "backfill":
        return ["policy", "backfill",
                "--committee", _committee(required=True, allow_all=False),
                "--since-meeting", str(_int("since_meeting", None, 1, 100000, required=True)),
                "--max-per-run", str(_int("max_per_run", 10, 1, 30))]
    if cmd == "digest":  # --dry-run: never post to the webhook from a UI click
        return ["policy", "digest", "--since-days", str(_int("since_days", 7, 1, 90)), "--dry-run"]
    raise ValueError(f"unsupported command: {cmd}")


def _run_command_job(argv: list[str]) -> None:
    tail: deque[str] = deque(maxlen=_OUTPUT_MAX)
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "repower.cli", *argv],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, encoding="utf-8", errors="replace",
        )
        for line in proc.stdout or []:
            tail.append(line.rstrip("\n"))
            with _job_lock:
                _job["output"] = list(tail)
        code = proc.wait()
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
                    result=None, output=[], error=None)
        snap = dict(_job)
    threading.Thread(target=_run_command_job, args=(argv,), daemon=True).start()
    return 202, snap


# ── HTTP handler ─────────────────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    db_path: str | None = None

    def _send(self, code: int, obj: object) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
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

    def do_OPTIONS(self) -> None:  # noqa: N802 — CORS preflight
        self._send(200, {})

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
        self._guard(self._route_get)

    def do_POST(self) -> None:  # noqa: N802
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
        if path in ("/api/policy/catchup", "/api/policy/job"):
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
