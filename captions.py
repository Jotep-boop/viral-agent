"""captions.py — Transcribe audio with Whisper and burn captions into video."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import config

logger = logging.getLogger(__name__)


def add_captions(video: Path, audio: Path, out_name: str = "final.mp4") -> Path:
    """Burn word-level captions into *video* using Whisper transcription."""
    out_path = config.OUTPUT_DIR / "videos" / out_name

    logger.info("Transcribing audio with Whisper (%s)...", config.WHISPER_MODEL)
    srt_path = _transcribe(audio)

    logger.info("Burning captions into video...")
    _burn_captions(video, srt_path, out_path)

    logger.info("Final video with captions: %s", out_path)
    return out_path


def _transcribe(audio: Path) -> Path:
    """Run Whisper and return the path to the generated .srt file."""
    import whisper  # type: ignore  # loaded lazily (large import)

    model = whisper.load_model(config.WHISPER_MODEL)
    result = model.transcribe(str(audio), word_timestamps=True)

    srt_path = audio.with_suffix(".srt")
    _write_srt(result["segments"], srt_path)
    return srt_path


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
        "ffmpeg", "-y",
        "-i", str(video),
        "-vf", subtitle_filter,
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Caption burn failed:\n{result.stderr[-2000:]}")
