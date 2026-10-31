"""Curated free learning resources (data/resources.json).

The ONLY source of links shown to users. The AI may choose between the entries listed for a skill but can never
introduce a URL of its own: unknown ids are dropped. Skills without a curated list get a clearly-labelled search
link instead of an invented one.
"""
import json
import re
from pathlib import Path
from urllib.parse import quote_plus

RESOURCES_PATH = Path(__file__).resolve().parents[2] / "data" / "resources.json"
_DATA: dict = json.loads(RESOURCES_PATH.read_text(encoding="utf-8"))
_SKILLS: dict[str, list[dict]] = _DATA["skills"]
_BY_ID: dict[str, dict] = {r["id"]: r for items in _SKILLS.values() for r in items}
MAX_PER_TASK = 3


def resources_for(skill: str) -> list[dict]:
    """Curated resources for a canonical skill name (empty if none)."""
    return [dict(r) for r in _SKILLS.get(skill, [])]


def has_curated(skill: str) -> bool:
    return skill in _SKILLS


def search_fallback(skill: str) -> dict:
    slug = re.sub(r"[^a-z0-9]+", "-", skill.lower()).strip("-") or "skill"
    return {"id": f"search-{slug}", "title": f"Search for free {skill} courses", "type": "search", "hours": None,
            "provider": "Web search", "url": f"https://www.google.com/search?q={quote_plus(f'free {skill} course tutorial')}"}


def default_for_part(skill: str, part: int, parts: int) -> list[dict]:
    """Deterministic pick: one-week skills get every resource; multi-week skills rotate through them."""
    items = resources_for(skill)
    if not items:
        return [search_fallback(skill)]
    if parts <= 1:
        return items[:MAX_PER_TASK]
    return [items[(part - 1) % len(items)]]


def choose(skill: str, ids: list[str]) -> list[dict]:
    """Resources the model picked, restricted to ids that really belong to `skill`."""
    allowed = {r["id"] for r in _SKILLS.get(skill, [])}
    picked, seen = [], set()
    for rid in ids:
        if rid in allowed and rid not in seen:
            seen.add(rid)
            picked.append(dict(_BY_ID[rid]))
    return picked[:MAX_PER_TASK]
