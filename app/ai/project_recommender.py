"""Project Recommender: portfolio projects that close the user's priority skill gaps.

How it works (the model never decides WHAT to recommend):
1. `rank_templates` scores every template in data/projects.json by how many of the user's top gaps it covers
   (earlier gaps weigh more, and a gap already covered by an earlier pick counts less, so the list is varied),
   nudged by experience level and role family. Templates covering no gap are never offered.
2. The LLM, if available, may only REWORD the chosen templates for the candidate (title, problem, description,
   features, deliverables). Skills, stack, difficulty and hours always come from the template.
3. Gaps no template covers fall back to a small generic project built around those skills.
"""
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from app.ai.client import LLMClient, LLMError
from app.ai.schemas import PersonalisedProjects, ProjectIdea
from app.utils.skills_taxonomy import category_of

logger = logging.getLogger(__name__)

TEMPLATES_PATH = Path(__file__).resolve().parents[2] / "data" / "projects.json"
TEMPLATES: list[dict] = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))["projects"]
TOP_GAPS = 5                 # "covers N of your top 5 gaps"
REPEAT_DISCOUNT = 0.4        # a gap already covered by an earlier pick is worth this much for the next one
_DIFFICULTY_ORDER = {"beginner": 0, "intermediate": 1, "advanced": 2}
_PREFERRED = {"entry": "beginner", "junior": "beginner", "mid": "intermediate", "senior": "advanced", "lead": "advanced"}


@dataclass
class ProjectContext:
    target_role: str | None
    experience_level: str | None
    gap_skills: list[str]  # priority order
    known_skills: list[str]
    responsibilities: list[str]  # sample responsibilities from target JDs
    role_family: str | None = None


def rank_templates(ctx: ProjectContext, count: int) -> list[tuple[dict, list[str]]]:
    """Pick up to `count` templates, best first. Returns [(template, covered_gaps_in_priority_order)]."""
    gaps = ctx.gap_skills
    base_weight = {g: 1.0 / (1 + 0.5 * i) for i, g in enumerate(gaps)}      # top gap 1.0, second 0.67, third 0.5, ...
    remaining = {g: 1.0 for g in gaps}
    want = _DIFFICULTY_ORDER[_PREFERRED.get(ctx.experience_level or "", "intermediate")]
    chosen: list[tuple[dict, list[str]]] = []
    pool = [t for t in TEMPLATES if set(t["skills"]) & set(gaps)]
    while pool and len(chosen) < count:
        def score(t: dict) -> tuple[float, int, str]:
            covered = [g for g in gaps if g in t["skills"]]
            value = sum(base_weight[g] * remaining[g] for g in covered)
            value += 0.25 if ctx.role_family and ctx.role_family in t["role_families"] else 0.0
            value -= 0.15 * abs(_DIFFICULTY_ORDER[t["difficulty"]] - want)
            return round(value, 4), -t["estimated_hours"], t["id"]

        best = max(pool, key=score)
        covered = [g for g in gaps if g in best["skills"]]
        chosen.append((best, covered))
        pool.remove(best)
        for g in covered:
            remaining[g] *= REPEAT_DISCOUNT
    return chosen


def _idea(t: dict, covered: list[str], ctx: ProjectContext) -> ProjectIdea:
    description = t["description"]
    if ctx.responsibilities:
        description += f" It mirrors real work such as: '{ctx.responsibilities[0]}'."
    return ProjectIdea(
        title=t["title"], problem_statement=t["problem_statement"], description=description[:2000],
        skills_covered=t["skills"], tech_stack=t["tech_stack"][:12], core_features=t["core_features"],
        difficulty=t["difficulty"], deliverables=t["deliverables"], estimated_hours=t["estimated_hours"],
        template_id=t["id"], gaps_covered=covered,
    )


def _pick_stack(skills: list[str], known: list[str]) -> list[str]:
    stack = list(skills)
    for k in known:
        if len(stack) >= 7:
            break
        if k not in stack and category_of(k) not in {"soft_skill", "practice"}:
            stack.append(k)
    return stack[:8]


