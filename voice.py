"""voice.py — Convert script text to MP3 via ElevenLabs."""
from __future__ import annotations

import logging
from pathlib import Path

from elevenlabs.client import ElevenLabs  # type: ignore

import config

logger = logging.getLogger(__name__)


def text_to_speech(text: str, filename: str = "voiceover.mp3", output_path: Path | None = None) -> Path:
    """Generate speech audio from *text* and save to a target mp3 path."""
    out_path = output_path or (config.OUTPUT_DIR / "audio" / filename)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)

    logger.info("Generating TTS for %d characters...", len(text))

    audio_stream = client.text_to_speech.convert(
        voice_id=config.ELEVENLABS_VOICE_ID,
        text=text,
        model_id="eleven_multilingual_v2",
        output_format="mp3_44100_128",
    )

    with open(out_path, "wb") as f:
        for chunk in audio_stream:
            if chunk:
                f.write(chunk)

    logger.info("Audio saved: %s (%.1f KB)", out_path, out_path.stat().st_size / 1024)
    return out_path
