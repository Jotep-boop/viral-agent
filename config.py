"""config.py — Load and validate all environment variables."""
import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Ensure ffmpeg is on PATH ─────────────────────────────────────────────────
if not shutil.which("ffmpeg"):
    _ffmpeg_candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "WindowsTemp_e2769c81"
    if (_ffmpeg_candidate / "ffmpeg.exe").exists():
        os.environ["PATH"] = str(_ffmpeg_candidate) + os.pathsep + os.environ.get("PATH", "")

# ── API keys ──────────────────────────────────────────────────────────────────
OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL: str = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4")
ELEVENLABS_API_KEY: str = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID: str = os.environ.get("ELEVENLABS_VOICE_ID", "CwhRBWXzGAHq8TQ4Fs17")
PEXELS_API_KEY: str = os.environ.get("PEXELS_API_KEY", "")
YOUTUBE_CLIENT_SECRETS: str = os.environ.get("YOUTUBE_CLIENT_SECRETS", "client_secrets.json")
YOUTUBE_API_KEY: str = os.environ.get("YOUTUBE_API_KEY", "")
FAL_KEY: str = os.environ.get("FAL_KEY", "")
FALAI_MODEL: str = os.environ.get("FALAI_MODEL", "fal-ai/kling-video/v1.6/standard/text-to-video")
DEFAULT_FORMAT: str = os.environ.get("DEFAULT_FORMAT", "informative")

# ── Channel niche ─────────────────────────────────────────────────────────────
NICHE: str = "everyday materials and objects with impossible-sounding properties"
NICHE_DESCRIPTION: str = (
    "everyday materials, substances, and objects (concrete, metal, glass, sound, water, light, ice) "
    "that have secretly extreme or impossible-sounding properties. "
    "Winning pattern: familiar object + behavior that sounds impossible or alive "
    "(heals itself, remembers shape, flows like liquid, creates plasma). "
    "Hook style: 'this sounds fake but it's real' or 'this material is basically alive'. "
    "Avoid: broad animal facts, general space facts, nature lists, unsolved mysteries without a physical object."
)
NICHE_FORMATS: list[str] = ["informative", "scary", "mythbuster"]

# ── fal.ai model overrides ────────────────────────────────────────────────────
FALAI_IMAGE_MODEL: str = os.environ.get("FALAI_IMAGE_MODEL", "fal-ai/flux/schnell")
FALAI_I2V_MODEL: str = os.environ.get("FALAI_I2V_MODEL", "fal-ai/kling-video/v1.6/standard/image-to-video")

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
        "FAL_KEY": FAL_KEY,
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
