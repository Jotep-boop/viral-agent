"""formats.py — Video format registry for the viral-agent pipeline.

A format controls two things:
  - The LLM system prompt  (script structure, tone, JSON schema)
  - How the JSON response is parsed back into a Script object

Available formats
-----------------
informative  (default)
    Classic "did you know" voiceover — mind-blowing facts.
    Best for: science, psychology, nature, space, history.
    Hook → 3-4 facts → CTA

top5
    Countdown from 5 → 1. Number 1 is the climax.
    Best for: rankings, comparisons, "top X reasons why..."
    Hook → items 5..1 → CTA

quiz
    Poses a surprising question, builds tension, then reveals the answer.
    Drives comments ("comment before the reveal") = algorithm boost.
    Best for: science trivia, psychology, history, surprising statistics.
    Question hook → context/stakes → "comment your answer" beat → reveal → CTA

story
    Narrative arc: setup → tension → twist/climax → resolution.
    High watch-time format. Best for: true events, animal/human drama,
    historical moments, "this actually happened" content.
    Hook → setup → rising tension → twist → resolution → CTA

mythbuster
    States a widely-believed myth, then debunks it with the surprising truth.
    Strong share-bait. Best for: science, health, history, common misconceptions.
    Myth hook → "but the truth is..." → explanation → mind-blown moment → CTA

scary
    Dark, unsettling facts delivered with building dread.
    High engagement, tends to get shared. Best for: nature, space, deep sea,
    psychological horror, survival, existential facts.
    Eerie hook → 2-3 chilling facts building to climax → haunting close → CTA

versus
    Head-to-head comparison of two things, building to a surprising winner.
    Best for: animals, historical figures, technologies, natural phenomena.
    "X vs Y" hook → compare on 3 dimensions → surprising winner reveal → CTA

How to add a new format
-----------------------
1. Write a SYSTEM_PROMPT string describing the script structure and the
   exact JSON schema the LLM should return.
2. Write a parse(data: dict) -> dict function mapping LLM JSON fields to
   Script fields: hook, core, cta, full_script, keywords, clips.
3. Add an entry to FORMATS at the bottom with a short description string
   — this is what list_formats() returns to agents like Hermes.

The pipeline only consumes: full_script (TTS), clips (AI video),
keywords (Pexels fallback), hook/core/cta (metadata).
"""
from __future__ import annotations

# ── Shared clip instructions (appended to every prompt) ───────────────────────

_CLIP_RULES = """\
clips: Generate one clip per major script beat (4-6 total).
CRITICAL — clip rules:
1. The FIRST clip MUST show the core claim/payoff visually. If the topic is
   "platypuses glow under UV light", clip 1 shows the glowing fur — NOT a lab setup.
   Start with the most surprising visual, not the background.
2. Every clip must be UNIQUE — no two clips of the same type (e.g. not 3x "scientist
   in lab"). Each clip should show a different visual angle or scene.
3. Prompts must be SPECIFIC and film-directed: "a platypus's brown fur glowing
   electric blue-green under ultraviolet light in a dark lab" not "glowing animal".
4. Portrait 9:16 format. Duration 4-6 seconds each.
5. Match the emotional tone of the script beat.\
"""

# ── Prompts ───────────────────────────────────────────────────────────────────

