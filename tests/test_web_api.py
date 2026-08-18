"""Tests for the local web-api policy-command allowlist / argv builder.

The job runner shells out to `repower policy <cmd>`, so the argv builder is the
security boundary: it must reject unknown commands, validate committee keys against
the catalog, require mandatory args, and clamp numeric ones.
"""

from __future__ import annotations

import pytest

from repower.policy import store
from repower.web_api import _build_policy_argv


def _db(tmp_path):
    db = str(tmp_path / "t.db")
    store.sync_committees(db_path=db)
    return db


def test_auth_free_and_run_defaults(tmp_path):
    db = _db(tmp_path)
    assert _build_policy_argv("detect", {}, db) == ["policy", "detect", "--committee", "all"]
    assert _build_policy_argv("discover", {}, db) == ["policy", "discover"]
    assert _build_policy_argv("crosscheck", {}, db) == ["policy", "crosscheck"]
    assert _build_policy_argv("run", {}, db) == ["policy", "run", "--committee", "all", "--max-per-run", "5"]
    # digest is forced dry-run so a UI click never posts to the webhook
    assert _build_policy_argv("digest", {}, db) == ["policy", "digest", "--since-days", "7", "--dry-run"]


def test_committee_validated_against_catalog(tmp_path):
    db = _db(tmp_path)
    assert _build_policy_argv("run", {"committee": "system_review"}, db) == [
        "policy", "run", "--committee", "system_review", "--max-per-run", "5",
    ]
    with pytest.raises(ValueError):
        _build_policy_argv("run", {"committee": "no_such_committee"}, db)


def test_backfill_requires_committee_and_since(tmp_path):
    db = _db(tmp_path)
    assert _build_policy_argv(
        "backfill", {"committee": "system_review", "since_meeting": 50}, db
    ) == ["policy", "backfill", "--committee", "system_review", "--since-meeting", "50", "--max-per-run", "10"]
    with pytest.raises(ValueError):  # since_meeting required
        _build_policy_argv("backfill", {"committee": "system_review"}, db)
    with pytest.raises(ValueError):  # committee required (no 'all' for backfill)
        _build_policy_argv("backfill", {"since_meeting": 5}, db)


def test_numeric_args_clamped_and_unknown_cmd_rejected(tmp_path):
    db = _db(tmp_path)
    assert _build_policy_argv("run", {"max_per_run": 999}, db)[-1] == "20"  # clamped to 20
    assert _build_policy_argv("run", {"max_per_run": 0}, db)[-1] == "1"  # clamped to >=1
    with pytest.raises(ValueError):
        _build_policy_argv("rm -rf /", {}, db)
    with pytest.raises(ValueError):
        _build_policy_argv("run", {"committee": "system_review", "max_per_run": "abc"}, db)


def test_single_meeting_run_is_targeted_and_validated(tmp_path):
    """"Run now" must reach exactly one meeting of one real committee — never the
    whole tracked set — so the meeting number and the key are both validated."""
    db = _db(tmp_path)
    assert _build_policy_argv("run", {"committee": "system_review", "meeting": 114}, db) == [
        "policy", "run", "--committee", "system_review", "--meeting", "114",
    ]
    # A meeting number without a real committee must not silently widen to 'all'.
    with pytest.raises(ValueError):
        _build_policy_argv("run", {"meeting": 3}, db)
    with pytest.raises(ValueError):
        _build_policy_argv("run", {"committee": "system_review", "meeting": "not-a-number"}, db)
    # "Latest only" is the ordinary run with a budget of one.
    assert _build_policy_argv("run", {"committee": "system_review", "max_per_run": 1}, db) == [
        "policy", "run", "--committee", "system_review", "--max-per-run", "1",
    ]
