"""Learning plans: generation, task tracking and *versioned* adjustments.

Versioning rules
* The first plan a user generates becomes `active`.
* Any later generation or adjustment creates a NEW plan with status `proposed`
  (linked through parent_plan_id). The active plan is never modified by AI.
* The user reviews `change_summary` and calls accept (old active -> archived,
  proposal -> active) or reject. Older pending proposals become `superseded`.
"""
from datetime import date, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import orchestrator
from app.ai.client import LLMClient
from app.ai.planner import ScheduledTask, SkillNeed, estimate_hours
from app.core.database import utcnow
from app.core.errors import ConflictError, NotFoundError, ValidationFailed
from app.models import LearningPlan, SkillGapAnalysis, User, UserProfile, WeeklyTask
from app.modules.learning_plans.schemas import (
    AdjustPlanRequest,
    GeneratePlanRequest,
    PlanOut,
    PlanProgress,
    PlanSummaryOut,
    PlanWeekOut,
    TaskUpdate,
    WeeklyTaskOut,
)
from app.modules.profile.skill_service import list_user_skills
from app.modules.skill_gap.service import get_analysis, latest_analysis
from app.utils.skills_taxonomy import normalize_skill


async def _profile(db: AsyncSession, user: User) -> UserProfile | None:
    return await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))


async def _active_plan(db: AsyncSession, user: User) -> LearningPlan | None:
    return await db.scalar(select(LearningPlan).where(LearningPlan.user_id == user.id, LearningPlan.status == "active"))


async def _next_version(db: AsyncSession, user: User) -> int:
    current = await db.scalar(select(func.max(LearningPlan.version)).where(LearningPlan.user_id == user.id))
    return (current or 0) + 1


def _tasks_to_rows(tasks: list[ScheduledTask]) -> list[WeeklyTask]:
    return [
        WeeklyTask(week_number=t.week_number, skill_name=t.skill_name, title=t.title[:255], topics=t.topics,
                   activities=t.activities, exercises=t.exercises, estimated_hours=t.hours,
                   expected_outcome=t.expected_outcome, status="pending")
        for t in tasks
    ]


async def generate_plan(db: AsyncSession, llm: LLMClient, user: User, body: GeneratePlanRequest) -> LearningPlan:
    analysis: SkillGapAnalysis | None = (
        await get_analysis(db, user, body.analysis_id) if body.analysis_id else await latest_analysis(db, user)
    )
    if analysis is None:
        raise ValidationFailed("Run a skill-gap analysis first (POST /api/skill-gap/analyze).")
    profile = await _profile(db, user)
    weekly_hours = body.weekly_hours or (profile.weekly_hours if profile else 8)
    level = profile.experience_level if profile else None

    gaps = [i for i in analysis.items if i.gap_level != "none" and (i.is_priority or i.importance >= 0.25)]
    if not gaps:
        raise ValidationFailed("No significant skill gaps found - you already match these job descriptions.")
    needs = [SkillNeed(skill_name=i.skill_name, hours=estimate_hours(i.skill_name, i.gap_level, level),
                       gap_level=i.gap_level) for i in gaps]
    known = [us.skill.name for us in await list_user_skills(db, user.id)]

    tasks, deferred, generated_by, llm_summary = await orchestrator.create_learning_plan(
        llm, needs, weekly_hours=weekly_hours, max_weeks=body.max_weeks, target_role=analysis.target_role,
        experience_level=level, known_skills=known,
    )
    total_weeks = max((t.week_number for t in tasks), default=0)
    summary = (
        f"{total_weeks}-week plan at {weekly_hours} h/week covering {len({t.skill_name for t in tasks})} skill gap(s), "
        f"ordered by importance in your target job descriptions."
    )
    if deferred:
        summary += f" Not scheduled (exceeds {body.max_weeks} weeks): {', '.join(deferred)}."
    if llm_summary:
        summary += "\n\n" + llm_summary

    active = await _active_plan(db, user)
    plan = LearningPlan(
        user_id=user.id, analysis_id=analysis.id, parent_plan_id=active.id if active else None,
        version=await _next_version(db, user), status="proposed" if active else "active",
        title=f"Path to {analysis.target_role or 'your target role'}", target_role=analysis.target_role,
        weekly_hours=weekly_hours, total_weeks=total_weeks, start_date=body.start_date or date.today(),
        summary=summary, generated_by=generated_by,
        adjustment_reason="Regenerated from a new skill-gap analysis" if active else None,
        change_summary=_diff(active, tasks) if active else {},
        tasks=_tasks_to_rows(tasks),
    )
    if active:
        await _supersede_pending(db, user)
    db.add(plan)
    await db.commit()
    return await get_plan(db, user, plan.id)


