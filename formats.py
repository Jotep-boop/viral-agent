"""formats.py — Video format registry for the viral-agent pipeline.

A format controls two things:
  - The LLM system prompt  (script structure, tone, JSON schema)
  - How the JSON response is parsed back into a Script object

Available formats
-----------------
informative  (default)
    Classic "did you know" voiceover with mind-blowing facts.
    Best for: science, psychology, nature, space, history.
    Script structure: hook → 3-4 facts → CTA

top5
    Countdown from 5 → 1. Number 1 is the climax / most surprising item.
    Best for: rankings, comparisons, "top X reasons why / ways to..."
    Script structure: intro hook → item 5 → 4 → 3 → 2 → 1 → CTA

How to add a new format
-----------------------
1. Write a SYSTEM_PROMPT string that tells the LLM the script structure
   and the exact JSON schema it should return.
2. Write a parse(data: dict) -> dict function that maps the LLM JSON
   fields to Script fields: hook, core, cta, full_script, keywords, clips.
3. Register it in FORMATS at the bottom of this file with a short
   description string — this is what list_formats() returns to agents.

The pipeline only reads: full_script (TTS), clips (AI video), keywords
(Pexels fallback), hook/core/cta (metadata). The rest of the JSON from
the LLM is format-specific and consumed only by parse().
"""
from __future__ import annotations

# ── Prompts ───────────────────────────────────────────────────────────────────

_INFORMATIVE_PROMPT = """\
You are an expert viral short-form video scriptwriter for TikTok/Reels/Shorts.

Your goal is to create VIRAL content that gets millions of views. Focus on:
- Mind-blowing facts and "did you know" content
- Funny or absurd animal behavior
- Jaw-dropping science, nature, or space facts
- Psychology tricks and surprising brain facts
- "You've been doing X wrong your whole life" reveals
- Shocking comparisons or scale visualizations

RULES:
1. Universal appeal only — no local news, small towns, or regional events.
2. Voiceover over AI-generated clips — NEVER reference visuals on screen.
3. Never tell the viewer to pause, rewind, or interact with the video.

Return ONLY valid JSON:
{
  "hook": "Opening 1-2 sentence hook (first 3 seconds, must grab attention)",
  "core": "Main content (15-20 seconds, 3-4 interesting facts or a mini story)",
  "cta": "Call to action (last 5 seconds, e.g. follow/share)",
  "full_script": "Complete script as one block (~80-100 words)",
  "keywords": ["fallback1", "fallback2", "fallback3"],
  "clips": [
    {"prompt": "specific funny/visual scene for AI video generation, portrait 9:16", "duration": 5},
    {"prompt": "...", "duration": 5},
    {"prompt": "...", "duration": 5},
    {"prompt": "...", "duration": 5}
  ]
}
keywords: generic English terms for stock footage fallback, no place names.
clips: 4-5 clips, each prompt specific and visual — direct like a film director.\
"""

_TOP5_PROMPT = """\
You are an expert viral short-form video scriptwriter for TikTok/Reels/Shorts.

Create a TOP 5 countdown video. Build suspense — save the most surprising item for Number 1.

Structure:
- Hook: "Here are the top 5 [X]..." (1-2 sentences)
- Items 5 → 1: "Number [N]: [title]. [1-2 punchy sentences]."
- CTA: one closing sentence (follow/share)

RULES:
1. Universal appeal — no local news or regional events.
2. Voiceover only — never reference visuals on screen.
3. Total script 90-110 words. Each item concise and punchy.
4. Number 1 must feel like a satisfying climax.

Return ONLY valid JSON:
{
  "hook": "Opening hook sentence(s)",
  "items": [
    {"rank": 5, "title": "Short title", "description": "1-2 sentences read aloud."},
    {"rank": 4, "title": "...", "description": "..."},
    {"rank": 3, "title": "...", "description": "..."},
    {"rank": 2, "title": "...", "description": "..."},
    {"rank": 1, "title": "...", "description": "..."}
  ],
  "cta": "Closing call to action",
  "full_script": "Complete script with 'Number 5:', 'Number 4:' etc. as one block",
  "keywords": ["fallback1", "fallback2", "fallback3"],
  "clips": [
    {"prompt": "visual scene matching item 5, portrait 9:16, specific and entertaining", "duration": 5},
    {"prompt": "visual scene matching item 4", "duration": 5},
    {"prompt": "visual scene matching item 3", "duration": 5},
    {"prompt": "visual scene matching item 2", "duration": 5},
    {"prompt": "most dramatic/funny scene for the Number 1 reveal", "duration": 6}
  ]
}
clips: one clip per item in order 5 → 1. Make the Number 1 clip the most impressive.\
"""


# ── Parsers ───────────────────────────────────────────────────────────────────

def _parse_informative(data: dict) -> dict:
    return {
        "hook": data["hook"],
        "core": data["core"],
        "cta": data["cta"],
        "full_script": data["full_script"],
        "keywords": data.get("keywords", []),
        "clips": data.get("clips", []),
    }


def _parse_top5(data: dict) -> dict:
    items = data.get("items", [])
    core = " | ".join(f"#{i['rank']} {i['title']}" for i in items)
    return {
        "hook": data["hook"],
        "core": core,
        "cta": data["cta"],
        "full_script": data["full_script"],
        "keywords": data.get("keywords", []),
        "clips": data.get("clips", []),
    }


# ── Registry ──────────────────────────────────────────────────────────────────

FORMATS: dict[str, dict] = {
    "informative": {
        "description": (
            "Classic 'did you know' voiceover with mind-blowing facts. "
            "Best for: science, psychology, nature, space, history."
        ),
        "system_prompt": _INFORMATIVE_PROMPT,
        "parse": _parse_informative,
    },
    "top5": {
        "description": (
            "Countdown Top 5 list — Number 1 is the climax. "
            "Best for: rankings, comparisons, 'top X reasons / ways to...'"
        ),
        "system_prompt": _TOP5_PROMPT,
        "parse": _parse_top5,
    },
}


def get(name: str) -> dict:
    """Return a format dict. Raises ValueError for unknown names."""
    if name not in FORMATS:
        raise ValueError(
            f"Unknown format {name!r}. Available: {list(FORMATS)}"
        )
    return FORMATS[name]
