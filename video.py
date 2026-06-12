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


# ── fal.ai AI footage ─────────────────────────────────────────────────────────

def generate_footage_ai(clips: list[dict]) -> list[Path]:
    """Generate video clips via image-first pipeline: Flux stills → vision review → Kling i2v.

    Falls back to text-to-video if image generation fails.
    Runs up to 3 generations in parallel.
    """
    os.environ.setdefault("FAL_KEY", config.FAL_KEY)
    try:
        return _generate_footage_image_first(clips)
    except Exception as exc:
        logger.warning("Image-first pipeline failed (%s) — falling back to text-to-video.", exc)
        return _generate_footage_text_to_video(clips)


def _generate_still(i: int, clip: dict) -> tuple[int, dict, str]:
    """Generate a single still image via Flux/schnell. Returns (index, clip, image_url)."""
    import fal_client  # type: ignore
    prompt = clip["prompt"]
    logger.info("Generating still %d: %s", i, prompt[:70])
    result = fal_client.subscribe(
        config.FALAI_IMAGE_MODEL,
        arguments={
            "prompt": prompt,
            "image_size": "portrait_4_3",
            "num_images": 1,
            "enable_safety_checker": False,
        },
    )
    image_url = result["images"][0]["url"]
    logger.info("Still %d ready: %s", i, image_url[:60])
    return i, clip, image_url


def _review_still(clip: dict, image_url: str) -> bool:
    """Ask a vision model whether the still matches the intended clip prompt.

    Returns True if the image is acceptable, False if it should be regenerated.
    Uses a conservative threshold — only rejects clearly off-topic images.
    """
    try:
        from openai import OpenAI
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=config.OPENROUTER_API_KEY,
        )
        prompt_text = clip["prompt"]
        response = client.chat.completions.create(
            model=config.OPENROUTER_MODEL,
            max_tokens=100,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": (
                        f"Intended clip: \"{prompt_text}\"\n\n"
                        "Does this image approximately match what the clip intends to show? "
                        "Reply with just YES or NO and one brief reason."
                    )},
                ],
            }],
        )
        answer = response.choices[0].message.content.strip().upper()
        ok = answer.startswith("YES")
        if not ok:
            logger.warning("Still rejected by vision review: %s", answer[:80])
        return ok
    except Exception as exc:
        logger.warning("Vision review failed (%s) — accepting still.", exc)
        return True


def _generate_footage_image_first(clips: list[dict]) -> list[Path]:
    """Generate stills → vision review → animate to video for each clip."""
    import fal_client  # type: ignore
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Step 1: generate stills in parallel
    stills: dict[int, tuple[dict, str]] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_generate_still, i, c): i for i, c in enumerate(clips)}
        for f in as_completed(futures):
            i, clip, image_url = f.result()
            stills[i] = (clip, image_url)

    # Step 2: vision review — regenerate rejected stills once
    for i in sorted(stills):
        clip, image_url = stills[i]
        if not _review_still(clip, image_url):
            logger.info("Regenerating still %d after rejection...", i)
            try:
                _, clip, image_url = _generate_still(i, clip)
                stills[i] = (clip, image_url)
            except Exception as exc:
                logger.warning("Regeneration of still %d failed (%s) — using original.", i, exc)

    # Step 3: animate stills to video in parallel
    video_paths: dict[int, Path] = {}

    def _animate(i: int, clip: dict, image_url: str) -> tuple[int, Path]:
        dest = config.OUTPUT_DIR / "clips" / f"ai_clip_{i:02d}.mp4"
        duration = str(min(int(clip.get("duration", 5)), 10))
        logger.info("Animating still %d (%ss) → video", i, duration)
        result = fal_client.subscribe(
            config.FALAI_I2V_MODEL,
            arguments={
                "image_url": image_url,
                "prompt": clip["prompt"],
                "duration": duration,
                "aspect_ratio": "9:16",
            },
        )
        video_url = result["video"]["url"]
        _download_file(video_url, dest)
        logger.info("Animated clip %d done → %s", i, dest.name)
        return i, dest

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {
            pool.submit(_animate, i, clip, image_url): i
            for i, (clip, image_url) in stills.items()
        }
        for f in as_completed(futures):
            i, path = f.result()
            video_paths[i] = path

    ordered = [video_paths[i] for i in sorted(video_paths)]
    logger.info("Generated %d AI clip(s) via image-first pipeline.", len(ordered))
    return ordered


def _generate_footage_text_to_video(clips: list[dict]) -> list[Path]:
    """Fallback: generate clips directly from text prompts via Kling text-to-video."""
    import fal_client  # type: ignore
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _generate(i: int, clip: dict) -> tuple[int, Path]:
        dest = config.OUTPUT_DIR / "clips" / f"ai_clip_{i:02d}.mp4"
        prompt = clip["prompt"]
        duration = str(min(int(clip.get("duration", 5)), 10))
        logger.info("Generating t2v clip %d (%ss): %s", i, duration, prompt[:70])
        result = fal_client.subscribe(
            config.FALAI_MODEL,
            arguments={"prompt": prompt, "duration": duration, "aspect_ratio": "9:16"},
        )
        video_url = result["video"]["url"]
        _download_file(video_url, dest)
        return i, dest

    paths: dict[int, Path] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(_generate, i, c): i for i, c in enumerate(clips)}
        for f in as_completed(futures):
            i, path = f.result()
            paths[i] = path

    ordered = [paths[i] for i in sorted(paths)]
    logger.info("Generated %d AI clip(s) via text-to-video.", len(ordered))
    return ordered


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

    # Concat + add audio with loudness normalisation (-14 LUFS for Shorts)
    cmd = [
        _ffmpeg_bin(), "-y",
        "-f", "concat", "-safe", "0", "-i", str(concat_list),
        "-i", str(audio),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
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
    # Pre-scale 5% larger so Ken Burns zoom-in has pixel-quality headroom
    ws, hs = int(w * 1.05), int(h * 1.05)
    # Subtle Ken Burns: zoom from 1.0→1.05 over the clip, centered
    vf_ken_burns = (
        f"scale={ws}:{hs}:force_original_aspect_ratio=increase,"
        f"crop={ws}:{hs},"
        f"zoompan=z='min(pzoom+0.0002,1.05)':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2':d=1:s={w}x{h},"
        f"setsar=1"
    )
    vf_plain = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h}"
    )
    cmd = [
        _ffmpeg_bin(), "-y", "-i", str(src),
        "-vf", vf_ken_burns,
        "-r", "30",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-an",
        str(dst),
    ]
    try:
        _run(cmd)
    except RuntimeError:
        logger.warning("Ken Burns failed for %s — retrying without zoom.", src.name)
        _run([
            _ffmpeg_bin(), "-y", "-i", str(src),
            "-vf", vf_plain,
            "-r", "30",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-an",
            str(dst),
        ])


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
