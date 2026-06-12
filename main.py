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

MIN_SCRIPT_WORDS = 45
MAX_SCRIPT_WORDS = 90
IDEAL_SCRIPT_WORDS = 72
MIN_VIDEO_DURATION = 18.0
MAX_VIDEO_DURATION = 38.0


def _run_stage(name: str, fn, *args, **kwargs):
    """Run a pipeline stage, log timing, re-raise on failure."""
    logger.info("▶ Stage: %s", name)
    started = time.perf_counter()
    try:
        result = fn(*args, **kwargs)
        elapsed = time.perf_counter() - started
        logger.info("✓ %s done in %.1fs", name, elapsed)
        return result
    except Exception:
        logger.exception("✗ %s FAILED", name)
        raise


def _get_audio_duration(audio_path: Path) -> float:
    """Return audio duration in seconds using ffprobe."""
    import subprocess

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def _check_quality(script, duration: float) -> tuple[bool, list[str]]:
    """Return (ok, issues) for a script+duration pair."""
    issues = []
    word_count = len(script.full_script.split())
    if not MIN_SCRIPT_WORDS <= word_count <= MAX_SCRIPT_WORDS:
        issues.append(
            f"word_count {word_count} out of range {MIN_SCRIPT_WORDS}-{MAX_SCRIPT_WORDS}"
        )
    if not MIN_VIDEO_DURATION <= duration <= MAX_VIDEO_DURATION:
        issues.append(
            f"duration {duration:.1f}s out of range {MIN_VIDEO_DURATION:.0f}-{MAX_VIDEO_DURATION:.0f}s"
        )
    for phrase in ["look at", "see this", "watch this", "as you can see"]:
        if phrase in script.full_script.lower():
            issues.append(f"visual reference: '{phrase}'")
    # Reject hooks that don't start in-medias-res
    _generic_openers = [
        # Too academic / educational
        "everyone knows", "did you know", "you probably know",
        "as you know", "most people know", "we all know",
        "scientists have", "research shows", "studies show", "science says",
        "according to", "researchers found", "a new study",
        # Filler intros
        "today we", "today i", "in this video", "in today", "welcome",
        "hello", "hi everyone", "what's up", "hey everyone",
        "let me tell you", "let me show you", "let's talk about",
        "have you ever wondered", "have you ever heard",
        # Weak setups
        "you might think", "you might have heard", "many people think",
        "it might seem", "it may seem",
    ]
    hook_lower = script.hook.lower()
    for opener in _generic_openers:
        if hook_lower.startswith(opener):
            issues.append(f"weak hook opener: '{opener}' — hook must open in-medias-res")
    return not issues, issues


def _extract_frames(video_path: Path, count: int = 3) -> list[str]:
    """Extract evenly-spaced frames and return them as base64-encoded JPEG strings."""
    import base64, tempfile, subprocess as _sp
    probe = _sp.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True,
    )
    try:
        duration = float(probe.stdout.strip())
    except ValueError:
        duration = 30.0
    frames = []
    with tempfile.TemporaryDirectory() as tmp:
        for idx in range(count):
            t = duration * (idx + 1) / (count + 1)
            out = Path(tmp) / f"frame_{idx}.jpg"
            _sp.run(
                ["ffmpeg", "-y", "-ss", f"{t:.2f}", "-i", str(video_path),
                 "-frames:v", "1", "-q:v", "5", str(out)],
                capture_output=True,
            )
            if out.exists():
                frames.append(base64.b64encode(out.read_bytes()).decode())
    return frames


def _frame_review_is_hard_fail(issues: list[str]) -> bool:
    """Return True only for quality issues that should block upload outright."""
    if not issues:
        return False

    hard_fail_terms = [
        "mirrored", "mirror-imaged", "backwards ui text", "backward ui text",
        "upside-down", "upside down", "sideways", "warped", "physically wrong",
        "impossible keyboard", "impossible keyboards", "bent screen", "bent screens",
        "broken hand", "broken hands", "unreadable", "corrupted", "solid black",
        "black frame", "black screen", "broken device", "artifact",
    ]
    combined = " ".join(issue.lower() for issue in issues)
    return any(term in combined for term in hard_fail_terms)


