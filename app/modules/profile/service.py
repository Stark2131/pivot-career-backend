"""Profile & resume intake business logic."""
import re

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import orchestrator
from app.ai.client import LLMClient
from app.core.config import get_settings
from app.core.errors import NotFoundError, ValidationFailed
from app.models import Resume, User, UserProfile, UserSkill
from app.modules.profile.schemas import ProfileOut, ProfileUpdate, ResumeOut, UserSkillOut
from app.modules.profile.skill_service import get_or_create_skill, list_user_skills
from app.utils.docx_text import DOCX_MIME, extract_docx_text
from app.utils.pdf import extract_pdf_text
from app.utils.skills_taxonomy import normalize_skill


def _safe_filename(name: str | None) -> str:
    name = (name or "resume.pdf").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)[:200]
    return name or "resume.pdf"


async def get_or_create_profile(db: AsyncSession, user: User) -> UserProfile:
    profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    if profile is None:
        profile = UserProfile(user_id=user.id)
        db.add(profile)
        await db.flush()
    return profile


async def upload_resume(
    db: AsyncSession, llm: LLMClient, user: User, *, filename: str | None, content_type: str | None, data: bytes
) -> Resume:
    settings = get_settings()
    if len(data) > settings.max_resume_bytes:
        raise ValidationFailed(f"File too large. Maximum size is {settings.max_resume_size_mb} MB.")
    safe_name = _safe_filename(filename).lower()
    is_docx = safe_name.endswith(".docx")
    if not (is_docx or safe_name.endswith(".pdf")):
        raise ValidationFailed("Only .pdf and .docx resumes are supported.")
    allowed = {DOCX_MIME, "application/octet-stream"} if is_docx else {"application/pdf", "application/x-pdf"}
    if content_type not in allowed | {None, ""}:
        raise ValidationFailed("The file type does not match its extension. Upload a .pdf or .docx resume.")

    extract = extract_docx_text if is_docx else extract_pdf_text
    text, pages = extract(data, max_pages=settings.max_resume_pages)
    text = text[: settings.max_document_chars]

    extraction, generated_by, warnings = await orchestrator.parse_resume(llm, text)

    # Only one active resume at a time; old ones are kept for history.
    await db.execute(update(Resume).where(Resume.user_id == user.id).values(is_active=False))
    resume = Resume(
        user_id=user.id,
        filename=_safe_filename(filename),
        size_bytes=len(data),
        page_count=pages,
        text=text,
        parsed_data=extraction.model_dump(),
        parse_status="parsed",
        generated_by=generated_by,
        validation_warnings=warnings,
        is_active=True,
    )
    db.add(resume)

    profile = await get_or_create_profile(db, user)
    profile.work_experience = [w.model_dump() for w in extraction.work_experience]
    profile.education = [e.model_dump() for e in extraction.education]
    profile.projects = [p.model_dump() for p in extraction.projects]
    profile.certifications = [c.model_dump() for c in extraction.certifications]
    profile.soft_skills = sorted(set(profile.soft_skills or []) | set(extraction.soft_skills))
    # Don't overwrite values the user typed in themselves.
    profile.current_role = profile.current_role or extraction.current_role
    if profile.years_experience is None:
        profile.years_experience = extraction.years_experience
    profile.summary = profile.summary or extraction.summary

    await _sync_resume_skills(db, user.id, extraction)
    await db.commit()
    await db.refresh(resume)
    return resume


async def _sync_resume_skills(db: AsyncSession, user_id: int, extraction) -> None:
    """Upsert resume skills as *unconfirmed*; never downgrade user-confirmed/assessed skills."""
    existing = {us.skill_id: us for us in await list_user_skills(db, user_id)}
    seen: set[int] = set()
    for s in extraction.technical_skills:
        skill = await get_or_create_skill(db, s.name)
        if skill is None or skill.id in seen:
            continue
        seen.add(skill.id)
        us = existing.get(skill.id)
        if us is None:
            db.add(UserSkill(user_id=user_id, skill_id=skill.id, proficiency=s.proficiency_hint, source="resume",
                             confirmed=False, evidence=s.evidence or None))
        elif us.source == "resume":
            us.evidence = s.evidence or us.evidence
            us.proficiency = us.proficiency or s.proficiency_hint
    # Resume-only skills that disappeared from the new resume are removed (user-entered ones stay).
    for skill_id, us in existing.items():
        if us.source == "resume" and not us.confirmed and skill_id not in seen:
            await db.delete(us)


async def get_profile(db: AsyncSession, user: User) -> ProfileOut:
    profile = await get_or_create_profile(db, user)
    resume = await db.scalar(select(Resume).where(Resume.user_id == user.id, Resume.is_active.is_(True)))
    skills = await list_user_skills(db, user.id)
    await db.commit()
    return ProfileOut(
        current_role=profile.current_role,
        target_role=profile.target_role,
        experience_level=profile.experience_level,
        years_experience=profile.years_experience,
        weekly_hours=profile.weekly_hours,
        summary=profile.summary,
        experience_notes=profile.experience_notes,
        soft_skills=profile.soft_skills or [],
        work_experience=profile.work_experience or [],
        education=profile.education or [],
        projects=profile.projects or [],
        certifications=profile.certifications or [],
        skills=[
            UserSkillOut(skill_id=us.skill_id, name=us.skill.name, category=us.skill.category,
                         proficiency=us.proficiency, source=us.source, confirmed=us.confirmed, evidence=us.evidence)
            for us in skills
        ],
        active_resume=ResumeOut.model_validate(resume) if resume else None,
        needs_review=any(not us.confirmed for us in skills),
    )


async def update_profile(db: AsyncSession, user: User, body: ProfileUpdate) -> ProfileOut:
    profile = await get_or_create_profile(db, user)
    data = body.model_dump(exclude_unset=True)
    skills_in = data.pop("skills", None)
    if "soft_skills" in data and data["soft_skills"] is not None:
        data["soft_skills"] = sorted({(normalize_skill(s).name if normalize_skill(s) else s) for s in data["soft_skills"]})
    for field, value in data.items():
        if value is None and field in {"weekly_hours", "soft_skills", "work_experience", "education", "projects", "certifications"}:
            continue  # these columns are non-nullable
        setattr(profile, field, value)

    if skills_in is not None:
        existing = {us.skill_id: us for us in await list_user_skills(db, user.id)}
        keep: set[int] = set()
        for item in body.skills or []:
            skill = await get_or_create_skill(db, item.name)
            if skill is None or skill.id in keep:
                continue
            keep.add(skill.id)
            us = existing.get(skill.id)
            if us is None:
                db.add(UserSkill(user_id=user.id, skill_id=skill.id, proficiency=item.proficiency,
                                 source="self_reported", confirmed=True))
            else:
                us.confirmed = True
                if item.proficiency is not None:
                    us.proficiency = item.proficiency
        for skill_id, us in existing.items():
            if skill_id not in keep:
                await db.delete(us)
    await db.commit()
    return await get_profile(db, user)


async def list_resumes(db: AsyncSession, user: User) -> list[Resume]:
    return list(await db.scalars(select(Resume).where(Resume.user_id == user.id).order_by(Resume.id.desc())))


async def get_resume(db: AsyncSession, user: User, resume_id: int) -> Resume:
    resume = await db.scalar(select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id))
    if resume is None:
        raise NotFoundError("Resume not found.")
    return resume
