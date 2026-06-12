"""publish_stats.py — Sync YouTube video statistics into the ClipForge registry and run manifests."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from content_registry import load_registry, update_registry_entry
from manifest import update_run_manifest
from publish import get_video_stats
from publish_tracking import infer_registry_id_from_video_path


DEFAULT_REGISTRY_PATH = Path("data/content_registry.json")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _string_count(value: Any) -> str:
    if value in (None, "", False):
        return "0"
    return str(value)


def fetch_stats_for_entry(source: Any) -> dict[str, str] | None:
    """Normalize YouTube statistics for a raw stats dict, registry entry, or video id.

    Accepted inputs:
    - raw YouTube statistics dict, e.g. {"viewCount": "123", ...}
    - registry entry dict containing `youtube_video_id`
    - YouTube video id string
    """
    if isinstance(source, dict):
        if not source or any(key in source for key in ("viewCount", "likeCount", "commentCount", "favoriteCount", "faveCount")):
            raw_stats = source
        else:
            video_id = source.get("youtube_video_id")
            if not video_id:
                return None
            video_stats = get_video_stats(str(video_id))
            if not video_stats or video_stats.get("error"):
                return None
            raw_stats = {
                "viewCount": video_stats.get("views"),
                "likeCount": video_stats.get("likes"),
                "commentCount": video_stats.get("comments"),
                "favoriteCount": video_stats.get("favorites", video_stats.get("favoriteCount")),
            }
    elif isinstance(source, str):
        video_stats = get_video_stats(source)
        if not video_stats or video_stats.get("error"):
            return None
        raw_stats = {
            "viewCount": video_stats.get("views"),
            "likeCount": video_stats.get("likes"),
            "commentCount": video_stats.get("comments"),
            "favoriteCount": video_stats.get("favorites", video_stats.get("favoriteCount")),
        }
    else:
        return None

    result = {
        "views": _string_count(raw_stats.get("viewCount")),
        "likes": _string_count(raw_stats.get("likeCount")),
        "comments": _string_count(raw_stats.get("commentCount")),
        "favorites": _string_count(raw_stats.get("favoriteCount", raw_stats.get("faveCount"))),
        "fetched_at": _utc_now_iso(),
    }
    return result


def update_with_stats(
    entry_id: str,
    stats: dict[str, Any],
    *,
    registry_path: str | Path | None = None,
) -> Path | None:
    """Write normalized YouTube stats back to a registry entry."""
    resolved_registry = Path(registry_path) if registry_path is not None else DEFAULT_REGISTRY_PATH
    data = load_registry(resolved_registry)
    entries = data.get("entries", [])
    if not any(str(entry.get("id", "")) == entry_id for entry in entries):
        return None

    normalized = {
        "views": _string_count(stats.get("views")),
        "likes": _string_count(stats.get("likes")),
        "comments": _string_count(stats.get("comments")),
        "favorites": _string_count(stats.get("favorites")),
        "fetched_at": str(stats.get("fetched_at") or _utc_now_iso()),
    }
    return update_registry_entry(
        entry_id=entry_id,
        updates={
            "youtube_stats": normalized,
            "status": "stats_synced",
        },
        registry_path=resolved_registry,
    )


def _update_manifest_stats(video_path: str | Path, stats: dict[str, Any]) -> str | None:
    resolved_video_path = Path(video_path).resolve()
    run_dir = resolved_video_path.parents[1]
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        return None

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["youtube_stats"] = {
        "views": _string_count(stats.get("views")),
        "likes": _string_count(stats.get("likes")),
        "comments": _string_count(stats.get("comments")),
        "favorites": _string_count(stats.get("favorites")),
        "fetched_at": str(stats.get("fetched_at") or _utc_now_iso()),
    }
    manifest_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    update_run_manifest(manifest_path, status="stats_synced")
    return str(manifest_path)


def sync_for_run(
    *,
    video_path: str | Path,
    stats: dict[str, Any],
    registry_path: str | Path | None = None,
) -> dict[str, Any]:
    """Sync stats for a specific run by inferring the registry id from the video path."""
    registry_id = infer_registry_id_from_video_path(video_path)
    if registry_id is None:
        return {
            "success": False,
            "registry_id": None,
            "manifest_path": None,
        }

    updated_registry_path = update_with_stats(registry_id, stats, registry_path=registry_path)
    if updated_registry_path is None:
        return {
            "success": False,
            "registry_id": registry_id,
            "manifest_path": None,
        }

    manifest_path = _update_manifest_stats(video_path, stats)
    return {
        "success": True,
        "registry_id": registry_id,
        "registry_path": str(updated_registry_path),
        "manifest_path": manifest_path,
    }


def fetch_all_and_update(*, registry_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Fetch stats for all uploaded entries and write back any successful results."""
    resolved_registry = Path(registry_path) if registry_path is not None else DEFAULT_REGISTRY_PATH
    entries = load_registry(resolved_registry).get("entries", [])
    results: list[dict[str, Any]] = []

    for entry in entries:
        entry_id = str(entry.get("id", ""))
        if not entry_id:
            results.append({"success": False, "entry_id": None, "reason": "missing_entry_id"})
            continue

        stats = fetch_stats_for_entry(entry)
        if not stats:
            results.append({"success": False, "entry_id": entry_id, "reason": "no_stats"})
            continue

        updated_path = update_with_stats(entry_id, stats, registry_path=resolved_registry)
        if updated_path is None:
            results.append({"success": False, "entry_id": entry_id, "reason": "missing_registry_entry"})
            continue

        results.append({
            "success": True,
            "entry_id": entry_id,
            "registry_path": str(updated_path),
            "stats": stats,
        })

    return results
