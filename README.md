# viral-agent 🎬

AI-powered pipeline that auto-generates and publishes short viral videos to YouTube.

## What it does

1. **Finds the best trending topic** — collects candidates from YouTube trending, Google Trends, Hacker News, and Google RSS, then uses an LLM to score and select the one with the highest viral potential
2. **Improves over time** — logs every upload to `output/performance.json`, refreshes view counts after 48 h, and feeds top-performing topics into future scoring
3. **Writes a script** — LLM via OpenRouter generates a punchy 30-sec hook/core/CTA + per-clip visual prompts for AI video generation
4. **Generates voiceover** — ElevenLabs TTS
5. **Generates video clips** — fal.ai (Kling) creates AI-generated clips matching the script; falls back to Pexels stock footage if `FAL_KEY` is not set
6. **Assembles the video** — ffmpeg concatenation + audio mix
7. **Burns karaoke captions** — OpenAI Whisper word-level timestamps with per-word yellow highlighting
8. **Uploads to YouTube** — YouTube Data API v3

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

> **ffmpeg** must be installed separately and on your PATH:
> - Windows: `winget install ffmpeg`
> - macOS: `brew install ffmpeg`
> - Ubuntu: `sudo apt install ffmpeg`

### 2. Get API keys

| Service | Purpose | Where to get it |
|---|---|---|
| OpenRouter | LLM (script + topic scoring) | https://openrouter.ai/keys |
| ElevenLabs | Text-to-speech | https://elevenlabs.io |
| fal.ai | AI video generation (Kling) | https://fal.ai/dashboard/keys |
| Pexels | Stock footage fallback | https://www.pexels.com/api |
| YouTube API key | Fetch YouTube trending topics | https://console.cloud.google.com → Enable YouTube Data API v3 → Create API key |
| YouTube OAuth | Upload videos | Same project → Create OAuth 2.0 credentials → Download as `client_secrets.json` |

### 3. Configure

```bash
cp .env.example .env
# Edit .env and fill in your keys
```

Place `client_secrets.json` (YouTube OAuth) in the same folder.

### 4. Run

```bash
# Test without uploading (recommended first run)
python main.py --dry-run

# Custom topic, no upload
python main.py --topic "why we dream" --dry-run

# Full run (trending topic → AI video → upload to YouTube)
python main.py

# Custom topic + upload
python main.py --topic "black holes explained"
```

Logs go to `output/pipeline.log`.

## AI video generation

When `FAL_KEY` is set the pipeline uses **fal.ai** to generate video clips via Kling instead of downloading generic stock footage. The LLM writes specific, funny visual prompts per clip (e.g. *"a confused golden retriever staring at math equations on a chalkboard"*) and up to 3 clips are generated in parallel.

To change the model, set `FALAI_MODEL` in `.env`:

```
# Default
FALAI_MODEL=fal-ai/kling-video/v1.6/standard/text-to-video

# Higher quality
FALAI_MODEL=fal-ai/kling-video/v2.1/standard/text-to-video
```

If `FAL_KEY` is not set, the pipeline falls back to Pexels stock footage automatically.

## Karaoke captions

Captions use ASS format with per-word yellow highlighting — the currently spoken word lights up while the surrounding context stays white. Three words are shown per group at font size 65.

## Performance feedback loop

Every uploaded video is logged to `output/performance.json`. At the start of each run, view counts are refreshed via the YouTube API for entries older than 48 hours. The top 5 performers (≥100 views) are passed into the topic-scoring prompt so the LLM learns to prefer styles and categories that have worked before.

## MCP server

The pipeline is also exposed as an MCP server for agent integration (e.g. Hermes):

```bash
python mcp_server.py
```

Available tools: `get_trending_topic`, `generate_video`, `upload_to_youtube`, `get_channel_stats`, `get_video_stats`, `list_recent_videos`.

## Output structure

```
output/
  audio/           voiceover MP3s + .ass caption files
  clips/           AI-generated or downloaded + normalised clips
  videos/          raw_*.mp4 (no captions) + final_*.mp4 (with captions)
  performance.json upload history + view counts
  pipeline.log
```

## Tips for going viral

- Run daily via cron/Task Scheduler — volume matters early on
- Let the feedback loop run for 2–3 weeks before drawing conclusions
- Monitor YouTube Studio for CTR and average view duration
- Keep `full_script` under 90 words — faster pacing = better retention