def _review_frames(frames: list[str], script) -> tuple[bool, list[str]]:
    """Send extracted frames to a vision model to verify the video looks acceptable."""
    if not frames:
        return True, []
    try:
        from openai import OpenAI
        import config as _cfg
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=_cfg.OPENROUTER_API_KEY,
        )
        content: list[dict] = []
        for b64 in frames:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
        content.append({
            "type": "text",
            "text": (
                f"Script topic: {script.topic}\nScript hook: {script.hook}\n\n"
                "These are frames from a YouTube Shorts science video. Check carefully:\n"
                "1. Do the visuals relate to the science topic?\n"
                "2. Is there anything obviously broken (solid black, corrupted, completely off-topic)?\n"
                "3. Are any screens, monitors, phones, dashboards, code editors, or text-based interfaces mirrored, upside-down, sideways, warped, or otherwise physically wrong?\n"
                "4. Are there obvious AI artifacts that would look bad in a published short (backwards UI text, impossible keyboards, bent screens, broken hands, unreadable device layouts)?\n"
                "Use FAIL only for issues serious enough to block upload. If the visuals are merely somewhat metaphorical or loosely related to the topic, still return PASS.\n"
                "Format exactly: PASS or FAIL, then one issue per new line."
            ),
        })
        response = client.chat.completions.create(
            model=_cfg.OPENROUTER_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": content}],
        )
        answer = response.choices[0].message.content.strip()
        ok = answer.upper().startswith("PASS")
        issues = [line.strip() for line in answer.split("\n")[1:] if line.strip()]
        if not ok:
            if _frame_review_is_hard_fail(issues):
                logger.warning("Frame review HARD FAIL: %s", issues)
                return False, issues
            logger.warning("Frame review SOFT FAIL accepted for upload: %s", issues)
            return True, issues
        return ok, issues
    except Exception as exc:
        logger.warning("Frame review error (%s) — skipping check.", exc)
        return True, []


def _is_screen_prompt_risky(prompt: str) -> bool:
    prompt_lower = prompt.lower()
    screen_terms = [
        "screen", "monitor", "laptop", "computer", "desktop", "dashboard",
        "terminal", "code editor", "editor", "smartphone", "phone", "tablet",
        "ui", "interface", "display",
    ]
    guardrails = [
        "not mirrored", "upright", "right-side up", "legible", "readable",
        "correct orientation", "straight-on", "unmirrored",
    ]
    return any(term in prompt_lower for term in screen_terms) and not any(
        phrase in prompt_lower for phrase in guardrails
    )


def _pick_best_script(candidates: list[dict], topic: str) -> tuple:
    """Generate scripts for top candidates, run partial quality gate, pick the best.

    Returns (VideoIdea, Script) for the best passing candidate.
    Falls back to the highest-score candidate if none pass.
    """
    from idea import VideoIdea, generate_script
    import config as _cfg

    top3 = sorted(candidates, key=lambda c: c.get("score", 0), reverse=True)[:3]
    results = []
    for cdata in top3:
        fmt = cdata.get("format", _cfg.NICHE_FORMATS[0])
        if fmt not in _cfg.NICHE_FORMATS:
            fmt = _cfg.NICHE_FORMATS[0]
        idea = VideoIdea(
            topic=topic,
            angle=cdata["angle"],
            format=fmt,
            target_emotion=cdata.get("target_emotion", "curiosity"),
            viewer_question=cdata.get("viewer_question", ""),
        )
        try:
            script = generate_script(idea)
            wc = len(script.full_script.split())
            issues = []
            if not MIN_SCRIPT_WORDS <= wc <= MAX_SCRIPT_WORDS:
                issues.append(f"word_count {wc}")
            for phrase in ["look at", "see this", "watch this", "as you can see"]:
                if phrase in script.full_script.lower():
                    issues.append(f"visual ref: '{phrase}'")
            results.append((idea, script, len(issues), abs(wc - IDEAL_SCRIPT_WORDS), wc))
        except Exception as exc:
            logger.warning("Script generation failed for angle '%s': %s", cdata["angle"][:50], exc)

    if not results:
        raise RuntimeError("All script candidates failed to generate")

    results.sort(key=lambda r: (r[2], r[3], r[4]))
    best_idea, best_script, n_issues, _distance, best_wc = results[0]
    if n_issues > 0:
        logger.warning("Best script candidate has %d partial quality issue(s) — using anyway.", n_issues)
    logger.info(
        "Selected script: '%s' [%s] (%d words)",
        best_idea.angle[:60],
        best_idea.format,
        best_wc,
    )
    return best_idea, best_script


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

    for index, clip in enumerate(clips):
        prompt = str(clip.get("prompt", ""))
        if _is_screen_prompt_risky(prompt):
            issues.append(
                f"clip {index} uses a screen-like visual without orientation guardrails: add upright/not-mirrored/legible framing"
            )

    return not issues, issues


