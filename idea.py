"""idea.py — Fetch trending topics and generate structured video scripts via OpenRouter."""
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
    angle: str
    format: str
    target_emotion: str
    viewer_question: str


@dataclass
class VideoMetadata:
    title: str
    description: str
    hashtags: list[str]
    pinned_comment: str


@dataclass
class Script:
    topic: str
    hook: str
    core: str
    cta: str
    full_script: str
    keywords: list[str]
    theme: str
    fact_summary: str
    hook_angle: str
    clips: list[dict] = field(default_factory=list)
    beats: list[dict] = field(default_factory=list)
    format: str = "informative"
    emphasis_words: list[str] = field(default_factory=list)


_IDEA_PROMPT = """\
You are a YouTube Shorts strategist for a mind-blowing science channel.
Channel niche: {niche} — {niche_desc}.

Given a topic, generate the best possible viral angle.
Your job is NOT to describe the topic generally. Your job is to find the one specific angle
that will make someone stop scrolling and watch. Think: surprising fact, counterintuitive truth,
emotional hook, or jaw-dropping statistic.

Only use formats that fit the science niche: informative, scary, or mythbuster.

Return ONLY valid JSON:
{{
  "angle": "the specific hook angle as a short punchy phrase",
  "format": "one of: informative | scary | mythbuster",
  "target_emotion": "one of: fear | surprise | curiosity | humor | awe",
  "viewer_question": "the question left unanswered in the viewer's head that makes them watch"
}}"""

_METADATA_PROMPT = """\
You are a YouTube SEO expert and viral title writer. Generate metadata for a YouTube Short.

Rules for titles (generate 3 variants):
- Max 60 characters ideally (hard max 100)
- Each variant must take a DIFFERENT psychological angle:
  1. Curiosity gap ("The real reason X does Y")
  2. Personal threat/impact ("This is happening inside your body right now")
  3. Shocking fact/number ("X is 1000x more Y than you think")
- No clickbait that lies — the video must deliver on the promise
- All text must be natural English
- best_title_index: pick the variant most likely to get a click from a 14-year-old scrolling fast

Return ONLY valid JSON:
{
  "titles": ["title variant 1", "title variant 2", "title variant 3"],
  "best_title_index": 0,
  "description": "2-3 sentence description, includes main keywords, ends with hashtags on separate line",
  "hashtags": ["#shorts", "#relevant", "#tags"],
  "pinned_comment": "an engaging first comment that asks a question or shares a related fact to spark replies"
}"""

_METADATA_SUFFIX = """\
In addition to the format-specific fields you were already asked to return, ALSO include these JSON fields:
- "theme": short lowercase theme label like animal biology, strange engineering, deep sea behavior, ancient history
- "fact_summary": one-sentence factual summary of the unique claim or premise
- "hook_angle": one sentence describing why the hook feels surprising or clickable
- optional "title": short English title under 100 characters if you can improve the input topic
Do not omit any required fields from the chosen format schema.
All returned text fields must be natural English.
"""


# ── Idea generation ──────────────────────────────────────────────────────────

_IDEA_BATCH_PROMPT = """\
You are a YouTube Shorts strategist for a mind-blowing science channel.
Channel niche: {niche} — {niche_desc}.

Generate {count} DIFFERENT viral angle ideas for the given topic.

Rules:
- ALL ideas must be framed as counterintuitive or jaw-dropping science facts
- Only use formats that fit the niche: informative, scary, mythbuster
- Every angle must be UNIQUE — different hook, different framing
- Each angle must be a short punchy phrase that could work as the opening sentence
- Prefer angles that reference specific numbers, comparisons, or extreme scales

PROVEN WINNING FORMULA for this channel: [familiar object] + [sounds impossible/alive]
Examples of the style that works: "concrete that bleeds and heals itself", "metal that remembers its shape"
Prioritise ideas that follow this exact formula.

Among the {count} ideas, cover AT LEAST ONE of each psychological archetype:
- "Impossible object" — everyday material/substance with a property that sounds made-up (HIGHEST PRIORITY)
- "Hidden threat" — something in the viewer's environment that is secretly extreme or dangerous
- "Shocking scale" — extreme numbers or comparisons that reframe something familiar
- "Myth destroyed" — a widely-held belief that science proves wrong with a physical demonstration

Return ONLY a valid JSON array of exactly {count} objects:
[
  {{
    "angle": "specific punchy hook phrase",
    "format": "informative|scary|mythbuster",
    "target_emotion": "fear|surprise|curiosity|humor|awe",
    "viewer_question": "question left in viewer's head"
  }}
]"""

