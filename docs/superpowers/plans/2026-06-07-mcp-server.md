# MCP Server Wrapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap the viral-agent pipeline as an MCP server so Hermes can orchestrate video generation via three tools: `get_trending_topic`, `generate_video`, `upload_to_youtube`.

**Architecture:** A single `mcp_server.py` file using the `mcp` Python SDK's `FastMCP` class with stdio transport. Each tool wraps existing pipeline functions from `idea.py`, `video.py`, `captions.py`, and `publish.py`. Hermes starts the server as a subprocess configured in its `config.yaml`.

**Tech Stack:** Python 3.8+, `mcp` SDK (FastMCP), existing viral-agent modules

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `mcp_server.py` | Create | MCP server with 3 tool definitions |
| `requirements.txt` | Modify | Add `mcp` dependency |

---

### Task 1: Install mcp dependency

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add mcp to requirements.txt**

Add to the end of `requirements.txt`:

```
# MCP server
mcp>=1.0.0
```

- [ ] **Step 2: Install the dependency**

Run: `pip install mcp`

- [ ] **Step 3: Verify installation**

Run: `python -c "from mcp.server.fastmcp import FastMCP; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "feat: add mcp dependency for MCP server wrapper"
```

---

### Task 2: Create MCP server with get_trending_topic tool

**Files:**
- Create: `mcp_server.py`

- [ ] **Step 1: Create mcp_server.py with server setup and first tool**

```python
"""mcp_server.py — MCP server exposing viral-agent pipeline tools."""
from __future__ import annotations

import json
import sys
import os

# Ensure the project root is on the Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("viral-agent")


@mcp.tool()
def get_trending_topic(geo: str = "SE") -> str:
    """Get a currently trending topic suitable for a viral video.

    Args:
        geo: Country code for trend detection (default: SE for Sweden)

    Returns:
        JSON with topic and source: {"topic": "...", "source": "pytrends|reddit|google_rss"}
    """
    try:
        import config  # noqa: F811 — triggers PATH setup and env loading
        from idea import get_trending_topic as _get_topic

        topic = _get_topic(geo=geo)
        return json.dumps({"topic": topic, "source": "auto"})
    except Exception as e:
        return json.dumps({"error": str(e), "stage": "trending_topic"})


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 2: Verify the server starts**

Run: `python -c "import mcp_server; print('Server module loads OK')"`

Expected: `Server module loads OK` (no import errors)

- [ ] **Step 3: Commit**

```bash
git add mcp_server.py
git commit -m "feat: add MCP server with get_trending_topic tool"
```

---

### Task 3: Add generate_video tool

**Files:**
- Modify: `mcp_server.py`

- [ ] **Step 1: Add generate_video tool to mcp_server.py**

Add before the `if __name__` block:

```python
@mcp.tool()
def generate_video(topic: str, dry_run: bool = True) -> str:
    """Generate a viral short-form video from a topic.

    Runs the full pipeline: script generation → TTS → stock footage → video assembly → captions.
    If dry_run is False, also uploads to YouTube.

    Args:
        topic: The video topic (e.g. "black holes", "animal facts")
        dry_run: If True, skip YouTube upload (default: True)

    Returns:
        JSON with video_path, script, keywords, duration_seconds, and optionally youtube_url.
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
            from publish import upload_to_youtube
            url = upload_to_youtube(
                final_video,
                title=script.topic,
                description=script.full_script,
                tags=script.keywords,
            )
            result["youtube_url"] = url

        return json.dumps(result)
    except Exception as e:
        return json.dumps({"error": str(e), "stage": _guess_stage(e)})


def _get_duration(video_path) -> float:
    """Get video duration using ffmpeg."""
    import re
    import subprocess
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
    """Best-effort guess at which pipeline stage failed based on the traceback."""
    import traceback
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    tb_text = "".join(tb).lower()
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
```

- [ ] **Step 2: Verify module still loads**

Run: `python -c "import mcp_server; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add mcp_server.py
git commit -m "feat: add generate_video MCP tool with full pipeline"
```

---

### Task 4: Add upload_to_youtube tool

**Files:**
- Modify: `mcp_server.py`

- [ ] **Step 1: Add upload_to_youtube tool to mcp_server.py**

Add before the `if __name__` block:

```python
@mcp.tool()
def upload_to_youtube(video_path: str, title: str,
                      description: str = "", tags: str = "") -> str:
    """Upload a previously generated video to YouTube.

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
            return json.dumps({"error": f"Video file not found: {video_path}", "stage": "upload"})

        from publish import upload_to_youtube as _upload

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        url = _upload(
            path,
            title=title[:100],
            description=description,
            tags=tag_list,
        )
        video_id = url.split("v=")[-1] if "v=" in url else ""

        return json.dumps({"url": url, "video_id": video_id})
    except Exception as e:
        return json.dumps({"error": str(e), "stage": "upload"})
```

- [ ] **Step 2: Verify module still loads**

Run: `python -c "import mcp_server; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add mcp_server.py
git commit -m "feat: add upload_to_youtube MCP tool"
```

---

### Task 5: End-to-end verification

- [ ] **Step 1: Verify MCP server starts and lists tools**

Run: `python -c "from mcp_server import mcp; print([t.name for t in mcp._tool_manager.list_tools()])"`

Expected output containing: `['get_trending_topic', 'generate_video', 'upload_to_youtube']`

If the above doesn't work due to internal API, verify by running:
`echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0.1"}}}' | python mcp_server.py`

Expected: JSON response with server capabilities

- [ ] **Step 2: Test get_trending_topic via direct call**

Run: `python -c "from mcp_server import get_trending_topic; print(get_trending_topic())"`

Expected: JSON string like `{"topic": "...", "source": "auto"}`

- [ ] **Step 3: Test generate_video via direct call**

Run: `python -c "from mcp_server import generate_video; print(generate_video(topic='ocean facts', dry_run=True))"`

Expected: JSON string with `video_path`, `script`, `keywords`, `duration_seconds` (takes ~60s)

- [ ] **Step 4: Final commit and push**

```bash
git add -A
git commit -m "feat: complete MCP server wrapper for viral-agent pipeline"
git push origin main
```

---

## Hermes Configuration

After implementation, add to Hermes `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  viral_agent:
    command: "python"
    args: ["C:/Users/Jesper/Desktop/Claude/viral-agent/mcp_server.py"]
    timeout: 300
```

Hermes will discover three tools:
- `mcp_viral_agent_get_trending_topic`
- `mcp_viral_agent_generate_video`
- `mcp_viral_agent_upload_to_youtube`
