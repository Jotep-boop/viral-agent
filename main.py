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
from datetime import datetime
from pathlib import Path

# ── Logging setup (must happen before importing pipeline modules) ──────────────
Path("output").mkdir(parents=True, exist_ok=True)
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


def run_pipeline(topic: str | None, dry_run: bool,
                  video_format: str | None = None) -> None:
    import config
    config.validate_config(skip_youtube=dry_run)
    video_format = video_format or config.DEFAULT_FORMAT

    from idea import get_trending_topic, generate_script
    from voice import text_to_speech
    from video import fetch_footage, generate_footage_ai, assemble_video
    from captions import add_captions
    import tracker
    if not dry_run:
        from publish import upload_to_youtube

    # Refresh historical stats and load top performers for scoring
    if not dry_run:
        try:
            _run_stage("Refresh performance stats", tracker.refresh_stats)
        except Exception:
            pass  # non-fatal
    top_performers = tracker.get_top_performers()
    if top_performers:
        logger.info("Top performers loaded: %s", [p["topic"] for p in top_performers])

    # 1. Topic + script
    if not topic:
        topic = _run_stage("Get trending topic", get_trending_topic,
                           top_performers=top_performers)
    script = _run_stage("Generate script", generate_script, topic,
                        format_name=video_format)

    logger.info("Script preview:\n%s", script.full_script[:200])

    # Unique tag per run so videos don't overwrite each other
    tag = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 2. Text → speech
    audio: Path = _run_stage("Text-to-speech", text_to_speech, script.full_script)

    # 3. Footage — AI-generated (fal.ai) when available, else Pexels stock
    if config.FAL_KEY and script.clips:
        clips: list[Path] = _run_stage("Generate AI footage", generate_footage_ai, script.clips)
    else:
        clips = _run_stage("Fetch stock footage", fetch_footage, script.keywords)
    raw_video: Path = _run_stage("Assemble video", assemble_video, clips, audio,
                                  out_name=f"raw_{tag}.mp4")

    # 4. Captions
    final_video: Path = _run_stage("Add captions", add_captions, raw_video, audio,
                                    script_text=script.full_script,
                                    out_name=f"final_{tag}.mp4")

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
        # Log the run for future feedback-loop scoring
        try:
            from urllib.parse import urlparse, parse_qs
            video_id = parse_qs(urlparse(url).query).get("v", [None])[0]
            if video_id:
                tracker.log_run(topic=script.topic, video_id=video_id, url=url)
        except Exception as exc:
            logger.warning("Could not log run to tracker: %s", exc)

        logger.info("🏁 Pipeline complete! %s", url)
        print(f"\nDone! Video live at: {url}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Viral video pipeline")
    parser.add_argument("--topic", type=str, default=None,
                        help="Custom topic (default: auto-detect trending)")
    parser.add_argument("--format", type=str, default=None,
                        help="Video format: informative, top5 (default: informative)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Run all stages except YouTube upload")
    args = parser.parse_args()

    run_pipeline(topic=args.topic, dry_run=args.dry_run, video_format=args.format)


if __name__ == "__main__":
    main()
