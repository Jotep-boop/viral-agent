# MCP Server Wrapper for viral-agent

## Context

The viral-agent pipeline generates viral short-form videos end-to-end (trending topic → script → TTS → stock footage → video assembly → captions → YouTube upload). The user's Hermes agent (NousResearch) needs to orchestrate this pipeline for automated social media content generation. An MCP server wrapper exposes the pipeline as structured tools that Hermes discovers and calls natively.

## Architecture

A single new file `mcp_server.py` in the project root using the `mcp` Python SDK with **stdio transport**. Hermes starts it as a subprocess — no network configuration needed.

### Hermes config.yaml

```yaml
mcp_servers:
  viral_agent:
    command: "python"
    args: ["/path/to/viral-agent/mcp_server.py"]
```

## Tools

### 1. `get_trending_topic`

Returns a trending topic suitable for viral video content.

- **Input:** `geo` (string, optional, default `"SE"`)
- **Output:** `{ "topic": "...", "source": "pytrends|reddit|google_rss" }`
- **Fallback chain:** pytrends → Reddit → Google Trends RSS

### 2. `generate_video`

Runs the full pipeline: script generation → TTS → stock footage → video assembly → captions.

- **Input:**
  - `topic` (string, required) — the video topic
  - `dry_run` (bool, optional, default `true`) — if false, also uploads to YouTube
- **Output:**
  - `video_path` (string) — absolute path to final.mp4
  - `script` (string) — the full narration script
  - `keywords` (list[string]) — keywords used for footage search
  - `duration_seconds` (float) — video duration
  - `youtube_url` (string|null) — only if dry_run=false

### 3. `upload_to_youtube`

Uploads a previously generated video to YouTube. Separate from generate_video so Hermes can review before publishing.

- **Input:**
  - `video_path` (string, required) — path to the video file
  - `title` (string, required) — video title (max 100 chars)
  - `description` (string, optional) — video description
  - `tags` (list[string], optional) — video tags
- **Output:**
  - `url` (string) — YouTube video URL
  - `video_id` (string) — YouTube video ID

## Data Flow

```
Hermes                          MCP Server (viral-agent)
  │                                    │
  ├─ get_trending_topic(geo="SE") ────►│─► pytrends/reddit/RSS
  │◄── { topic: "...", source: "..." } │
  │                                    │
  ├─ generate_video(topic, dry_run) ──►│─► LLM → TTS → Pexels → ffmpeg → Whisper
  │◄── { video_path, script, ... }     │
  │                                    │
  ├─ (Hermes reviews/decides)          │
  │                                    │
  ├─ upload_to_youtube(path, title) ──►│─► YouTube API (OAuth2)
  │◄── { url, video_id }              │
  │                                    │
  └─ Posts URL to Telegram/Discord     │
```

## Error Handling

All tools return structured JSON. On failure:

```json
{
  "error": "Description of what went wrong",
  "stage": "trending_topic|script|tts|footage|assembly|captions|upload"
}
```

Hermes can inspect the error and stage to decide how to recover (retry, skip, notify user).

## Implementation

### File: `mcp_server.py`

- Uses `mcp` Python SDK (`FastMCP` class)
- Imports existing pipeline modules (idea, voice, video, captions, publish)
- Each tool is a decorated async function
- Runs via `server.run()` with stdio transport
- Catches exceptions per-tool and returns structured error JSON

### New dependency

- `mcp` package added to `requirements.txt`

## Verification

1. Run `python mcp_server.py` — should start and accept stdio JSON-RPC
2. Test with MCP inspector or direct JSON-RPC calls
3. Configure in Hermes config.yaml and verify tool discovery
4. Run `get_trending_topic` → `generate_video` → `upload_to_youtube` flow
