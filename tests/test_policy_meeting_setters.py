"""``set_meeting_dates`` and ``set_meeting_index_notes`` write one field of a committee's meetings
through the same helper (``store._set_meeting_field``), so what they both promise is held to the same
tests here: only rows that change are counted, a number with no row is ignored, ``updated_at`` is left
alone, and nothing outside the named committee is touched. The one thing that differs, what ``None``
means, is pinned on each side.

``test_set_meeting_dates_and_missing`` and
``test_set_meeting_index_notes_sets_clears_and_ignores_unknown_rows`` cover the same ground for one
setter each; these add the parts they leave out (dates: ``None``, ``updated_at``, changing a date;
both: committee scoping and batches larger than one query takes).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pytest
from sqlalchemy import event

from repower.db import PolicyMeeting, get_engine
from repower.policy import store
from repower.policy.scraper import NOTE_NO_PAPERS

KEY, OTHER = "santeii", "saisei_kano"


@dataclass(frozen=True)
class Setter:
    call: Callable[..., int]
    field: str  # the PolicyMeeting attribute it writes
    first: Any
    second: Any


DATES = Setter(store.set_meeting_dates, "meeting_date", date(2026, 1, 5), date(2026, 2, 2))
NOTES = Setter(store.set_meeting_index_notes, "index_note", NOTE_NO_PAPERS, "other")
BOTH = pytest.mark.parametrize("setter", [DATES, NOTES], ids=["dates", "notes"])


def _seed(db: str, key: str, nums) -> None:
    """Meetings with nothing else recorded, in one write (a test of 1500 must not take 1500 sessions)."""
    with store.session_scope(db) as session:
        session.add_all(PolicyMeeting(committee_key=key, meeting_num=n) for n in nums)


def _stored(db: str, key: str, field: str) -> dict[int, Any]:
    with store.session_scope(db, commit=False) as session:
        return {m.meeting_num: getattr(m, field)
                for m in session.query(PolicyMeeting).filter_by(committee_key=key)}


@BOTH
def test_counts_only_the_rows_that_change_and_ignores_unknown_numbers(policy_db, setter):
    _seed(policy_db, KEY, [1, 2, 3])

    assert setter.call(KEY, {1: setter.first, 2: setter.first, 99: setter.first}, db_path=policy_db) == 2
    # 99 has no row and does not get one.
    assert _stored(policy_db, KEY, setter.field) == {1: setter.first, 2: setter.first, 3: None}

    assert setter.call(KEY, {1: setter.first, 2: setter.first}, db_path=policy_db) == 0   # idempotent
    assert setter.call(KEY, {1: setter.second, 2: setter.first}, db_path=policy_db) == 1  # one value moved
    assert _stored(policy_db, KEY, setter.field) == {1: setter.second, 2: setter.first, 3: None}


@BOTH
def test_nothing_to_write_is_zero(policy_db, setter):
    _seed(policy_db, KEY, [1])
    assert setter.call(KEY, {}, db_path=policy_db) == 0
    assert _stored(policy_db, KEY, setter.field) == {1: None}


@BOTH
def test_updated_at_is_left_alone(policy_db, setter):
    """The UI reads ``updated_at`` as "last touched": a backfill must not reshuffle those views."""
    _seed(policy_db, KEY, [1, 2])
    old = datetime(2020, 1, 1)
    with store.session_scope(policy_db) as session:
        for m in session.query(PolicyMeeting):
            m.updated_at = old

    assert setter.call(KEY, {1: setter.first, 2: setter.second}, db_path=policy_db) == 2

    assert _stored(policy_db, KEY, "updated_at") == {1: old, 2: old}


@BOTH
def test_only_the_named_committee_is_touched(policy_db, setter):
    _seed(policy_db, KEY, [1, 2])
    _seed(policy_db, OTHER, [1, 2])  # the same meeting numbers under another committee

    assert setter.call(KEY, {1: setter.first, 2: setter.first}, db_path=policy_db) == 2

    assert _stored(policy_db, KEY, setter.field) == {1: setter.first, 2: setter.first}
    assert _stored(policy_db, OTHER, setter.field) == {1: None, 2: None}


@BOTH
def test_writes_the_one_field_and_leaves_a_summarised_meeting_as_it_was(policy_db, setter):
    """Only the number and the field are read back, so the rest of a row (a whole briefing) must come
    through the write untouched."""
    _seed(policy_db, KEY, [1])
    with store.session_scope(policy_db) as session:
        m = session.query(PolicyMeeting).one()
        m.state, m.briefing_md, m.digest_en_json = "done", "# 要約", '{"answer": "x"}'

    assert setter.call(KEY, {1: setter.first}, db_path=policy_db) == 1

    assert _stored(policy_db, KEY, setter.field) == {1: setter.first}
    assert _stored(policy_db, KEY, "state") == {1: "done"}
    assert _stored(policy_db, KEY, "briefing_md") == {1: "# 要約"}
    assert _stored(policy_db, KEY, "digest_en_json") == {1: '{"answer": "x"}'}


# ── What None means: the one difference ──────────────────────────────────────
def test_a_none_date_is_unknown_and_never_blanks_a_known_one(policy_db):
    _seed(policy_db, KEY, [1, 2, 3])
    assert store.set_meeting_dates(KEY, {1: DATES.first}, db_path=policy_db) == 1

    assert store.set_meeting_dates(KEY, {1: None, 2: None, 3: DATES.second}, db_path=policy_db) == 1

    assert _stored(policy_db, KEY, "meeting_date") == {1: DATES.first, 2: None, 3: DATES.second}


def test_a_none_note_clears_a_stale_one(policy_db):
    """Papers posted after a written meeting: the index row loses its remark, so the note must go."""
    _seed(policy_db, KEY, [1, 2, 3])
    assert store.set_meeting_index_notes(KEY, {1: NOTE_NO_PAPERS, 2: NOTE_NO_PAPERS}, db_path=policy_db) == 2

    assert store.set_meeting_index_notes(KEY, {1: None, 2: NOTE_NO_PAPERS, 3: None}, db_path=policy_db) == 1

    assert _stored(policy_db, KEY, "index_note") == {1: None, 2: NOTE_NO_PAPERS, 3: None}


# ── Batches: one query per chunk, and never past SQLite's variable limit ─────
def _cap_variables(db: str, limit: int) -> None:
    """Make this DB's connections refuse a statement binding more than *limit* values, as an SQLite
    older than 3.32 does (the build running the tests allows far more)."""
    engine = get_engine(db)
    engine.dispose()  # a pooled connection opened before the cap would not carry it

    @event.listens_for(engine, "connect")
    def _cap(dbapi_con, _record):
        dbapi_con.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, limit)

    with engine.connect() as con:
        assert con.connection.dbapi_connection.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER) == limit


@BOTH
def test_a_batch_bigger_than_the_variable_limit_still_goes_through(policy_db, setter):
    n = 1500
    _seed(policy_db, KEY, range(1, n + 1))
    _cap_variables(policy_db, 999)

    assert setter.call(KEY, dict.fromkeys(range(1, n + 1), setter.first), db_path=policy_db) == n

    assert set(_stored(policy_db, KEY, setter.field).values()) == {setter.first}


@BOTH
@pytest.mark.parametrize("n", [1, 2, 3, 4, 6, 7])
def test_every_row_is_reached_across_chunk_edges(policy_db, monkeypatch, setter, n):
    monkeypatch.setattr(store, "_SQLITE_IN_CHUNK", 3)
    _seed(policy_db, KEY, range(1, n + 1))

    values = dict.fromkeys(range(1, n + 1), setter.first) | {999: setter.first}
    assert setter.call(KEY, values, db_path=policy_db) == n

    assert set(_stored(policy_db, KEY, setter.field).values()) == {setter.first}


@BOTH
def test_rows_are_loaded_a_chunk_at_a_time_not_one_by_one(policy_db, monkeypatch, setter):
    monkeypatch.setattr(store, "_SQLITE_IN_CHUNK", 25)
    _seed(policy_db, KEY, range(1, 61))
    selects: list[str] = []
    engine = get_engine(policy_db)

    def count(_con, _cursor, statement, _params, _ctx, _many):
        if statement.lstrip().upper().startswith("SELECT") and "policy_meeting" in statement:
            selects.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        assert setter.call(KEY, dict.fromkeys(range(1, 61), setter.first), db_path=policy_db) == 60
    finally:
        event.remove(engine, "before_cursor_execute", count)

    assert len(selects) == 3  # ceil(60 / 25): it used to be one SELECT per number
