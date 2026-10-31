"""Job description intake: store the original text, extract & normalise requirements."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import orchestrator
from app.ai.client import LLMClient
from app.ai.schemas import JDSkill
from app.core.config import get_settings
from app.core.database import utcnow
from app.core.errors import NotFoundError, ValidationFailed
from app.models import JobDescription, JobRequirement, User, UserProfile
from app.modules.jobs.market import fetch_postings, role_family_of
from app.modules.jobs.schemas import (
    JobCreate,
    JobOut,
    JobRequirementOut,
    JobSummaryOut,
    MarketImportOut,
    MarketImportRequest,
)
from app.modules.profile.skill_service import get_or_create_skill
from app.utils.url_fetch import fetch_job_text


async def create_job(
    db: AsyncSession, llm: LLMClient, user: User, body: JobCreate, *,
    source_type_override: str | None = None, source_provider: str | None = None, role_family: str | None = None,
) -> JobDescription:
    settings = get_settings()
    source_url = str(body.source_url) if body.source_url else None
    if body.text:
        text, source_type = body.text, "pasted"
    elif source_url:
        text, source_type = await fetch_job_text(source_url), "url"
    else:
        text, source_type = "", "manual"
    source_type = source_type_override or source_type
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
        role_family=role_family or role_family_of(body.title),
        source_provider=source_provider,
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


async def import_market_postings(db: AsyncSession, user: User, body: MarketImportRequest) -> MarketImportOut:
    """Import postings for the target role (live API -> cache -> seed) as the user's saved job descriptions.

    Extraction is rule-based on purpose: bulk imports must be fast and deterministic. Postings already imported
    (same provider, title and company) are skipped, so the call is safe to repeat.
    """
    profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    role = (body.target_role or (profile.target_role if profile else None) or "").strip()
    if not role:
        raise ValidationFailed("Set a target role in your profile (or pass target_role) before importing postings.")
    result = await fetch_postings(db, role, country=body.country, limit=body.limit, refresh=body.refresh, source=body.source)
    if not result.postings:
        raise ValidationFailed(
            f"No postings available for '{role}'. Seed data covers: Data Analyst, Product Manager, Machine Learning "
            "Engineer. Paste job descriptions manually or configure JSEARCH_API_KEY / ADZUNA_APP_ID.")
    family = role_family_of(role)
    existing = {(j.source_provider, j.title.lower(), (j.company or "").lower()) for j in await list_jobs(db, user)}
    nollm = orchestrator.NoLLM()
    ids: list[int] = []
    skipped = 0
    for p in result.postings:
        sig = (result.source, p.title.lower(), (p.company or "").lower())
        if sig in existing:
            skipped += 1
            continue
        existing.add(sig)
        job = await _create_imported(db, nollm, user, p, result.source, family)
        ids.append(job.id)
    return MarketImportOut(
        source=result.source, requested_role=role, role_family=family, imported=len(ids), skipped_duplicates=skipped,
        job_ids=ids, cached=result.cached, fallback_reason=result.fallback_reason, notes=result.notes)


async def _create_imported(db, llm, user, p, source: str, family: str | None) -> JobDescription:
    body = JobCreate(title=p.title[:200] if len(p.title) >= 2 else "Job posting", company=(p.company or None),
                     text=(p.text if len(p.text) >= 50 else p.text.ljust(50, " "))[:50_000])
    job = await create_job(db, llm, user, body, source_type_override="market", source_provider=source,
                           role_family=family or role_family_of(p.title))
    if p.url and p.url.startswith(("http://", "https://")):
        job.source_url = p.url[:2048]  # stored as-is; never fetched
        await db.commit()
    return job


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
        source_provider=job.source_provider, role_family=job.role_family, raw_text=job.raw_text, structured_data=job.structured_data, extracted_at=job.extracted_at,
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
        source_provider=job.source_provider, role_family=job.role_family, generated_by=job.generated_by,
        required_count=sum(1 for r in job.requirements if r.requirement_type == "required"),
        preferred_count=sum(1 for r in job.requirements if r.requirement_type == "preferred"),
        created_at=job.created_at,
    )