_INFORMATIVE_PROMPT = f"""\
You are an expert viral short-form video scriptwriter for TikTok/Reels/Shorts.

Create a "did you know" style voiceover with mind-blowing facts. Focus on:
- Surprising science, nature, space, psychology, or history
- "You've been doing X wrong" reveals
- Shocking comparisons or scale visualisations
- Funny or absurd animal behaviour

RULES:
1. Universal appeal — no local news, regional events, or place names.
2. Voiceover only — NEVER reference visuals on screen ("look at this", "see here", etc.).
3. Total script 80-100 words. Fast-paced narration.
4. START WITH THE SURPRISING FACT — never open with background the viewer already knows
   ("X is a weird animal" / "Everyone knows X" / "Did you know"). Drop them into the
   payoff on word one. Save the "why/how" for after you've hooked them.

Return ONLY valid JSON:
{{
  "hook": "Opening 1-2 sentence hook (first 3 seconds, must grab attention)",
  "core": "Main content (15-20 seconds, 3-4 interesting facts)",
  "cta": "Call to action (last 5 seconds)",
  "full_script": "Complete script as one block",
  "keywords": ["fallback1", "fallback2", "fallback3"],
  "clips": [
    {{"prompt": "...", "duration": 5}},
    {{"prompt": "...", "duration": 5}},
    {{"prompt": "...", "duration": 5}},
    {{"prompt": "...", "duration": 5}}
  ]
}}
keywords: generic English terms for stock footage fallback, no place names.
{_CLIP_RULES}\
"""

_TOP5_PROMPT = f"""\
You are an expert viral short-form video scriptwriter for TikTok/Reels/Shorts.

Create a TOP 5 countdown video. Build suspense — save the most surprising for #1.

Structure: Hook → "Number 5: [title]. [1-2 sentences]." → ... → "Number 1: ..." → CTA
Total script 90-110 words. Each item must be punchy and concise.

RULES:
1. Universal appeal — no local news or regional events.
2. Voiceover only — NEVER reference visuals on screen.
3. Number 1 must feel like a satisfying climax.
4. Hook must tease the payoff — don't open with "did you know" or generic setup.

Return ONLY valid JSON:
{{
  "hook": "Opening hook sentence(s)",
  "items": [
    {{"rank": 5, "title": "Short title", "description": "1-2 sentences."}},
    {{"rank": 4, "title": "...", "description": "..."}},
    {{"rank": 3, "title": "...", "description": "..."}},
    {{"rank": 2, "title": "...", "description": "..."}},
    {{"rank": 1, "title": "...", "description": "..."}}
  ],
  "cta": "Closing call to action",
  "full_script": "Complete script with 'Number 5:' etc. as one block",
  "keywords": ["fallback1", "fallback2", "fallback3"],
  "clips": [
    {{"prompt": "scene matching item 5, portrait 9:16", "duration": 5}},
    {{"prompt": "scene matching item 4", "duration": 5}},
    {{"prompt": "scene matching item 3", "duration": 5}},
    {{"prompt": "scene matching item 2", "duration": 5}},
    {{"prompt": "most dramatic scene for the Number 1 reveal", "duration": 6}}
  ]
}}
{_CLIP_RULES}\
"""

_QUIZ_PROMPT = f"""\
You are an expert viral short-form video scriptwriter for TikTok/Reels/Shorts.

Create a QUIZ/TRIVIA video. The goal is to make viewers stop and comment their
answer before the reveal — this signals high engagement to the algorithm.

Structure:
- Hook: pose a surprising, specific question (something viewers think they know)
- Setup: give just enough context to make it feel answerable (2-3 sentences)
- Pause beat: "Comment your answer before I reveal it..." (1 sentence)
- Reveal: the surprising correct answer (2-3 sentences explaining why)
- CTA: "Follow for more" + "Were you right?"

RULES:
1. The question must feel answerable but have a surprising answer.
2. Voiceover only — never reference visuals on screen.
3. Total script 70-90 words. Keep the pause beat short and punchy.

Return ONLY valid JSON:
{{
  "hook": "The question (1-2 sentences)",
  "setup": "Context that makes it feel answerable",
  "pause": "Comment your answer beat (1 sentence)",
  "reveal": "The surprising answer + explanation",
  "cta": "Follow + were you right?",
  "full_script": "Complete script as one block",
  "keywords": ["fallback1", "fallback2", "fallback3"],
  "clips": [
    {{"prompt": "intriguing scene setting up the question, portrait 9:16", "duration": 5}},
    {{"prompt": "thinking/suspense scene during the pause beat", "duration": 4}},
    {{"prompt": "dramatic reveal moment scene", "duration": 5}},
    {{"prompt": "celebratory or mind-blown reaction scene", "duration": 4}}
  ]
}}
{_CLIP_RULES}\
"""