def run_pipeline(
    topic: str | None,
    dry_run: bool,
    video_format: str | None = None,
    pillar: str | None = None,
    hook_type: str | None = None,
) -> None:
    import config

    config.validate_config(skip_youtube=dry_run)
    video_format = video_format or config.DEFAULT_FORMAT

    from artifact_paths import reserve_artifact_paths
    from captions import add_captions
    from content_registry import append_registry_entry, build_registry_entry
    from idea import generate_metadata, generate_script, get_trending_topic, run_idea_tournament
    from manifest import probe_duration_seconds, write_run_manifest
    from publish_tracking import track_successful_upload
    import tracker
    from video import assemble_video, generate_footage_ai
    from voice import text_to_speech

    if not dry_run:
        try:
            _run_stage("Refresh performance stats", tracker.refresh_stats)
        except Exception as exc:
            logger.warning("Skipping stats refresh: %s", exc)

    top_performers = tracker.get_top_performers()
    if top_performers:
        logger.info("Top performers loaded: %s", [entry["topic"] for entry in top_performers])

    artifact_paths = reserve_artifact_paths(
        config.OUTPUT_DIR,
        registry_path=config.CONTENT_REGISTRY_PATH,
    )
    registry_id = artifact_paths.registry_id

    # 1. Topic → Idea tournament → Multi-candidate script selection
    if not topic:
        topic = _run_stage("Get trending topic", get_trending_topic,
                           top_performers=top_performers)
    insights = tracker.get_performance_insights()
    _winner, candidates = _run_stage("Idea tournament", run_idea_tournament,
                                      topic, video_format, insights=insights)

    # Pick the best script from top-3 tournament candidates (cheap LLM calls, no TTS yet)
    idea, script = _run_stage("Pick best script", _pick_best_script, candidates, topic)
    logger.info("Script preview:\n%s", script.full_script[:200])

    audio: Path = _run_stage(
        "Text-to-speech",
        text_to_speech,
        script.full_script,
        output_path=artifact_paths.audio,
    )

    audio_duration = _get_audio_duration(audio)
    ok, issues = _check_quality(script, audio_duration)
    if not ok:
        logger.warning("Quality gate FAILED: %s — retrying script once.", issues)
        script = _run_stage("Generate script (retry)", generate_script, idea)
        logger.info("Script preview (retry):\n%s", script.full_script[:200])
        audio = _run_stage(
            "Text-to-speech (retry)",
            text_to_speech,
            script.full_script,
            output_path=artifact_paths.audio,
        )
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
            audio = _run_stage(
                "Text-to-speech (clip retry)",
                text_to_speech,
                script.full_script,
                output_path=artifact_paths.audio,
            )
            audio_duration = _get_audio_duration(audio)
            ok, issues = _check_quality(script, audio_duration)
            if not ok:
                logger.warning("Quality gate after clip retry: %s — continuing anyway.", issues)
            ok_clips, clip_issues = _check_clip_prompts(idea, script.clips)
            if not ok_clips:
                logger.warning("Clip prompts still failing: %s — continuing anyway.", clip_issues)

    if not config.FAL_KEY:
        raise RuntimeError(
            "FAL_KEY is not set. AI footage generation is required — add FAL_KEY to your .env file."
        )
    if not script.clips:
        raise RuntimeError(
            "Script contains no clip prompts. Re-run or check the format prompt for clip generation."
        )

    clips: list[Path] = _run_stage(
        "Generate AI footage",
        generate_footage_ai,
        script.clips,
        clips_dir=artifact_paths.clips_dir,
    )

    raw_video: Path = _run_stage(
        "Assemble video",
        assemble_video,
        clips,
        audio,
        out_name=artifact_paths.raw_video.name,
        videos_dir=artifact_paths.videos_dir,
        normalized_clips_dir=artifact_paths.clips_dir,
        segment_texts=[beat.get("text", "") for beat in script.beats] if len(script.beats) == len(clips) else None,
    )
    final_video: Path = _run_stage(
        "Add captions",
        add_captions,
        raw_video,
        audio,
        script_text=script.full_script,
        emphasis_words=getattr(script, "emphasis_words", None),
        output_path=artifact_paths.final_video,
    )

    registry_entry = build_registry_entry(
        topic=script.topic,
        theme=script.theme,
        fact_summary=script.fact_summary,
        hook_angle=script.hook_angle,
        keywords=script.keywords,
        format_id=script.format,
        pillar=pillar,
        hook_type=hook_type,
        status="produced-dry-run" if dry_run else "produced",
        registry_path=config.CONTENT_REGISTRY_PATH,
        entry_id=registry_id,
    )
    append_registry_entry(registry_entry, registry_path=config.CONTENT_REGISTRY_PATH)
    logger.info("Registered clip in content registry: %s", registry_entry["id"])

    duration_seconds = probe_duration_seconds(final_video)

    # 7. Frame review — vision model checks frames before upload
    frames = _extract_frames(final_video)
    frame_ok, frame_issues = _review_frames(frames, script)
    if not frame_ok:
        logger.warning(
            "Frame review FAILED: %s — saving video locally but skipping upload.", frame_issues
        )
        logger.info("Video saved locally: %s", final_video)
        print(f"\nFrame review failed: {frame_issues}\nVideo saved (not uploaded): {final_video.resolve()}")
        return

    # 8. Publish (skipped in dry-run)
    if dry_run:
        manifest_path = write_run_manifest(
            paths=artifact_paths,
            topic=script.topic,
            theme=script.theme,
            pillar=pillar,
            hook_type=hook_type,
            fact_summary=script.fact_summary,
            hook_angle=script.hook_angle,
            keywords=script.keywords,
            status="produced-dry-run",
            script_text=script.full_script,
            duration_seconds=duration_seconds,
        )
        logger.info("Wrote run manifest: %s", manifest_path)
        logger.info("🏁 DRY RUN complete. Final video: %s", final_video)
        print(
            f"\nDry run complete!\n"
            f"Video saved to: {final_video.resolve()}\n"
            f"Manifest: {manifest_path.resolve()}"
        )
        return

    from publish import upload_to_youtube

    metadata = _run_stage("Generate metadata", generate_metadata, script, idea)
    url: str = _run_stage(
        "Upload to YouTube",
        upload_to_youtube,
        final_video,
        title=metadata.title,
        description=metadata.description,
        tags=script.keywords + metadata.hashtags,
    )

    video_id = url.split("v=")[-1] if "v=" in url else None
    manifest_path = write_run_manifest(
        paths=artifact_paths,
        topic=script.topic,
        theme=script.theme,
        pillar=pillar,
        hook_type=hook_type,
        fact_summary=script.fact_summary,
        hook_angle=script.hook_angle,
        keywords=script.keywords,
        status="uploaded",
        script_text=script.full_script,
        duration_seconds=duration_seconds,
        youtube_url=url,
        video_id=video_id,
    )
    tracking = track_successful_upload(
        video_path=final_video,
        youtube_url=url,
        registry_path=config.CONTENT_REGISTRY_PATH,
    )
    logger.info("Wrote run manifest: %s", manifest_path)
    logger.info(
        "Upload tracking synced: registry=%s video_id=%s",
        tracking["registry_id"],
        tracking["video_id"],
    )

    try:
        if tracking["video_id"]:
            tracker.log_run(
                topic=script.topic,
                video_id=tracking["video_id"],
                url=url,
                angle=idea.angle,
                format=script.format,
                hook=script.hook,
                word_count=len(script.full_script.split()),
                duration=audio_duration,
            )
    except Exception as exc:
        logger.warning("Could not log run to tracker: %s", exc)

    logger.info("🏁 Pipeline complete! %s", url)
    print(f"\nDone! Video live at: {url}\nManifest: {manifest_path.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Viral video pipeline")
    parser.add_argument("--topic", type=str, default=None, help="Custom topic (default: auto-detect trending)")
    parser.add_argument("--format", type=str, default=None, help="Video format (default: DEFAULT_FORMAT)")
    parser.add_argument("--dry-run", action="store_true", help="Run all stages except YouTube upload")
    parser.add_argument("--pillar", type=str, default=None, help="Optional pillar label for registry/manifest metadata")
    parser.add_argument("--hook-type", type=str, default=None, help="Optional hook type label for registry/manifest metadata")
    args = parser.parse_args()

    run_pipeline(
        topic=args.topic,
        dry_run=args.dry_run,
        video_format=args.format,
        pillar=args.pillar,
        hook_type=args.hook_type,
    )


if __name__ == "__main__":
    main()
