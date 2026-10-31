from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import orchestrator
from app.ai.client import LLMClient
from app.core.database import utcnow
from app.core.errors import NotFoundError
from app.models import JobApplication, User
from app.modules.applications.analytics import AppFact, compute_analytics
from app.modules.applications.schemas import ApplicationAnalytics, ApplicationCreate, ApplicationUpdate
from app.modules.jobs.service import get_job
from app.modules.profile.skill_service import list_user_skills
from app.utils.skills_taxonomy import normalize_skill

INTERVIEW_STATUSES = {"interview", "offer"}


def _norm_skills(names: list[str]) -> list[str]:
    return list(dict.fromkeys(n.name for n in (normalize_skill(s) for s in names) if n))


async def create_application(db: AsyncSession, user: User, body: ApplicationCreate) -> JobApplication:
    skills = _norm_skills(body.skills_highlighted)
    jd_text = body.job_description_text
    if body.job_description_id is not None:
        job = await get_job(db, user, body.job_description_id)  # ownership check
        jd_text = jd_text or job.raw_text
        if not skills:
            # Default: the user's skills that this JD asks for.
            mine = {us.skill.name for us in await list_user_skills(db, user.id)}
            skills = [r.skill.name for r in job.requirements if r.skill.name in mine]
    app = JobApplication(
        user_id=user.id, company_name=body.company_name, role_title=body.role_title,
        job_description_id=body.job_description_id, job_description_text=jd_text, applied_date=body.applied_date,
        status=body.status, reached_interview=body.status in INTERVIEW_STATUSES,
        experience_level=body.experience_level, skills_highlighted=skills, notes=body.notes,
        status_changed_at=utcnow(),
    )
    db.add(app)
    await db.commit()
    return app


async def get_application(db: AsyncSession, user: User, app_id: int) -> JobApplication:
    app = await db.scalar(select(JobApplication).where(JobApplication.id == app_id, JobApplication.user_id == user.id))
    if app is None:
        raise NotFoundError("Application not found.")
    return app


async def list_applications(db: AsyncSession, user: User, status: str | None = None) -> list[JobApplication]:
    stmt = select(JobApplication).where(JobApplication.user_id == user.id)
    if status:
        stmt = stmt.where(JobApplication.status == status)
    return list(await db.scalars(stmt.order_by(JobApplication.applied_date.desc(), JobApplication.id.desc())))


async def update_application(db: AsyncSession, user: User, app_id: int, body: ApplicationUpdate) -> JobApplication:
    app = await get_application(db, user, app_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("status") and data["status"] != app.status:
        app.status = data["status"]
        app.status_changed_at = utcnow()
        if app.status in INTERVIEW_STATUSES:
            app.reached_interview = True  # sticky: stays true if later rejected
    data.pop("status", None)
    if data.get("reached_interview") is not None:
        app.reached_interview = data["reached_interview"] or app.status in INTERVIEW_STATUSES
    data.pop("reached_interview", None)
    if data.get("skills_highlighted") is not None:
        data["skills_highlighted"] = _norm_skills(data["skills_highlighted"])
    for field, value in data.items():
        if value is None and field in {"company_name", "role_title", "skills_highlighted"}:
            continue
        setattr(app, field, value)
    await db.commit()
    return app


async def delete_application(db: AsyncSession, user: User, app_id: int) -> None:
    await db.delete(await get_application(db, user, app_id))
    await db.commit()


async def analytics(db: AsyncSession, llm: LLMClient, user: User, include_ai_summary: bool) -> ApplicationAnalytics:
    apps = await list_applications(db, user)
    facts = [AppFact(role_title=a.role_title, status=a.status, reached_interview=a.reached_interview,
                     experience_level=a.experience_level, skills=a.skills_highlighted or []) for a in apps]
    stats = compute_analytics(facts)
    narrative, generated_by = await orchestrator.summarize_applications(
        llm if include_ai_summary else None, stats)
    return ApplicationAnalytics(stats=stats, narrative=narrative, generated_by=generated_by)
