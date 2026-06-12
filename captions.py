"""captions.py — Transcribe audio with Whisper and burn karaoke captions into video."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

import config

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 2              # words shown per caption group (fewer = more readable)
_HIGHLIGHT  = "&H0000FFFF&"  # yellow in ASS BGR format (active word)
_EMPHASIS   = "&H000080FF&"  # orange in ASS BGR format (emphasis/keyword word)
_FONT_SIZE  = 72


def _ffmpeg_bin() -> str:
    path = shutil.which("ffmpeg")
    if path:
        return path
    candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "WindowsTemp_e2769c81" / "ffmpeg.exe"
    if candidate.exists():
        return str(candidate)
    return "ffmpeg"


def add_captions(video: Path, audio: Path, script_text: str = "",
                  out_name: str = "final.mp4",
                  emphasis_words: list[str] | None = None,
                  output_path: Path | None = None) -> Path:
    """Burn karaoke-style captions into *video* with per-word colour highlighting.

    Active words are highlighted yellow; words in *emphasis_words* are highlighted
    orange so key terms stand out even more.
    """
    out_path = output_path or (config.OUTPUT_DIR / "videos" / out_name)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info("Transcribing audio with Whisper (%s)...", config.WHISPER_MODEL)
    words = _transcribe_words(audio, script_text)

    ass_path = audio.with_suffix(".ass")
    em_set = {w.lower().strip(".,!?") for w in (emphasis_words or [])}
    _write_ass_karaoke(words, ass_path, emphasis=em_set)

    logger.info("Burning karaoke captions into video...")
    _burn_captions(video, ass_path, out_path)

    logger.info("Final video with captions: %s", out_path)
    return out_path


def _transcribe_words(audio: Path, script_text: str = "") -> list[dict]:
    """Run Whisper and return word-level timestamps, optionally aligned to *script_text*.

    Whisper timing is always kept. If script_text is provided, Whisper's
    (possibly garbled) words are replaced with the original to avoid typos.
    """
    import whisper  # type: ignore

    model = whisper.load_model(config.WHISPER_MODEL)
    result = model.transcribe(
        str(audio),
        word_timestamps=True,
        condition_on_previous_text=False,
    )

    raw: list[dict] = []
    for seg in result["segments"]:
        for word_info in seg.get("words", []):
            word = word_info.get("word", "").strip()
            if not word:
                continue
            start = float(word_info["start"])
            end = max(float(word_info["end"]), start + 0.05)
            raw.append({"word": word, "start": start, "end": end})

    if not script_text or not raw:
        return raw

    script_words = script_text.split()
    aligned: list[dict] = []
    for index, word_info in enumerate(raw):
        if index < len(script_words):
            aligned.append(
                {"word": script_words[index], "start": word_info["start"], "end": word_info["end"]}
            )

    if len(script_words) > len(raw) and raw:
        current_time = raw[-1]["end"]
        for word in script_words[len(raw):]:
            aligned.append({"word": word, "start": current_time, "end": current_time + 0.25})
            current_time += 0.25

    return aligned


def _write_ass_karaoke(words: list[dict], out_path: Path,
                        emphasis: set[str] | None = None) -> None:
    """Generate an ASS subtitle file with karaoke-style per-word colour highlighting.

    Active word → yellow. Active word AND in emphasis set → orange.
    Inactive words → white (style default).
    """
    em = emphasis or set()
    events: list[tuple[float, float, str]] = []

    for chunk_start in range(0, len(words), _CHUNK_SIZE):
        chunk = words[chunk_start:chunk_start + _CHUNK_SIZE]
        for active_index, active_word in enumerate(chunk):
            parts = []
            for j, w in enumerate(chunk):
                if j == active_index:
                    colour = _EMPHASIS if w["word"].lower().strip(".,!?") in em else _HIGHLIGHT
                    parts.append(f"{{\\c{colour}\\b1}}{w['word']}{{\\r}}")
                else:
                    parts.append(w["word"])
            events.append((active_word["start"], active_word["end"], " ".join(parts)))

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {config.VIDEO_WIDTH}\n"
        f"PlayResY: {config.VIDEO_HEIGHT}\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Arial,{_FONT_SIZE},&H00FFFFFF,&H000000FF,"
        f"&H00000000,&H80000000,0,0,0,0,100,100,2,0,1,4,3,2,40,40,{int(config.VIDEO_HEIGHT * 0.28)},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines = [header]
    for start, end, text in events:
        lines.append(
            f"Dialogue: 0,{_fmt_ass_time(start)},{_fmt_ass_time(end)},"
            f"Default,,0,0,0,,{text}"
        )

    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.debug("ASS karaoke written: %s (%d events)", out_path, len(events))


def _burn_captions(video: Path, ass: Path, out: Path) -> None:
    ass_escaped = str(ass.resolve()).replace("\\", "/").replace(":", "\\:")
    cmd = [
        _ffmpeg_bin(), "-y",
        "-i", str(video),
        "-vf", f"ass='{ass_escaped}'",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "copy",
        str(out),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Caption burn failed:\n{result.stderr[-2000:]}")


def _fmt_ass_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    whole_seconds = seconds % 60
    centiseconds = int((whole_seconds % 1) * 100)
    return f"{hours}:{minutes:02d}:{int(whole_seconds):02d}.{centiseconds:02d}"
