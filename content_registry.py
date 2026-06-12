"""content_registry.py — Track generated clip ideas and block duplicates."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

DEFAULT_REGISTRY_PATH = Path("data/content_registry.json")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "because", "before", "but", "by",
    "can", "does", "for", "from", "has", "have", "how", "in", "into", "is", "it",
    "its", "just", "not", "of", "on", "or", "so", "than", "that", "the", "their",
    "this", "to", "very", "was", "while", "why", "with",
}


def registry_path(path: str | Path | None = None) -> Path:
    return Path(path) if path is not None else DEFAULT_REGISTRY_PATH


def normalize_text(value: str) -> str:
    value = value.casefold()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def slugify(value: str) -> str:
    return normalize_text(value).replace(" ", "-")


def _tokenize(value: str) -> set[str]:
    return {
        token
        for token in normalize_text(value).split()
        if len(token) >= 3 and token not in _STOPWORDS
    }


def _sequence_similarity(left: str, right: str) -> float:
    left_key = normalize_text(left)
    right_key = normalize_text(right)
    if not left_key or not right_key:
        return 0.0
    return SequenceMatcher(a=left_key, b=right_key).ratio()


def _token_overlap(left: str, right: str) -> float:
    left_tokens = _tokenize(left)
    right_tokens = _tokenize(right)
    if not left_tokens or not right_tokens:
        return 0.0
    shared = left_tokens & right_tokens
    return len(shared) / min(len(left_tokens), len(right_tokens))


def _shared_token_count(left: str, right: str) -> int:
    left_tokens = _tokenize(left)
    right_tokens = _tokenize(right)
    return len(left_tokens & right_tokens)


def _similarity_score(left: str, right: str) -> float:
    return max(_sequence_similarity(left, right), _token_overlap(left, right))


def load_registry(path: str | Path | None = None) -> dict[str, Any]:
    resolved = registry_path(path)
    if not resolved.exists():
        return {"entries": []}
    data = json.loads(resolved.read_text(encoding="utf-8"))
    if "entries" not in data or not isinstance(data["entries"], list):
        data["entries"] = []
    return data


def save_registry(data: dict[str, Any], path: str | Path | None = None) -> Path:
    resolved = registry_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return resolved


def is_duplicate_candidate(
    topic: str,
    fact_summary: str,
    registry_path: str | Path | None = None,
    theme: str = "",
    hook_angle: str = "",
) -> bool:
    topic_key = normalize_text(topic)
    summary_key = normalize_text(fact_summary)
    theme_key = normalize_text(theme)
    hook_key = normalize_text(hook_angle)
    candidate_theme_slug = slugify(f"{theme}-{topic}") if theme_key and topic_key else ""

    for entry in load_registry(registry_path).get("entries", []):
        entry_topic = str(entry.get("topic", ""))
        entry_summary = str(entry.get("fact_summary", ""))
        entry_theme = str(entry.get("theme", ""))
        entry_hook = str(entry.get("hook_angle", ""))
        entry_theme_slug = normalize_text(str(entry.get("theme_slug", "")))

        entry_topic_key = normalize_text(entry_topic)
        entry_summary_key = normalize_text(entry_summary)
        entry_theme_key = normalize_text(entry_theme)
        same_theme = bool(theme_key and entry_theme_key and theme_key == entry_theme_key)

        if topic_key and entry_topic_key == topic_key:
            return True
        if summary_key and entry_summary_key == summary_key:
            return True
        if candidate_theme_slug and entry_theme_slug == normalize_text(candidate_theme_slug):
            return True

        summary_similarity = _similarity_score(fact_summary, entry_summary)
        topic_similarity = _similarity_score(topic, entry_topic)
        hook_similarity = _similarity_score(hook_angle, entry_hook)
        shared_summary_tokens = _shared_token_count(fact_summary, entry_summary)

        if summary_similarity >= 0.72:
            return True
        if same_theme and shared_summary_tokens >= 3:
            return True
        if same_theme and summary_similarity >= 0.52:
            return True
        if same_theme and topic_similarity >= 0.60 and hook_key and hook_similarity >= 0.45:
            return True
        if same_theme and topic_similarity >= 0.60 and summary_similarity >= 0.45:
            return True

    return False


def recent_registry_entries(limit: int = 25, registry_path: str | Path | None = None) -> list[dict[str, Any]]:
    entries = load_registry(registry_path).get("entries", [])
    return entries[-limit:]


def build_avoidance_prompt(limit: int = 25, registry_path: str | Path | None = None) -> str:
    entries = recent_registry_entries(limit=limit, registry_path=registry_path)
    if not entries:
        return "No prior entries recorded yet."

    lines = ["Avoid duplicating or closely rephrasing any of these prior clips:"]
    for entry in entries:
        topic = entry.get("topic", "")
        fact_summary = entry.get("fact_summary", "")
        hook_angle = entry.get("hook_angle", "")
        theme_slug = entry.get("theme_slug", "")
        lines.append(f"- {theme_slug}: topic={topic}; fact={fact_summary}; hook={hook_angle}")
    return "\n".join(lines)


def next_registry_id(prefix: str = "clipforge", registry_path: str | Path | None = None) -> str:
    entries = load_registry(registry_path).get("entries", [])
    today = datetime.now(timezone.utc).date().isoformat()
    pattern = re.compile(rf"^{re.escape(prefix)}-{today}-(\d+)$")
    seen = [int(match.group(1)) for entry in entries if (match := pattern.match(str(entry.get("id", ""))))]
    next_number = max(seen, default=0) + 1
    return f"{prefix}-{today}-{next_number:03d}"


def build_registry_entry(*, topic: str, theme: str, fact_summary: str, hook_angle: str,
                         keywords: list[str], format_id: str = "fake-but-true-v1",
                         status: str = "generated", registry_path: str | Path | None = None,
                         entry_id: str | None = None,
                         pillar: str | None = None,
                         hook_type: str | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": entry_id or next_registry_id(registry_path=registry_path),
        "created_at": now,
        "status": status,
        "format_id": format_id,
        "pillar": pillar,
        "hook_type": hook_type,
        "theme": theme,
        "topic": topic,
        "theme_slug": slugify(f"{theme}-{topic}"),
        "fact_summary": fact_summary,
        "hook_angle": hook_angle,
        "keywords": keywords,
    }


def append_registry_entry(entry: dict[str, Any], registry_path: str | Path | None = None) -> Path:
    data = load_registry(registry_path)
    data.setdefault("entries", []).append(entry)
    return save_registry(data, registry_path)


def update_registry_entry(
    entry_id: str,
    updates: dict[str, Any],
    registry_path: str | Path | None = None,
) -> Path:
    data = load_registry(registry_path)
    for entry in data.setdefault("entries", []):
        if str(entry.get("id", "")) == entry_id:
            entry.update(updates)
            return save_registry(data, registry_path)
    raise ValueError(f"Registry entry not found: {entry_id}")
