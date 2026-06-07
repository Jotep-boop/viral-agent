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
    """Return a trending search topic. Falls back to Reddit if pytrends fails."""
    try:
        return _trending_via_pytrends(geo)
    except Exception as exc:
        logger.warning("pytrends failed (%s), falling back to Reddit.", exc)
        return _trending_via_reddit()


def _trending_via_pytrends(geo: str) -> str:
    from pytrends.request import TrendReq  # type: ignore
    pt = TrendReq(hl="sv-SE", tz=60)
    df = pt.trending_searches(pn=geo.lower())
    topic: str = df.iloc[0, 0]
    logger.info("Trending topic (Google Trends): %s", topic)
    return topic


def _trending_via_reddit() -> str:
    url = "https://www.reddit.com/r/popular/hot.json?limit=5"
    headers = {"User-Agent": "viral-agent/1.0"}
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    posts = resp.json()["data"]["children"]
    topic: str = posts[0]["data"]["title"]
    logger.info("Trending topic (Reddit): %s", topic)
    return topic


# ── Script generation ─────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert viral short-form video scriptwriter.
Given a topic, write a punchy script for a 30-second vertical video (TikTok/Reels/Shorts).

Return ONLY valid JSON with this exact structure:
{
  "hook": "Opening 1-2 sentence hook (first 3 seconds, must grab attention)",
  "core": "Main content (15-20 seconds, 3-4 interesting facts or a mini story)",
  "cta": "Call to action (last 5 seconds, e.g. follow/share)",
  "full_script": "Complete script as one block",
  "keywords": ["keyword1", "keyword2", "keyword3"]
}
The full_script should be around 80-100 words total — fast-paced narration.\
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
