from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import orchestrator
from app.ai.client import LLMClient
from app.ai.skill_analyzer import JobInput, Requirement, UserSkillInfo
from app.core.errors import NotFoundError, ValidationFailed
from app.models import SkillGapAnalysis, SkillGapItem, User, UserProfile
from app.modules.jobs.market import role_family_of
from app.modules.jobs.service import get_jobs_by_ids
from app.modules.profile.skill_service import list_user_skills
from app.modules.skill_gap.schemas import AnalyzeRequest


async def analyze(db: AsyncSession, llm: LLMClient, user: User, body: AnalyzeRequest) -> SkillGapAnalysis:
    jobs = await get_jobs_by_ids(db, user, body.job_description_ids)
    jobs = [j for j in jobs if j.requirements]
    if not jobs:
        raise ValidationFailed("Add at least one job description with extractable skills before running an analysis.")

    profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    target_role = body.target_role or (profile.target_role if profile else None) or jobs[0].title
    # Importance = share of *this role's* postings that mention a skill, so postings for other roles that the
    # user also saved must not dilute it. Only applies when the user did not pick specific postings.
    family = role_family_of(target_role)
    if family and not body.job_description_ids:
        same_role = [j for j in jobs if j.role_family == family]
        if same_role:
            jobs = same_role

    user_skills = {
        us.skill.name: UserSkillInfo(proficiency=us.proficiency, confirmed=us.confirmed, source=us.source)
        for us in await list_user_skills(db, user.id)
    }
    job_inputs = [
        JobInput(id=j.id, title=j.title, company=j.company, requirements=[
            Requirement(skill_id=r.skill_id, skill_name=r.skill.name, category=r.skill.category,
                        requirement_type=r.requirement_type, required_proficiency=r.required_proficiency,
                        evidence=r.evidence)
            for r in j.requirements
        ])
        for j in jobs
    ]
    report, generated_by = await orchestrator.analyze_skill_gaps(llm, user_skills, job_inputs, target_role)

    analysis = SkillGapAnalysis(
        user_id=user.id, target_role=target_role, job_description_ids=[j.id for j in jobs],
        job_count=len(jobs), role_family=family,
        job_sources=dict(Counter(j.source_provider or j.source_type for j in jobs)),
        match_score=report.match_score, summary=report.summary, generated_by=generated_by,
        items=[
            SkillGapItem(
                skill_id=i.skill_id, skill_name=i.skill_name, category=i.category,
                current_proficiency=i.current_proficiency, required_proficiency=i.required_proficiency,
                gap_level=i.gap_level, importance=i.importance, importance_label=i.importance_label,
                frequency=i.frequency, required_count=i.required_count, preferred_count=i.preferred_count,
                priority_rank=i.priority_rank, is_priority=i.is_priority, explanation=i.explanation,
                job_references=i.job_references,
            )
            for i in report.items
        ],
    )
    db.add(analysis)
    await db.commit()
    return await get_analysis(db, user, analysis.id)


async def get_analysis(db: AsyncSession, user: User, analysis_id: int) -> SkillGapAnalysis:
    stmt = select(SkillGapAnalysis).where(SkillGapAnalysis.id == analysis_id, SkillGapAnalysis.user_id == user.id)
    analysis = await db.scalar(stmt.execution_options(populate_existing=True))
    if analysis is None:
        raise NotFoundError("Skill gap analysis not found.")
    return analysis


async def latest_analysis(db: AsyncSession, user: User) -> SkillGapAnalysis | None:
    stmt = (select(SkillGapAnalysis).where(SkillGapAnalysis.user_id == user.id)
            .order_by(SkillGapAnalysis.id.desc()).limit(1))
    return await db.scalar(stmt)


async def list_analyses(db: AsyncSession, user: User) -> list[SkillGapAnalysis]:
    rows = await db.scalars(
        select(SkillGapAnalysis).where(SkillGapAnalysis.user_id == user.id).order_by(SkillGapAnalysis.id.desc())
    )
    return list(rows)
