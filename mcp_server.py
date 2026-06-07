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
def generate_video(topic: str, dry_run: bool = True) -> str:
    """Generate a viral short-form video from a topic.

    Runs the full pipeline: script generation, TTS, stock footage,
    video assembly, and caption burning. Takes about 60 seconds.

    Args:
        topic: The video topic (e.g. "black holes", "animal facts")
        dry_run: If True skip YouTube upload (default: True)

    Returns:
        JSON with video_path, script, keywords, duration_seconds,
        and optionally youtube_url.
    """
    try:
        import config
        config.validate_config(skip_youtube=dry_run)

        from idea import generate_script
        from voice import text_to_speech
        from video import fetch_footage, assemble_video
        from captions import add_captions

        script = generate_script(topic)
        audio = text_to_speech(script.full_script)
        clips = fetch_footage(script.keywords)
        raw_video = assemble_video(clips, audio)
        final_video = add_captions(raw_video, audio, script_text=script.full_script)

        result = {
            "video_path": str(final_video.resolve()),
            "script": script.full_script,
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
