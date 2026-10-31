"""Skill Gap Analyst.

`compute_gaps` is fully deterministic: it decides gap levels, importance and
priority from data (no LLM). The LLM (`explain_gaps`) may only write the prose
summary/explanations - it can never change who has which skill.

Key rule: a user only "has" a skill if it is in their profile. A *related*
skill (e.g. MySQL when PostgreSQL is required) yields at most a PARTIAL match,
and the explanation says so explicitly.
"""
import json
import logging
from dataclasses import asdict, dataclass, field

from app.ai.client import LLMClient, LLMError
from app.ai.schemas import GapNarrative
from app.utils.skills_taxonomy import related_skills

logger = logging.getLogger(__name__)

ASSUMED_WORKING_LEVEL = 3  # used only when a JD does not state a level


@dataclass
class UserSkillInfo:
    proficiency: int | None
    confirmed: bool
    source: str


@dataclass
class Requirement:
    skill_id: int
    skill_name: str
    category: str
    requirement_type: str  # required | preferred
    required_proficiency: int | None
    evidence: str | None


@dataclass
class JobInput:
    id: int
    title: str
    company: str | None
    requirements: list[Requirement]


@dataclass
class GapItem:
    skill_id: int
    skill_name: str
    category: str
    current_proficiency: int | None
    required_proficiency: int | None
    gap_level: str
    importance: float
    importance_label: str
    frequency: int
    required_count: int
    preferred_count: int
    priority_rank: int = 0
    is_priority: bool = False
    explanation: str = ""
    job_references: list[dict] = field(default_factory=list)
    priority_score: float = 0.0


@dataclass
class GapReport:
    items: list[GapItem]
    match_score: float
    summary: str


def _importance_label(x: float) -> str:
    if x >= 0.75:
        return "critical"
    if x >= 0.5:
        return "high"
    if x >= 0.25:
        return "medium"
    return "low"


def compute_gaps(user_skills: dict[str, UserSkillInfo], jobs: list[JobInput]) -> GapReport:
    n_jobs = max(len(jobs), 1)
    by_skill: dict[str, dict] = {}
    for job in jobs:
        for req in job.requirements:
            entry = by_skill.setdefault(req.skill_name, {"req": req, "refs": [], "required": 0, "preferred": 0, "levels": []})
            entry[req.requirement_type] += 1
            if req.required_proficiency:
                entry["levels"].append(req.required_proficiency)
            entry["refs"].append({"job_id": job.id, "title": job.title, "company": job.company,
                                  "requirement_type": req.requirement_type, "evidence": req.evidence})

    items: list[GapItem] = []
    for name, e in by_skill.items():
        req: Requirement = e["req"]
        importance = round(min(1.0, (e["required"] + 0.5 * e["preferred"]) / n_jobs), 3)
        required_level = max(e["levels"]) if e["levels"] else None
        mine = user_skills.get(name)
        current = mine.proficiency if mine else None
        jobs_txt = f"{len(e['refs'])} of {len(jobs)} job description(s) ({e['required']} required, {e['preferred']} preferred)"

        if mine:
            target = required_level or ASSUMED_WORKING_LEVEL
            if current is not None and current < target:
                gap = "partial"
                expl = (f"You list {name} at level {current}/5, but the target is about {target}/5"
                        f"{'' if required_level else ' (assumed working proficiency; JDs do not state a level)'}. "
                        f"Mentioned in {jobs_txt}.")
            else:
                gap = "none"
                level_txt = f"level {current}/5" if current else "level not specified"
                expl = f"You already have {name} ({level_txt}). Mentioned in {jobs_txt}."
            if not mine.confirmed:
                expl += " (Detected from your resume - confirm it in your profile.)"
        else:
            have_related = sorted(r for r in related_skills(name) if r in user_skills)
            if have_related:
                gap = "partial"
                expl = (f"{name} is not in your profile. You have related experience ({', '.join(have_related)}), "
                        f"which should make it faster to learn, but it does not count as having {name}. "
                        f"Mentioned in {jobs_txt}.")
            else:
                gap = "missing"
                expl = f"{name} is not in your profile. Mentioned in {jobs_txt}."

        weight = {"missing": 1.0, "partial": 0.5, "none": 0.0}[gap]
        items.append(GapItem(
            skill_id=req.skill_id, skill_name=name, category=req.category, current_proficiency=current,
            required_proficiency=required_level, gap_level=gap, importance=importance,
            importance_label=_importance_label(importance), frequency=len({r["job_id"] for r in e["refs"]}),
            required_count=e["required"], preferred_count=e["preferred"], explanation=expl,
            job_references=e["refs"], priority_score=round(importance * weight, 4),
        ))

    # Rank: biggest (importance x gap) first; covered skills go last.
    items.sort(key=lambda i: (-i.priority_score, -i.importance, i.skill_name))
    gaps = [i for i in items if i.gap_level != "none"]
    for rank, item in enumerate(items, start=1):
        item.priority_rank = rank
    for idx, item in enumerate(gaps):
        # Prioritise important gaps, and always at least the top 3 gaps.
        item.is_priority = item.importance >= 0.5 or idx < 3

    total = sum(i.importance for i in items) or 1.0
    coverage = {"none": 1.0, "partial": 0.5, "missing": 0.0}
    match = round(100 * sum(i.importance * coverage[i.gap_level] for i in items) / total, 1)
    summary = _default_summary(items, match, len(jobs))
    return GapReport(items=items, match_score=match, summary=summary)


def _default_summary(items: list[GapItem], match: float, n_jobs: int) -> str:
    if not items:
        return "No skill requirements were found in the selected job descriptions."
    have = [i.skill_name for i in items if i.gap_level == "none"]
    partial = [i.skill_name for i in items if i.gap_level == "partial"]
    missing = [i.skill_name for i in items if i.gap_level == "missing"]
    prio = [i.skill_name for i in items if i.is_priority][:5]
    return (f"Across {n_jobs} job description(s) your weighted skill match is {match}%. "
            f"You already cover {len(have)} skill(s), partially cover {len(partial)} and are missing {len(missing)}. "
            + (f"Focus first on: {', '.join(prio)}." if prio else "No significant gaps found."))


async def explain_gaps(llm: LLMClient, report: GapReport, target_role: str | None) -> str:
    """Optionally improve prose with the LLM. Returns generated_by. Numbers/levels are never modified."""
    if not llm.available or not report.items:
        return "rule_based"
    facts = [
        {k: v for k, v in asdict(i).items() if k in {"skill_name", "gap_level", "importance_label", "current_proficiency",
                                                      "required_proficiency", "frequency", "explanation"}}
        for i in report.items
    ]
    system = ("You are a career coach. Rewrite the explanations to be clear, encouraging and actionable for someone "
              "pivoting into the target role. Do NOT change any facts, gap levels or numbers, and never state that the "
              "user has a skill unless gap_level is 'none'.")
    user = json.dumps({"target_role": target_role, "match_score": report.match_score, "skills": facts})
    try:
        narrative = await llm.generate_json(task="gap_explain", system=system, user=user, schema=GapNarrative)
    except LLMError as exc:
        logger.warning("Gap narrative failed, keeping rule-based text: %s", exc)
        return "rule_based"
    by_name = {i.skill_name: i for i in report.items}
    for e in narrative.explanations:
        if e.skill_name in by_name and e.explanation.strip():
            by_name[e.skill_name].explanation = e.explanation.strip()
    report.summary = narrative.summary.strip() or report.summary
    return "llm"