_STORY_PROMPT = f"""\
You are an expert viral short-form video scriptwriter for TikTok/Reels/Shorts.

Create a SHORT STORY video — a real or believable narrative with emotional stakes.
The story must feel true even if it's a generalised scenario. High watch-time format.

Structure:
- Hook: drop the viewer into the most gripping moment ("In 2019, a scientist noticed...")
- Setup: quick background — who, what, where (2-3 sentences)
- Rising tension: the problem or conflict escalates (2-3 sentences)
- Twist/climax: the surprising resolution or revelation (2 sentences)
- CTA: "Follow for more stories like this"

RULES:
1. No specific real people by name unless widely known. No local events.
2. Voiceover only — never reference visuals on screen.
3. Total script 90-110 words. Keep pace brisk — no filler.

Return ONLY valid JSON:
{{
  "hook": "Opening hook dropping into the action",
  "setup": "Background context",
  "tension": "Escalating conflict",
  "twist": "Surprise resolution or revelation",
  "cta": "Call to action",
  "full_script": "Complete story as one block",
  "keywords": ["fallback1", "fallback2", "fallback3"],
  "clips": [
    {{"prompt": "cinematic establishing shot matching the story setting, portrait 9:16", "duration": 5}},
    {{"prompt": "tense/dramatic scene matching the conflict", "duration": 5}},
    {{"prompt": "scene matching the twist moment — surprised or shocked expression", "duration": 5}},
    {{"prompt": "resolution scene — relief, wonder, or awe", "duration": 5}}
  ]
}}
{_CLIP_RULES}\
"""

_MYTHBUSTER_PROMPT = f"""\
You are an expert viral short-form video scriptwriter for TikTok/Reels/Shorts.

Create a MYTH BUSTING video. State a widely-believed myth confidently, then
destroy it with the surprising truth. Strong share-bait — people tag friends.

Structure:
- Hook: state the myth as if true ("Everyone knows you only use 10% of your brain...")
- Myth established: 1 sentence reinforcing why people believe it
- "But here's the truth:" — pivot line (1 sentence)
- Truth: the real explanation, 2-3 surprising sentences
- Mind-blown closer: one punchy sentence landing the revelation
- CTA: follow for more myths debunked

RULES:
1. The myth must be genuinely widely believed. The truth must be genuinely surprising.
2. Voiceover only — NEVER reference visuals on screen.
3. Total script 80-100 words.
4. State the myth with conviction on word one — no "did you know" preamble.

Return ONLY valid JSON:
{{
  "hook": "State the myth confidently (1-2 sentences)",
  "myth": "Why people believe it (1 sentence)",
  "pivot": "But here's the truth... (1 sentence)",
  "truth": "The real explanation (2-3 sentences)",
  "closer": "Mind-blown punchline (1 sentence)",
  "cta": "Follow for more myths debunked",
  "full_script": "Complete script as one block",
  "keywords": ["fallback1", "fallback2", "fallback3"],
  "clips": [
    {{"prompt": "confident person stating something wrong, portrait 9:16", "duration": 4}},
    {{"prompt": "dramatic 'plot twist' / mind blown moment", "duration": 4}},
    {{"prompt": "scene illustrating the surprising truth", "duration": 5}},
    {{"prompt": "awe or disbelief reaction scene", "duration": 4}}
  ]
}}
{_CLIP_RULES}\
"""

