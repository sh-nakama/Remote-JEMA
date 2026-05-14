"""Scrape Japanese energy news from RSS feeds.

Sources:
- Reuters JP energy
- METI press releases
- OCCTO (Organization for Cross-regional Coordination of Transmission Operators)
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime

import feedparser
from sqlalchemy.dialects.sqlite import insert as sqlite_upsert

from repower.db import NewsItem, get_session, init_db

logger = logging.getLogger(__name__)

# RSS feeds to monitor
FEEDS = [
    {
        "url": "https://www.meti.go.jp/english/press/index_rss.xml",
        "source": "METI",
    },
    {
        "url": "https://www.occto.or.jp/rss/occto_whatsnew.xml",
        "source": "OCCTO",
    },
    {
        "url": "https://news.google.com/rss/search?q=%E9%9B%BB%E5%8A%9B+%E5%B8%82%E5%A0%B4+%E6%97%A5%E6%9C%AC&hl=ja&gl=JP&ceid=JP:ja",
        "source": "Google News JP",
    },
]

# Keywords to filter relevant articles (at least one must match title or summary)
KEYWORDS = [
    "電力", "LNG", "原発", "再エネ", "JEPX", "火力", "卸電力",
    "power", "energy", "electricity", "nuclear", "renewable",
    "gas", "coal", "fuel", "grid", "demand", "supply",
]


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:64]


def _matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in KEYWORDS)


def _parse_published(entry) -> datetime | None:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        from time import mktime
        return datetime.fromtimestamp(mktime(entry.published_parsed))
    return None


def fetch_news() -> list[dict]:
    """Fetch and filter news items from all configured RSS feeds."""
    items: list[dict] = []

    for feed_cfg in FEEDS:
        try:
            feed = feedparser.parse(feed_cfg["url"])
            for entry in feed.entries:
                title = getattr(entry, "title", "") or ""
                summary = getattr(entry, "summary", "") or ""
                link = getattr(entry, "link", "") or ""

                if not link:
                    continue

                # Filter by keywords
                if not _matches_keywords(title + " " + summary):
                    continue

                items.append({
                    "url_hash": _url_hash(link),
                    "source": feed_cfg["source"],
                    "title": title[:500],
                    "summary": summary[:1000],
                    "published_at": _parse_published(entry),
                    "fetched_at": datetime.utcnow(),
                })
        except Exception as e:
            logger.error("RSS %s: %s", feed_cfg["source"], e)

    return items


def upsert_news(items: list[dict], db_path: str | None = None) -> int:
    """Upsert news items (deduped by URL hash). Returns new items inserted."""
    if not items:
        return 0

    init_db(db_path)
    session = get_session(db_path)
    inserted = 0

    try:
        for item in items:
            stmt = sqlite_upsert(NewsItem).values(**item)
            stmt = stmt.on_conflict_do_nothing(index_elements=["url_hash"])
            result = session.execute(stmt)
            if result.rowcount > 0:
                inserted += 1
        session.commit()
    finally:
        session.close()

    return inserted


def scrape_news(db_path: str | None = None) -> int:
    """Scrape all RSS feeds and store new items. Returns count of new items."""
    items = fetch_news()
    n = upsert_news(items, db_path)
    logger.info("News: fetched %d items, %d new", len(items), n)
    return n
