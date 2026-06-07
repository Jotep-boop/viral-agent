"""video.py — Fetch Pexels footage and assemble with audio via ffmpeg."""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path

import requests

import config

logger = logging.getLogger(__name__)

PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"

def _ffmpeg_bin(name: str = "ffmpeg") -> str:
    """Return full path to ffmpeg/ffprobe, checking common locations."""
    import shutil
    path = shutil.which(name)
    if path:
        return path
    candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "WindowsTemp_e2769c81" / f"{name}.exe"
    if candidate.exists():
        return str(candidate)
    return name


# ── Pexels footage ────────────────────────────────────────────────────────────

def fetch_footage(keywords: list[str], max_clips: int = 6) -> list[Path]:
    """Download stock video clips from Pexels matching *keywords*."""
    query = " ".join(keywords[:3])
    headers = {"Authorization": config.PEXELS_API_KEY}
    params = {
        "query": query,
        "per_page": max_clips,
        "orientation": "portrait",
        "size": "medium",
    }
    logger.info("Searching Pexels for: %s", query)
    resp = requests.get(PEXELS_VIDEO_URL, headers=headers, params=params, timeout=15)
    resp.raise_for_status()
    videos = resp.json().get("videos", [])

    if not videos:
        raise RuntimeError(f"No Pexels footage found for query: {query!r}")

    paths: list[Path] = []
    for i, video in enumerate(videos[:max_clips]):
        # Pick highest-quality portrait file
        files = sorted(
            [f for f in video["video_files"] if f.get("width", 0) <= 1080],
            key=lambda f: f.get("width", 0),
            reverse=True,
        )
        if not files:
            continue
        url = files[0]["link"]
        dest = config.OUTPUT_DIR / "clips" / f"clip_{i:02d}.mp4"
        _download_file(url, dest)
        paths.append(dest)

    logger.info("Downloaded %d clip(s).", len(paths))
    return paths


def _download_file(url: str, dest: Path) -> None:
    logger.debug("Downloading %s → %s", url, dest)
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)


# ── ffmpeg assembly ───────────────────────────────────────────────────────────

def assemble_video(clips: list[Path], audio: Path, out_name: str = "raw.mp4") -> Path:
    """Concatenate *clips* (looping if needed) and mix in *audio*."""
    out_path = config.OUTPUT_DIR / "videos" / out_name

    # Get audio duration
    audio_duration = _probe_duration(audio)
    logger.info("Audio duration: %.2f s", audio_duration)

    # Re-encode each clip to uniform portrait 1080×1920 @ 30fps
    normalised: list[Path] = []
    for i, clip in enumerate(clips):
        norm = config.OUTPUT_DIR / "clips" / f"norm_{i:02d}.mp4"
        _reencode_clip(clip, norm)
        normalised.append(norm)

    # Loop clips until we have enough footage
    looped = _loop_clips(normalised, audio_duration)

    # Write concat list
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        for p in looped:
            f.write(f"file '{p.resolve()}'\n")
        concat_list = Path(f.name)

    # Concat + add audio
    cmd = [
        _ffmpeg_bin(), "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-i", str(audio),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",
        str(out_path),
    ]
    _run(cmd)
    concat_list.unlink(missing_ok=True)
    logger.info("Raw video: %s", out_path)
    return out_path


def _reencode_clip(src: Path, dst: Path) -> None:
    w, h = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
    scale_crop = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h}"
    )
    cmd = [
        _ffmpeg_bin(), "-y", "-i", str(src),
        "-vf", scale_crop,
        "-r", "30",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-an",
        str(dst),
    ]
    _run(cmd)


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            _ffmpeg_bin(), "-i", str(path),
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    import re
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", result.stderr)
    if not match:
        raise RuntimeError(f"Could not determine duration of {path}")
    h, m, s, cs = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100


def _loop_clips(clips: list[Path], target_duration: float) -> list[Path]:
    """Return a list of clip paths whose total duration ≥ target_duration."""
    durations = [_probe_duration(c) for c in clips]
    total = sum(durations)
    if total >= target_duration:
        return clips
    looped: list[Path] = []
    acc = 0.0
    idx = 0
    while acc < target_duration:
        looped.append(clips[idx % len(clips)])
        acc += durations[idx % len(clips)]
        idx += 1
    return looped


def _run(cmd: list[str]) -> None:
    logger.debug("ffmpeg: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error:\n{result.stderr[-2000:]}")
