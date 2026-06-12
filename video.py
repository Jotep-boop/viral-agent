"""video.py — Fetch stock footage or AI footage and assemble with audio via ffmpeg."""
from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

import requests

import config

logger = logging.getLogger(__name__)

PEXELS_VIDEO_URL = "https://api.pexels.com/videos/search"


def _select_pexels_file(video: dict) -> str | None:
    files = sorted(
        [item for item in video["video_files"] if item.get("width", 0) <= 1080],
        key=lambda item: item.get("width", 0),
        reverse=True,
    )
    if not files:
        return None
    return files[0]["link"]


def _search_pexels_videos(query: str, max_results: int = 1) -> list[dict]:
    headers = {"Authorization": config.PEXELS_API_KEY}
    params = {
        "query": query,
        "per_page": max_results,
        "orientation": "portrait",
        "size": "medium",
    }
    logger.info("Searching Pexels for: %s", query)
    response = requests.get(PEXELS_VIDEO_URL, headers=headers, params=params, timeout=15)
    response.raise_for_status()
    return response.json().get("videos", [])


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

def fetch_footage(
    keywords: list[str],
    max_clips: int = 6,
    clip_name_prefix: str = "",
    clips_dir: Path | None = None,
) -> list[Path]:
    """Download stock video clips from Pexels matching *keywords*."""
    query = " ".join(keywords[:3])
    videos = _search_pexels_videos(query, max_results=max_clips)

    if not videos:
        raise RuntimeError(f"No Pexels footage found for query: {query!r}")

    output_clips_dir = clips_dir or (config.OUTPUT_DIR / "clips")
    output_clips_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for index, video in enumerate(videos[:max_clips]):
        url = _select_pexels_file(video)
        if not url:
            continue
        filename = f"{clip_name_prefix}clip_{index:02d}.mp4" if clip_name_prefix else f"clip_{index:02d}.mp4"
        destination = output_clips_dir / filename
        _download_file(url, destination)
        paths.append(destination)

    logger.info("Downloaded %d clip(s).", len(paths))
    return paths


