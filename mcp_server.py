"""mcp_server.py — MCP server exposing viral-agent pipeline tools."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("viral-agent")


@mcp.tool()
def generate_ideas(topic: str = "", count: int = 5) -> str:
    """Generate and rank viral video ideas for a topic (or auto-detect trending topic)."""
    try:
        import config  # noqa
        from idea import get_trending_topic as _get_topic, run_idea_tournament

        if not topic:
            topic = _get_topic()

        count = min(count, 10)
        try:
            import tracker
            insights = tracker.get_performance_insights()
        except Exception:
            insights = None
        _winner, candidates = run_idea_tournament(topic, format_name=None, count=count, insights=insights)
        # Sort by score descending so Hermes sees the best first
        candidates_sorted = sorted(candidates, key=lambda c: c.get("score", 0), reverse=True)
        return json.dumps(candidates_sorted)
    except Exception as e:
        return json.dumps({"error": str(e), "stage": "generate_ideas"})


@mcp.tool()
def get_performance_insights() -> str:
    """Get performance insights from previous videos to inform content decisions."""
    try:
        import tracker

        return json.dumps(tracker.get_performance_insights())
    except Exception as exc:
        return json.dumps({"error": str(exc), "stage": "performance_insights"})


@mcp.tool()
def get_trending_topic(geo: str = "SE") -> str:
    """Get a currently trending topic suitable for a viral video."""
    try:
        from idea import get_trending_topic as _get_topic

        topic = _get_topic(geo=geo)
        return json.dumps({"topic": topic, "source": "auto"})
    except Exception as exc:
        return json.dumps({"error": str(exc), "stage": "trending_topic"})


@mcp.tool()
def list_formats() -> str:
    """List available video formats and their descriptions."""
    try:
        import formats as fmt

        return json.dumps({name: entry["description"] for name, entry in fmt.FORMATS.items()})
    except Exception as exc:
        return json.dumps({"error": str(exc)})


@mcp.tool()
def generate_video(
    topic: str,
    format: str = "informative",
    angle: str = "",
    dry_run: bool = True,
    pillar: str | None = None,
    hook_type: str | None = None,
) -> str:
    """Generate a viral short-form video from a topic."""
    try:
        import config
        from artifact_paths import reserve_artifact_paths
        from captions import add_captions
        from content_registry import append_registry_entry, build_registry_entry
        from idea import VideoIdea, generate_idea, generate_metadata, generate_script
        from manifest import probe_duration_seconds, write_run_manifest
        from publish_tracking import track_successful_upload
        import tracker
        from video import assemble_video, generate_footage_ai
        from voice import text_to_speech

        config.validate_config(skip_youtube=dry_run)

        artifact_paths = reserve_artifact_paths(
            config.OUTPUT_DIR,
            registry_path=config.CONTENT_REGISTRY_PATH,
        )
        registry_id = artifact_paths.registry_id

        if angle:
            idea = VideoIdea(
                topic=topic,
                angle=angle,
                format=format,
                target_emotion="curiosity",
                viewer_question="",
            )
        else:
            idea = generate_idea(topic, format)

        script = generate_script(idea)
        audio = text_to_speech(script.full_script, output_path=artifact_paths.audio)

        if not config.FAL_KEY:
            return json.dumps({"error": "FAL_KEY not configured", "stage": "footage"})
        if not script.clips:
            return json.dumps({
                "error": "Script contains no clip prompts. Re-run or check the format prompt for clip generation.",
                "stage": "footage",
            })
        clips = generate_footage_ai(script.clips, clips_dir=artifact_paths.clips_dir)

        raw_video = assemble_video(
            clips,
            audio,
            out_name=artifact_paths.raw_video.name,
            videos_dir=artifact_paths.videos_dir,
            normalized_clips_dir=artifact_paths.clips_dir,
            segment_texts=[beat.get("text", "") for beat in script.beats] if len(script.beats) == len(clips) else None,
        )
        final_video = add_captions(
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

        duration_seconds = probe_duration_seconds(final_video)
        metadata = generate_metadata(script, idea)
        youtube_url = None
        video_id = None
        manifest_path: str | None = None

        if dry_run:
            manifest = write_run_manifest(
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
            manifest_path = str(manifest.resolve())
        else:
            from publish import upload_to_youtube as _upload

            youtube_url = _upload(
                final_video,
                title=metadata.title,
                description=metadata.description,
                tags=script.keywords + metadata.hashtags,
            )
            video_id = youtube_url.split("v=")[-1] if "v=" in youtube_url else ""
            manifest = write_run_manifest(
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
                youtube_url=youtube_url,
                video_id=video_id,
            )
            tracking = track_successful_upload(
                video_path=final_video,
                youtube_url=youtube_url,
                registry_path=config.CONTENT_REGISTRY_PATH,
            )
            video_id = str(tracking["video_id"] or video_id)
            manifest_path = str(tracking["manifest_path"] or manifest.resolve())
            try:
                if video_id:
                    tracker.log_run(
                        topic=script.topic,
                        video_id=video_id,
                        url=youtube_url,
                        angle=idea.angle,
                        format=script.format,
                        hook=script.hook,
                        word_count=len(script.full_script.split()),
                        duration=duration_seconds,
                    )
            except Exception:
                pass

        result = {
            "video_path": str(final_video.resolve()),
            "title": metadata.title,
            "angle": idea.angle,
            "script": script.full_script,
            "format": script.format,
            "keywords": script.keywords,
            "hashtags": metadata.hashtags,
            "pinned_comment": metadata.pinned_comment,
            "duration_seconds": duration_seconds,
            "youtube_url": youtube_url,
            "registry_id": registry_entry["id"],
            "fact_summary": script.fact_summary,
            "theme": script.theme,
            "pillar": pillar,
            "hook_type": hook_type,
            "manifest_path": manifest_path,
        }
        if video_id:
            result["video_id"] = video_id

        return json.dumps(result)
    except Exception as exc:
        return json.dumps({"error": str(exc), "stage": _guess_stage(exc)})


@mcp.tool()
def upload_to_youtube(video_path: str, title: str, description: str = "", tags: str = "") -> str:
    """Upload a previously generated video to YouTube."""
    try:
        import config
        from publish_tracking import track_successful_upload

        config.validate_config(skip_youtube=False)

        path = Path(video_path)
        if not path.exists():
            return json.dumps({"error": f"Video file not found: {video_path}", "stage": "upload"})

        from publish import upload_to_youtube as _upload

        tag_list = [tag.strip() for tag in tags.split(",") if tag.strip()] if tags else []
        url = _upload(path, title=title[:100], description=description, tags=tag_list)
        tracking = track_successful_upload(
            video_path=path,
            youtube_url=url,
            registry_path=config.CONTENT_REGISTRY_PATH,
        )

        return json.dumps(
            {
                "url": url,
                "video_id": tracking["video_id"] or (url.split("v=")[-1] if "v=" in url else ""),
                "registry_id": tracking["registry_id"],
                "manifest_path": tracking["manifest_path"],
                "published_at": tracking["published_at"],
            }
        )
    except Exception as exc:
        return json.dumps({"error": str(exc), "stage": "upload"})


@mcp.tool()
def get_channel_stats() -> str:
    """Get YouTube channel statistics."""
    try:
        from publish import get_channel_stats as _get_stats

        return json.dumps(_get_stats())
    except Exception as exc:
        return json.dumps({"error": str(exc), "stage": "analytics"})


@mcp.tool()
def get_video_stats(video_id: str) -> str:
    """Get statistics for a specific YouTube video."""
    try:
        from publish import get_video_stats as _get_stats

        return json.dumps(_get_stats(video_id))
    except Exception as exc:
        return json.dumps({"error": str(exc), "stage": "analytics"})


@mcp.tool()
def list_recent_videos(max_results: int = 10) -> str:
    """List recent uploaded videos with their performance stats."""
    try:
        from publish import list_recent_videos as _list_videos

        return json.dumps(_list_videos(min(max_results, 50)))
    except Exception as exc:
        return json.dumps({"error": str(exc), "stage": "analytics"})


def _get_duration(video_path: Path) -> float:
    from video import _ffmpeg_bin

    result = subprocess.run(
        [_ffmpeg_bin(), "-i", str(video_path), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", result.stderr)
    if not match:
        return 0.0
    hours, minutes, seconds, centiseconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(centiseconds) / 100


def _guess_stage(exc: Exception) -> str:
    traceback_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).lower()
    for stage, markers in [
        ("script", ["idea.py", "generate_script", "openrouter", "formats"]),
        ("tts", ["voice.py", "elevenlabs", "text_to_speech"]),
        ("footage", ["pexels", "fetch_footage", "fal", "kling", "generate_footage_ai"]),
        ("assembly", ["assemble_video", "concat"]),
        ("captions", ["captions.py", "whisper", "burn_captions"]),
        ("upload", ["publish.py", "youtube", "upload"]),
    ]:
        if any(marker in traceback_text for marker in markers):
            return stage
    return "unknown"


if __name__ == "__main__":
    mcp.run()
