"""SQLAlchemy models and engine factory for the repower SQLite database."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from repower.config import DB_PATH


class Base(DeclarativeBase):
    pass


# ── TEPCO area supply/demand (30-min) ──────────────────────────────────────
class DemandSupply30m(Base):
    __tablename__ = "demand_supply_30m"
    id = Column(Integer, primary_key=True, autoincrement=True)
    # tepco, hokkaido, tohoku, chubu, hokuriku, kansai, chugoku, shikoku, kyushu
    area = Column(String(16), nullable=False, default="tepco")
    date = Column(Date, nullable=False)
    time = Column(String(5), nullable=False)  # "HH:MM"
    area_demand_mw = Column(Float)
    nuclear = Column(Float)
    lng = Column(Float)
    coal = Column(Float)
    oil = Column(Float)
    thermal_other = Column(Float)
    hydro = Column(Float)
    geothermal = Column(Float)
    biomass = Column(Float)
    solar_actual = Column(Float)
    solar_curtail = Column(Float)
    wind_actual = Column(Float)
    wind_curtail = Column(Float)
    pumped = Column(Float)
    battery = Column(Float)
    interconnect = Column(Float)
    other = Column(Float)
    total_supply = Column(Float)
    __table_args__ = (UniqueConstraint("area", "date", "time", name="uq_ds_area_date_time"),)


# ── JEPX day-ahead spot prices (30-min) ───────────────────────────────────
class JepxSpot30m(Base):
    __tablename__ = "jepx_spot_30m"
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    time = Column(String(5), nullable=False)
    system_price = Column(Float)
    tokyo_area_price = Column(Float)
    __table_args__ = (UniqueConstraint("date", "time", name="uq_jepx_date_time"),)


# ── JEPX per-area prices (30-min, long format) ────────────────────────────
class JepxAreaPrice30m(Base):
    """Per-region JEPX area price, keyed (area, date, time) like DemandSupply30m."""
    __tablename__ = "jepx_area_price_30m"
    id = Column(Integer, primary_key=True, autoincrement=True)
    # hokkaido, tohoku, tepco, chubu, hokuriku, kansai, chugoku, shikoku, kyushu
    area = Column(String(16), nullable=False)
    date = Column(Date, nullable=False)
    time = Column(String(5), nullable=False)
    price = Column(Float)
    __table_args__ = (UniqueConstraint("area", "date", "time", name="uq_jepx_area_date_time"),)


# ── Fuel / commodity prices (daily) ───────────────────────────────────────
class FuelDaily(Base):
    __tablename__ = "fuels_daily"
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    ticker = Column(String(20), nullable=False)
    close = Column(Float)
    currency = Column(String(5))
    __table_args__ = (UniqueConstraint("date", "ticker", name="uq_fuel_date_ticker"),)


# EPRX balancing + tieline *data* live in compressed Parquet (see
# repower.config.EPRX_BALANCING_PARQUET / EPRX_TIELINE_PARQUET), not SQLite —
# the long format compresses ~200x better as columnar Parquet (≈7 MB vs ≈1.4 GB)
# and keeps the HF-synced DB small. Only the conditional-GET cache stays in SQLite.


# ── HTTP conditional-GET cache (ETag / Last-Modified), shared via HF-synced DB ──
# Used by the TSO area, JEPX, and EPRX scrapers so re-runs (including across the
# ephemeral daily CI runs) skip downloading + re-parsing unchanged files.
class HttpCache(Base):
    __tablename__ = "http_cache"
    url = Column(String(512), primary_key=True)
    etag = Column(String(256))
    last_modified = Column(String(64))
    last_status = Column(Integer)
    last_checked = Column(DateTime)


# ── News items ─────────────────────────────────────────────────────────────
class NewsItem(Base):
    __tablename__ = "news_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    url_hash = Column(String(64), unique=True, nullable=False)
    source = Column(String(50))
    title = Column(Text)
    summary = Column(Text)
    published_at = Column(DateTime)
    fetched_at = Column(DateTime, default=lambda: datetime.now(UTC))


# ── Analysis outputs ──────────────────────────────────────────────────────
class AnalysisRecord(Base):
    __tablename__ = "analyses"
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, unique=True, nullable=False)
    features_json = Column(Text)
    narrative_md = Column(Text)
    model = Column(String(50))
    tokens_in = Column(Integer)
    tokens_out = Column(Integer)
    cost_usd = Column(Float)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))


# ── Policy observer ─────────────────────────────────────────────────────────
# Tracks Japanese energy-policy committees (METI/OCCTO/EGC), their meetings, and
# the NotebookLM-generated summaries. Low-volume structured records, so SQLite
# (like AnalysisRecord) rather than Parquet. The TEXT summary columns ride the
# existing repower.db → Hugging Face sync, so no hf_sync change is needed.
class PolicyCommittee(Base):
    """One tracked committee + its rolled-up running document and synthesis state."""

    __tablename__ = "policy_committee"
    committee_key = Column(String(64), primary_key=True)
    name_ja = Column(Text)
    name_en = Column(Text)
    url = Column(Text)
    source = Column(String(8))  # METI | OCCTO | EGC
    latest_meeting = Column(Integer)  # highest meeting reaching state='done'
    synthesis_notebook_id = Column(String(64))  # persistent per-committee notebook
    last_synth_meeting = Column(Integer)  # highest meeting folded into the synthesis
    archive_watermark_meeting = Column(Integer)  # summaries ≤ this rolled into an archive source
    source_count = Column(Integer)  # live sources in the synthesis notebook
    running_summary_md = Column(Text)  # Japanese running document (regenerated from DB)
    running_digest_en_md = Column(Text)  # compact English running digest
    last_checked = Column(DateTime)  # last detection run
    last_refreshed_at = Column(DateTime)  # last summarisation run
    # Tracked-set state (see repower.policy.store):
    #   enabled     — the daily detect/summarise pipeline processes this committee.
    #   user_added  — added at runtime (discovery / UI) vs seeded from committees.py.
    #   priority    — summarisation priority (mirrors the config value; lower first).
    #   archived    — the committee has concluded: skip every fetch pass (detection
    #                 and both backfills). Independent of ``enabled``, which only
    #                 gates summarisation: a dormant committee can be tracked but
    #                 archived, or untracked but still actively detected.
    enabled = Column(Boolean, default=True, nullable=False)
    user_added = Column(Boolean, default=False, nullable=False)
    priority = Column(Integer, default=100)
    archived = Column(Boolean, default=False, nullable=False)
    # Per-source scraper config (mirrors committees.Committee) so a committee added
    # at runtime is scrapeable without a code change. OCCTO: max_meeting/prefix;
    # EGC: log_pages (JSON array of log-page filenames) / min_meeting.
    max_meeting = Column(Integer)
    prefix = Column(String(64))
    log_pages = Column(Text)
    min_meeting = Column(Integer)


class PolicyMeeting(Base):
    """One committee meeting and its per-meeting summary lifecycle."""

    __tablename__ = "policy_meeting"
    id = Column(Integer, primary_key=True, autoincrement=True)
    committee_key = Column(String(64), nullable=False)
    meeting_num = Column(Integer, nullable=False)
    meeting_date = Column(Date)
    title = Column(Text)
    notebook_id = Column(String(64))  # ephemeral notebook (deleted after done)
    report_task_id = Column(String(64))
    briefing_md = Column(Text)  # detailed Japanese per-meeting briefing
    digest_en_json = Column(Text)  # English ask --json (answer + references[])
    has_minutes = Column(Boolean, default=False)  # 議事録 present
    has_torimatome = Column(Boolean, default=False)  # とりまとめ present → milestone
    # detected → downloading → ingesting → generating → done | error
    state = Column(String(16), default="detected", nullable=False)
    quality_flag = Column(String(32))  # e.g. ocr_suspect, short_output
    gen_seconds = Column(Float)
    retry_count = Column(Integer, default=0)
    # True once this meeting's briefing has been folded into the committee synthesis
    # notebook. Tracked per-meeting (not via a single high-water mark) so backfilled
    # / out-of-order meetings are included rather than skipped.
    synth_done = Column(Boolean, default=False)
    # Set when a user asks the dashboard to summarise this meeting but auth was stale
    # (or they queued it): the next `policy run` drains requested meetings first.
    gen_requested = Column(Boolean, default=False)
    detected_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC))
    __table_args__ = (
        UniqueConstraint("committee_key", "meeting_num", name="uq_policy_meeting"),
    )


class PolicyUpcoming(Base):
    """A scheduled (future) committee meeting from an external schedule source.

    Committee pages only list a meeting once its materials exist, so upcoming
    meetings come from forward-looking calendars (METI committee calendar +
    電気新聞 weekly schedule). This table is a rolling snapshot — it is fully
    replaced on each ``policy schedule`` refresh — so it needs no lifecycle state.

    ``committee_key`` is set when the entry matches a tracked committee (nullable
    otherwise). Deduped on ``(meeting_date, source_key)`` where ``source_key`` is a
    normalised name, so the same meeting listed by two sources collapses to one row.
    """

    __tablename__ = "policy_upcoming"
    id = Column(Integer, primary_key=True, autoincrement=True)
    meeting_date = Column(Date, nullable=False)
    name_ja = Column(Text, nullable=False)
    source_key = Column(String(160), nullable=False)  # normalised name for dedup
    org = Column(String(16))  # METI | OCCTO | EGC | other
    committee_key = Column(String(64))  # matched tracked committee, else NULL
    meeting_num = Column(Integer)  # from 第N回, if present
    source = Column(String(16))  # meti (the METI committee calendar)
    source_url = Column(Text)
    detected_at = Column(DateTime, default=lambda: datetime.now(UTC))
    __table_args__ = (
        UniqueConstraint("meeting_date", "source_key", name="uq_policy_upcoming"),
    )


class PolicyMaterial(Base):
    """One source document (PDF) belonging to a meeting."""

    __tablename__ = "policy_material"
    id = Column(Integer, primary_key=True, autoincrement=True)
    committee_key = Column(String(64), nullable=False)
    meeting_num = Column(Integer, nullable=False)
    pdf_id = Column(String(128), nullable=False)  # stable per-committee dedup key
    kind = Column(String(16))  # minutes | brief | compilation | appendix | handout | agenda | other
    url = Column(Text)
    title = Column(Text)  # link text
    nblm_source_id = Column(String(64))  # NotebookLM source id once ingested
    sha256 = Column(String(64))
    status = Column(String(16), default="detected")  # detected | downloaded | ingested | error
    __table_args__ = (
        UniqueConstraint("committee_key", "pdf_id", name="uq_policy_material"),
    )


# ── Engine / session ──────────────────────────────────────────────────────
# Engines are memoized per resolved path so we don't rebuild them (or re-run
# create_all/migrate) on every upsert. Guarded by a lock so concurrent callers
# (e.g. a threaded scrape, or Streamlit's worker threads) can't race on cache
# population or run the migration twice.
_ENGINES: dict[str, Engine] = {}
_INITIALIZED: set[str] = set()
_LOCK = threading.Lock()


def get_engine(db_path: str | None = None) -> Engine:
    path = db_path or str(DB_PATH)
    engine = _ENGINES.get(path)
    if engine is not None:
        return engine
    with _LOCK:
        engine = _ENGINES.get(path)
        if engine is None:
            engine = create_engine(f"sqlite:///{path}", echo=False)
            _ENGINES[path] = engine
        return engine


def init_db(db_path: str | None = None) -> Engine:
    engine = get_engine(db_path)
    path = db_path or str(DB_PATH)
    if path in _INITIALIZED:
        return engine
    with _LOCK:
        if path not in _INITIALIZED:
            Base.metadata.create_all(engine)
            _migrate_add_area_column(engine)
            _migrate_add_policy_synth_done(engine)
            _migrate_add_policy_registry(engine)
            _INITIALIZED.add(path)
    return engine


def _migrate_add_area_column(engine) -> None:
    """Add `area` column and rebuild table if old (date,time)-only unique constraint exists.

    SQLite cannot drop an inline UNIQUE constraint, so we detect the old shape and
    perform a CREATE-INSERT-DROP-RENAME cycle to swap to the new schema.
    """
    from sqlalchemy import inspect
    from sqlalchemy import text as sql_text
    insp = inspect(engine)
    if "demand_supply_30m" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("demand_supply_30m")}
    uniques = insp.get_unique_constraints("demand_supply_30m")
    has_area = "area" in cols
    has_old_uniq = any(
        set(u.get("column_names") or []) == {"date", "time"} for u in uniques
    )
    has_new_uniq = any(
        set(u.get("column_names") or []) == {"area", "date", "time"} for u in uniques
    )
    if has_area and has_new_uniq and not has_old_uniq:
        return  # already migrated

    with engine.begin() as conn:
        if not has_area:
            conn.execute(sql_text(
                "ALTER TABLE demand_supply_30m ADD COLUMN area VARCHAR(16) "
                "NOT NULL DEFAULT 'tepco'"
            ))
            conn.execute(sql_text(
                "UPDATE demand_supply_30m SET area = 'tepco' "
                "WHERE area IS NULL OR area = ''"
            ))
        if has_old_uniq or not has_new_uniq:
            # Rebuild table to swap unique constraint.
            conn.execute(sql_text("ALTER TABLE demand_supply_30m RENAME TO _ds_old"))
            Base.metadata.tables["demand_supply_30m"].create(conn)
            # Copy rows; the new table has the same column set plus `area`.
            old_cols = ["area", "date", "time",
                        "area_demand_mw", "nuclear", "lng", "coal", "oil",
                        "thermal_other", "hydro", "geothermal", "biomass",
                        "solar_actual", "solar_curtail", "wind_actual", "wind_curtail",
                        "pumped", "battery", "interconnect", "other", "total_supply"]
            col_list = ", ".join(old_cols)
            conn.execute(sql_text(
                f"INSERT INTO demand_supply_30m ({col_list}) "
                f"SELECT {col_list} FROM _ds_old"
            ))
            conn.execute(sql_text("DROP TABLE _ds_old"))


def _migrate_add_policy_synth_done(engine) -> None:
    """Add the per-meeting ``synth_done`` flag to ``policy_meeting`` (additive).

    Seeds it from the legacy single high-water mark so existing summaries aren't
    re-added to the synthesis: meetings at or below a committee's
    ``last_synth_meeting`` were already folded in.
    """
    from sqlalchemy import inspect
    from sqlalchemy import text as sql_text
    insp = inspect(engine)
    if "policy_meeting" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("policy_meeting")}
    if "synth_done" in cols:
        return
    with engine.begin() as conn:
        conn.execute(sql_text("ALTER TABLE policy_meeting ADD COLUMN synth_done BOOLEAN DEFAULT 0"))
        conn.execute(sql_text(
            "UPDATE policy_meeting SET synth_done = 1 "
            "WHERE state = 'done' AND meeting_num <= ("
            "  SELECT COALESCE(c.last_synth_meeting, -1) FROM policy_committee c"
            "  WHERE c.committee_key = policy_meeting.committee_key)"
        ))


def _migrate_add_policy_registry(engine) -> None:
    """Add the dashboard-editable registry columns (all additive).

    ``policy_committee`` gains enabled/user_added/priority + the OCCTO/EGC scrape
    params so committees can be added and toggled from the UI; ``policy_meeting``
    gains ``gen_requested``. Existing committees default to enabled (so the current
    tracked set is unchanged); ``priority`` is added NULL and seeded from the code
    config by ``sync_committees`` (which can't be expressed in plain SQL here).
    """
    from sqlalchemy import inspect
    from sqlalchemy import text as sql_text
    insp = inspect(engine)
    names = insp.get_table_names()

    if "policy_committee" in names:
        cols = {c["name"] for c in insp.get_columns("policy_committee")}
        adds = [
            ("enabled", "ALTER TABLE policy_committee ADD COLUMN enabled BOOLEAN NOT NULL DEFAULT 1"),
            ("user_added", "ALTER TABLE policy_committee ADD COLUMN user_added BOOLEAN NOT NULL DEFAULT 0"),
            ("priority", "ALTER TABLE policy_committee ADD COLUMN priority INTEGER"),
            ("max_meeting", "ALTER TABLE policy_committee ADD COLUMN max_meeting INTEGER"),
            ("prefix", "ALTER TABLE policy_committee ADD COLUMN prefix VARCHAR(64)"),
            ("log_pages", "ALTER TABLE policy_committee ADD COLUMN log_pages TEXT"),
            ("min_meeting", "ALTER TABLE policy_committee ADD COLUMN min_meeting INTEGER"),
            ("archived", "ALTER TABLE policy_committee ADD COLUMN archived BOOLEAN NOT NULL DEFAULT 0"),
        ]
        with engine.begin() as conn:
            for col, ddl in adds:
                if col not in cols:
                    conn.execute(sql_text(ddl))

    if "policy_meeting" in names:
        cols = {c["name"] for c in insp.get_columns("policy_meeting")}
        if "gen_requested" not in cols:
            with engine.begin() as conn:
                conn.execute(sql_text(
                    "ALTER TABLE policy_meeting ADD COLUMN gen_requested BOOLEAN DEFAULT 0"
                ))


def get_session(db_path: str | None = None) -> Session:
    engine = get_engine(db_path)
    return sessionmaker(bind=engine)()