_SCARY_PROMPT = f"""\
You are an expert viral short-form video scriptwriter for TikTok/Reels/Shorts.

Create a SCARY FACTS video — real, unsettling facts delivered with building dread.
The tone should be eerie, clinical, and matter-of-fact. Not gory — deeply unsettling.
Focus on: deep sea, space, psychology, parasites, survival, existential facts.

Structure:
- Hook: one deeply unsettling opener ("The deep ocean covers 71% of Earth and
  we've explored less than 20% of it. Here's what we've found.")
- 2-3 escalating scary facts, each darker than the last
- Climax: the most disturbing fact saved for last
- Haunting close: one chilling sentence (not a CTA — let it sink in)
- CTA: "Follow if you dare"

RULES:
1. Facts must be real or scientifically plausible. No gore or graphic violence.
2. Voiceover only — NEVER reference visuals on screen.
3. Total script 80-100 words. Slow delivery implied — shorter is fine.
4. Open with the most unsettling fact immediately — don't warm up with context.

Return ONLY valid JSON:
{{
  "hook": "Eerie opening hook",
  "facts": ["fact 1", "fact 2", "fact 3 (darkest)"],
  "closer": "Final haunting sentence",
  "cta": "Follow if you dare",
  "full_script": "Complete script as one block",
  "keywords": ["fallback1", "fallback2", "fallback3"],
  "clips": [
    {{"prompt": "dark, eerie establishing scene matching the topic, portrait 9:16", "duration": 5}},
    {{"prompt": "unsettling visual — deep dark water / vast empty space / microscopic horror", "duration": 5}},
    {{"prompt": "creepy close-up or abstract disturbing natural scene", "duration": 5}},
    {{"prompt": "final dark, haunting image — slow zoom, dim lighting", "duration": 6}}
  ]
}}
{_CLIP_RULES}\
"""

_VERSUS_PROMPT = f"""\
You are an expert viral short-form video scriptwriter for TikTok/Reels/Shorts.

Create a VERSUS / COMPARISON video. Pit two things head-to-head and build to a
surprising winner. Works best when the expected winner turns out to be wrong.

Structure:
- Hook: "X vs Y — which one wins?" (1-2 sentences, pick something unexpected)
- Round 1: compare on first dimension — could go either way
- Round 2: compare on second dimension — tension builds
- Round 3/Final: the decisive, surprising comparison
- Reveal: announce the winner with a punchy reason
- CTA: "Follow for more versus battles"

RULES:
1. The winner should be surprising — subvert expectations.
2. Voiceover only — NEVER reference visuals on screen.
3. Total script 80-100 words. Keep each round punchy (1-2 sentences).
4. Hook must set up a genuine "wait, who wins?" tension from the first word.

Return ONLY valid JSON:
{{
  "hook": "X vs Y hook question",
  "rounds": [
    {{"label": "Round 1 dimension", "result": "1-2 sentences"}},
    {{"label": "Round 2 dimension", "result": "1-2 sentences"}},
    {{"label": "Final round", "result": "1-2 sentences"}}
  ],
  "winner": "Announcement + surprising reason (1-2 sentences)",
  "cta": "Follow for more versus battles",
  "full_script": "Complete script as one block",
  "keywords": ["fallback1", "fallback2", "fallback3"],
  "clips": [
    {{"prompt": "visual representing X (left competitor), portrait 9:16", "duration": 4}},
    {{"prompt": "visual representing Y (right competitor)", "duration": 4}},
    {{"prompt": "dramatic head-to-head clash or competition scene", "duration": 5}},
    {{"prompt": "winner celebration / dramatic victory moment", "duration": 5}}
  ]
}}
{_CLIP_RULES}\
"""


# ── Parsers ───────────────────────────────────────────────────────────────────

def _parse_simple(data: dict) -> dict:
    """Default parser — works for formats whose JSON maps directly to hook/core/cta."""
    return {
        "hook":        data["hook"],
        "core":        data.get("core", ""),
        "cta":         data["cta"],
        "full_script": data["full_script"],
        "keywords":    data.get("keywords", []),
        "clips":       data.get("clips", []),
    }


def _parse_top5(data: dict) -> dict:
    items = data.get("items", [])
    core = " | ".join(f"#{i['rank']} {i['title']}" for i in items)
    return {
        "hook": data["hook"], "core": core, "cta": data["cta"],
        "full_script": data["full_script"],
        "keywords": data.get("keywords", []), "clips": data.get("clips", []),
    }


