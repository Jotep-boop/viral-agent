"""mcp_server.py — MCP server exposing viral-agent pipeline tools."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("viral-agent")


@mcp.tool()
def get_trending_topic(geo: str = "SE") -> str:
    """Get a currently trending topic suitable for a viral video.

    Args:
        geo: Country code for trend detection (default: SE for Sweden)

    Returns:
        JSON with topic and source.
    """
    try:
        import config  # noqa: F811
        from idea import get_trending_topic as _get_topic

        topic = _get_topic(geo=geo)
        return json.dumps({"topic": topic, "source": "auto"})
    except Exception as e:
        return json.dumps({"error": str(e), "stage": "trending_topic"})


@mcp.tool()
def list_formats() -> str:
    """List available video formats and their descriptions.

    Use this to discover what formats exist before calling generate_video.
    Pass the format name to generate_video's `format` parameter.

    Returns:
        JSON object mapping format name → description.
    """
    try:
        import formats as fmt
        return json.dumps({
            name: f["description"]
            for name, f in fmt.FORMATS.items()
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def generate_video(topic: str, format: str = "informative",
                   dry_run: bool = True) -> str:
    """Generate a viral short-form video from a topic.

    Runs the full pipeline: script → TTS → AI video clips → assembly → captions.
    Use list_formats() first to see available formats.

    Args:
        topic:   The video topic (e.g. "black holes", "animal facts")
        format:  Video format — "informative" (default) or "top5".
                 Use list_formats() to see all options.
        dry_run: If True, skip YouTube upload (default: True)

    Returns:
        JSON with video_path, script, format, keywords, duration_seconds,
        and optionally youtube_url.
    """
    try:
        import config
        config.validate_config(skip_youtube=dry_run)

        from idea import generate_script
        from voice import text_to_speech
        from video import fetch_footage, generate_footage_ai, assemble_video
        from captions import add_captions

        from datetime import datetime
        tag = datetime.now().strftime("%Y%m%d_%H%M%S")

        script = generate_script(topic, format_name=format)
        audio = text_to_speech(script.full_script)

        if config.FAL_KEY and script.clips:
            clips = generate_footage_ai(script.clips)
        else:
            clips = fetch_footage(script.keywords)

        raw_video = assemble_video(clips, audio, out_name=f"raw_{tag}.mp4")
        final_video = add_captions(raw_video, audio, script_text=script.full_script,
                                    out_name=f"final_{tag}.mp4")

        result = {
            "video_path": str(final_video.resolve()),
            "script": script.full_script,
            "format": script.format,
            "keywords": script.keywords,
            "duration_seconds": _get_duration(final_video),
            "youtube_url": None,
        }

        if not dry_run:
            from publish import upload_to_youtube as _upload
            url = _upload(
                final_video,
                title=script.topic,
                description=script.full_script,
                tags=script.keywords,
            )
            result["youtube_url"] = url

        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e), "stage": _guess_stage(e)})


@mcp.tool()
def upload_to_youtube(video_path: str, title: str,
                      description: str = "", tags: str = "") -> str:
    """Upload a previously generated video to YouTube.

    Use this after generate_video to publish when ready.

    Args:
        video_path: Absolute path to the video file
        title: Video title (max 100 characters)
        description: Video description
        tags: Comma-separated tags (e.g. "science,facts,viral")

    Returns:
        JSON with url and video_id.
    """
    try:
        from pathlib import Path
        import config
        config.validate_config(skip_youtube=False)

        path = Path(video_path)
        if not path.exists():
            return json.dumps({"error": f"Video file not found: {video_path}",
                               "stage": "upload"})

        from publish import upload_to_youtube as _upload

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        url = _upload(path, title=title[:100], description=description, tags=tag_list)
        video_id = url.split("v=")[-1] if "v=" in url else ""

        return json.dumps({"url": url, "video_id": video_id})
    except Exception as e:
        return json.dumps({"error": str(e), "stage": "upload"})


@mcp.tool()
def get_channel_stats() -> str:
    """Get YouTube channel statistics.

    Returns:
        JSON with channel_title, subscribers, total_views, video_count.
    """
    try:
        import config  # noqa: F811
        from publish import get_channel_stats as _get_stats
        return json.dumps(_get_stats())
    except Exception as e:
        return json.dumps({"error": str(e), "stage": "analytics"})


@mcp.tool()
def get_video_stats(video_id: str) -> str:
    """Get statistics for a specific YouTube video.

    Args:
        video_id: The YouTube video ID (e.g. "dQw4w9WgXcQ")

    Returns:
        JSON with title, views, likes, comments, published_at.
    """
    try:
        import config  # noqa: F811
        from publish import get_video_stats as _get_stats
        return json.dumps(_get_stats(video_id))
    except Exception as e:
        return json.dumps({"error": str(e), "stage": "analytics"})


@mcp.tool()
def list_recent_videos(max_results: int = 10) -> str:
    """List recent uploaded videos with their performance stats.

    Args:
        max_results: Number of videos to return (default: 10, max: 50)

    Returns:
        JSON array of videos with video_id, title, published_at, views, likes, comments.
    """
    try:
        import config  # noqa: F811
        from publish import list_recent_videos as _list_videos
        return json.dumps(_list_videos(min(max_results, 50)))
    except Exception as e:
        return json.dumps({"error": str(e), "stage": "analytics"})


def _get_duration(video_path) -> float:
    from video import _ffmpeg_bin
    result = subprocess.run(
        [_ffmpeg_bin(), "-i", str(video_path), "-f", "null", "-"],
        capture_output=True, text=True,
    )
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", result.stderr)
    if not match:
        return 0.0
    h, m, s, cs = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(cs) / 100


def _guess_stage(exc: Exception) -> str:
    tb_text = "".join(traceback.format_exception(type(exc), exc,
                                                  exc.__traceback__)).lower()
    for stage, markers in [
        ("script", ["idea.py", "generate_script", "openrouter"]),
        ("tts", ["voice.py", "elevenlabs", "text_to_speech"]),
        ("footage", ["pexels", "fetch_footage"]),
        ("assembly", ["assemble_video", "concat"]),
        ("captions", ["captions.py", "whisper", "burn_caption"]),
        ("upload", ["publish.py", "youtube", "upload"]),
    ]:
        if any(m in tb_text for m in markers):
            return stage
    return "unknown"


if __name__ == "__main__":
    mcp.run()
