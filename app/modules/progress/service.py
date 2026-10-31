"""Progress tracking: aggregates plan tasks, assessments, interviews and projects.

All numbers come from the user's own records - nothing is simulated.
"""
from dataclasses import asdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import orchestrator
from app.ai.client import LLMClient
from app.ai.progress_analyst import ProgressSnapshot, TaskFact, detect_struggles, struggling_skills
from app.core.database import as_utc, utcnow
from app.core.errors import ValidationFailed
from app.models import LearningPlan, MockInterview, ProgressRecord, ProjectRecommendation, User, UserProfile, UserSkill
from app.modules.learning_plans import service as plan_service
from app.modules.profile.skill_service import get_or_create_skill
from app.modules.progress.schemas import (
    AssessmentCreate,
    ConsistencyOut,
    InterviewProgressOut,
    PlanProgressOut,
    ProgressOverview,
    RecalculateOut,
    RecalculateRequest,
    SkillProgressOut,
    StruggleOut,
)


async def record_assessment(db: AsyncSession, user: User, body: AssessmentCreate) -> ProgressRecord:
    skill = await get_or_create_skill(db, body.skill_name)
    if skill is None:
        raise ValidationFailed("Invalid skill name.")
    us = await db.scalar(select(UserSkill).where(UserSkill.user_id == user.id, UserSkill.skill_id == skill.id))
    previous = us.proficiency if us else None
    if us is None:
        db.add(UserSkill(user_id=user.id, skill_id=skill.id, proficiency=body.proficiency, source="assessment",
                         confirmed=True, last_assessed_at=utcnow()))
    else:
        us.proficiency, us.confirmed, us.last_assessed_at = body.proficiency, True, utcnow()
        if us.source == "resume":
            us.source = "assessment"
    record = ProgressRecord(user_id=user.id, record_type="skill_assessment", skill_id=skill.id, skill_name=skill.name,
                            proficiency=body.proficiency, previous_proficiency=previous,
                            assessment_method=body.method, notes=body.notes)
    db.add(record)
    await db.commit()
    return record


async def list_assessments(db: AsyncSession, user: User) -> list[ProgressRecord]:
    rows = await db.scalars(select(ProgressRecord).where(
        ProgressRecord.user_id == user.id, ProgressRecord.record_type == "skill_assessment").order_by(ProgressRecord.id.desc()))
    return list(rows)


def _week_index(start: date, when) -> int:
    return (as_utc(when).date() - start).days // 7 + 1


