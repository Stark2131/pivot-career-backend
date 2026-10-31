"""Project Recommender: portfolio projects that close the user's priority skill gaps.

LLM ideas are accepted only if they cover at least one real gap skill; otherwise
(or without an LLM) we use category templates filled with the user's gap skills.
"""
import json
import logging
from dataclasses import dataclass

from app.ai.client import LLMClient, LLMError
from app.ai.schemas import ProjectIdea, ProjectList
from app.utils.skills_taxonomy import category_of, normalize_skill

logger = logging.getLogger(__name__)


@dataclass
class ProjectContext:
    target_role: str | None
    experience_level: str | None
    gap_skills: list[str]  # priority order
    known_skills: list[str]
    responsibilities: list[str]  # sample responsibilities from target JDs


_TEMPLATES = [
    {
        "match": {"ml_ai"},
        "title": "End-to-end {role} prediction service",
        "problem": "Teams need reliable predictions served behind an API, not just notebooks.",
        "desc": "Train a model on a public dataset, track experiments, and serve predictions through a documented API "
                "with input validation, tests and a container image.",
        "features": ["Reproducible training script with evaluation metrics", "Model versioning", "Prediction REST endpoint with validation",
                     "Monitoring of prediction latency and input drift (basic)"],
        "deliverables": ["GitHub repo with README and architecture diagram", "Evaluation report (metrics, error analysis)",
                         "Dockerfile and deployment instructions", "Short demo video or GIF"],
    },
    {
        "match": {"data", "database"},
        "title": "Automated analytics pipeline and dashboard",
        "problem": "Business users wait days for manual reports built from messy source data.",
        "desc": "Ingest a public dataset on a schedule, clean and model it in a database, and publish a dashboard that "
                "answers 3-5 concrete business questions.",
        "features": ["Scheduled ingestion with data-quality checks", "Modelled tables (facts/dimensions)",
                     "Dashboard with key metrics and filters", "Documented SQL transformations"],
        "deliverables": ["Repo with pipeline code and SQL", "Dashboard link or screenshots", "Write-up of insights found"],
    },
    {
        "match": {"backend", "architecture", "programming_language", "security", "testing"},
        "title": "Production-ready REST API for a real-world domain",
        "problem": "Many portfolios show toy CRUD apps; employers want to see auth, testing and deployment.",
        "desc": "Design and build an API for a domain you care about (e.g. clinic bookings) with authentication, "
                "persistence, automated tests and CI.",
        "features": ["JWT authentication and role checks", "Relational schema with migrations", "Pagination, filtering and validation",
                     "Automated tests in CI"],
        "deliverables": ["Repo with OpenAPI docs", "Test coverage report", "Deployed demo URL", "README with design decisions"],
    },
    {
        "match": {"frontend", "mobile", "design"},
        "title": "Responsive web app with real data",
        "problem": "Users need a fast, accessible interface for a task they do every day.",
        "desc": "Build a responsive, accessible front-end that consumes a public API, with state management, "
                "loading/error states and component tests.",
        "features": ["Responsive layout and accessibility checks", "Client-side routing and state", "API integration with error handling",
                     "Component tests"],
        "deliverables": ["Deployed app URL", "Repo with README and screenshots", "Lighthouse/accessibility report"],
    },
    {
        "match": {"cloud", "devops"},
        "title": "Cloud deployment with CI/CD and infrastructure as code",
        "problem": "Manual deployments are slow and error-prone.",
        "desc": "Containerise an existing app, define its infrastructure as code, and deploy it automatically on "
                "every merge with monitoring and rollback.",
        "features": ["Container image build", "Infrastructure defined as code", "CI/CD pipeline with tests and deploy stage",
                     "Basic monitoring and alerting"],
        "deliverables": ["Repo with pipeline and IaC", "Architecture diagram", "Runbook (deploy/rollback)"],
    },
]


