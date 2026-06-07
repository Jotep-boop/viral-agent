# viral-agent 🎬

AI-powered pipeline that auto-generates and publishes short viral videos to YouTube.

## What it does

1. **Finds a trending topic** — Google Trends (falls back to Reddit)
2. **Writes a script** — LLM via OpenRouter generates a punchy 30-sec hook/core/CTA
3. **Generates voiceover** — ElevenLabs TTS
4. **Fetches stock footage** — Pexels portrait video clips
5. **Assembles the video** — ffmpeg concatenation + audio mix
6. **Burns in captions** — OpenAI Whisper transcription
7. **Uploads to YouTube** — YouTube Data API v3

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

| Service | Where to get it |
|---|---|
| OpenRouter | https://openrouter.ai/keys |
| ElevenLabs | https://elevenlabs.io |
| Pexels | https://www.pexels.com/api |
| YouTube | https://console.cloud.google.com → Create project → Enable YouTube Data API v3 → Create OAuth 2.0 credentials → Download as `client_secrets.json` |

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

# Full run (trending topic → upload to YouTube)
python main.py

# Custom topic + upload
python main.py --topic "black holes explained"
```

Logs go to `output/pipeline.log`.

## Output structure

```
output/
  audio/        voiceover MP3s
  clips/        downloaded + normalised Pexels clips
  videos/       raw.mp4 (no captions) + final.mp4 (with captions)
  pipeline.log
```

## Tips for going viral

- Run daily via cron/Task Scheduler for volume
- Monitor YouTube Studio analytics — check CTR and average view duration
- Niche down: "did you know" facts about a specific topic outperform generic content
- Keep full_script under 90 words — faster pacing = better retention
