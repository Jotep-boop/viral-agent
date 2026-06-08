"""idea.py — Fetch a trending topic and generate a video script via OpenRouter."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

import requests
from openai import OpenAI

import config

logger = logging.getLogger(__name__)


@dataclass
class Script:
    topic: str
    hook: str         # 0-3 sec
    core: str         # 3-25 sec
    cta: str          # 25-30 sec
    full_script: str
    keywords: list[str]
    clips: list[dict] = field(default_factory=list)  # per-clip AI video prompts
    format: str = "informative"                       # which format produced this script


# ── Trending topic ────────────────────────────────────────────────────────────

_SCORING_PROMPT = """\
You are a YouTube Shorts content strategist. Pick the BEST topic from the list below to make a viral short-form video (under 60 seconds).

Score each topic on all four criteria:
1. Hook potential — can it open with a "did you know" or jaw-dropping fact?
2. Universal appeal — globally interesting, not tied to local news or regional events?
3. Visual potential — can generic stock footage (nature, animals, space, people) cover it?
4. Momentum — does it feel fresh and on the rise, not already saturated?

Return ONLY valid JSON:
{
  "winner": "the best topic exactly as it appeared in the list",
  "reason": "one sentence why it wins"
}"""


def get_trending_topic(geo: str = "SE", top_performers: list[dict] | None = None) -> str:
    """Return the best trending topic for a viral YouTube Short.

    Gathers candidates from multiple sources, then uses an LLM to score
    and select the one with the highest viral potential.
    top_performers: previous high-view entries from tracker.get_top_performers().
    """
    candidates = get_trending_candidates(geo)
    if not candidates:
        raise RuntimeError("No trending candidates found from any source")
    if len(candidates) == 1:
        return candidates[0]
    return score_and_select_topic(candidates, top_performers or [])


def get_trending_candidates(geo: str = "SE") -> list[str]:
    """Gather trending topic candidates from all available sources."""
    candidates: list[str] = []
    sources = [
        ("YouTube",       _trending_via_youtube,     (geo,)),
        ("Google Trends", _trending_via_pytrends,    (geo,)),
        ("Hacker News",   _trending_via_hackernews,  ()),
        ("Google RSS",    _trending_via_google_rss,  (geo,)),
    ]
    for name, fn, args in sources:
        try:
            results = fn(*args)
            candidates.extend(results)
            logger.info("%s contributed %d candidates.", name, len(results))
        except Exception as exc:
            logger.warning("%s failed (%s), skipping.", name, exc)

    # Deduplicate while preserving insertion order
    seen: set[str] = set()
    unique: list[str] = []
    for c in candidates:
        key = c.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(c)

    logger.info("Total unique candidates across all sources: %d", len(unique))
    return unique


def score_and_select_topic(candidates: list[str], top_performers: list[dict] | None = None) -> str:
    """Use LLM to pick the most viral-worthy topic from a list of candidates."""
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=config.OPENROUTER_API_KEY,
    )
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(candidates))
    logger.info("Scoring %d candidates via LLM...", len(candidates))

    user_content = f"Trending candidates:\n{numbered}"
    if top_performers:
        performers_text = "\n".join(
            f'- "{p["topic"]}" — {p["views"]:,} views'
            for p in top_performers
        )
        user_content += f"\n\nPrevious top performers on this channel:\n{performers_text}\nPrefer topics in a similar style or category to these proven performers."

    response = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        max_tokens=256,
        messages=[
            {"role": "system", "content": _SCORING_PROMPT},
            {"role": "user",   "content": user_content},
        ],
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    data: dict = json.loads(raw)
    winner: str = data["winner"]
    reason: str = data.get("reason", "")
    logger.info("Selected topic: %s — %s", winner, reason)
    return winner


def _trending_via_youtube(geo: str) -> list[str]:
    """Fetch titles of the most popular YouTube videos in the given region."""
    if not config.YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY not configured")
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/videos",
        params={
            "part": "snippet",
            "chart": "mostPopular",
            "regionCode": geo.upper(),
            "maxResults": 10,
            "key": config.YOUTUBE_API_KEY,
        },
        timeout=10,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    return [item["snippet"]["title"] for item in items if "snippet" in item]


def _trending_via_pytrends(geo: str) -> list[str]:
    from pytrends.request import TrendReq  # type: ignore
    pt = TrendReq(hl="sv-SE", tz=60)
    df = pt.trending_searches(pn=geo.lower())
    topics: list[str] = df.iloc[:10, 0].tolist()
    return topics


def _trending_via_hackernews() -> list[str]:
    """Fetch top story titles from the public Hacker News API (no auth required)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    base = "https://hacker-news.firebaseio.com/v0"
    ids_resp = requests.get(f"{base}/topstories.json", timeout=10)
    ids_resp.raise_for_status()
    top_ids: list[int] = ids_resp.json()[:10]

    def _fetch_title(item_id: int) -> str | None:
        r = requests.get(f"{base}/item/{item_id}.json", timeout=10)
        r.raise_for_status()
        return r.json().get("title")

    titles: list[str] = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_fetch_title, i): i for i in top_ids}
        for f in as_completed(futures):
            try:
                title = f.result()
                if title:
                    titles.append(title)
            except Exception:
                pass
    return titles


def _trending_via_google_rss(geo: str) -> list[str]:
    import xml.etree.ElementTree as ET
    # The older daily path is more stable; try it first before the newer /trending/rss
    urls = [
        f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo.upper()}",
        f"https://trends.google.com/trending/rss?geo={geo.upper()}",
    ]
    for url in urls:
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
            titles = [el.text.strip() for el in root.findall(".//item/title") if el.text]
            if titles:
                return titles
        except Exception:
            continue
    raise RuntimeError("No trending topics found in Google RSS feed")


# ── Script generation ─────────────────────────────────────────────────────────

def generate_script(topic: str, format_name: str = "informative") -> Script:
    """Call LLM via OpenRouter to generate a structured video script for *topic*.

    format_name selects the script structure — see formats.py for available options.
    """
    import formats as fmt
    format_def = fmt.get(format_name)

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=config.OPENROUTER_API_KEY,
    )
    logger.info("Generating script — topic: %s | format: %s | model: %s",
                topic, format_name, config.OPENROUTER_MODEL)

    response = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        max_tokens=600,
        messages=[
            {"role": "system", "content": format_def["system_prompt"]},
            {"role": "user",   "content": f"Topic: {topic}"},
        ],
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    data: dict = json.loads(raw)
    kwargs = format_def["parse"](data)

    script = Script(topic=topic, format=format_name, **kwargs)
    if not script.keywords:
        script.keywords = [topic]
    logger.info("Script generated (%d words, format: %s).",
                len(script.full_script.split()), format_name)
    return script
