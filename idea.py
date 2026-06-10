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
class VideoIdea:
    topic: str
    angle: str           # specific hook angle, e.g. "the scariest thing about black holes isn't gravity"
    format: str          # recommended format based on the angle
    target_emotion: str  # "fear" | "surprise" | "curiosity" | "humor" | "awe"
    viewer_question: str # the question the viewer is left asking, e.g. "wait, what IS it then?"


@dataclass
class VideoMetadata:
    title: str          # click-optimised YouTube title (max 100 chars)
    description: str    # full video description with context + hashtags
    hashtags: list[str] # e.g. ["#shorts", "#science", "#facts"]
    pinned_comment: str # first comment to pin, drives engagement


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


# ── Idea generation ──────────────────────────────────────────────────────────

_IDEA_PROMPT = """\
You are a YouTube Shorts strategist. Given a topic, generate the best possible viral angle.

Your job is NOT to describe the topic generally. Your job is to find the one specific angle
that will make someone stop scrolling and watch. Think: surprising fact, counterintuitive truth,
emotional hook, or jaw-dropping statistic.

Return ONLY valid JSON:
{
  "angle": "the specific hook angle as a short punchy phrase",
  "format": "one of: informative | top5 | quiz | story | mythbuster | scary | versus",
  "target_emotion": "one of: fear | surprise | curiosity | humor | awe",
  "viewer_question": "the question left unanswered in the viewer's head that makes them watch"
}"""

_METADATA_PROMPT = """\
You are a YouTube SEO expert and viral title writer. Generate metadata for a YouTube Short.

Rules for title:
- Max 60 characters ideally (hard max 100)
- Must create curiosity or urgency — never just state the topic
- Use numbers, "you", "actually", "nobody talks about", "will shock you", "at night" etc when natural
- No clickbait that lies — the video must deliver on the promise

Return ONLY valid JSON:
{
  "title": "click-optimised YouTube title",
  "description": "2-3 sentence description, includes main keywords, ends with hashtags on separate line",
  "hashtags": ["#shorts", "#relevant", "#tags"],
  "pinned_comment": "an engaging first comment that asks a question or shares a related fact to spark replies"
}"""


def generate_idea(topic: str, format_name: str | None = None) -> VideoIdea:
    """Generate a specific viral angle for *topic* using LLM."""
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=config.OPENROUTER_API_KEY,
    )
    user_msg = f"Topic: {topic}"
    if format_name:
        user_msg += f"\nPreferred format: {format_name} (suggest this unless a different format is clearly better)"

    response = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        max_tokens=256,
        messages=[
            {"role": "system", "content": _IDEA_PROMPT},
            {"role": "user",   "content": user_msg},
        ],
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    data: dict = json.loads(raw)

    idea = VideoIdea(
        topic=topic,
        angle=data["angle"],
        format=data.get("format", format_name or config.DEFAULT_FORMAT),
        target_emotion=data.get("target_emotion", "curiosity"),
        viewer_question=data.get("viewer_question", ""),
    )
    logger.info("VideoIdea — angle: %s | emotion: %s | format: %s",
                idea.angle, idea.target_emotion, idea.format)
    return idea


def generate_metadata(script: "Script", idea: VideoIdea | None = None) -> VideoMetadata:
    """Generate click-optimised YouTube metadata from a script and optional VideoIdea."""
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=config.OPENROUTER_API_KEY,
    )
    context = f"Topic: {script.topic}\nScript hook: {script.hook}\nScript excerpt: {script.full_script[:300]}"
    if idea:
        context += f"\nAngle: {idea.angle}\nTarget emotion: {idea.target_emotion}"

    response = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        max_tokens=400,
        messages=[
            {"role": "system", "content": _METADATA_PROMPT},
            {"role": "user",   "content": context},
        ],
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    data: dict = json.loads(raw)

    metadata = VideoMetadata(
        title=data["title"][:100],
        description=data.get("description", script.full_script[:500]),
        hashtags=data.get("hashtags", ["#shorts"]),
        pinned_comment=data.get("pinned_comment", ""),
    )
    logger.info("VideoMetadata — title: %s", metadata.title)
    return metadata


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

def generate_script(topic: "str | VideoIdea", format_name: str = "informative") -> Script:
    """Call LLM via OpenRouter to generate a structured video script.

    topic may be a plain string or a VideoIdea (angle + emotion used to guide the script).
    format_name selects the script structure — see formats.py for available options.
    """
    import formats as fmt

    idea: VideoIdea | None = None
    if isinstance(topic, VideoIdea):
        idea = topic
        if idea.format and idea.format != format_name:
            format_name = idea.format
        topic_str = idea.topic
    else:
        topic_str = topic

    format_def = fmt.get(format_name)

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=config.OPENROUTER_API_KEY,
    )
    logger.info("Generating script — topic: %s | format: %s | model: %s",
                topic_str, format_name, config.OPENROUTER_MODEL)

    user_content = f"Topic: {topic_str}"
    if idea:
        user_content += (
            f"\nAngle: {idea.angle}"
            f"\nTarget emotion: {idea.target_emotion}"
            f"\nViewer question to answer: {idea.viewer_question}"
        )

    response = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        max_tokens=600,
        messages=[
            {"role": "system", "content": format_def["system_prompt"]},
            {"role": "user",   "content": user_content},
        ],
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    data: dict = json.loads(raw)
    kwargs = format_def["parse"](data)

    script = Script(topic=topic_str, format=format_name, **kwargs)
    if not script.keywords:
        script.keywords = [topic_str]
    logger.info("Script generated (%d words, format: %s).",
                len(script.full_script.split()), format_name)
    return script