def _download_file(url: str, dest: Path) -> None:
    logger.debug("Downloading %s → %s", url, dest)
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with open(dest, "wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 20):
                handle.write(chunk)


def fetch_footage_for_beats(
    beats: list[dict],
    fallback_keywords: list[str] | None = None,
    clip_name_prefix: str = "",
    clips_dir: Path | None = None,
) -> list[Path]:
    """Download one stock clip per beat so video content follows the narration order."""
    if not beats:
        raise RuntimeError("No beat metadata provided for stock footage")

    output_clips_dir = clips_dir or (config.OUTPUT_DIR / "clips")
    output_clips_dir.mkdir(parents=True, exist_ok=True)

    fallback_query = " ".join((fallback_keywords or [])[:3]).strip()
    paths: list[Path] = []

    for index, beat in enumerate(beats):
        queries = []
        for candidate in [beat.get("query"), beat.get("stock_query"), beat.get("prompt"), fallback_query]:
            text = str(candidate or "").strip()
            if text and text not in queries:
                queries.append(text)

        video_url: str | None = None
        for query in queries:
            videos = _search_pexels_videos(query, max_results=1)
            if not videos:
                continue
            video_url = _select_pexels_file(videos[0])
            if video_url:
                break

        if not video_url:
            raise RuntimeError(f"No Pexels footage found for beat {index}: {queries}")

        filename = f"{clip_name_prefix}clip_{index:02d}.mp4" if clip_name_prefix else f"clip_{index:02d}.mp4"
        destination = output_clips_dir / filename
        _download_file(video_url, destination)
        paths.append(destination)

    logger.info("Downloaded %d beat-aligned clip(s).", len(paths))
    return paths


# ── fal.ai AI footage ─────────────────────────────────────────────────────────

def generate_footage_ai(
    clips: list[dict],
    clip_name_prefix: str = "",
    clips_dir: Path | None = None,
) -> list[Path]:
    """Generate AI footage via image-first flow, with t2v fallback if needed."""
    if not config.FAL_KEY:
        raise RuntimeError("FAL_KEY not configured")
    if not clips:
        raise RuntimeError("No AI clip prompts were provided")

    output_clips_dir = clips_dir or (config.OUTPUT_DIR / "clips")
    output_clips_dir.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("FAL_KEY", config.FAL_KEY)
    try:
        return _generate_footage_image_first(
            clips,
            clip_name_prefix=clip_name_prefix,
            clips_dir=output_clips_dir,
        )
    except Exception as exc:
        logger.warning("Image-first fal.ai pipeline failed (%s) — falling back to text-to-video.", exc)
        return _generate_footage_text_to_video(
            clips,
            clip_name_prefix=clip_name_prefix,
            clips_dir=output_clips_dir,
        )


def _normalize_fal_duration(value: str | int | float | None) -> str:
    """fal.ai Kling currently only accepts clip durations of 5 or 10 seconds."""
    try:
        seconds = int(value) if value is not None else 5
    except (TypeError, ValueError):
        seconds = 5
    normalized = "5" if seconds <= 7 else "10"
    if str(seconds) != normalized:
        logger.info("Adjusted unsupported AI clip duration %s → %s for fal.ai", seconds, normalized)
    return normalized


def _fal_subscribe(model: str, arguments: dict) -> dict:
    import fal_client  # type: ignore

    return fal_client.subscribe(
        model,
        arguments=arguments,
        start_timeout=config.FAL_START_TIMEOUT,
        client_timeout=config.FAL_CLIENT_TIMEOUT,
    )


def _generate_still(index: int, clip: dict) -> tuple[int, dict, str]:
    prompt = str(clip["prompt"]).strip()
    logger.info("Generating still %d: %s", index, prompt[:120])
    result = _fal_subscribe(
        config.FALAI_IMAGE_MODEL,
        {
            "prompt": prompt,
            "image_size": "portrait_4_3",
            "num_images": 1,
            "enable_safety_checker": False,
        },
    )
    image_url = result["images"][0]["url"]
    logger.info("Still %d ready → %s", index, image_url[:80])
    return index, clip, image_url


def _review_still(clip: dict, image_url: str) -> bool:
    """Use the vision-capable LLM as a soft filter for clearly off-topic stills."""
    try:
        from openai import OpenAI

        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=config.OPENROUTER_API_KEY,
        )
        prompt_text = str(clip.get("prompt", "")).strip()
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
        raw_answer = response.choices[0].message.content or ""
        answer = raw_answer.strip().upper()
        ok = answer.startswith("YES")
        if not ok:
            logger.warning("Still rejected by vision review: %s", answer[:120])
        return ok
    except Exception as exc:
        logger.warning("Vision review failed (%s) — accepting still.", exc)
        return True


def _generate_footage_image_first(
    clips: list[dict],
    *,
    clip_name_prefix: str = "",
    clips_dir: Path | None = None,
) -> list[Path]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    output_clips_dir = clips_dir or (config.OUTPUT_DIR / "clips")
    output_clips_dir.mkdir(parents=True, exist_ok=True)

    stills: dict[int, tuple[dict, str]] = {}
    with ThreadPoolExecutor(max_workers=min(3, len(clips))) as pool:
        futures = {pool.submit(_generate_still, index, clip): index for index, clip in enumerate(clips)}
        for future in as_completed(futures):
            index, clip, image_url = future.result()
            stills[index] = (clip, image_url)

    for index in sorted(stills):
        clip, image_url = stills[index]
        if _review_still(clip, image_url):
            continue
        logger.info("Regenerating still %d after review rejection.", index)
        try:
            _, clip, image_url = _generate_still(index, clip)
            stills[index] = (clip, image_url)
        except Exception as exc:
            logger.warning("Still regeneration failed for clip %d (%s) — using first still.", index, exc)

    def _animate(index: int, clip: dict, image_url: str) -> Path:
        filename = f"{clip_name_prefix}ai_clip_{index:02d}.mp4" if clip_name_prefix else f"ai_clip_{index:02d}.mp4"
        destination = output_clips_dir / filename
        duration = _normalize_fal_duration(clip.get("duration", 5))
        prompt = str(clip["prompt"]).strip()
        logger.info("Animating still %d (%ss): %s", index, duration, prompt[:120])
        result = _fal_subscribe(
            config.FALAI_I2V_MODEL,
            {
                "image_url": image_url,
                "prompt": prompt,
                "duration": duration,
                "aspect_ratio": "9:16",
            },
        )
        video_url = result["video"]["url"]
        _download_file(video_url, destination)
        logger.info("AI clip %d done → %s", index, destination.name)
        return destination

    paths: dict[int, Path] = {}
    with ThreadPoolExecutor(max_workers=min(3, len(clips))) as pool:
        futures = {
            pool.submit(_animate, index, clip, image_url): index
            for index, (clip, image_url) in stills.items()
        }
        for future in as_completed(futures):
            paths[futures[future]] = future.result()

    ordered = [paths[index] for index in sorted(paths)]
    logger.info("Generated %d AI clip(s) via image-first pipeline.", len(ordered))
    return ordered