def generic_projects(ctx: ProjectContext, gaps: list[str], count: int) -> list[ProjectIdea]:
    """Fallback for gaps no template covers: a focused showcase project per small group of skills."""
    role = ctx.target_role or "target-role"
    difficulty = _PREFERRED.get(ctx.experience_level or "", "intermediate")
    ideas: list[ProjectIdea] = []
    leftover = [g for g in gaps if category_of(g) not in {"soft_skill", "practice"}] or list(gaps)
    while len(ideas) < count and leftover:
        chunk, leftover = leftover[:3], leftover[3:]
        ideas.append(ProjectIdea(
            title=f"Hands-on {' + '.join(chunk)} showcase", problem_statement=f"Show practical, job-ready use of {', '.join(chunk)}.",
            description=f"A focused project that applies {', '.join(chunk)} to a realistic {role} task with tests and documentation.",
            skills_covered=chunk, tech_stack=_pick_stack(chunk, ctx.known_skills),
            core_features=[f"Core workflow implemented with {s}" for s in chunk] + ["Tests and README"],
            difficulty=difficulty, deliverables=["GitHub repo with README", "Short write-up of what you learned"],
            estimated_hours=10 + 6 * len(chunk), gaps_covered=list(chunk),
        ))
    return ideas


async def _personalise(llm: LLMClient, picks: list[tuple[dict, list[str]]], ctx: ProjectContext) -> dict[str, dict]:
    """{template_id: reworded fields}. Unknown ids and non-wording fields are ignored."""
    system = (
        "You adapt portfolio-project templates for a specific candidate. Rewrite ONLY the title, problem_statement, "
        "description and (optionally) core_features / deliverables so they fit the candidate's target role and the "
        "responsibilities in their target job postings. Keep each template_id unchanged. Do not change which skills a "
        "project covers, its tech stack, difficulty or time estimate, and do not add new skills or links."
    )
    user = json.dumps({
        "target_role": ctx.target_role, "experience_level": ctx.experience_level,
        "sample_responsibilities": ctx.responsibilities[:6], "candidate_known_skills": ctx.known_skills[:30],
        "templates": [{"template_id": t["id"], "title": t["title"], "problem_statement": t["problem_statement"],
                       "description": t["description"], "skills": t["skills"], "core_features": t["core_features"],
                       "deliverables": t["deliverables"], "gaps_it_closes": covered} for t, covered in picks],
    })
    result = await llm.generate_json(task="project_personalise", system=system, user=user,
                                     schema=PersonalisedProjects, temperature=0.4)
    allowed = {t["id"] for t, _ in picks}
    return {p.template_id: p.model_dump() for p in result.projects if p.template_id in allowed}


async def recommend(llm: LLMClient, ctx: ProjectContext, count: int) -> tuple[list[ProjectIdea], str]:
    picks = rank_templates(ctx, count)
    ideas = [_idea(t, covered, ctx) for t, covered in picks]
    generated_by = "rule_based"
    if picks and llm.available:
        try:
            reworded = await _personalise(llm, picks, ctx)
            for idx, (t, _) in enumerate(picks):
                r = reworded.get(t["id"])
                if r:
                    ideas[idx] = ideas[idx].model_copy(update={
                        "title": r["title"], "problem_statement": r["problem_statement"], "description": r["description"],
                        "core_features": r["core_features"] or ideas[idx].core_features,
                        "deliverables": r["deliverables"] or ideas[idx].deliverables})
            if reworded:
                generated_by = "llm"
        except LLMError as exc:
            logger.warning("Project personalisation failed, using template wording: %s", exc)
    if len(ideas) < count:
        covered_by_picks = {g for _, cov in picks for g in cov}
        ideas += generic_projects(ctx, [g for g in ctx.gap_skills if g not in covered_by_picks], count - len(ideas))
    return ideas[:count], generated_by