def _diff(old: LearningPlan, new_tasks: list[ScheduledTask], hours_changes: dict | None = None) -> dict:
    old_skills = {t.skill_name for t in old.tasks}
    new_skills = {t.skill_name for t in new_tasks}
    return {
        "compared_to_plan_id": old.id,
        "added_skills": sorted(new_skills - old_skills),
        "removed_skills": sorted(old_skills - new_skills),
        "kept_skills": sorted(old_skills & new_skills),
        "weeks_before": old.total_weeks,
        "weeks_after": max((t.week_number for t in new_tasks), default=0),
        "completed_tasks_carried_over": sum(1 for t in old.tasks if t.status == "completed"),
        "hours_changes": {k: {"before": v[0], "after": v[1]} for k, v in (hours_changes or {}).items()},
    }


async def _supersede_pending(db: AsyncSession, user: User) -> None:
    await db.execute(
        update(LearningPlan).where(LearningPlan.user_id == user.id, LearningPlan.status == "proposed")
        .values(status="superseded")
    )


async def propose_adjustment(
    db: AsyncSession, llm: LLMClient, user: User, plan: LearningPlan, *, reason: str,
    struggling: set[str], focus: list[str], weekly_hours: int | None = None, max_weeks: int | None = None,
    extra_change_info: dict | None = None,
) -> LearningPlan:
    """Create a proposed new version of `plan` that carries over remaining work."""
    if plan.status not in {"active", "proposed"}:
        raise ConflictError(f"Cannot adjust a plan with status '{plan.status}'.")
    profile = await _profile(db, user)
    level = profile.experience_level if profile else None
    weekly_hours = weekly_hours or plan.weekly_hours

    remaining: dict[str, float] = {}
    order: list[str] = []
    for t in plan.tasks:
        if t.skill_name not in order:
            order.append(t.skill_name)
        if t.status != "completed":
            remaining[t.skill_name] = round(remaining.get(t.skill_name, 0) + t.estimated_hours, 1)
    focus_norm = [n.name for n in (normalize_skill(f) for f in focus) if n]
    struggling_norm = {n.name for n in (normalize_skill(s) for s in struggling) if n}

    needs, changes = orchestrator.adjust_plan_needs(
        remaining, order, struggling=struggling_norm, focus=focus_norm, experience_level=level
    )
    if not needs:
        raise ValidationFailed("All tasks in this plan are completed - generate a new plan from a fresh analysis instead.")
    known = [us.skill.name for us in await list_user_skills(db, user.id)]
    max_weeks = max_weeks or max(plan.total_weeks + 4, 4)
    tasks, deferred, generated_by, llm_summary = await orchestrator.create_learning_plan(
        llm, needs, weekly_hours=weekly_hours, max_weeks=min(max_weeks, 26), target_role=plan.target_role,
        experience_level=level, known_skills=known,
    )
    change_summary = _diff(plan, tasks, changes)
    change_summary["struggling_skills"] = sorted(struggling_norm)
    change_summary["focus_skills"] = focus_norm
    change_summary["deferred"] = deferred
    change_summary.update(extra_change_info or {})

    summary = (f"Adjusted plan: {max((t.week_number for t in tasks), default=0)} weeks at {weekly_hours} h/week "
               f"for the remaining work. Reason: {reason}")
    if llm_summary:
        summary += "\n\n" + llm_summary
    await _supersede_pending(db, user)
    new_plan = LearningPlan(
        user_id=user.id, analysis_id=plan.analysis_id, parent_plan_id=plan.id,
        version=await _next_version(db, user), status="proposed",
        title=plan.title, target_role=plan.target_role, weekly_hours=weekly_hours,
        total_weeks=max((t.week_number for t in tasks), default=0), start_date=date.today(), summary=summary,
        adjustment_reason=reason, change_summary=change_summary, generated_by=generated_by,
        tasks=_tasks_to_rows(tasks),
    )
    db.add(new_plan)
    await db.commit()
    return await get_plan(db, user, new_plan.id)


