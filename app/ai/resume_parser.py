"""Resume Parser agent: resume text -> structured, *validated* profile data.

Anti-hallucination rule: every technical skill must literally appear in the
resume text (the canonical name or a known alias). Anything else is dropped and
reported in `warnings` so the user can add it back manually if it is real.
"""
import logging
import re

from app.ai.client import LLMClient, LLMError, wrap_untrusted
from app.ai.schemas import (
    Certification,
    Education,
    ExtractedSkill,
    ResumeExtraction,
    ResumeProject,
    WorkExperience,
)
from app.utils.skills_taxonomy import (
    SOFT_SKILL_CATEGORY,
    find_skills_in_text,
    normalize_skill,
    skill_mentioned_in,
)

logger = logging.getLogger(__name__)

SYSTEM = """You extract structured information from a resume.
Rules:
- Only include information explicitly present in the resume. Do NOT infer or invent skills, employers, dates,
  degrees or certifications.
- For every technical skill give a short verbatim `evidence` quote from the resume.
- `proficiency_hint` (1-5) only if the resume makes it clear (e.g. years of use, "expert in"); otherwise null.
- `years_experience`: total professional years if clearly derivable, else null."""


async def parse_resume(llm: LLMClient, text: str) -> tuple[ResumeExtraction, str, list[str]]:
    """Return (extraction, generated_by, warnings)."""
    warnings: list[str] = []
    generated_by = "rule_based"
    extraction: ResumeExtraction | None = None
    if llm.available:
        try:
            extraction = await llm.generate_json(
                task="resume_parse",
                system=SYSTEM,
                user=wrap_untrusted("RESUME", text),
                schema=ResumeExtraction,
                temperature=0.0,
            )
            generated_by = "llm"
        except LLMError as exc:
            logger.warning("Resume LLM parse failed, using rule-based fallback: %s", exc)
            warnings.append("AI parsing unavailable; used rule-based extraction. Please review carefully.")
    if extraction is None:
        extraction = rule_based_parse(text)
    extraction = validate_against_text(extraction, text, warnings)
    return extraction, generated_by, warnings


def validate_against_text(extraction: ResumeExtraction, text: str, warnings: list[str]) -> ResumeExtraction:
    """Normalise skills and drop any that are not grounded in the resume text."""
    kept: dict[str, ExtractedSkill] = {}
    for s in extraction.technical_skills:
        norm = normalize_skill(s.name)
        if norm is None:
            continue
        grounded = skill_mentioned_in(text, norm.name) or s.name.lower() in text.lower()
        if not grounded:
            warnings.append(f"Ignored skill '{s.name}': it does not appear in the resume text.")
            continue
        if norm.category == SOFT_SKILL_CATEGORY:
            if norm.name not in extraction.soft_skills:
                extraction.soft_skills.append(norm.name)
            continue
        if norm.name not in kept:
            kept[norm.name] = ExtractedSkill(name=norm.name, evidence=s.evidence, proficiency_hint=s.proficiency_hint)

    # Add explicit taxonomy mentions the LLM may have missed (literal matches, so safe).
    for name, snippet in find_skills_in_text(text).items():
        norm = normalize_skill(name)
        if norm and norm.category != SOFT_SKILL_CATEGORY and name not in kept:
            kept[name] = ExtractedSkill(name=name, evidence=snippet[:300])

    soft: list[str] = []
    for s in extraction.soft_skills:
        norm = normalize_skill(s)
        if norm and norm.name not in soft and (skill_mentioned_in(text, norm.name) or s.lower() in text.lower()):
            soft.append(norm.name)
    extraction.technical_skills = list(kept.values())
    extraction.soft_skills = soft
    return extraction


# --- Rule-based fallback ------------------------------------------------------------------
_SECTION_ALIASES = {
    "experience": {"experience", "work experience", "professional experience", "employment", "employment history", "work history"},
    "education": {"education", "academic background", "qualifications"},
    "projects": {"projects", "personal projects", "selected projects", "key projects"},
    "certifications": {"certifications", "certificates", "licenses", "licenses & certifications", "courses"},
    "skills": {"skills", "technical skills", "core skills", "skills & tools", "technologies"},
    "summary": {"summary", "profile", "professional summary", "about", "objective"},
}


def split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            sections.setdefault(current, []).append("")
            continue
        key = re.sub(r"[^a-z& ]", "", line.lower()).strip()
        matched = next((name for name, aliases in _SECTION_ALIASES.items() if key in aliases), None)
        if matched and len(line) < 40:
            current = matched
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _blocks(lines: list[str]) -> list[list[str]]:
    blocks, cur = [], []
    for line in lines:
        if not line:
            if cur:
                blocks.append(cur)
                cur = []
        else:
            cur.append(line.lstrip("•-* ").strip())
    if cur:
        blocks.append(cur)
    return blocks


def rule_based_parse(text: str) -> ResumeExtraction:
    sections = split_sections(text)
    years = None
    m = re.search(r"(\d{1,2})\+?\s*years?\s+(?:of\s+)?(?:professional\s+)?experience", text, re.IGNORECASE)
    if m:
        years = float(m.group(1))

    experience = []
    for block in _blocks(sections.get("experience", [])):
        experience.append(WorkExperience(title=block[0][:200], highlights=[b[:300] for b in block[1:15]]))
    education = [Education(degree=b[0][:200], institution=(b[1][:200] if len(b) > 1 else "")) for b in _blocks(sections.get("education", []))]
    projects = [ResumeProject(name=b[0][:200], description=" ".join(b[1:])[:1000]) for b in _blocks(sections.get("projects", []))]
    certs = [Certification(name=line[:200]) for line in sections.get("certifications", []) if line]
    summary_lines = [line for line in sections.get("summary", []) if line]

    found = find_skills_in_text(text)
    technical = [ExtractedSkill(name=n, evidence=s[:300]) for n, s in found.items()]
    soft = [n for n in found if normalize_skill(n) and normalize_skill(n).category == SOFT_SKILL_CATEGORY]
    return ResumeExtraction(
        current_role=experience[0].title if experience else None,
        years_experience=years,
        summary=" ".join(summary_lines)[:1500] or None,
        technical_skills=technical,
        soft_skills=soft,
        work_experience=experience[:20],
        education=education[:10],
        projects=projects[:20],
        certifications=certs[:20],
    )
