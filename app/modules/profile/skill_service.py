"""Shared skill helpers used by several modules (profile, jobs, progress, ...)."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Skill, UserSkill
from app.utils.skills_taxonomy import normalize_skill, slugify


async def get_or_create_skill(db: AsyncSession, raw_name: str) -> Skill | None:
    """Return the canonical Skill row for a free-text name (creating it if needed)."""
    norm = normalize_skill(raw_name)
    if norm is None:
        return None
    slug = slugify(norm.name)
    skill = await db.scalar(select(Skill).where(Skill.slug == slug))
    if skill is None:
        skill = Skill(name=norm.name, slug=slug, category=norm.category, in_taxonomy=norm.in_taxonomy)
        db.add(skill)
        await db.flush()
    return skill


async def list_user_skills(db: AsyncSession, user_id: int) -> list[UserSkill]:
    stmt = select(UserSkill).where(UserSkill.user_id == user_id).order_by(UserSkill.id)
    # populate_existing makes sure `.skill` is eagerly loaded even for rows created in this session.
    rows = await db.scalars(stmt.execution_options(populate_existing=True))
    return list(rows)


async def user_skill_map(db: AsyncSession, user_id: int) -> dict[str, UserSkill]:
    """{canonical skill name: UserSkill}"""
    return {us.skill.name: us for us in await list_user_skills(db, user_id)}