async def _collect(db: AsyncSession, user: User) -> tuple[ProgressOverview, ProgressSnapshot, LearningPlan | None]:
    today = date.today()
    plan = await plan_service.get_active_plan(db, user)

    # --- plan & consistency ---
    pp = PlanProgressOut(plan_id=plan.id if plan else None)
    facts: list[TaskFact] = []
    weeks_elapsed, active_weeks, streak, last_activity = 0, 0, 0, None
    if plan:
        for t in plan.tasks:
            week_end = plan.start_date + timedelta(weeks=t.week_number)
            overdue = t.status != "completed" and week_end < today
            facts.append(TaskFact(t.skill_name, t.week_number, t.status, t.estimated_hours, t.difficulty_rating, overdue))
            pp.total_tasks += 1
            pp.hours_total += t.estimated_hours
            pp.overdue += overdue
            if t.status == "completed":
                pp.completed += 1
                pp.hours_completed += t.estimated_hours
            elif t.status == "skipped":
                pp.skipped += 1
            elif t.status == "in_progress":
                pp.in_progress += 1
            else:
                pp.pending += 1
        pp.percent_complete = round(100 * pp.completed / pp.total_tasks, 1) if pp.total_tasks else 0.0
        pp.hours_total, pp.hours_completed = round(pp.hours_total, 1), round(pp.hours_completed, 1)

        weeks_elapsed = max(0, min((today - plan.start_date).days // 7 + 1, plan.total_weeks or 1))
        done_times = [as_utc(t.completed_at) for t in plan.tasks if t.completed_at]
        weeks_with_activity = {_week_index(plan.start_date, d) for d in done_times}
        active_weeks = len({w for w in weeks_with_activity if 1 <= w <= max(weeks_elapsed, 1)})
        last_activity = max(done_times) if done_times else None
        w = weeks_elapsed
        while w >= 1 and w in weeks_with_activity:
            streak, w = streak + 1, w - 1
    consistency = ConsistencyOut(
        weeks_elapsed=weeks_elapsed, active_weeks=active_weeks,
        consistency_rate=round(active_weeks / weeks_elapsed, 2) if weeks_elapsed else None,
        current_streak_weeks=streak, last_activity_at=last_activity,
    )

    # --- assessments ---
    records = await db.scalars(select(ProgressRecord).where(
        ProgressRecord.user_id == user.id, ProgressRecord.record_type == "skill_assessment").order_by(ProgressRecord.id))
    history: dict[str, list[int]] = {}
    for r in records:
        if r.skill_name and r.proficiency is not None:
            seq = history.setdefault(r.skill_name, [])
            if not seq and r.previous_proficiency is not None:
                seq.append(r.previous_proficiency)  # baseline before first assessment
            seq.append(r.proficiency)
    skills = [SkillProgressOut(skill_name=k, first_level=v[0], latest_level=v[-1], change=v[-1] - v[0], assessments=len(v))
              for k, v in sorted(history.items())]

    # --- interviews ---
    interviews = list(await db.scalars(select(MockInterview).where(MockInterview.user_id == user.id).order_by(MockInterview.id)))
    by_skill: dict[str, list[float]] = {}
    trend = []
    for i in interviews:
        if i.overall_score is not None:
            trend.append({"interview_id": i.id, "date": i.created_at.date().isoformat(), "score": i.overall_score})
        for q in i.questions:
            if q.evaluation and q.skill_name:
                by_skill.setdefault(q.skill_name, []).append(q.evaluation.overall_score)
    interview_out = InterviewProgressOut(
        interviews_evaluated=len(trend),
        average_score=round(sum(t["score"] for t in trend) / len(trend), 1) if trend else None,
        trend=trend, score_by_skill={k: round(sum(v) / len(v), 1) for k, v in by_skill.items()},
    )

    # --- projects ---
    projects: dict[str, int] = {"recommended": 0, "in_progress": 0, "completed": 0, "dismissed": 0}
    for p in await db.scalars(select(ProjectRecommendation).where(ProjectRecommendation.user_id == user.id)):
        projects[p.status] = projects.get(p.status, 0) + 1

    snapshot = ProgressSnapshot(tasks=facts, interview_scores_by_skill=by_skill, assessments_by_skill=history,
                                projects_by_status=projects, consistency_rate=consistency.consistency_rate,
                                weeks_elapsed=weeks_elapsed)
    struggles = [StruggleOut(**asdict(s)) for s in detect_struggles(snapshot)]
    overview = ProgressOverview(plan=pp, consistency=consistency, skills=skills, interviews=interview_out,
                                projects=projects, struggling_areas=struggles)
    return overview, snapshot, plan


async def get_overview(db: AsyncSession, llm: LLMClient, user: User, include_ai_insights: bool) -> ProgressOverview:
    overview, snapshot, plan = await _collect(db, user)
    if include_ai_insights:
        profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
        insights, generated_by, trace = await orchestrator.analyze_progress(
            llm, snapshot, profile.target_role if profile else None)
        overview.insights, overview.insights_generated_by = insights, generated_by
        db.add(ProgressRecord(user_id=user.id, record_type="progress_analysis",
                              data={"insights": insights.model_dump(), "generated_by": generated_by,
                                    "tool_calls": [t["tool"] for t in trace]}))
        await db.commit()
    return overview


async def recalculate_plan(db: AsyncSession, llm: LLMClient, user: User, body: RecalculateRequest) -> RecalculateOut:
    overview, snapshot, plan = await _collect(db, user)
    if plan is None:
        raise ValidationFailed("No active learning plan to recalculate. Generate one first.")
    struggles = detect_struggles(snapshot)  # same rules as the overview
    struggling = struggling_skills(struggles)
    weekly_hours = body.weekly_hours
    if weekly_hours is None and any(s.signal == "consistency" for s in struggles):
        weekly_hours = max(2, round(plan.weekly_hours * 0.75))  # sustainable pace suggestion
    proposed = await plan_service.propose_adjustment(
        db, llm, user, plan, reason=body.reason, struggling=struggling, focus=[], weekly_hours=weekly_hours,
        extra_change_info={"triggered_by": "progress_recalculation",
                           "signals": [{"area": s.area, "signal": s.signal, "evidence": s.evidence} for s in struggles]},
    )
    return RecalculateOut(
        struggling_areas=overview.struggling_areas, proposed_plan=plan_service.to_out(proposed),
        note="This is a PROPOSAL. Your current plan is unchanged until you call POST /api/plans/{id}/accept.",
    )
