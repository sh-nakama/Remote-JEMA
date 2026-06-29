"""JST-anchored date helpers: data is JST, but CI runs in UTC."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def today_jst() -> date:
    return datetime.now(JST).date()


def yesterday_jst() -> date:
    return today_jst() - timedelta(days=1)
