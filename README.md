# viral-agent

Automated pipeline that generates and publishes mind-blowing science YouTube Shorts.
Every run goes from zero to a published video: trending topic → AI script → voiceover → AI video → captions → YouTube.

---

## How the pipeline works

```
Trending sources (YouTube, Google Trends, HN, Google RSS)
        ↓
  LLM picks best science topic
        ↓
  Idea tournament  (10 angles generated, all scored, top 3 get scripts)
        ↓
  Script selected  (partial quality gate picks best of top 3)
        ↓
  ElevenLabs TTS
        ↓
  Quality gate  (word count, duration, no visual refs)
        ↓
  Flux/schnell generates a still image per clip
        ↓
  Vision model reviews each still  (regenerates once if rejected)
        ↓
  Kling image-to-video animates approved stills
        ↓
  ffmpeg assembles video  (loudnorm −14 LUFS for Shorts)
        ↓
  Whisper karaoke captions  (yellow active word, orange emphasis words)
        ↓
  Frame review  (3 frames checked by vision model before upload)
        ↓
  YouTube upload  (skipped in --dry-run)
        ↓
  Performance logged → feeds back into next run's scoring
```

### Channel niche

The pipeline is locked to **mind-blowing science** — counterintuitive facts about physics, space, mathematics, biology, chemistry, and the human body. All topic selection and idea scoring enforce this niche. Only three formats are used: `informative`, `scary`, and `mythbuster`.

### Idea tournament

Each run generates 10 different angles for the chosen topic, scores them all against five criteria (hook strength, curiosity gap, visual payoff, comment potential, niche fit), then generates scripts for the top 3 before selecting the best. This means TTS and video generation only happen for the strongest angle.

### Image-first video

Instead of generating video directly from text (which is a lottery), the pipeline:
1. Generates a **still image** (Flux/schnell) for each clip — fast and cheap
2. A **vision model reviews** each still against the clip description — regenerates once if off-topic
3. **Kling image-to-video** animates the approved stills

Falls back to text-to-video if image generation fails.

### Frame review

After captions are burned, 3 frames are extracted from the final video and reviewed by a vision model. If the video is clearly broken or off-topic, it is saved locally but **not uploaded**. This is the last safety net before the video goes public.

### Performance feedback loop

Every uploaded video is logged to `output/performance.json`. Stats (views, likes, comments) are refreshed hourly for videos under 48 hours old, then every 48 hours after that. The top performers feed into topic selection and idea scoring on the next run, so the pipeline gradually learns what works on the channel.

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

**ffmpeg** must be installed separately and on your PATH:

| OS | Command |
|---|---|
| Windows | `winget install ffmpeg` |
| macOS | `brew install ffmpeg` |
| Ubuntu | `sudo apt install ffmpeg` |

### 2. Get API keys

| Service | Purpose | Where |
|---|---|---|
| OpenRouter | LLM (scripts, scoring, vision review) | https://openrouter.ai/keys |
| ElevenLabs | Text-to-speech voiceover | https://elevenlabs.io |
| fal.ai | Image generation (Flux) + video (Kling) | https://fal.ai/dashboard/keys |
| YouTube API key | Fetch trending topics | https://console.cloud.google.com — enable YouTube Data API v3, create API key |
| YouTube OAuth | Upload videos | Same project — create OAuth 2.0 credentials, download as `client_secrets.json` |

### 3. Configure

```bash
cp .env.example .env
# Fill in your keys
```

Place `client_secrets.json` in the project root.

Key environment variables:

```env
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=anthropic/claude-sonnet-4

ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=CwhRBWXzGAHq8TQ4Fs17

FAL_KEY=...
FALAI_IMAGE_MODEL=fal-ai/flux/schnell           # still image generation
FALAI_I2V_MODEL=fal-ai/kling-video/v1.6/standard/image-to-video   # animation
FALAI_MODEL=fal-ai/kling-video/v1.6/standard/text-to-video        # t2v fallback

YOUTUBE_API_KEY=...
YOUTUBE_CLIENT_SECRETS=client_secrets.json
```

### 4. Run

```bash
# Test without uploading (recommended first run)
python main.py --dry-run

# Custom topic, no upload
python main.py --topic "speed of light" --dry-run

# Full run: trending topic → AI video → YouTube upload
python main.py

# Custom topic + upload
python main.py --topic "black holes"
```

Logs go to `output/pipeline.log`.

---

## Video formats

| Format | Structure | Best for |
|---|---|---|
| `informative` | Hook → 3 surprising facts → CTA | General science facts |
| `scary` | Fear hook → escalating danger → shocking reveal | Extreme physics, dangerous biology |
| `mythbuster` | Common belief → evidence against → truth reveal | Debunking popular misconceptions |

The idea tournament picks the format automatically based on the topic and channel performance data.

---

## Captions

ASS karaoke format with two highlight colours:

- **Yellow** — the word currently being spoken
- **Orange** — emphasis/keyword words specified by the script

Three words shown per group at font size 72. Positioned 28% from the bottom of the frame (safe zone for mobile).

---

## MCP server

The pipeline is also exposed as an MCP server for agent integration:

```bash
python mcp_server.py
```

Available tools:

| Tool | Description |
|---|---|
| `get_trending_topic` | Returns the best trending science topic |
| `generate_ideas` | Runs the idea tournament and returns ranked candidates |
| `get_performance_insights` | Format breakdown, top hooks, average views |
| `generate_video` | Runs the full pipeline (dry_run=true by default) |
| `upload_to_youtube` | Uploads a locally generated video |
| `get_channel_stats` | Channel subscribers, total views, video count |
| `get_video_stats` | Views, likes, comments for a specific video |
| `list_recent_videos` | Recent uploads with performance stats |
| `list_formats` | Available video formats and descriptions |

---

## Output structure

```
output/
  audio/              voiceover MP3s
  clips/              still images, normalised clips, ai_clip_*.mp4
  videos/             raw_*.mp4 (no captions), final_*.mp4 (with captions)
  performance.json    upload history + refreshed view counts
  idea_candidates.jsonl   all tournament candidates for debugging
  pipeline.log
```

---

## Quality gates

The pipeline has four checkpoints that can stop or retry before spending money:

1. **Script quality gate** — word count 60–115, duration 20–55 s, no visual references ("look at this"), no generic openers. Retries script once if failed.
2. **Clip prompt gate** — first clip must reference the core claim, no archetype repeated 3+ times. Retries script once if failed.
3. **Still review** — vision model checks each generated still against the clip prompt. Regenerates once if rejected.
4. **Frame review** — 3 frames from the final video reviewed before upload. Skips upload (saves locally) if failed.
