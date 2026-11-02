"""NotebookLM's 5-hour limit is a hard rule, so the gate that enforces it is tested directly."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from repower.policy.run_gate import MAX_RUNS_PER_DAY, SUMMARISE_STEP, WINDOW, Usage, collect, decide

NOW = datetime(2026, 11, 3, 6, 0, tzinfo=UTC)  # 15:00 JST


def _used(hours_ago: float, length_hours: float = 1.0) -> Usage:
    ended = NOW - timedelta(hours=hours_ago)
    return Usage(ended - timedelta(hours=length_hours), ended)


def _stamp(at: datetime) -> str:
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(run_id: int, hours_ago: float, status: str = "completed") -> dict:
    at = NOW - timedelta(hours=hours_ago)
    return {"id": run_id, "status": status, "created_at": _stamp(at), "updated_at": _stamp(at)}


def _jobs(conclusion: str | None, ended_hours_ago: float = 1.0) -> list[dict]:
    end = NOW - timedelta(hours=ended_hours_ago)
    return [{"steps": [{"name": "Install dependencies", "conclusion": "success"},
                       {"name": SUMMARISE_STEP, "conclusion": conclusion,
                        "started_at": _stamp(end - timedelta(hours=1)), "completed_at": _stamp(end)}]}]


def test_with_no_earlier_run_it_is_due():
    assert decide(NOW, [])[0] is True


def test_the_limit_is_measured_from_the_end_of_the_last_run():
    just_inside = NOW - WINDOW + timedelta(minutes=1)
    assert decide(NOW, [Usage(just_inside - timedelta(hours=2), just_inside)])[0] is False
    assert decide(NOW, [Usage(NOW - WINDOW - timedelta(hours=2), NOW - WINDOW)])[0] is True


def test_a_long_run_that_started_long_ago_still_waits():
    assert decide(NOW, [_used(hours_ago=1, length_hours=7)])[0] is False


def test_the_daily_cap_counts_the_jst_day():
    # Midnight JST is 15:00 UTC the day before, so four runs this morning JST fill the cap.
    four = [_used(hours_ago=h, length_hours=0.5) for h in (14, 11, 8, 6)]
    assert len(four) == MAX_RUNS_PER_DAY
    due, why = decide(NOW, four)
    assert due is False and "cap" in why
    # The same run count ending before midnight JST belongs to yesterday.
    assert decide(NOW, [_used(hours_ago=h, length_hours=0.5) for h in (24, 21, 18, 16)])[0] is True


def test_an_active_run_blocks_the_gate():
    assert decide(NOW, [], active=True)[0] is False


def test_only_a_run_whose_summarise_step_ran_counts():
    runs = [_run(3, 1), _run(2, 2), _run(1, 8)]
    jobs = {3: _jobs("skipped"), 2: _jobs("success", 2), 1: _jobs("failure", 8)}
    usages, active = collect(runs, jobs.__getitem__, now=NOW)
    assert active is False
    assert [u.ended for u in usages] == [NOW - timedelta(hours=2), NOW - timedelta(hours=8)]


def test_the_gate_sees_a_queued_run_but_a_run_ignores_itself_and_those_behind_it():
    runs = [_run(3, 0, "queued"), _run(2, 0, "in_progress"), _run(1, 8)]
    jobs = {1: _jobs("success", 8)}
    assert collect(runs, jobs.__getitem__, now=NOW)[1] is True
    assert collect(runs, jobs.__getitem__, now=NOW, own_run_id=2)[1] is False


def test_it_keeps_looking_past_midnight_until_it_finds_the_last_summarising_run():
    runs = [_run(3, 20), _run(2, 30), _run(1, 40)]
    jobs = {3: _jobs("skipped"), 2: _jobs("success", 30), 1: _jobs("success", 40)}
    usages, _ = collect(runs, jobs.__getitem__, now=NOW)
    assert [u.ended for u in usages] == [NOW - timedelta(hours=30)]


def test_a_cancelled_step_with_no_end_time_uses_the_runs_last_update():
    jobs = _jobs("cancelled", 3)
    jobs[0]["steps"][1]["completed_at"] = None
    usages, _ = collect([_run(1, 3)], lambda _: jobs, now=NOW)
    assert usages[0].ended == NOW - timedelta(hours=3)
