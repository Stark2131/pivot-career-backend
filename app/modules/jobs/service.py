"""Job description intake: store the original text, extract & normalise requirements."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import orchestrator
from app.ai.client import LLMClient
from app.ai.schemas import JDSkill
from app.core.config import get_settings
from app.core.database import utcnow
from app.core.errors import NotFoundError
from app.models import JobDescription, JobRequirement, User
from app.modules.jobs.schemas import JobCreate, JobOut, JobRequirementOut, JobSummaryOut
from app.modules.profile.skill_service import get_or_create_skill
from app.utils.url_fetch import fetch_job_text


async def create_job(db: AsyncSession, llm: LLMClient, user: User, body: JobCreate) -> JobDescription:
    settings = get_settings()
    source_url = str(body.source_url) if body.source_url else None
    if body.text:
        text, source_type = body.text, "pasted"
    elif source_url:
        text, source_type = await fetch_job_text(source_url), "url"
    else:
        text, source_type = "", "manual"
    text = text[: settings.max_document_chars]

    warnings: list[str] = []
    generated_by = "manual"
    structured: dict = {}
    required: list[JDSkill] = []
    preferred: list[JDSkill] = []
    if text:
        extraction, generated_by, warnings = await orchestrator.extract_job(llm, text)
        required, preferred = extraction.required_skills, extraction.preferred_skills
        structured = extraction.model_dump(exclude={"required_skills", "preferred_skills"})

    # Manually-entered skills are trusted as the user's own input.
    required += [JDSkill(name=s, evidence="(entered manually)") for s in body.required_skills]
    preferred += [JDSkill(name=s, evidence="(entered manually)") for s in body.preferred_skills]

    # Resolve skills first, then build the job with its requirements in one go
    # (avoids lazy-loading collections, which async SQLAlchemy does not allow).
    requirements: list[JobRequirement] = []
    seen: set[int] = set()
    for req_type, items in (("required", required), ("preferred", preferred)):
        for s in items:
            skill = await get_or_create_skill(db, s.name)
            if skill is None or skill.id in seen:
                continue  # required wins because it is processed first
            seen.add(skill.id)
            requirements.append(
                JobRequirement(skill_id=skill.id, requirement_type=req_type, kind=s.kind,
                               required_proficiency=s.required_proficiency, evidence=s.evidence or None)
            )
    job = JobDescription(
        user_id=user.id,
        title=body.title,
        company=body.company or structured.get("company"),
        source_type=source_type,
        source_url=source_url,
        raw_text=text or "(manual entry - no description text)",
        structured_data=structured,
        extracted_at=utcnow(),
        generated_by=generated_by,
        extraction_warnings=warnings,
        requirements=requirements,
    )
    db.add(job)
    await db.commit()
    return await get_job(db, user, job.id)


async def get_job(db: AsyncSession, user: User, job_id: int) -> JobDescription:
    # populate_existing: refresh objects already in the session so eager loaders (selectin) run.
    stmt = select(JobDescription).where(JobDescription.id == job_id, JobDescription.user_id == user.id)
    job = await db.scalar(stmt.execution_options(populate_existing=True))
    if job is None:
        raise NotFoundError("Job description not found.")
    return job


async def list_jobs(db: AsyncSession, user: User) -> list[JobDescription]:
    rows = await db.scalars(
        select(JobDescription).where(JobDescription.user_id == user.id).order_by(JobDescription.id.desc())
    )
    return list(rows)


async def get_jobs_by_ids(db: AsyncSession, user: User, job_ids: list[int] | None) -> list[JobDescription]:
    """Used by skill-gap analysis. Always scoped to the user."""
    stmt = select(JobDescription).where(JobDescription.user_id == user.id)
    if job_ids:
        stmt = stmt.where(JobDescription.id.in_(job_ids))
    jobs = list(await db.scalars(stmt.order_by(JobDescription.id)))
    if job_ids and len(jobs) != len(set(job_ids)):
        raise NotFoundError("One or more job descriptions were not found.")
    return jobs


async def delete_job(db: AsyncSession, user: User, job_id: int) -> None:
    job = await get_job(db, user, job_id)
    await db.delete(job)
    await db.commit()


def to_out(job: JobDescription) -> JobOut:
    return JobOut(
        id=job.id, title=job.title, company=job.company, source_type=job.source_type, source_url=job.source_url,
        raw_text=job.raw_text, structured_data=job.structured_data, extracted_at=job.extracted_at,
        generated_by=job.generated_by, extraction_warnings=job.extraction_warnings,
        requirements=[
            JobRequirementOut(skill_id=r.skill_id, skill_name=r.skill.name, category=r.skill.category,
                              requirement_type=r.requirement_type, kind=r.kind,
                              required_proficiency=r.required_proficiency, evidence=r.evidence)
            for r in job.requirements
        ],
        created_at=job.created_at,
    )


def to_summary(job: JobDescription) -> JobSummaryOut:
    return JobSummaryOut(
        id=job.id, title=job.title, company=job.company, source_type=job.source_type, source_url=job.source_url,
        generated_by=job.generated_by,
        required_count=sum(1 for r in job.requirements if r.requirement_type == "required"),
        preferred_count=sum(1 for r in job.requirements if r.requirement_type == "preferred"),
        created_at=job.created_at,
    )
