"""Job-description extraction: raw JD text -> required/preferred skills, responsibilities, etc."""
import logging
import re

from app.ai.client import LLMClient, LLMError, wrap_untrusted
from app.ai.schemas import JDExtraction, JDSkill
from app.utils.skills_taxonomy import find_skills_in_text, normalize_skill, skill_mentioned_in

logger = logging.getLogger(__name__)

SYSTEM = """You extract structured requirements from a job description.
Rules:
- Only list skills/tools explicitly mentioned in the job description. Do not add skills from your own knowledge.
- Put a skill in `required_skills` if it is a must-have, `preferred_skills` if it is "nice to have"/"bonus"/"preferred".
- `kind`="tool" for concrete products/tools (e.g. Docker, Jira), "skill" otherwise.
- `required_proficiency` (1-5) only when the text implies a level (e.g. "expert", "5+ years"), else null.
- `evidence`: short verbatim quote."""

_PREFERRED_HINT = re.compile(r"nice to have|preferred|bonus|a plus|plus\b|desirable|good to have|optional", re.I)
_REQUIRED_HEAD = re.compile(r"requirements|qualifications|must have|what you.ll need|you have|required", re.I)
_RESP_HEAD = re.compile(r"responsibilities|what you.ll do|the role|duties|you will", re.I)
_YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-|to)?\s*\d{0,2}\s*\+?\s*years?", re.I)
_EDU = re.compile(r"\b(bachelor|master|phd|ph\.d|degree|b\.s|m\.s|bsc|msc|b\.tech|m\.tech)\b", re.I)


async def extract_job(llm: LLMClient, text: str) -> tuple[JDExtraction, str, list[str]]:
    warnings: list[str] = []
    result: JDExtraction | None = None
    generated_by = "rule_based"
    if llm.available:
        try:
            result = await llm.generate_json(
                task="jd_extract",
                system=SYSTEM,
                user=wrap_untrusted("JOB_DESCRIPTION", text),
                schema=JDExtraction,
                temperature=0.0,
            )
            generated_by = "llm"
        except LLMError as exc:
            logger.warning("JD LLM extraction failed, using fallback: %s", exc)
            warnings.append("AI extraction unavailable; used rule-based extraction.")
    if result is None:
        result = rule_based_extract(text)
    return _ground(result, text, warnings), generated_by, warnings


def _ground(result: JDExtraction, text: str, warnings: list[str]) -> JDExtraction:
    """Normalise skill names, drop ungrounded ones, and de-duplicate (required wins over preferred)."""

    def clean(items: list[JDSkill]) -> list[JDSkill]:
        out: dict[str, JDSkill] = {}
        for s in items:
            norm = normalize_skill(s.name)
            if norm is None:
                continue
            if not (skill_mentioned_in(text, norm.name) or s.name.lower() in text.lower()):
                warnings.append(f"Ignored '{s.name}': not mentioned in the job description.")
                continue
            if norm.name not in out:
                out[norm.name] = s.model_copy(update={"name": norm.name})
        return list(out.values())

    required = clean(result.required_skills)
    req_names = {s.name for s in required}
    preferred = [s for s in clean(result.preferred_skills) if s.name not in req_names]
    result.required_skills, result.preferred_skills = required, preferred
    return result


def rule_based_extract(text: str) -> JDExtraction:
    lines = [ln.strip(" •-*\t") for ln in text.splitlines()]
    required: dict[str, JDSkill] = {}
    preferred: dict[str, JDSkill] = {}
    responsibilities: list[str] = []
    experience: list[str] = []
    education: list[str] = []
    mode = None  # "resp" | "req" | "pref"
    for line in lines:
        if not line:
            continue
        is_heading = len(line) < 60 and (line.endswith(":") or line.isupper() or len(line.split()) <= 5)
        if is_heading and _PREFERRED_HINT.search(line):
            mode = "pref"
            continue
        if is_heading and _REQUIRED_HEAD.search(line):
            mode = "req"
            continue
        if is_heading and _RESP_HEAD.search(line):
            mode = "resp"
            continue
        if mode == "resp" and len(responsibilities) < 30:
            responsibilities.append(line[:300])
        if _YEARS.search(line) and len(experience) < 15:
            experience.append(line[:300])
        if _EDU.search(line) and len(education) < 10:
            education.append(line[:300])
        bucket = preferred if (mode == "pref" or _PREFERRED_HINT.search(line)) else required
        for name in find_skills_in_text(line):
            norm = normalize_skill(name)
            if norm is None or norm.name in required or norm.name in bucket:
                continue
            kind = "tool" if norm.category in {"tools", "devops", "cloud", "database"} else "skill"
            bucket[norm.name] = JDSkill(name=norm.name, kind=kind, evidence=line[:300])

    years_min = None
    m = _YEARS.search(" ".join(experience))
    if m:
        years_min = float(m.group(1))
    return JDExtraction(
        required_skills=list(required.values())[:60],
        preferred_skills=[s for n, s in preferred.items() if n not in required][:60],
        experience_requirements=experience,
        experience_years_min=years_min,
        responsibilities=responsibilities,
        education_requirements=education,
    )
