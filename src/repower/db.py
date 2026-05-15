"""SQLAlchemy models and engine factory for the repower SQLite database."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
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
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from repower.config import DB_PATH


class Base(DeclarativeBase):
    pass


# ── TEPCO area supply/demand (30-min) ──────────────────────────────────────
class DemandSupply30m(Base):
    __tablename__ = "demand_supply_30m"
    id = Column(Integer, primary_key=True, autoincrement=True)
    area = Column(String(16), nullable=False, default="tepco")  # tepco, hokkaido, tohoku, chubu, hokuriku, kansai, chugoku, shikoku, kyushu
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


# ── Fuel / commodity prices (daily) ───────────────────────────────────────
class FuelDaily(Base):
    __tablename__ = "fuels_daily"
    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False)
    ticker = Column(String(20), nullable=False)
    close = Column(Float)
    currency = Column(String(5))
    __table_args__ = (UniqueConstraint("date", "ticker", name="uq_fuel_date_ticker"),)


# ── News items ─────────────────────────────────────────────────────────────
class NewsItem(Base):
    __tablename__ = "news_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    url_hash = Column(String(64), unique=True, nullable=False)
    source = Column(String(50))
    title = Column(Text)
    summary = Column(Text)
    published_at = Column(DateTime)
    fetched_at = Column(DateTime, default=datetime.utcnow)


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
    created_at = Column(DateTime, default=datetime.utcnow)


# ── Engine / session ──────────────────────────────────────────────────────
def get_engine(db_path: str | None = None):
    path = db_path or str(DB_PATH)
    return create_engine(f"sqlite:///{path}", echo=False)


def init_db(db_path: str | None = None):
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    _migrate_add_area_column(engine)
    return engine


def _migrate_add_area_column(engine) -> None:
    """Add `area` column and rebuild table if old (date,time)-only unique constraint exists.

    SQLite cannot drop an inline UNIQUE constraint, so we detect the old shape and
    perform a CREATE-INSERT-DROP-RENAME cycle to swap to the new schema.
    """
    from sqlalchemy import inspect, text as sql_text
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


def get_session(db_path: str | None = None) -> Session:
    engine = get_engine(db_path)
    return sessionmaker(bind=engine)()
