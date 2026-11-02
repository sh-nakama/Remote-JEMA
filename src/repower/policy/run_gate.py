"""Whether a policy run may summarise now: NotebookLM's 5-hour limit, enforced.

Clock slots cannot promise a gap, because GitHub starts crons hours late and a run's length varies.
So ``policy-gate.yml`` asks this every hour and starts ``policy.yml`` when it is due, and
``policy.yml`` asks again itself, so a run started by hand obeys too. The record is GitHub's own
list of runs, which sees only runs on Actions: a local ``policy run`` on the same account is
invisible here.

Standard library only, so the hourly gate needs no install. Run as a script by both workflows.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

WORKFLOW = "policy.yml"
# The step that spends NotebookLM quota; tests/test_workflow_docs.py keeps this in step with the file.
SUMMARISE_STEP = "Summarise pending meetings + emit digest"
WINDOW = timedelta(hours=5, minutes=5)  # the limit plus a margin, measured from the step's end
MAX_RUNS_PER_DAY = 4
JST = timezone(timedelta(hours=9))


@dataclass(frozen=True)
class Usage:
    """One run's summarise step."""

    started: datetime
    ended: datetime


def decide(now: datetime, usages: Iterable[Usage], *, active: bool = False) -> tuple[bool, str]:
    """(due, why). Pure, so the rule can be tested without GitHub."""
    if active:
        return False, "a policy run is already queued or running"
    usages = list(usages)
    today = now.astimezone(JST).date()
    todays = sum(u.started.astimezone(JST).date() == today for u in usages)
    if todays >= MAX_RUNS_PER_DAY:
        return False, f"{todays} summarising runs already today (JST); the cap is {MAX_RUNS_PER_DAY}"
    if usages:
        last = max(u.ended for u in usages)
        ready = last + WINDOW
        if now < ready:
            minutes = int((ready - now).total_seconds() // 60) + 1
            return False, f"last run ended {last:%H:%M} UTC; the limit clears in about {minutes} min"
    return True, "the 5-hour limit has cleared"


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def collect(
    runs: list[dict],
    jobs_of: Callable[[int], list[dict]],
    *,
    now: datetime,
    own_run_id: int | None = None,
) -> tuple[list[Usage], bool]:
    """Summarising runs among *runs* (newest first) back to the start of the JST day, always
    including the latest one, and whether another run is queued or running. Inside a run the
    hf-dataset queue already keeps runs apart, so anything active is one waiting behind it."""
    midnight = now.astimezone(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    usages: list[Usage] = []
    active = False
    for run in runs:
        if run["id"] == own_run_id:
            continue
        if run["status"] != "completed":
            active = active or own_run_id is None
            continue
        for job in jobs_of(run["id"]):
            for step in job.get("steps", []):
                if step["name"] == SUMMARISE_STEP and step.get("conclusion") not in (None, "skipped"):
                    usages.append(Usage(_parse(step["started_at"]),
                                        _parse(step.get("completed_at") or run["updated_at"])))
        if usages and _parse(run["created_at"]) < midnight:
            break
    return usages, active


def _api(path: str) -> dict:
    out = subprocess.run(["gh", "api", path], capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(out.stdout)


def main() -> int:
    repo = os.environ["GITHUB_REPOSITORY"]
    own = os.environ.get("POLICY_RUN_ID")
    now = datetime.now(UTC)
    runs = _api(f"repos/{repo}/actions/workflows/{WORKFLOW}/runs?per_page=30")["workflow_runs"]
    usages, active = collect(
        runs,
        lambda run_id: _api(f"repos/{repo}/actions/runs/{run_id}/jobs")["jobs"],
        now=now,
        own_run_id=int(own) if own else None,
    )
    due, why = decide(now, usages, active=active)
    print(f"::notice::Summarising skipped: {why}" if own and not due else why)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"due={str(due).lower()}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