def _generate_footage_text_to_video(
    clips: list[dict],
    *,
    clip_name_prefix: str = "",
    clips_dir: Path | None = None,
) -> list[Path]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    output_clips_dir = clips_dir or (config.OUTPUT_DIR / "clips")
    output_clips_dir.mkdir(parents=True, exist_ok=True)

    def _generate(index: int, clip: dict) -> Path:
        filename = f"{clip_name_prefix}ai_clip_{index:02d}.mp4" if clip_name_prefix else f"ai_clip_{index:02d}.mp4"
        destination = output_clips_dir / filename
        prompt = str(clip["prompt"]).strip()
        duration = _normalize_fal_duration(clip.get("duration", 5))
        logger.info("Generating t2v clip %d (%ss): %s", index, duration, prompt[:120])
        result = _fal_subscribe(
            config.FALAI_MODEL,
            {"prompt": prompt, "duration": duration, "aspect_ratio": "9:16"},
        )
        video_url = result["video"]["url"]
        _download_file(video_url, destination)
        logger.info("AI clip %d done → %s", index, destination.name)
        return destination

    paths: dict[int, Path] = {}
    with ThreadPoolExecutor(max_workers=min(3, len(clips))) as pool:
        futures = {pool.submit(_generate, index, clip): index for index, clip in enumerate(clips)}
        for future in as_completed(futures):
            paths[futures[future]] = future.result()

    ordered = [paths[index] for index in sorted(paths)]
    logger.info("Generated %d AI clip(s) via text-to-video fallback.", len(ordered))
    return ordered


def should_prefer_natural_audio(*texts: str) -> bool:
    """Return True when real source audio is part of the hook."""
    haystack = " ".join(texts).lower().strip()
    if not haystack:
        return False

    sound_terms = [
        r"\blyrebird\b",
        r"\bmimic\w*\b",
        r"\bcopy\w*\b",
        r"\bsound\w*\b",
        r"\bcall\w*\b",
        r"\bsing\w*\b",
        r"\bsong\w*\b",
        r"\bvoice\w*\b",
        r"\bchainsaw\w*\b",
        r"\bcamera shutter\b",
        r"\bcar alarm\w*\b",
    ]
    return any(re.search(pattern, haystack) for pattern in sound_terms)


