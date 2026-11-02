"""The additive migrations in ``repower.db``, run over legacy database files.

The production DB is pulled from Hugging Face, so the file the code meets can predate any column it
reads (``policy_meeting.index_note`` did, and until the pull re-ran the migrations every query then
raised "no such column"). Each migration has to bring such a file up to the model's schema without
losing a row, whichever of its columns are missing and whichever tables exist yet.

A legacy file is built the way it would have looked: the current schema from ``create_all`` with the
chosen columns removed by rebuilding their table (SQLite's own DROP COLUMN would do for most, but
needs 3.35 and refuses a column that is indexed or constrained), then a few rows inserted. ``init_db``
runs over it and every column in ``Base.metadata`` must be there, every row intact.

``MIGRATED`` is written out by hand rather than read from ``db.py``, so it is an independent account of
what a legacy file can lack. A new ``_migrate_add_*`` has to be added to it (the first test says so).
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine

from repower import db
from repower.db import Base, dispose_engines, init_db

# {migration: {table: [columns it adds]}}, in the order each one runs in ``init_db``.
MIGRATED: dict[str, dict[str, list[str]]] = {
    "_migrate_add_policy_synth_done": {"policy_meeting": ["synth_done"]},
    "_migrate_add_policy_registry": {
        "policy_committee": ["enabled", "user_added", "priority", "max_meeting", "prefix", "log_pages",
                             "min_meeting", "archived"],
        "policy_meeting": ["gen_requested"],
    },
    "_migrate_add_fetch_observability": {
        "http_cache": ["last_error_kind", "last_error_at", "last_error_detail"],
        "policy_committee": ["last_fetch_status", "last_fetch_kind", "last_fetch_detail", "last_fetch_url",
                             "last_fetch_at", "last_ok_at", "consecutive_failures"],
    },
    "_migrate_add_policy_meeting_error": {"policy_meeting": ["last_error", "last_error_at"]},
    "_migrate_add_policy_tags": {
        "policy_committee": ["tags", "tags_source"],
        "policy_meeting": ["tags", "tags_source"],
    },
    "_migrate_add_policy_citations": {"policy_meeting": ["citations_json"]},
    "_migrate_add_policy_minutes_watch": {
        "policy_meeting": ["resummarise_requested", "materials_checked_at", "summarised_at",
                           "resummarised_at", "digest_ja_json"],
        "policy_material": ["first_seen_at"],
    },
    "_migrate_add_policy_index_note": {
        "policy_meeting": ["index_note"],
        "policy_committee": ["index_notes_at"],
    },
}
# `_migrate_add_policy_synth_done` also backfills from policy_committee, so it cannot run on a file that
# has policy_meeting but no policy_committee; the tests of absent tables leave it out.
PURE = [n for n in MIGRATED if n != "_migrate_add_policy_synth_done"]


def _all_missing() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for tables in MIGRATED.values():
        for table, cols in tables.items():
            out.setdefault(table, []).extend(cols)
    return out


ALL_MISSING = _all_missing()

# Tables added to the schema after the first market-data ones.
ADDED_TABLES = ["policy_committee", "policy_meeting", "policy_material", "policy_fetch_event",
                "policy_upcoming", "http_cache"]

# name -> (columns to remove, tables to remove). Besides the full set and each migration alone: files
# from before whole tables existed, which ``create_all`` builds and the migrations must cope without.
SHAPES: dict[str, tuple[dict[str, list[str]], list[str]]] = {
    "all_missing": (ALL_MISSING, []),
    **{f"only_{n.removeprefix('_migrate_add_')}": (cols, []) for n, cols in MIGRATED.items()},
    "some_tables_absent": (ALL_MISSING, ["policy_material", "http_cache"]),
    "policy_tables_absent": ({}, ADDED_TABLES),
    "empty_file": ({}, list(Base.metadata.tables)),
}

STAMP = "2026-07-01 09:30:00.000000"  # how SQLAlchemy stores a DateTime on SQLite

# Rows as they would sit in a current file; a legacy shape keeps only the columns it still has.
ROWS: dict[str, list[dict[str, Any]]] = {
    "policy_committee": [
        {"committee_key": "santeii", "name_ja": "調整力等委員会", "name_en": "Adequacy Committee",
         "url": "https://example.invalid/santeii", "source": "METI", "latest_meeting": 7,
         "last_synth_meeting": 5, "last_checked": STAMP, "enabled": 1, "user_added": 0, "priority": 10,
         "archived": 0, "max_meeting": 9, "prefix": "p", "log_pages": '["a.html"]', "min_meeting": 1,
         "tags": '["storage"]', "tags_source": "rule", "index_notes_at": STAMP, "last_fetch_status": "ok",
         "last_fetch_url": "https://example.invalid/santeii", "last_fetch_at": STAMP, "last_ok_at": STAMP,
         "consecutive_failures": 0},
        {"committee_key": "saisei_kano", "name_ja": "再エネ小委員会", "name_en": "Renewables Subcommittee",
         "source": "EGC", "enabled": 0, "user_added": 1, "priority": 50, "archived": 1,
         "last_fetch_status": "error", "last_fetch_kind": "blocked_403", "last_fetch_detail": "refused",
         "consecutive_failures": 3},
    ],
    "policy_meeting": [
        {"committee_key": "santeii", "meeting_num": 3, "meeting_date": "2026-01-05", "title": "第3回",
         "briefing_md": "# 要約", "digest_en_json": '{"answer": "x"}', "digest_ja_json": '{"answer": "y"}',
         "citations_json": '{"v": 1, "items": []}', "has_minutes": 1, "has_torimatome": 0, "state": "done",
         "gen_seconds": 12.5, "retry_count": 0, "synth_done": 1, "gen_requested": 0,
         "resummarise_requested": 0, "materials_checked_at": STAMP, "summarised_at": STAMP,
         "tags": '["storage"]', "tags_source": "llm", "detected_at": STAMP, "updated_at": STAMP},
        {"committee_key": "santeii", "meeting_num": 4, "state": "detected", "synth_done": 0,
         "detected_at": STAMP, "updated_at": STAMP},
        {"committee_key": "santeii", "meeting_num": 7, "meeting_date": "2026-06-30", "state": "done",
         "briefing_md": "# 要約7", "synth_done": 0, "detected_at": STAMP, "updated_at": STAMP},
        {"committee_key": "saisei_kano", "meeting_num": 1, "state": "error", "quality_flag": "no_sources",
         "last_error": "no usable source documents", "last_error_at": STAMP, "retry_count": 2,
         "index_note": "no_papers", "synth_done": 0, "detected_at": STAMP, "updated_at": STAMP},
    ],
    "policy_material": [
        {"committee_key": "santeii", "meeting_num": 3, "pdf_id": "003_minutes", "kind": "minutes",
         "url": "https://example.invalid/003.pdf", "title": "議事録", "nblm_source_id": "s1",
         "sha256": "ab" * 32, "status": "ingested", "first_seen_at": STAMP},
        {"committee_key": "santeii", "meeting_num": 4, "pdf_id": "004_agenda", "kind": "agenda",
         "url": "https://example.invalid/004.pdf", "title": "議事次第", "status": "detected"},
    ],
    "http_cache": [
        {"url": "https://example.invalid/a.csv", "etag": '"abc"',
         "last_modified": "Wed, 01 Jul 2026 00:00:00 GMT", "last_status": 200, "last_checked": STAMP,
         "last_error_kind": "blocked_403", "last_error_at": STAMP, "last_error_detail": "refused"},
    ],
}

# What an ALTER leaves in rows that were already there, where it is not NULL.
FILLED = {
    ("policy_committee", "enabled"): 1,  # existing committees stay tracked
    ("policy_committee", "user_added"): 0,
    ("policy_committee", "archived"): 0,
    ("policy_committee", "consecutive_failures"): 0,
    ("policy_meeting", "gen_requested"): 0,
    ("policy_meeting", "resummarise_requested"): 0,
}


@pytest.fixture(autouse=True)
def _release_engines():
    yield
    dispose_engines()  # pooled connections would keep the tmp files open


# ── Building a legacy file ───────────────────────────────────────────────────
def _columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def _rebuild_without(con: sqlite3.Connection, table: str, drop: list[str]) -> None:
    ddl = con.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()[0]
    keep = [c for c in _columns(con, table) if c not in drop]
    # create_all writes one column per line, each starting with its name.
    legacy_ddl = "\n".join(ln for ln in ddl.splitlines() if ln.strip().split(" ")[0] not in drop)
    con.execute(f"ALTER TABLE {table} RENAME TO _rebuild")
    con.execute(legacy_ddl)
    cols = ", ".join(keep)
    con.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _rebuild")
    con.execute("DROP TABLE _rebuild")
    assert _columns(con, table) == keep


def _insert(con: sqlite3.Connection, table: str, row: dict[str, Any]) -> None:
    have = set(_columns(con, table))
    cols = [c for c in row if c in have]
    con.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [row[c] for c in cols])


def build_legacy(path: Path, missing: dict[str, list[str]], absent: list[str]) -> None:
    """The current schema with *missing* columns removed and *absent* tables dropped, plus the rows."""
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    with closing(sqlite3.connect(path)) as con:
        for table, cols in missing.items():
            _rebuild_without(con, table, cols)
        for table in absent:
            con.execute(f"DROP TABLE {table}")
        for table, rows in ROWS.items():
            if table not in absent:
                for row in rows:
                    _insert(con, table, row)
        con.commit()


# ── Reading it back ──────────────────────────────────────────────────────────
def dump(path: Path) -> dict[str, Any]:
    """Everything a schema comparison needs: each object's DDL, each table's columns, every row."""
    with closing(sqlite3.connect(path)) as con:
        con.row_factory = sqlite3.Row
        objects = [tuple(r) for r in con.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name")]
        tables = sorted(r[1] for r in objects if r[0] == "table")
        info = {t: [tuple(r) for r in con.execute(f"PRAGMA table_info({t})")] for t in tables}
        rows = {t: [dict(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY rowid")] for t in tables}
    return {"objects": objects, "info": info, "rows": rows}


def _expected_rows(table: str, missing: list[str], absent: list[str]) -> list[dict[str, Any]]:
    """The inserted rows as they should read after migration: kept columns unchanged, each added column
    at what its ALTER fills in."""
    if table in absent:
        return []
    committees = {r["committee_key"]: r for r in ROWS["policy_committee"]}
    out = []
    for i, row in enumerate(ROWS[table], start=1):
        exp: dict[str, Any] = {}
        for col in (c.name for c in Base.metadata.tables[table].columns):
            if col == "id":
                exp[col] = i
            elif col not in missing:
                exp[col] = row.get(col)
            elif (table, col) == ("policy_meeting", "synth_done"):
                # Seeded from the committee's old high-water mark: done, and at or below it.
                done_upto = committees[row["committee_key"]].get("last_synth_meeting") or -1
                exp[col] = int(row["state"] == "done" and row["meeting_num"] <= done_upto)
            else:
                exp[col] = FILLED.get((table, col))
        out.append(exp)
    return out


def assert_up_to_date(path: Path, missing: dict[str, list[str]], absent: list[str]) -> None:
    """Every table and column of the model is there (and nothing else), and so is every row."""
    got = dump(path)
    assert set(got["info"]) == set(Base.metadata.tables)
    for name, table in Base.metadata.tables.items():
        assert {c[1] for c in got["info"][name]} == {c.name for c in table.columns}, name
    for table in ROWS:
        assert got["rows"][table] == _expected_rows(table, missing.get(table, []), absent), table


# ── The migrations ───────────────────────────────────────────────────────────
def test_the_manifest_names_every_additive_migration():
    """A new ``_migrate_add_*`` must be added to ``MIGRATED``, or no legacy shape would exercise it."""
    found = {n for n in dir(db) if n.startswith("_migrate_add_")} - {"_migrate_add_area_column"}
    assert found == set(MIGRATED)  # the area migration rebuilds a table, and is not one of these
    model = {name: {c.name for c in t.columns} for name, t in Base.metadata.tables.items()}
    for cols in MIGRATED.values():
        for table, names in cols.items():
            assert set(names) <= model[table]
    for table, rows in ROWS.items():
        for row in rows:
            assert set(row) <= model[table]


@pytest.mark.parametrize("shape", SHAPES)
def test_init_db_brings_a_legacy_file_up_to_the_model_and_keeps_its_rows(tmp_path, shape):
    missing, absent = SHAPES[shape]
    legacy = tmp_path / "legacy.db"
    build_legacy(legacy, missing, absent)
    before = dump(legacy)  # the shape really is what it says
    assert set(before["info"]).isdisjoint(absent)
    for table, cols in missing.items():
        if table in before["info"]:
            assert {c[1] for c in before["info"][table]}.isdisjoint(cols)

    init_db(str(legacy))

    assert_up_to_date(legacy, missing, absent)


@pytest.mark.parametrize("name", MIGRATED)
def test_each_migration_restores_only_its_own_columns(tmp_path, name):
    missing = MIGRATED[name]
    legacy = tmp_path / "legacy.db"
    build_legacy(legacy, missing, [])
    before = dump(legacy)
    engine = create_engine(f"sqlite:///{legacy}")

    getattr(db, name)(engine)

    after = dump(legacy)
    for table, cols in after["info"].items():
        old = [c[1] for c in before["info"][table]]
        new = [c[1] for c in cols]
        # Its columns are appended; every other table, and every other column, is left as it was.
        assert new[:len(old)] == old, table
        assert set(new[len(old):]) == set(missing.get(table, [])), table
    assert_up_to_date(legacy, missing, [])
    getattr(db, name)(engine)  # idempotent
    assert dump(legacy) == after
    engine.dispose()


@pytest.mark.parametrize("name", PURE)
def test_a_migration_skips_a_table_that_is_not_there(tmp_path, name):
    """Only policy_meeting exists: a migration that names other tables as well must add to it, skip
    the rest and not build them (``create_all`` does that, whole)."""
    others = [t for t in Base.metadata.tables if t != "policy_meeting"]
    legacy = tmp_path / "legacy.db"
    build_legacy(legacy, ALL_MISSING, others)
    before = dump(legacy)
    engine = create_engine(f"sqlite:///{legacy}")

    getattr(db, name)(engine)
    engine.dispose()

    after = dump(legacy)
    assert set(after["info"]) == {"policy_meeting"}
    old = [c[1] for c in before["info"]["policy_meeting"]]
    new = [c[1] for c in after["info"]["policy_meeting"]]
    assert new[:len(old)] == old
    assert set(new[len(old):]) == set(MIGRATED[name].get("policy_meeting", []))


@pytest.mark.parametrize("name", PURE)
def test_a_migration_on_a_file_with_no_tables_does_nothing(tmp_path, name):
    empty = tmp_path / "empty.db"
    engine = create_engine(f"sqlite:///{empty}")

    getattr(db, name)(engine)
    engine.dispose()

    assert dump(empty)["objects"] == []


def test_a_second_init_db_changes_nothing(tmp_path):
    legacy = tmp_path / "legacy.db"
    build_legacy(legacy, ALL_MISSING, [])
    init_db(str(legacy))
    once = dump(legacy)

    dispose_engines()  # forget the path was set up, as a pull does
    init_db(str(legacy))

    assert dump(legacy) == once
    assert_up_to_date(legacy, ALL_MISSING, [])


def test_a_current_file_is_left_exactly_as_it_is(tmp_path):
    """The common case: nothing to migrate, so init_db must not touch the file's schema or rows."""
    current = tmp_path / "current.db"
    build_legacy(current, {}, [])
    before = dump(current)

    init_db(str(current))

    assert dump(current) == before


