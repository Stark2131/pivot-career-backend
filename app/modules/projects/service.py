from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import orchestrator
from app.ai.client import LLMClient
from app.ai.project_recommender import ProjectContext
from app.core.database import utcnow
from app.core.errors import NotFoundError, ValidationFailed
from app.models import JobDescription, ProjectRecommendation, User, UserProfile
from app.modules.jobs.market import role_family_of
from app.modules.profile.skill_service import list_user_skills
from app.modules.projects.schemas import ProjectUpdate, RecommendRequest
from app.modules.skill_gap.service import get_analysis, latest_analysis


async def recommend(db: AsyncSession, llm: LLMClient, user: User, body: RecommendRequest) -> list[ProjectRecommendation]:
    analysis = await get_analysis(db, user, body.analysis_id) if body.analysis_id else await latest_analysis(db, user)
    if analysis is None:
        raise ValidationFailed("Run a skill-gap analysis first so projects can target your gaps.")
    gaps = [i.skill_name for i in sorted(analysis.items, key=lambda i: i.priority_rank) if i.gap_level != "none"]
    if not gaps:
        raise ValidationFailed("No skill gaps found in this analysis.")
    profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    jobs = await db.scalars(select(JobDescription).where(
        JobDescription.user_id == user.id, JobDescription.id.in_(analysis.job_description_ids or [0])))
    responsibilities = [r for j in jobs for r in (j.structured_data or {}).get("responsibilities", [])][:6]
    ctx = ProjectContext(
        target_role=analysis.target_role, experience_level=profile.experience_level if profile else None,
        gap_skills=gaps, known_skills=[us.skill.name for us in await list_user_skills(db, user.id)],
        responsibilities=responsibilities, role_family=analysis.role_family or role_family_of(analysis.target_role),
    )
    ideas, generated_by = await orchestrator.recommend_projects(llm, ctx, body.count)
    rows = [
        ProjectRecommendation(
            user_id=user.id, analysis_id=analysis.id, title=i.title, problem_statement=i.problem_statement,
            description=i.description, skills_covered=i.skills_covered, tech_stack=i.tech_stack,
            core_features=i.core_features, difficulty=i.difficulty, deliverables=i.deliverables,
            estimated_hours=i.estimated_hours, template_id=i.template_id, gaps_covered=i.gaps_covered,
            status="recommended", generated_by=generated_by,
        )
        for i in ideas
    ]
    db.add_all(rows)
    await db.commit()
    return rows


async def list_projects(db: AsyncSession, user: User, status: str | None = None) -> list[ProjectRecommendation]:
    stmt = select(ProjectRecommendation).where(ProjectRecommendation.user_id == user.id)
    if status:
        stmt = stmt.where(ProjectRecommendation.status == status)
    return list(await db.scalars(stmt.order_by(ProjectRecommendation.id.desc())))


async def get_project(db: AsyncSession, user: User, project_id: int) -> ProjectRecommendation:
    p = await db.scalar(select(ProjectRecommendation).where(
        ProjectRecommendation.id == project_id, ProjectRecommendation.user_id == user.id))
    if p is None:
        raise NotFoundError("Project not found.")
    return p


async def update_project(db: AsyncSession, user: User, project_id: int, body: ProjectUpdate) -> ProjectRecommendation:
    p = await get_project(db, user, project_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("status"):
        p.status = data["status"]
        p.completed_at = utcnow() if p.status == "completed" else None
    if "repo_url" in data:
        p.repo_url = str(data["repo_url"]) if data["repo_url"] else None
    if "notes" in data:
        p.notes = data["notes"]
    await db.commit()
    return p