def overlay_natural_audio_sample(
    video: Path,
    sample_clip: Path,
    *,
    sample_duration: float = 2.6,
    sample_volume: float = 0.9,
    output_path: Path | None = None,
) -> Path:
    """Mix a short excerpt of original clip audio under the opening narration."""
    out_path = output_path or video.with_name(f"{video.stem}_natural_audio{video.suffix}")

    if not _has_audio_stream(sample_clip):
        logger.info("Skipping natural audio overlay; clip has no audio stream: %s", sample_clip)
        return video

    command = [
        _ffmpeg_bin(),
        "-y",
        "-i",
        str(video),
        "-i",
        str(sample_clip),
        "-filter_complex",
        (
            f"[1:a]atrim=0:{sample_duration:.3f},asetpts=PTS-STARTPTS,volume={sample_volume}[nat];"
            "[0:a][nat]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        ),
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(out_path),
    ]
    _run(command)
    logger.info(
        "Natural audio sample mixed from %s into %s (%.1fs).",
        sample_clip.name,
        out_path,
        sample_duration,
    )
    return out_path


# ── ffmpeg assembly ───────────────────────────────────────────────────────────

def assemble_video(
    clips: list[Path],
    audio: Path,
    out_name: str = "raw.mp4",
    normalized_name_prefix: str = "",
    videos_dir: Path | None = None,
    normalized_clips_dir: Path | None = None,
    segment_texts: list[str] | None = None,
) -> Path:
    """Concatenate *clips* and mix in *audio*.

    When *segment_texts* is provided with the same length as *clips*, each clip is
    stretched/trimmed to an estimated narration duration for that beat instead of
    blindly looping the whole set.
    """
    output_videos_dir = videos_dir or (config.OUTPUT_DIR / "videos")
    output_videos_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_videos_dir / out_name

    audio_duration = _probe_duration(audio)
    logger.info("Audio duration: %.2f s", audio_duration)

    output_normalized_dir = normalized_clips_dir or (config.OUTPUT_DIR / "clips")
    output_normalized_dir.mkdir(parents=True, exist_ok=True)
    normalized: list[Path] = []
    use_segment_timing = bool(segment_texts) and len(segment_texts or []) == len(clips)
    target_durations = _estimate_segment_durations(segment_texts, audio_duration) if use_segment_timing else []
    for index, clip in enumerate(clips):
        filename = (
            f"{normalized_name_prefix}norm_{index:02d}.mp4"
            if normalized_name_prefix
            else f"norm_{index:02d}.mp4"
        )
        normalized_path = output_normalized_dir / filename
        if use_segment_timing:
            _render_clip_to_duration(clip, normalized_path, target_durations[index])
        else:
            _reencode_clip(clip, normalized_path)
        normalized.append(normalized_path)

    looped = normalized if use_segment_timing else _loop_clips(normalized, audio_duration)

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
        for path in looped:
            handle.write(f"file '{path.resolve()}'\n")
        concat_list = Path(handle.name)

    command = [
        _ffmpeg_bin(),
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-i",
        str(audio),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-shortest",
        str(out_path),
    ]
    _run(command)
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


def _estimate_segment_durations(segment_texts: list[str] | None, audio_duration: float) -> list[float]:
    if not segment_texts:
        return []
    word_counts = [max(1, len(str(text).split())) for text in segment_texts]
    total_words = sum(word_counts)
    raw = [(count / total_words) * audio_duration for count in word_counts]
    minimum = 1.5
    durations = [max(minimum, value) for value in raw]
    scale = audio_duration / sum(durations)
    return [value * scale for value in durations]


def _render_clip_to_duration(src: Path, dst: Path, duration: float) -> None:
    width, height = config.VIDEO_WIDTH, config.VIDEO_HEIGHT
    scale_crop = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}"
    )
    command = [
        _ffmpeg_bin(),
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(src),
        "-t",
        f"{duration:.3f}",
        "-vf",
        scale_crop,
        "-r",
        "30",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "28",
        "-an",
        str(dst),
    ]
    _run(command)


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [_ffmpeg_bin(), "-i", str(path), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    import re

    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", result.stderr)
    if not match:
        raise RuntimeError(f"Could not determine duration of {path}")
    hours, minutes, seconds, centiseconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(centiseconds) / 100


def _has_audio_stream(path: Path) -> bool:
    result = subprocess.run(
        [
            _ffmpeg_bin("ffprobe"),
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _loop_clips(clips: list[Path], target_duration: float) -> list[Path]:
    """Return a list of clip paths whose total duration ≥ target_duration."""
    durations = [_probe_duration(clip) for clip in clips]
    total = sum(durations)
    if total >= target_duration:
        return clips
    looped: list[Path] = []
    accumulated = 0.0
    index = 0
    while accumulated < target_duration:
        looped.append(clips[index % len(clips)])
        accumulated += durations[index % len(clips)]
        index += 1
    return looped


def _run(cmd: list[str]) -> None:
    logger.debug("ffmpeg: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error:\n{result.stderr[-2000:]}")
