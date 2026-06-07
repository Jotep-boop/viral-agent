"""captions.py — Transcribe audio with Whisper and burn captions into video."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

import config


def _ffmpeg_bin() -> str:
    path = shutil.which("ffmpeg")
    if path:
        return path
    candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "WindowsTemp_e2769c81" / "ffmpeg.exe"
    if candidate.exists():
        return str(candidate)
    return "ffmpeg"

logger = logging.getLogger(__name__)


def add_captions(video: Path, audio: Path, script_text: str = "",
                  out_name: str = "final.mp4") -> Path:
    """Burn captions into *video* using Whisper for timing + script text for accuracy."""
    out_path = config.OUTPUT_DIR / "videos" / out_name

    logger.info("Transcribing audio with Whisper (%s)...", config.WHISPER_MODEL)
    srt_path = _transcribe(audio, script_text)

    logger.info("Burning captions into video...")
    _burn_captions(video, srt_path, out_path)

    logger.info("Final video with captions: %s", out_path)
    return out_path


def _transcribe(audio: Path, script_text: str = "") -> Path:
    """Run Whisper and return the path to the generated .srt file.

    If script_text is provided, uses Whisper only for timing and replaces
    the transcribed text with the original script to avoid misspellings.
    """
    import whisper  # type: ignore  # loaded lazily (large import)

    model = whisper.load_model(config.WHISPER_MODEL)
    result = model.transcribe(
        str(audio),
        word_timestamps=True,
        condition_on_previous_text=False,
    )

    segments = _split_long_segments(result["segments"])
    if script_text:
        segments = _align_script_to_segments(segments, script_text)

    srt_path = audio.with_suffix(".srt")
    _write_srt(segments, srt_path)
    return srt_path


def _split_long_segments(segments: list, max_words: int = 8) -> list:
    """Split segments with word-level timestamps into chunks of max_words."""
    result = []
    for seg in segments:
        words = seg.get("words", [])
        if not words or len(words) <= max_words:
            result.append(seg)
            continue
        for i in range(0, len(words), max_words):
            chunk = words[i:i + max_words]
            result.append({
                "start": chunk[0]["start"],
                "end": chunk[-1]["end"],
                "text": " ".join(w["word"].strip() for w in chunk),
            })
    return result


def _align_script_to_segments(segments: list, script_text: str) -> list:
    """Replace Whisper transcription text with original script, keeping timing."""
    script_words = script_text.split()
    word_idx = 0
    aligned = []
    for seg in segments:
        whisper_word_count = len(seg["text"].strip().split())
        chunk = script_words[word_idx:word_idx + whisper_word_count]
        if chunk:
            aligned.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": " ".join(chunk),
            })
        word_idx += whisper_word_count
    return aligned


def _write_srt(segments: list, out: Path) -> None:
    lines: list[str] = []
    idx = 1
    for seg in segments:
        start = _fmt_time(seg["start"])
        end = _fmt_time(seg["end"])
        text = seg["text"].strip()
        lines.append(f"{idx}\n{start} --> {end}\n{text}\n")
        idx += 1
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.debug("SRT written: %s (%d entries)", out, idx - 1)


def _fmt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _burn_captions(video: Path, srt: Path, out: Path) -> None:
    # ffmpeg requires forward slashes and colon escaping on Windows
    srt_escaped = str(srt.resolve()).replace("\\", "/").replace(":", "\\:")

    subtitle_filter = (
        f"subtitles='{srt_escaped}':force_style='"
        "FontName=Arial,FontSize=14,Bold=1,"
        "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        "Outline=2,Alignment=2,MarginV=40'"
    )

    cmd = [
        _ffmpeg_bin(), "-y",
        "-i", str(video),
        "-vf", subtitle_filter,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Caption burn failed:\n{result.stderr[-2000:]}")
