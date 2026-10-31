"""A small, curated skill taxonomy used to normalise skill names.

Why not embeddings? Exact alias matching is predictable, explainable and never
claims a user has a skill "because it's semantically close". Related skills are
listed explicitly and only ever produce a *partial* match.

Entries live in data/skills_taxonomy.json (~160 skills).
Each entry: canonical name -> {cat, aliases, related, hours}
  * aliases  – alternative spellings that normalise to the canonical name
  * related  – adjacent skills (transferable knowledge => partial match)
  * hours    – rough hours for a motivated learner to reach working proficiency
               (used only for scheduling; deliberately conservative)
"""
import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

# The taxonomy lives in data/skills_taxonomy.json so it can be extended without touching code.
TAXONOMY_PATH = Path(__file__).resolve().parents[2] / "data" / "skills_taxonomy.json"
_T: dict[str, dict] = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))["skills"]

SOFT_SKILL_CATEGORY = "soft_skill"

# Topic templates per category, used by the rule-based planner/interviewer fallbacks.
CATEGORY_TOPICS: dict[str, list[str]] = {
    "programming_language": ["{s} syntax, types and control flow", "{s} standard library and idioms", "Error handling and debugging in {s}", "Writing tested, idiomatic {s} code"],
    "backend": ["Core concepts and request lifecycle in {s}", "Routing, validation and persistence with {s}", "Authentication and error handling with {s}", "Testing and deploying a {s} service"],
    "frontend": ["{s} fundamentals and component model", "State management and data fetching with {s}", "Styling, accessibility and performance in {s}", "Testing and shipping a {s} app"],
    "database": ["{s} data model and core queries", "Indexes, joins and query performance in {s}", "Transactions and integrity in {s}", "Using {s} from application code"],
    "data": ["{s} fundamentals", "Working with real datasets using {s}", "Common pitfalls and best practices in {s}", "End-to-end mini analysis/pipeline with {s}"],
    "ml_ai": ["Core concepts behind {s}", "Hands-on implementation of {s}", "Evaluating and debugging {s} solutions", "Deploying or integrating {s} in an application"],
    "cloud": ["{s} core services and pricing model", "Identity, networking and security on {s}", "Deploying an application to {s}", "Monitoring and cost control on {s}"],
    "devops": ["{s} fundamentals", "Using {s} in a real project workflow", "Troubleshooting {s}", "{s} best practices for production"],
    "architecture": ["Key principles of {s}", "Trade-offs: consistency, availability, latency", "Case studies of {s}", "Designing and documenting a system using {s}"],
    "fundamentals": ["Core concepts of {s}", "Practice problems on {s}", "Complexity and trade-offs in {s}", "Applying {s} in real code"],
    "soft_skill": ["Frameworks for {s}", "Practising {s} in realistic scenarios", "Getting feedback on {s}", "Demonstrating {s} in interviews"],
}
DEFAULT_TOPICS = ["Fundamentals of {s}", "Hands-on practice with {s}", "Applying {s} to a realistic problem", "Reviewing and consolidating {s}"]


@dataclass(frozen=True)
class NormalizedSkill:
    name: str
    category: str
    in_taxonomy: bool


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


# alias (lowercase) -> canonical name
_ALIAS_MAP: dict[str, str] = {}
for _name, _info in _T.items():
    _ALIAS_MAP[_key(_name)] = _name
    for _alias in _info["aliases"]:
        _ALIAS_MAP[_key(_alias)] = _name

_FUZZY_KEYS = [k for k in _ALIAS_MAP if len(k) >= 6]

# Build symmetric "related" relationships.
_RELATED: dict[str, set[str]] = {name: set(info["related"]) for name, info in _T.items()}
for _name, _rels in list(_RELATED.items()):
    for _r in _rels:
        _RELATED.setdefault(_r, set()).add(_name)


