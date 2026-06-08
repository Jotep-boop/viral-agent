"""tracker.py — Log pipeline runs and refresh YouTube performance stats."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import config

logger = logging.getLogger(__name__)

_LOG_FILE = config.OUTPUT_DIR / "performance.json"
_STATS_TTL_HOURS = 48


def log_run(topic: str, video_id: str, url: str) -> None:
    """Append a new pipeline run to the performance log."""
    entries = _load()
    entries.append({
        "topic": topic,
        "video_id": video_id,
        "url": url,
        "uploaded_at": _now(),
        "views": 0,
        "likes": 0,
        "stats_fetched_at": None,
    })
    _save(entries)
    logger.info("Logged run: %s → %s", topic, video_id)


def refresh_stats() -> None:
    """Fetch updated stats for entries whose stats are missing or stale (>48 h)."""
    entries = _load()
    stale = [
        e for e in entries
        if e.get("stats_fetched_at") is None
        or _hours_since(e["stats_fetched_at"]) >= _STATS_TTL_HOURS
    ]
    if not stale:
        logger.info("Performance stats are up to date (%d entries).", len(entries))
        return

    try:
        from publish import get_video_stats
    except ImportError:
        logger.warning("publish module unavailable — skipping stats refresh.")
        return

    updated = 0
    for entry in stale:
        try:
            stats = get_video_stats(entry["video_id"])
            entry["views"] = stats.get("views", 0)
            entry["likes"] = stats.get("likes", 0)
            entry["stats_fetched_at"] = _now()
            updated += 1
        except Exception as exc:
            logger.warning("Stats fetch failed for %s: %s", entry["video_id"], exc)

    _save(entries)
    logger.info("Refreshed stats for %d/%d stale entries.", updated, len(stale))


def get_top_performers(n: int = 5) -> list[dict]:
    """Return the top N entries by view count (minimum 100 views to qualify)."""
    entries = _load()
    qualified = [e for e in entries if e.get("views", 0) >= 100]
    return sorted(qualified, key=lambda e: e["views"], reverse=True)[:n]


def _load() -> list[dict]:
    if not _LOG_FILE.exists():
        return []
    try:
        return json.loads(_LOG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(entries: list[dict]) -> None:
    _LOG_FILE.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hours_since(iso_str: str) -> float:
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