_IDEA_SCORING_PROMPT = """\
You are a viral content analyst scoring YouTube Shorts ideas for a materials science channel.
Channel niche: {niche} — {niche_desc}.

PROVEN WINNING PATTERN on this channel: familiar everyday object + property that sounds impossible
or alive (e.g. "concrete that heals itself", "metal that remembers its shape").
Heavily reward ideas that match this pattern.

Score each idea 0-100 on these criteria:
1. object_hook (25 pts) — does it feature a specific, familiar object with an impossible-sounding property?
   Full points: concrete/metal/glass/ice/sound + alien behavior.
   Partial: abstract science concept without a graspable object.
   Zero: animal facts, general space trivia, nature lists.
2. hook_strength (25 pts) — how scroll-stopping in the first 3 seconds?
3. curiosity_gap (20 pts) — does it leave a burning unanswered question?
4. visual_payoff (20 pts) — can the FIRST clip show the core claim directly?
5. comment_potential (10 pts) — will people argue, share, or react?

Return ONLY valid JSON:
{{
  "scores": [
    {{"index": 0, "total": 87, "reason": "one sentence why"}},
    ...
  ],
  "winner": 3
}}"""

_CANDIDATES_LOG = None  # initialised lazily


def _candidates_log_path():
    return config.OUTPUT_DIR / "idea_candidates.jsonl"


def _log_candidates(candidates: list[dict]) -> None:
    import time as _time
    path = _candidates_log_path()
    ts = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps({**c, "logged_at": ts}) + "\n")


