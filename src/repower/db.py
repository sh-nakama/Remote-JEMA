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
    __table_args__ = (UniqueConstraint("date", "time", name="uq_ds_date_time"),)


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
    return engine


def get_session(db_path: str | None = None) -> Session:
    engine = get_engine(db_path)
    return sessionmaker(bind=engine)()
