"""publish_tracking.py — Sync upload metadata into run manifests and content registry."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from content_registry import update_registry_entry
from manifest import update_run_manifest


def infer_registry_id_from_video_path(video_path: str | Path) -> str | None:
    path = Path(video_path).resolve()
    parts = path.parts
    if "runs" not in parts:
        return None
    runs_index = parts.index("runs")
    if runs_index + 1 >= len(parts):
        return None
    return parts[runs_index + 1]


def track_successful_upload(
    *,
    video_path: str | Path,
    youtube_url: str,
    registry_path: str | Path,
    published_at: str | None = None,
) -> dict[str, str | None]:
    registry_id = infer_registry_id_from_video_path(video_path)
    video_id = youtube_url.split("v=")[-1] if "v=" in youtube_url else None
    published_timestamp = published_at or datetime.now(timezone.utc).isoformat()

    if registry_id is None:
        return {
            "registry_id": None,
            "video_id": video_id,
            "youtube_url": youtube_url,
            "published_at": published_timestamp,
            "manifest_path": None,
        }

    resolved_video_path = Path(video_path).resolve()
    run_dir = resolved_video_path.parents[1]
    manifest_path = run_dir / "manifest.json"

    if manifest_path.exists():
        update_run_manifest(
            manifest_path,
            status="uploaded",
            youtube_url=youtube_url,
            video_id=video_id,
            published_at=published_timestamp,
        )

    update_registry_entry(
        entry_id=registry_id,
        updates={
            "status": "uploaded",
            "youtube_url": youtube_url,
            "youtube_video_id": video_id,
            "published_at": published_timestamp,
        },
        registry_path=registry_path,
    )

    return {
        "registry_id": registry_id,
        "video_id": video_id,
        "youtube_url": youtube_url,
        "published_at": published_timestamp,
        "manifest_path": str(manifest_path) if manifest_path.exists() else None,
    }
