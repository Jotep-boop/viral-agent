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


def _get_audio_duration(audio_path: Path) -> float:
    """Return audio duration in seconds using ffprobe."""
    import subprocess, re as _re
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def _check_quality(script, duration: float) -> tuple[bool, list[str]]:
    """Return (ok, issues) for a script+duration pair."""
    issues = []
    wc = len(script.full_script.split())
    if not 60 <= wc <= 115:
        issues.append(f"word_count {wc} out of range 60-115")
    if not 20 <= duration <= 55:
        issues.append(f"duration {duration:.1f}s out of range 20-55s")
    for phrase in ["look at", "see this", "watch this", "as you can see"]:
        if phrase in script.full_script.lower():
            issues.append(f"visual reference: '{phrase}'")
    # Reject generic openers that bury the payoff
    _generic_openers = [
        "everyone knows", "did you know", "you probably know",
        "as you know", "most people know", "we all know",
    ]
    hook_lower = script.hook.lower()
    for opener in _generic_openers:
        if hook_lower.startswith(opener):
            issues.append(f"generic opener: '{opener}' — payoff must come first")
    return not issues, issues


def _check_clip_prompts(idea, clips: list[dict]) -> tuple[bool, list[str]]:
    """Verify clip prompts before sending to fal.ai — saves money on bad generations."""
    issues = []
    if not clips:
        return True, []

    # First clip should visually show the core claim
    first_prompt = clips[0]["prompt"].lower()
    key_terms = [t for t in idea.angle.lower().split() if len(t) > 4]
    if key_terms and not any(term in first_prompt for term in key_terms):
        issues.append(f"first clip doesn't reference core claim: '{idea.angle[:50]}'")

    # No repeated clip archetypes (e.g. "scientist in lab" × 3)
    bad_patterns = ["scientist", "in a lab", "looking shocked", "holding a", "looking at camera"]
    for pattern in bad_patterns:
        count = sum(1 for c in clips if pattern in c["prompt"].lower())
        if count >= 3:
            issues.append(f"repeated clip archetype '{pattern}' appears {count}×")

    return not issues, issues


def run_pipeline(topic: str | None, dry_run: bool,
                  video_format: str | None = None) -> None:
    import config
    config.validate_config(skip_youtube=dry_run)
    video_format = video_format or config.DEFAULT_FORMAT

    from idea import get_trending_topic, run_idea_tournament, generate_script, generate_metadata
    from voice import text_to_speech
    from video import generate_footage_ai, assemble_video
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

    # 1. Topic → Idea tournament → Script
    if not topic:
        topic = _run_stage("Get trending topic", get_trending_topic,
                           top_performers=top_performers)
    insights = tracker.get_performance_insights()
    idea, _candidates = _run_stage("Idea tournament", run_idea_tournament,
                                    topic, video_format, insights=insights)
    script = _run_stage("Generate script", generate_script, idea)

    logger.info("Script preview:\n%s", script.full_script[:200])

    # Unique tag per run so videos don't overwrite each other
    tag = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 2. Text → speech
    audio: Path = _run_stage("Text-to-speech", text_to_speech, script.full_script)

    # 3. Quality gate (word count, duration, no visual refs) — retry once if bad
    audio_duration = _get_audio_duration(audio)
    ok, issues = _check_quality(script, audio_duration)
    if not ok:
        logger.warning("Quality gate FAILED: %s — retrying script once.", issues)
        script = _run_stage("Generate script (retry)", generate_script, idea)
        audio = _run_stage("Text-to-speech (retry)", text_to_speech, script.full_script)
        audio_duration = _get_audio_duration(audio)
        ok, issues = _check_quality(script, audio_duration)
        if not ok:
            logger.warning("Quality gate still failing after retry: %s — continuing anyway.", issues)

    # 4. Clip-prompt quality gate (before paying for fal.ai)
    if script.clips:
        ok_clips, clip_issues = _check_clip_prompts(idea, script.clips)
        if not ok_clips:
            logger.warning("Clip prompt gate FAILED: %s — retrying script once.", clip_issues)
            script = _run_stage("Generate script (clip retry)", generate_script, idea)
            ok_clips, clip_issues = _check_clip_prompts(idea, script.clips)
            if not ok_clips:
                logger.warning("Clip prompts still failing: %s — continuing anyway.", clip_issues)

    # 5. Footage — AI-generated via fal.ai (required)
    if not config.FAL_KEY:
        raise RuntimeError(
            "FAL_KEY is not set. AI footage generation is required — "
            "add FAL_KEY to your .env file."
        )
    if not script.clips:
        raise RuntimeError(
            "Script contains no clip prompts. "
            "Re-run or check the format prompt for clip generation."
        )
    clips: list[Path] = _run_stage("Generate AI footage", generate_footage_ai, script.clips)
    raw_video: Path = _run_stage("Assemble video", assemble_video, clips, audio,
                                  out_name=f"raw_{tag}.mp4")

    # 6. Captions (with emphasis word highlighting)
    final_video: Path = _run_stage("Add captions", add_captions, raw_video, audio,
                                    script_text=script.full_script,
                                    out_name=f"final_{tag}.mp4",
                                    emphasis_words=script.emphasis_words)

    # 7. Publish (skipped in dry-run)
    if dry_run:
        logger.info("DRY RUN complete. Final video: %s", final_video)
        print(f"\nDry run complete!\nVideo saved to: {final_video.resolve()}")
    else:
        metadata = _run_stage("Generate metadata", generate_metadata, script, idea)
        url: str = _run_stage(
            "Upload to YouTube",
            upload_to_youtube,
            final_video,
            title=metadata.title,
            description=metadata.description,
            tags=script.keywords + metadata.hashtags,
        )
        # Log the run for future feedback-loop scoring
        try:
            from urllib.parse import urlparse, parse_qs
            video_id = parse_qs(urlparse(url).query).get("v", [None])[0]
            if video_id:
                tracker.log_run(
                    topic=script.topic,
                    video_id=video_id,
                    url=url,
                    angle=idea.angle,
                    format=script.format,
                    hook=script.hook,
                    word_count=len(script.full_script.split()),
                    duration=audio_duration,
                )
        except Exception as exc:
            logger.warning("Could not log run to tracker: %s", exc)

        logger.info("Pipeline complete! %s", url)
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