# ── The shared helper ────────────────────────────────────────────────────────
def test_add_missing_columns_adds_what_is_missing_and_skips_absent_tables(tmp_path):
    legacy = tmp_path / "legacy.db"
    build_legacy(legacy, {"policy_meeting": ["index_note", "tags"]}, ["http_cache"])
    engine = create_engine(f"sqlite:///{legacy}")
    spec = {
        "policy_meeting": [
            ("tags", "ALTER TABLE policy_meeting ADD COLUMN tags TEXT"),                     # missing
            ("state", "ALTER TABLE policy_meeting ADD COLUMN state TEXT"),                   # there: not run
            ("index_note", "ALTER TABLE policy_meeting ADD COLUMN index_note VARCHAR(16)"),  # missing
        ],
        "http_cache": [("etag", "ALTER TABLE http_cache ADD COLUMN etag TEXT")],             # no such table
        "policy_committee": [("enabled", "ALTER TABLE policy_committee ADD COLUMN enabled BOOLEAN")],  # there
    }

    db._add_missing_columns(engine, spec)
    engine.dispose()

    got = dump(legacy)
    cols = [c[1] for c in got["info"]["policy_meeting"]]
    assert cols[-2:] == ["tags", "index_note"]  # in spec order, after the columns it already had
    assert cols.count("state") == 1
    assert "http_cache" not in got["info"]


def test_add_missing_columns_is_idempotent(tmp_path):
    legacy = tmp_path / "legacy.db"
    build_legacy(legacy, {"policy_meeting": ["citations_json"]}, [])
    engine = create_engine(f"sqlite:///{legacy}")
    spec = {"policy_meeting": [("citations_json", "ALTER TABLE policy_meeting ADD COLUMN citations_json TEXT")]}
    db._add_missing_columns(engine, spec)
    once = dump(legacy)

    db._add_missing_columns(engine, spec)
    engine.dispose()

    assert dump(legacy) == once