async def adjust_plan(db: AsyncSession, llm: LLMClient, user: User, plan_id: int, body: AdjustPlanRequest) -> LearningPlan:
    plan = await get_plan(db, user, plan_id)
    # Tasks the user rated as hard (>=4) or skipped are treated as struggling too.
    struggling = set(body.struggling_skills) | {
        t.skill_name for t in plan.tasks if (t.difficulty_rating or 0) >= 4 or t.status == "skipped"
    }
    return await propose_adjustment(db, llm, user, plan, reason=body.reason, struggling=struggling,
                                    focus=body.focus_skills, weekly_hours=body.weekly_hours, max_weeks=body.max_weeks)


async def accept_plan(db: AsyncSession, user: User, plan_id: int) -> LearningPlan:
    plan = await get_plan(db, user, plan_id)
    if plan.status != "proposed":
        raise ConflictError("Only proposed plans can be accepted.")
    await db.execute(
        update(LearningPlan).where(LearningPlan.user_id == user.id, LearningPlan.status == "active")
        .values(status="archived")
    )
    plan.status = "active"
    await db.commit()
    return await get_plan(db, user, plan_id)


async def reject_plan(db: AsyncSession, user: User, plan_id: int) -> LearningPlan:
    plan = await get_plan(db, user, plan_id)
    if plan.status != "proposed":
        raise ConflictError("Only proposed plans can be rejected.")
    plan.status = "rejected"
    await db.commit()
    return await get_plan(db, user, plan_id)


async def get_plan(db: AsyncSession, user: User, plan_id: int) -> LearningPlan:
    stmt = select(LearningPlan).where(LearningPlan.id == plan_id, LearningPlan.user_id == user.id)
    plan = await db.scalar(stmt.execution_options(populate_existing=True))
    if plan is None:
        raise NotFoundError("Learning plan not found.")
    return plan


async def list_plans(db: AsyncSession, user: User, status: str | None = None) -> list[LearningPlan]:
    stmt = select(LearningPlan).where(LearningPlan.user_id == user.id)
    if status:
        stmt = stmt.where(LearningPlan.status == status)
    return list(await db.scalars(stmt.order_by(LearningPlan.id.desc())))


async def get_active_plan(db: AsyncSession, user: User) -> LearningPlan | None:
    plan = await _active_plan(db, user)
    return await get_plan(db, user, plan.id) if plan else None


async def update_task(db: AsyncSession, user: User, plan_id: int, task_id: int, body: TaskUpdate) -> WeeklyTask:
    plan = await get_plan(db, user, plan_id)
    if plan.status not in {"active", "proposed"}:
        raise ConflictError("Tasks of archived/rejected plans are read-only.")
    task = next((t for t in plan.tasks if t.id == task_id), None)
    if task is None:
        raise NotFoundError("Task not found in this plan.")
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] is not None:
        task.status = data.pop("status")
        task.completed_at = utcnow() if task.status == "completed" else None
    for field, value in data.items():
        if value is not None or field == "notes":
            setattr(task, field, value)
    await db.commit()
    return task


# --- serialisation ---------------------------------------------------------------------------
def _progress(plan: LearningPlan) -> PlanProgress:
    total = len(plan.tasks)
    done = sum(1 for t in plan.tasks if t.status == "completed")
    return PlanProgress(total_tasks=total, completed_tasks=done, percent_complete=round(100 * done / total, 1) if total else 0.0)


def to_summary(plan: LearningPlan) -> PlanSummaryOut:
    return PlanSummaryOut(
        id=plan.id, version=plan.version, status=plan.status, title=plan.title, target_role=plan.target_role,
        weekly_hours=plan.weekly_hours, total_weeks=plan.total_weeks, start_date=plan.start_date,
        parent_plan_id=plan.parent_plan_id, generated_by=plan.generated_by, progress=_progress(plan),
        created_at=plan.created_at,
    )


def to_out(plan: LearningPlan) -> PlanOut:
    weeks: dict[int, list[WeeklyTask]] = {}
    for t in plan.tasks:
        weeks.setdefault(t.week_number, []).append(t)
    week_out = [
        PlanWeekOut(
            week_number=w, start_date=plan.start_date + timedelta(weeks=w - 1),
            total_hours=round(sum(t.estimated_hours for t in ts), 1),
            skills=list(dict.fromkeys(t.skill_name for t in ts)),
            tasks=[WeeklyTaskOut.model_validate(t) for t in ts],
        )
        for w, ts in sorted(weeks.items())
    ]
    return PlanOut(
        **to_summary(plan).model_dump(), analysis_id=plan.analysis_id, summary=plan.summary,
        adjustment_reason=plan.adjustment_reason, change_summary=plan.change_summary, weeks=week_out,
    )