def normalize_skill(raw: str) -> NormalizedSkill | None:
    """Map a free-text skill to its canonical form. Returns None for junk input."""
    if not raw:
        return None
    text = re.sub(r"\s+", " ", raw).strip().strip(".,;:-•*")
    if not text or len(text) > 60:
        return None
    k = _key(text)
    candidates = [k, re.sub(r"\s*\d+(\.\d+)*\s*$", "", k)]  # drop trailing versions: "python 3.11"
    if k.endswith(" programming"):
        candidates.append(k.removesuffix(" programming"))
    for c in candidates:
        if c in _ALIAS_MAP:
            name = _ALIAS_MAP[c]
            return NormalizedSkill(name=name, category=_T[name]["cat"], in_taxonomy=True)
    fuzzy = _fuzzy_alias(k)
    if fuzzy:
        return NormalizedSkill(name=fuzzy, category=_T[fuzzy]["cat"], in_taxonomy=True)
    # Unknown skill: keep the user's/JD's wording, tidy capitalisation of all-lowercase input.
    display = text if any(ch.isupper() for ch in text) else text.title()
    return NormalizedSkill(name=display, category="other", in_taxonomy=False)


def _fuzzy_alias(key: str) -> str | None:
    """Typo tolerance ("pyhton", "kuberentes"). Deliberately strict: long words only, one clear winner.

    Never used to infer a *different* skill - only to repair spelling of a listed one.
    """
    if len(key) < 6 or " " in key and len(key) < 10:
        return None
    close = difflib.get_close_matches(key, _FUZZY_KEYS, n=2, cutoff=0.88)
    if not close:
        return None
    if len(close) == 2 and _ALIAS_MAP[close[0]] != _ALIAS_MAP[close[1]]:
        return None  # ambiguous
    return _ALIAS_MAP[close[0]]


def related_skills(name: str) -> set[str]:
    return _RELATED.get(name, set())


def learning_hours(name: str) -> int:
    return _T.get(name, {}).get("hours", 15)


def category_of(name: str) -> str:
    return _T.get(name, {}).get("cat", "other")


def topics_for(name: str) -> list[str]:
    templates = CATEGORY_TOPICS.get(category_of(name), DEFAULT_TOPICS)
    return [t.format(s=name) for t in templates]


def slugify(name: str) -> str:
    slug = name.lower().replace("+", "plus").replace("#", "sharp").replace("&", "and")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug or "skill"


# --- Free-text scanning ------------------------------------------------------
def _scan_terms() -> list[tuple[re.Pattern, str]]:
    terms = []
    for alias, canonical in _ALIAS_MAP.items():
        # Skip very short purely alphabetic aliases ("go", "r", "ml", "ts") – too many false positives.
        if len(alias) <= 2 and alias.isalpha():
            continue
        if alias in {"node", "spring", "express", "shell", "testing", "logging", "lambda", "rest", "containers",
                     "collaboration", "prototyping", "authentication", "spark", "android", "ios", "dart", "torch",
                     "vue", "mongo", "rails", "prompting", "algorithms", "unix", "probability", "java 8"}:
            continue  # ambiguous as plain words; still normalised when explicitly listed as a skill
        pattern = re.compile(r"(?<![A-Za-z0-9+#])" + re.escape(alias) + r"(?![A-Za-z0-9+#])", re.IGNORECASE)
        terms.append((pattern, canonical))
    # Longer aliases first so "react native" wins over "react".
    terms.sort(key=lambda t: -len(t[0].pattern))
    return terms


_SCAN_TERMS = _scan_terms()


def find_skills_in_text(text: str) -> dict[str, str]:
    """Return {canonical_skill: matched_snippet} for taxonomy skills explicitly mentioned in `text`."""
    found: dict[str, str] = {}
    consumed: list[tuple[int, int]] = []
    for pattern, canonical in _SCAN_TERMS:
        for m in pattern.finditer(text):
            span = m.span()
            if any(s <= span[0] < e or s < span[1] <= e for s, e in consumed):
                continue  # already part of a longer match
            consumed.append(span)
            if canonical not in found:
                start, end = max(0, span[0] - 60), min(len(text), span[1] + 60)
                found[canonical] = re.sub(r"\s+", " ", text[start:end]).strip()
    return found


def skill_mentioned_in(text: str, skill_name: str) -> bool:
    """True if the canonical skill (or any alias) literally appears in `text`.

    Used to reject LLM-extracted skills that are not actually in the resume.
    """
    low = text.lower()
    names = {_key(skill_name)} | {a for a, c in _ALIAS_MAP.items() if c == skill_name}
    for n in names:
        if re.search(r"(?<![a-z0-9+#])" + re.escape(n) + r"(?![a-z0-9+#])", low):
            return True
    return False