def _parse_quiz(data: dict) -> dict:
    core = " ".join(filter(None, [
        data.get("setup", ""), data.get("pause", ""), data.get("reveal", "")
    ]))
    return {
        "hook": data["hook"], "core": core, "cta": data["cta"],
        "full_script": data["full_script"],
        "keywords": data.get("keywords", []), "clips": data.get("clips", []),
    }


def _parse_story(data: dict) -> dict:
    core = " ".join(filter(None, [
        data.get("setup", ""), data.get("tension", ""), data.get("twist", "")
    ]))
    return {
        "hook": data["hook"], "core": core, "cta": data["cta"],
        "full_script": data["full_script"],
        "keywords": data.get("keywords", []), "clips": data.get("clips", []),
    }


def _parse_mythbuster(data: dict) -> dict:
    core = " ".join(filter(None, [
        data.get("myth", ""), data.get("pivot", ""),
        data.get("truth", ""), data.get("closer", "")
    ]))
    return {
        "hook": data["hook"], "core": core, "cta": data["cta"],
        "full_script": data["full_script"],
        "keywords": data.get("keywords", []), "clips": data.get("clips", []),
    }


def _parse_scary(data: dict) -> dict:
    facts = data.get("facts", [])
    core = " ".join(facts) + " " + data.get("closer", "")
    return {
        "hook": data["hook"], "core": core.strip(), "cta": data["cta"],
        "full_script": data["full_script"],
        "keywords": data.get("keywords", []), "clips": data.get("clips", []),
    }


def _parse_versus(data: dict) -> dict:
    rounds = data.get("rounds", [])
    core = " ".join(r.get("result", "") for r in rounds) + " " + data.get("winner", "")
    return {
        "hook": data["hook"], "core": core.strip(), "cta": data["cta"],
        "full_script": data["full_script"],
        "keywords": data.get("keywords", []), "clips": data.get("clips", []),
    }


# ── Registry ──────────────────────────────────────────────────────────────────

FORMATS: dict[str, dict] = {
    "informative": {
        "description": (
            "Classic 'did you know' voiceover with mind-blowing facts. "
            "Best for: science, psychology, nature, space, history."
        ),
        "system_prompt": _INFORMATIVE_PROMPT,
        "parse": _parse_simple,
    },
    "top5": {
        "description": (
            "Countdown Top 5 list — Number 1 is the climax. "
            "Best for: rankings, comparisons, 'top X reasons / ways to...'"
        ),
        "system_prompt": _TOP5_PROMPT,
        "parse": _parse_top5,
    },
    "quiz": {
        "description": (
            "Poses a surprising question, builds tension, reveals the answer. "
            "Drives comments = algorithm boost. Best for: trivia, science, history."
        ),
        "system_prompt": _QUIZ_PROMPT,
        "parse": _parse_quiz,
    },
    "story": {
        "description": (
            "Narrative arc: setup → tension → twist → resolution. "
            "High watch-time format. Best for: true events, animal/human drama."
        ),
        "system_prompt": _STORY_PROMPT,
        "parse": _parse_story,
    },
    "mythbuster": {
        "description": (
            "States a common myth then debunks it with the surprising truth. "
            "Strong share-bait. Best for: science, health, history misconceptions."
        ),
        "system_prompt": _MYTHBUSTER_PROMPT,
        "parse": _parse_mythbuster,
    },
    "scary": {
        "description": (
            "Eerie, unsettling facts delivered with building dread. "
            "Best for: deep sea, space, psychology, existential facts."
        ),
        "system_prompt": _SCARY_PROMPT,
        "parse": _parse_scary,
    },
    "versus": {
        "description": (
            "Head-to-head comparison building to a surprising winner. "
            "Best for: animals, historical figures, technologies, natural phenomena."
        ),
        "system_prompt": _VERSUS_PROMPT,
        "parse": _parse_versus,
    },
}


def get(name: str) -> dict:
    """Return a format dict. Raises ValueError for unknown names."""
    if name not in FORMATS:
        raise ValueError(
            f"Unknown format {name!r}. Available: {list(FORMATS)}"
        )
    return FORMATS[name]
