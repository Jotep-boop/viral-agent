"""manifest.py — Build and persist per-run manifest metadata for ClipForge."""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from artifact_paths import ArtifactPaths


def _relative_to_run(path: Path, run_dir: Path) -> str:
    return str(path.relative_to(run_dir))


def _list_existing_relative_paths(paths: list[Path], run_dir: Path) -> list[str]:
    return [
        _relative_to_run(path, run_dir)
        for path in sorted(paths)
        if path.exists()
    ]


def probe_duration_seconds(video_path: Path) -> float:
    from video import _ffmpeg_bin

    result = subprocess.run(
        [_ffmpeg_bin(), "-i", str(video_path), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", result.stderr)
    if not match:
        return 0.0
    hours, minutes, seconds, centiseconds = match.groups()
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(centiseconds) / 100
    )


def build_run_manifest(
    *,
    paths: ArtifactPaths,
    topic: str,
    theme: str,
    pillar: str | None,
    hook_type: str | None,
    fact_summary: str,
    hook_angle: str,
    keywords: list[str],
    status: str,
    script_text: str,
    duration_seconds: float,
    youtube_url: str | None = None,
    video_id: str | None = None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    clips = sorted(paths.clips_dir.glob("clip_*.mp4"))
    normalized_clips = sorted(paths.clips_dir.glob("norm_*.mp4"))

    return {
        "registry_id": paths.registry_id,
        "created_at": now,
        "updated_at": now,
        "status": status,
        "topic": topic,
        "theme": theme,
        "pillar": pillar,
        "hook_type": hook_type,
        "fact_summary": fact_summary,
        "hook_angle": hook_angle,
        "keywords": keywords,
        "script_text": script_text,
        "duration_seconds": round(float(duration_seconds), 2),
        "youtube": {
            "url": youtube_url,
            "video_id": video_id,
            "published_at": None,
        },
        "paths": {
            "voiceover": _relative_to_run(paths.audio, paths.run_dir),
            "subtitles": _relative_to_run(paths.srt, paths.run_dir),
            "raw_video": _relative_to_run(paths.raw_video, paths.run_dir),
            "final_video": _relative_to_run(paths.final_video, paths.run_dir),
            "clips": _list_existing_relative_paths(clips, paths.run_dir),
            "normalized_clips": _list_existing_relative_paths(normalized_clips, paths.run_dir),
        },
        "files_exist": {
            "voiceover": paths.audio.exists(),
            "subtitles": paths.srt.exists(),
            "raw_video": paths.raw_video.exists(),
            "final_video": paths.final_video.exists(),
            "manifest": paths.manifest.exists(),
        },
    }


def write_run_manifest(
    *,
    paths: ArtifactPaths,
    topic: str,
    theme: str,
    pillar: str | None = None,
    hook_type: str | None = None,
    fact_summary: str,
    hook_angle: str,
    keywords: list[str],
    status: str,
    script_text: str,
    duration_seconds: float,
    youtube_url: str | None = None,
    video_id: str | None = None,
) -> Path:
    manifest = build_run_manifest(
        paths=paths,
        topic=topic,
        theme=theme,
        pillar=pillar,
        hook_type=hook_type,
        fact_summary=fact_summary,
        hook_angle=hook_angle,
        keywords=keywords,
        status=status,
        script_text=script_text,
        duration_seconds=duration_seconds,
        youtube_url=youtube_url,
        video_id=video_id,
    )
    manifest["files_exist"]["manifest"] = True
    paths.manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return paths.manifest


def update_run_manifest(
    manifest_path: str | Path,
    *,
    status: str | None = None,
    youtube_url: str | None = None,
    video_id: str | None = None,
    published_at: str | None = None,
) -> Path:
    resolved = Path(manifest_path)
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if status is not None:
        data["status"] = status
    youtube = data.setdefault("youtube", {})
    if youtube_url is not None:
        youtube["url"] = youtube_url
    if video_id is not None:
        youtube["video_id"] = video_id
    if published_at is not None:
        youtube["published_at"] = published_at
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    data.setdefault("files_exist", {})["manifest"] = True
    resolved.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return resolved