def run_idea_tournament(
    topic: str,
    format_name: str | None = None,
    count: int = 10,
    insights: dict | None = None,
) -> tuple[VideoIdea, list[dict]]:
    """Generate *count* angles, score them all, return (winner VideoIdea, all candidates).

    insights: output of tracker.get_performance_insights() — when provided,
    the scorer weighs angles against what has actually performed on the channel.
    Candidates are also appended to output/idea_candidates.jsonl for debugging.
    """
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=config.OPENROUTER_API_KEY,
    )
    count = max(2, min(count, 15))
    logger.info("Idea tournament: generating %d candidates for '%s'", count, topic)

    # Step 1 — batch-generate ideas
    batch_prompt = _IDEA_BATCH_PROMPT.format(
        count=count, niche=config.NICHE, niche_desc=config.NICHE_DESCRIPTION,
    )
    user_msg = f"Topic: {topic}"
    if format_name:
        user_msg += f"\nPreferred format hint: {format_name}"

    raw = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        max_tokens=1200,
        messages=[
            {"role": "system", "content": batch_prompt},
            {"role": "user",   "content": user_msg},
        ],
    ).choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    ideas_data: list[dict] = json.loads(raw)
    if not isinstance(ideas_data, list) or not ideas_data:
        raise RuntimeError("Batch idea generation returned empty list")

    # Step 2 — score all ideas
    numbered = "\n".join(
        f"{i}. [{d.get('format','?')} / {d.get('target_emotion','?')}] {d['angle']}"
        for i, d in enumerate(ideas_data)
    )
    score_user_content = f"Topic: {topic}\n\nIdeas:\n{numbered}"
    if insights and (insights.get("format_breakdown") or insights.get("top_hooks")):
        score_user_content += (
            "\n\nActual performance data from this channel (weigh this heavily —"
            " formats and hook styles that already worked deserve higher scores):\n"
            + json.dumps(insights, ensure_ascii=False)
        )
    scoring_prompt = _IDEA_SCORING_PROMPT.format(
        niche=config.NICHE, niche_desc=config.NICHE_DESCRIPTION,
    )
    score_raw = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        max_tokens=800,
        messages=[
            {"role": "system", "content": scoring_prompt},
            {"role": "user",   "content": score_user_content},
        ],
    ).choices[0].message.content.strip()
    score_raw = re.sub(r"^```(?:json)?\s*", "", score_raw)
    score_raw = re.sub(r"\s*```$", "", score_raw)
    score_data: dict = json.loads(score_raw)

    scores_by_index = {s["index"]: s for s in score_data.get("scores", [])}
    winner_idx = int(score_data.get("winner", 0))
    winner_idx = max(0, min(winner_idx, len(ideas_data) - 1))

    # Step 3 — build candidates list
    candidates: list[dict] = []
    for i, d in enumerate(ideas_data):
        sc = scores_by_index.get(i, {})
        candidates.append({
            "topic": topic,
            "angle": d.get("angle", ""),
            "format": d.get("format", format_name or config.DEFAULT_FORMAT),
            "target_emotion": d.get("target_emotion", "curiosity"),
            "viewer_question": d.get("viewer_question", ""),
            "score": sc.get("total", 0),
            "reason": sc.get("reason", ""),
            "winner": i == winner_idx,
        })

    try:
        _log_candidates(candidates)
    except Exception as exc:
        logger.warning("Could not log idea candidates: %s", exc)

    winner_data = ideas_data[winner_idx]
    winner_format = winner_data.get("format", format_name or config.DEFAULT_FORMAT)
    if winner_format not in config.NICHE_FORMATS:
        winner_format = config.NICHE_FORMATS[0]
    winner = VideoIdea(
        topic=topic,
        angle=winner_data["angle"],
        format=winner_format,
        target_emotion=winner_data.get("target_emotion", "curiosity"),
        viewer_question=winner_data.get("viewer_question", ""),
    )
    logger.info(
        "Tournament winner (score %s): %s [%s]",
        candidates[winner_idx]["score"], winner.angle, winner.format,
    )
    return winner, candidates


def generate_idea(topic: str, format_name: str | None = None) -> VideoIdea:
    """Generate a specific viral angle for *topic* using LLM."""
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=config.OPENROUTER_API_KEY,
    )
    user_msg = f"Topic: {topic}"
    if format_name:
        user_msg += f"\nPreferred format: {format_name} (suggest this unless a different format is clearly better)"

    system_prompt = _IDEA_PROMPT.format(niche=config.NICHE, niche_desc=config.NICHE_DESCRIPTION)
    response = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        max_tokens=256,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
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
    logger.info(
        "VideoIdea — angle: %s | emotion: %s | format: %s",
        idea.angle,
        idea.target_emotion,
        idea.format,
    )
    return idea


def generate_metadata(script: Script, idea: VideoIdea | None = None) -> VideoMetadata:
    """Generate click-optimised YouTube metadata with 3 title variants; picks highest-CTR title."""
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=config.OPENROUTER_API_KEY,
    )
    context = (
        f"Topic: {script.topic}\n"
        f"Script hook: {script.hook}\n"
        f"Script excerpt: {script.full_script[:300]}"
    )
    if idea:
        context += f"\nAngle: {idea.angle}\nTarget emotion: {idea.target_emotion}"

    response = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        max_tokens=500,
        messages=[
            {"role": "system", "content": _METADATA_PROMPT},
            {"role": "user", "content": context},
        ],
    )
    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    data: dict = json.loads(raw)

    # Support both new (titles list) and old (single title) response formats
    titles = data.get("titles", [])
    if titles:
        best_idx = int(data.get("best_title_index", 0))
        best_idx = max(0, min(best_idx, len(titles) - 1))
        title = titles[best_idx][:100]
        logger.info("Title variants: %s → selected [%d]: %s", titles, best_idx, title)
    else:
        title = data.get("title", script.topic)[:100]

    metadata = VideoMetadata(
        title=title,
        description=data.get("description", script.full_script[:500]),
        hashtags=data.get("hashtags", ["#shorts"]),
        pinned_comment=data.get("pinned_comment", ""),
    )
    logger.info("VideoMetadata — title: %s", metadata.title)
    return metadata