def _pick_stack(skills: list[str], known: list[str]) -> list[str]:
    stack = list(skills)
    for k in known:
        if len(stack) >= 7:
            break
        if k not in stack and category_of(k) not in {"soft_skill", "practice"}:
            stack.append(k)
    return stack[:8]


def template_projects(ctx: ProjectContext, count: int) -> list[ProjectIdea]:
    role = ctx.target_role or "target-role"
    tech_gaps = [g for g in ctx.gap_skills if category_of(g) not in {"soft_skill", "practice"}] or ctx.gap_skills
    difficulty = {"entry": "beginner", "junior": "beginner", "senior": "advanced", "lead": "advanced"}.get(
        ctx.experience_level or "", "intermediate")
    ideas: list[ProjectIdea] = []
    used: set[str] = set()
    for tpl in _TEMPLATES:
        skills = [g for g in tech_gaps if category_of(g) in tpl["match"]][:4]
        if not skills:
            continue
        # Add one complementary gap skill (e.g. Docker for an ML project) to make it realistic.
        extra = [g for g in tech_gaps if g not in skills and g not in used][:1]
        skills = skills + extra
        used.update(skills)
        ideas.append(ProjectIdea(
            title=tpl["title"].format(role=role), problem_statement=tpl["problem"],
            description=tpl["desc"] + (f" Mirrors responsibilities such as: '{ctx.responsibilities[0]}'." if ctx.responsibilities else ""),
            skills_covered=skills, tech_stack=_pick_stack(skills, ctx.known_skills), core_features=tpl["features"],
            difficulty=difficulty, deliverables=tpl["deliverables"], estimated_hours=15 + 8 * len(skills),
        ))
        if len(ideas) >= count:
            break
    leftover = [g for g in tech_gaps if g not in used]
    while len(ideas) < count and leftover:
        chunk, leftover = leftover[:3], leftover[3:]
        ideas.append(ProjectIdea(
            title=f"Hands-on {' + '.join(chunk)} showcase", problem_statement=f"Show practical, job-ready use of {', '.join(chunk)}.",
            description=f"A focused project that applies {', '.join(chunk)} to a realistic {role} task with tests and documentation.",
            skills_covered=chunk, tech_stack=_pick_stack(chunk, ctx.known_skills),
            core_features=[f"Core workflow implemented with {s}" for s in chunk] + ["Tests and README"],
            difficulty=difficulty, deliverables=["GitHub repo with README", "Short write-up of what you learned"],
            estimated_hours=10 + 6 * len(chunk),
        ))
    return ideas


async def recommend(llm: LLMClient, ctx: ProjectContext, count: int) -> tuple[list[ProjectIdea], str]:
    if llm.available and ctx.gap_skills:
        system = (
            "You are a senior hiring manager. Suggest portfolio projects that DIRECTLY demonstrate the candidate's "
            "missing skills for the target role. Each project must list in skills_covered only skills it truly "
            "exercises, and must cover at least one of the gap skills. Be realistic about scope for the experience level."
        )
        user = json.dumps({"target_role": ctx.target_role, "experience_level": ctx.experience_level,
                           "gap_skills_priority_order": ctx.gap_skills[:10], "known_skills": ctx.known_skills[:30],
                           "sample_responsibilities": ctx.responsibilities[:6], "count": count})
        try:
            result = await llm.generate_json(task="project_recommend", system=system, user=user, schema=ProjectList, temperature=0.5)
            gap_set = set(ctx.gap_skills)
            valid = []
            for idea in result.projects:
                covered = [n.name for n in (normalize_skill(s) for s in idea.skills_covered) if n]
                if gap_set & set(covered):
                    valid.append(idea.model_copy(update={"skills_covered": covered}))
            if valid:
                return valid[:count], "llm"
            logger.warning("LLM projects did not cover any gap skill; using templates")
        except LLMError as exc:
            logger.warning("Project recommendation failed, using templates: %s", exc)
    return template_projects(ctx, count), "rule_based"
