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


def log_run(
    topic: str,
    video_id: str,
    url: str,
    *,
    angle: str = "",
    format: str = "",
    hook: str = "",
    word_count: int = 0,
    duration: float = 0.0,
) -> None:
    """Append a new pipeline run to the performance log."""
    entries = _load()
    entries.append({
        "topic": topic,
        "angle": angle,
        "format": format,
        "hook": hook,
        "word_count": word_count,
        "duration": duration,
        "video_id": video_id,
        "url": url,
        "uploaded_at": _now(),
        "views": 0,
        "likes": 0,
        "comments": 0,
        "views_per_hour": None,
        "like_rate": None,
        "comment_rate": None,
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
            entry["comments"] = stats.get("comments", 0)
            entry.setdefault("views_per_hour", None)
            entry.setdefault("like_rate", None)
            entry.setdefault("comment_rate", None)
            now = _now()
            entry["stats_fetched_at"] = now

            # Compute rates when we have upload time and views
            uploaded_at = entry.get("uploaded_at")
            views = entry["views"]
            if uploaded_at and views > 0:
                hours = _hours_since(uploaded_at)
                if hours > 0:
                    entry["views_per_hour"] = round(views / hours, 2)
            if views > 0:
                entry["like_rate"] = round(entry["likes"] / views, 4)
                entry["comment_rate"] = round(entry["comments"] / views, 4)

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


def get_performance_insights() -> dict:
    """Return aggregated performance insights broken down by format.

    Returns a dict with:
      - format_breakdown: avg views, avg like_rate, avg comment_rate per format
      - top_hooks: the hook text of the 3 highest-view entries
      - overall_avg_views: mean views across all qualified entries
    """
    from collections import defaultdict

    entries = _load()
    qualified = [e for e in entries if e.get("views", 0) >= 100]
    if not qualified:
        return {"format_breakdown": {}, "top_hooks": [], "overall_avg_views": 0}

    by_format: dict[str, list[dict]] = defaultdict(list)
    for e in qualified:
        fmt = e.get("format") or "unknown"
        by_format[fmt].append(e)

    def _avg(lst, key):
        vals = [x[key] for x in lst if x.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    format_breakdown = {}
    for fmt, items in by_format.items():
        format_breakdown[fmt] = {
            "count": len(items),
            "avg_views": _avg(items, "views"),
            "avg_like_rate": _avg(items, "like_rate"),
            "avg_comment_rate": _avg(items, "comment_rate"),
            "avg_views_per_hour": _avg(items, "views_per_hour"),
        }

    top_hooks = [
        e.get("hook", "") for e in
        sorted(qualified, key=lambda e: e["views"], reverse=True)[:3]
    ]
    overall_avg = round(sum(e["views"] for e in qualified) / len(qualified))

    return {
        "format_breakdown": format_breakdown,
        "top_hooks": top_hooks,
        "overall_avg_views": overall_avg,
    }


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
