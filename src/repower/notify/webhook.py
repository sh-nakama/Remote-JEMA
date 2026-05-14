"""Post analysis digest to Discord/Slack via webhook."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from typing import Any

import httpx

from repower.config import WEBHOOK_URL
from repower.db import AnalysisRecord, get_session, init_db

logger = logging.getLogger(__name__)


def _format_discord_embed(features: dict[str, Any]) -> dict:
    """Format features dict into a Discord embed payload."""
    target_date = features.get("date", "unknown")

    # Build description sections
    sections = []

    # Demand section
    demand = features.get("demand", {})
    if demand and demand.get("status") != "no_data":
        vs = demand.get("vs_30d_avg_pct", "N/A")
        vs_str = f"{vs:+.1f}%" if isinstance(vs, (int, float)) else vs
        sections.append(
            f"**⚡ Demand**\n"
            f"Peak: {demand.get('peak_mw', '?'):,} MW @ {demand.get('peak_time', '?')}\n"
            f"Avg: {demand.get('avg_mw', '?'):,} MW (vs 30d: {vs_str})"
        )

    # JEPX section
    jepx = features.get("jepx", {})
    if jepx and jepx.get("status") != "no_data":
        vs = jepx.get("vs_30d_avg_pct", "N/A")
        vs_str = f"{vs:+.1f}%" if isinstance(vs, (int, float)) else vs
        pctile = jepx.get("percentile_30d", "N/A")
        sections.append(
            f"**💴 JEPX Tokyo Spot**\n"
            f"Avg: ¥{jepx.get('avg_yen_kwh', '?')}/kWh | "
            f"Max: ¥{jepx.get('max_yen_kwh', '?')}/kWh @ {jepx.get('peak_time', '?')}\n"
            f"vs 30d: {vs_str} | Percentile: {pctile}th"
        )

    # Generation mix
    mix = features.get("generation_mix_pct", {})
    re_share = features.get("renewable_share_pct")
    if mix:
        top3 = sorted(mix.items(), key=lambda x: x[1], reverse=True)[:3]
        mix_str = " | ".join(f"{k}: {v}%" for k, v in top3)
        re_str = f" | RE: {re_share}%" if re_share else ""
        sections.append(f"**🔋 Gen Mix (top 3)**\n{mix_str}{re_str}")

    # Fuels
    fuels = features.get("fuels", {})
    if fuels:
        fuel_lines = []
        for ticker, info in fuels.items():
            fuel_lines.append(f"{ticker}: {info['close']} {info['currency']}")
        sections.append(f"**🛢️ Fuels**\n" + " | ".join(fuel_lines))

    # News
    headlines = features.get("news_headlines", [])
    if headlines:
        news_str = "\n".join(f"• {h}" for h in headlines[:3])
        sections.append(f"**📰 News ({features.get('news_count', 0)} items)**\n{news_str}")

    description = "\n\n".join(sections) if sections else "No data available for this date."

    return {
        "embeds": [
            {
                "title": f"🇯🇵 Tokyo Power Market — {target_date}",
                "description": description,
                "color": 0x1E90FF,
            }
        ]
    }


def _format_slack_blocks(features: dict[str, Any]) -> dict:
    """Format features dict into Slack Block Kit payload."""
    # Reuse Discord description logic for simplicity
    embed = _format_discord_embed(features)
    text = embed["embeds"][0]["description"]
    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": embed["embeds"][0]["title"]}},
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        ]
    }


def post_webhook(
    features: dict[str, Any],
    webhook_url: str | None = None,
    dry_run: bool = False,
) -> bool:
    """Post formatted digest to webhook. Returns True on success."""
    url = webhook_url or WEBHOOK_URL
    if not url:
        logger.error("No WEBHOOK_URL configured")
        return False

    # Detect Discord vs Slack
    if "discord.com" in url or "discordapp.com" in url:
        payload = _format_discord_embed(features)
    else:
        payload = _format_slack_blocks(features)

    if dry_run:
        logger.info("DRY RUN webhook payload:\n%s", json.dumps(payload, indent=2, ensure_ascii=False))
        return True

    try:
        resp = httpx.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        logger.info("Webhook posted successfully (status %d)", resp.status_code)
        return True
    except Exception as e:
        logger.error("Webhook failed: %s", e)
        return False


def notify(target_date: date | None = None, dry_run: bool = False, db_path: str | None = None) -> bool:
    """Load features for a date and post to webhook."""
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    init_db(db_path)
    session = get_session(db_path)
    try:
        record = session.query(AnalysisRecord).filter_by(date=target_date).first()
        if not record or not record.features_json:
            logger.error("No analysis found for %s — run `repower analyze` first", target_date)
            return False

        features = json.loads(record.features_json)
        return post_webhook(features, dry_run=dry_run)
    finally:
        session.close()