# ── Trending topic selection ─────────────────────────────────────────────────

_SCORING_PROMPT = """\
You are a YouTube Shorts content strategist for a mind-blowing science channel.
Channel niche: {niche} — {niche_desc}.

Pick the BEST topic from the list below to make a viral short-form science video (under 60 seconds).
ONLY consider topics that can be framed as surprising, counterintuitive, or jaw-dropping science facts.
If no topic fits the science niche well, pick the one that can most naturally be given a science angle.

Score each topic on all four criteria:
1. Niche fit — can it be framed as a mind-blowing science fact?
2. Universal appeal — globally interesting, not tied to local news or regional events?
3. Visual potential — can AI-generated footage (space, lab, nature, extreme scales) cover it?
4. Hook potential — does it open with a fact that makes someone stop scrolling?

Return ONLY valid JSON:
{{
  "winner": "the best topic exactly as it appeared in the list",
  "reason": "one sentence why it wins"
}}"""


def get_trending_topic(geo: str = "SE", top_performers: list[dict] | None = None) -> str:
    """Return the best trending topic for a viral YouTube Short."""
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
        ("YouTube", _trending_via_youtube, (geo,)),
        ("Google Trends", _trending_via_pytrends, (geo,)),
        ("Hacker News", _trending_via_hackernews, ()),
        ("Google RSS", _trending_via_google_rss, (geo,)),
    ]
    for name, fn, args in sources:
        try:
            results = fn(*args)
            candidates.extend(results)
            logger.info("%s contributed %d candidates.", name, len(results))
        except Exception as exc:
            logger.warning("%s failed (%s), skipping.", name, exc)

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        key = candidate.lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)

    logger.info("Total unique candidates across all sources: %d", len(unique))
    return unique


