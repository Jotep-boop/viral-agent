"""idea.py — Fetch a trending topic and generate a video script via OpenRouter."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import requests
from openai import OpenAI

import config

logger = logging.getLogger(__name__)


@dataclass
class Script:
    topic: str
    hook: str       # 0-3 sec
    core: str       # 3-25 sec
    cta: str        # 25-30 sec
    full_script: str
    keywords: list[str]


# ── Trending topic ────────────────────────────────────────────────────────────

def get_trending_topic(geo: str = "SE") -> str:
    """Return a trending search topic. Tries pytrends → Reddit → Google Trends RSS."""
    try:
        return _trending_via_pytrends(geo)
    except Exception as exc:
        logger.warning("pytrends failed (%s), falling back to Reddit.", exc)
    try:
        return _trending_via_reddit()
    except Exception as exc:
        logger.warning("Reddit failed (%s), falling back to Google Trends RSS.", exc)
    return _trending_via_google_rss(geo)


def _trending_via_pytrends(geo: str) -> str:
    from pytrends.request import TrendReq  # type: ignore
    pt = TrendReq(hl="sv-SE", tz=60)
    df = pt.trending_searches(pn=geo.lower())
    topic: str = df.iloc[0, 0]
    logger.info("Trending topic (Google Trends): %s", topic)
    return topic


def _trending_via_reddit() -> str:
    url = "https://www.reddit.com/r/popular/hot.json?limit=5"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"}
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    posts = resp.json()["data"]["children"]
    topic: str = posts[0]["data"]["title"]
    logger.info("Trending topic (Reddit): %s", topic)
    return topic


def _trending_via_google_rss(geo: str) -> str:
    url = f"https://trends.google.com/trending/rss?geo={geo.upper()}"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    import xml.etree.ElementTree as ET
    root = ET.fromstring(resp.text)
    title = root.find(".//item/title")
    if title is None or not title.text:
        raise RuntimeError("No trending topics found in Google RSS feed")
    topic = title.text.strip()
    logger.info("Trending topic (Google RSS): %s", topic)
    return topic


# ── Script generation ─────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert viral short-form video scriptwriter for TikTok/Reels/Shorts.

Your goal is to create VIRAL content that gets millions of views. Focus on:
- Mind-blowing facts and "did you know" content
- Funny or absurd animal behavior
- Jaw-dropping science, nature, or space facts
- Psychology tricks and surprising brain facts
- "You've been doing X wrong your whole life" reveals
- Shocking comparisons or scale visualizations

IMPORTANT RULES:
1. Always make the content UNIVERSAL and globally appealing.
   Never make videos about local news, small towns, or regional events.
   The topic is just inspiration — twist it into something viral and shareable.
2. The script is a VOICEOVER played over stock footage clips.
   NEVER reference anything visual on screen ("look at this", "stare at this image",
   "watch this", "see this", "as you can see"). The viewer sees unrelated stock footage,
   not what the script describes. Write as a pure narrator telling amazing facts.
3. Never instruct the viewer to do something with the video itself (pause, rewind, etc.)

Return ONLY valid JSON with this exact structure:
{
  "hook": "Opening 1-2 sentence hook (first 3 seconds, must grab attention)",
  "core": "Main content (15-20 seconds, 3-4 interesting facts or a mini story)",
  "cta": "Call to action (last 5 seconds, e.g. follow/share)",
  "full_script": "Complete script as one block",
  "keywords": ["keyword1", "keyword2", "keyword3"]
}
The full_script should be around 80-100 words total — fast-paced narration.
Keywords MUST be generic English terms suitable for stock footage search (e.g. "ocean waves", "cute animals", "space galaxy") — never use place names or proper nouns as keywords.\
"""


def generate_script(topic: str) -> Script:
    """Call LLM via OpenRouter to generate a structured video script for *topic*."""
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=config.OPENROUTER_API_KEY,
    )
    logger.info("Generating script for topic: %s (model: %s)", topic, config.OPENROUTER_MODEL)

    response = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        max_tokens=512,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Topic: {topic}"},
        ],
    )

    raw = response.choices[0].message.content.strip()

    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    data: dict = json.loads(raw)

    script = Script(
        topic=topic,
        hook=data["hook"],
        core=data["core"],
        cta=data["cta"],
        full_script=data["full_script"],
        keywords=data.get("keywords", [topic]),
    )
    logger.info("Script generated (%d words).", len(script.full_script.split()))
    return script
