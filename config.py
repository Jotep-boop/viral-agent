"""config.py — Load and validate all environment variables."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── API keys ──────────────────────────────────────────────────────────────────
OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL: str = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")
ELEVENLABS_API_KEY: str = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID: str = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
PEXELS_API_KEY: str = os.environ.get("PEXELS_API_KEY", "")
YOUTUBE_CLIENT_SECRETS: str = os.environ.get("YOUTUBE_CLIENT_SECRETS", "client_secrets.json")

# ── Pipeline settings ─────────────────────────────────────────────────────────
OUTPUT_DIR: Path = Path(os.environ.get("OUTPUT_DIR", "output"))
VIDEO_WIDTH: int = int(os.environ.get("VIDEO_WIDTH", 1080))
VIDEO_HEIGHT: int = int(os.environ.get("VIDEO_HEIGHT", 1920))
MAX_VIDEO_DURATION: int = int(os.environ.get("MAX_VIDEO_DURATION", 60))
WHISPER_MODEL: str = os.environ.get("WHISPER_MODEL", "base")

# ── Auto-create output dirs ───────────────────────────────────────────────────
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "audio").mkdir(exist_ok=True)
(OUTPUT_DIR / "clips").mkdir(exist_ok=True)
(OUTPUT_DIR / "videos").mkdir(exist_ok=True)


def validate_config(skip_youtube: bool = False) -> None:
    """Raise ValueError if required keys are missing."""
    required = {
        "OPENROUTER_API_KEY": OPENROUTER_API_KEY,
        "ELEVENLABS_API_KEY": ELEVENLABS_API_KEY,
        "PEXELS_API_KEY": PEXELS_API_KEY,
    }
    if not skip_youtube:
        required["YOUTUBE_CLIENT_SECRETS (file must exist)"] = (
            YOUTUBE_CLIENT_SECRETS if Path(YOUTUBE_CLIENT_SECRETS).exists() else ""
        )
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise ValueError(
            f"Missing required config: {', '.join(missing)}\n"
            "Copy .env.example → .env and fill in your keys."
        )
