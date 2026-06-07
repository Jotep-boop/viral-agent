"""main.py — Viral video pipeline orchestrator.

Usage:
    python main.py                          # full run (trending topic)
    python main.py --topic "black holes"   # custom topic
    python main.py --dry-run               # skip YouTube upload
    python main.py --topic "X" --dry-run
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

# ── Logging setup (must happen before importing pipeline modules) ──────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("output/pipeline.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def _run_stage(name: str, fn, *args, **kwargs):
    """Run a pipeline stage, log timing, re-raise on failure."""
    logger.info("▶ Stage: %s", name)
    t0 = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
        elapsed = time.perf_counter() - t0
        logger.info("✓ %s done in %.1fs", name, elapsed)
        return result
    except Exception:
        logger.exception("✗ %s FAILED", name)
        raise


def run_pipeline(topic: str | None, dry_run: bool) -> None:
    import config
    config.validate_config(skip_youtube=dry_run)

    from idea import get_trending_topic, generate_script
    from voice import text_to_speech
    from video import fetch_footage, assemble_video
    from captions import add_captions
    if not dry_run:
        from publish import upload_to_youtube

    # 1. Topic + script
    if not topic:
        topic = _run_stage("Get trending topic", get_trending_topic)
    script = _run_stage("Generate script", generate_script, topic)

    logger.info("Script preview:\n%s", script.full_script[:200])

    # 2. Text → speech
    audio: Path = _run_stage("Text-to-speech", text_to_speech, script.full_script)

    # 3. Stock footage + assembly
    clips: list[Path] = _run_stage("Fetch footage", fetch_footage, script.keywords)
    raw_video: Path = _run_stage("Assemble video", assemble_video, clips, audio)

    # 4. Captions
    final_video: Path = _run_stage("Add captions", add_captions, raw_video, audio,
                                    script_text=script.full_script)

    # 5. Publish (skipped in dry-run)
    if dry_run:
        logger.info("🏁 DRY RUN complete. Final video: %s", final_video)
        print(f"\nDry run complete!\nVideo saved to: {final_video.resolve()}")
    else:
        url: str = _run_stage(
            "Upload to YouTube",
            upload_to_youtube,
            final_video,
            title=script.topic,
            description=script.full_script,
            tags=script.keywords,
        )
        logger.info("🏁 Pipeline complete! %s", url)
        print(f"\nDone! Video live at: {url}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Viral video pipeline")
    parser.add_argument("--topic", type=str, default=None,
                        help="Custom topic (default: auto-detect trending)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run all stages except YouTube upload")
    args = parser.parse_args()

    run_pipeline(topic=args.topic, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