def score_and_select_topic(candidates: list[str], top_performers: list[dict] | None = None) -> str:
    """Use LLM to pick the most viral-worthy topic from a list of candidates."""
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=config.OPENROUTER_API_KEY,
    )
    numbered = "\n".join(f"{index + 1}. {topic}" for index, topic in enumerate(candidates))
    logger.info("Scoring %d candidates via LLM...", len(candidates))

    user_content = f"Trending candidates:\n{numbered}"
    if top_performers:
        performers_text = "\n".join(
            f'- "{entry["topic"]}" — {entry["views"]:,} views'
            for entry in top_performers
        )
        user_content += (
            "\n\nPrevious top performers on this channel:\n"
            f"{performers_text}\n"
            "Prefer topics in a similar style or category to these proven performers."
        )

    scoring_prompt = _SCORING_PROMPT.format(
        niche=config.NICHE, niche_desc=config.NICHE_DESCRIPTION,
    )
    response = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        max_tokens=256,
        messages=[
            {"role": "system", "content": scoring_prompt},
            {"role": "user", "content": user_content},
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
    response = requests.get(
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
    response.raise_for_status()
    items = response.json().get("items", [])
    return [item["snippet"]["title"] for item in items if "snippet" in item]


def _trending_via_pytrends(geo: str) -> list[str]:
    from pytrends.request import TrendReq  # type: ignore

    pytrends = TrendReq(hl="sv-SE", tz=60)
    dataframe = pytrends.trending_searches(pn=geo.lower())
    return dataframe.iloc[:10, 0].tolist()


def _trending_via_hackernews() -> list[str]:
    """Fetch top story titles from the public Hacker News API (no auth required)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    base = "https://hacker-news.firebaseio.com/v0"
    ids_response = requests.get(f"{base}/topstories.json", timeout=10)
    ids_response.raise_for_status()
    top_ids: list[int] = ids_response.json()[:10]

    def _fetch_title(item_id: int) -> str | None:
        response = requests.get(f"{base}/item/{item_id}.json", timeout=10)
        response.raise_for_status()
        return response.json().get("title")

    titles: list[str] = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_fetch_title, item_id): item_id for item_id in top_ids}
        for future in as_completed(futures):
            try:
                title = future.result()
                if title:
                    titles.append(title)
            except Exception:
                pass
    return titles


def _trending_via_google_rss(geo: str) -> list[str]:
    import xml.etree.ElementTree as ET

    urls = [
        f"https://trends.google.com/trends/trendingsearches/daily/rss?geo={geo.upper()}",
        f"https://trends.google.com/trending/rss?geo={geo.upper()}",
    ]
    for url in urls:
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            root = ET.fromstring(response.text)
            titles = [text.strip() for element in root.findall(".//item/title") if (text := element.text)]
            if titles:
                return titles
        except Exception:
            continue
    raise RuntimeError("No trending topics found in Google RSS feed")


# ── Script generation ─────────────────────────────────────────────────────────

def generate_script(topic: str | VideoIdea, format_name: str = "informative") -> Script:
    """Call LLM via OpenRouter to generate a structured video script.

    topic may be a plain string or a VideoIdea (angle + emotion used to guide the script).
    format_name selects the script structure — see formats.py for available options.
    """
    import formats as fmt
    from content_registry import build_avoidance_prompt, is_duplicate_candidate

    idea: VideoIdea | None = None
    if isinstance(topic, VideoIdea):
        idea = topic
        if idea.format and idea.format != format_name:
            format_name = idea.format
        topic_str = idea.topic
    else:
        topic_str = topic

    if is_duplicate_candidate(topic=topic_str, fact_summary="", registry_path=config.CONTENT_REGISTRY_PATH):
        raise ValueError(f"Topic already exists in registry: {topic_str}")

    format_def = fmt.get(format_name)
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=config.OPENROUTER_API_KEY,
    )
    logger.info(
        "Generating script — topic: %s | format: %s | model: %s",
        topic_str,
        format_name,
        config.OPENROUTER_MODEL,
    )

    system_prompt = f"{format_def['system_prompt']}\n\n{_METADATA_SUFFIX}"
    avoidance_prompt = build_avoidance_prompt(registry_path=config.CONTENT_REGISTRY_PATH)
    user_content = f"Topic: {topic_str}\n\n{avoidance_prompt}"
    if idea:
        user_content += (
            f"\n\nAngle: {idea.angle}"
            f"\nTarget emotion: {idea.target_emotion}"
            f"\nViewer question to answer: {idea.viewer_question}"
        )

    response = client.chat.completions.create(
        model=config.OPENROUTER_MODEL,
        max_tokens=1400,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )

    raw = response.choices[0].message.content.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    data: dict = json.loads(raw)
    parsed = format_def["parse"](data)
    script = Script(
        topic=str(data.get("title") or topic_str),
        hook=parsed["hook"],
        core=parsed.get("core", ""),
        cta=parsed.get("cta", ""),
        full_script=parsed["full_script"],
        keywords=parsed.get("keywords", []) or [topic_str],
        theme=str(data.get("theme") or f"{format_name} facts"),
        fact_summary=str(data.get("fact_summary") or parsed["full_script"][:160]),
        hook_angle=str(data.get("hook_angle") or parsed["hook"]),
        clips=parsed.get("clips", []),
        beats=parsed.get("beats", []),
        format=format_name,
        emphasis_words=parsed.get("emphasis_words", []),
    )

    if is_duplicate_candidate(
        topic=script.topic,
        theme=script.theme,
        fact_summary=script.fact_summary,
        hook_angle=script.hook_angle,
        registry_path=config.CONTENT_REGISTRY_PATH,
    ):
        raise ValueError(
            "Generated script duplicates existing registry entry: "
            f"{script.topic} / {script.fact_summary}"
        )

    logger.info("Script generated (%d words, format: %s).", len(script.full_script.split()), format_name)
    return script
