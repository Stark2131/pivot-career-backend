"""Closed loop: new evidence (interview scores, assessments, slipping tasks) -> proficiency -> gaps -> plan proposal.

`adapt` is called by the routers after an interview is evaluated, an assessment is saved or a task is
updated. It never touches the active plan: at most it creates (or refreshes) a *proposed* version with a
human-readable `change_summary["reasons"]`. Failures here must never break the request that triggered them.
"""
import hashlib
import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import orchestrator
from app.ai.client import LLMClient
from app.ai.progress_analyst import detect_struggles
from app.core.database import utcnow
from app.core.errors import AppError
from app.models import LearningPlan, ProgressRecord, User, UserSkill
from app.modules.learning_plans import service as plan_service
from app.modules.profile.skill_service import user_skill_map
from app.modules.progress import service as progress_service
from app.modules.progress.schemas import AdaptationOut, ProficiencyUpdate
from app.modules.skill_gap import service as gap_service
from app.modules.skill_gap.schemas import AnalyzeRequest

logger = logging.getLogger(__name__)

EMA_ALPHA = 0.4  # weight of the newest evidence


def score_to_level(score_0_10: float) -> float:
    """Map a 0-10 rubric score onto the 1-5 proficiency scale."""
    return max(1.0, min(5.0, score_0_10 / 2))


def ema_level(previous: int, evidence_level: float, alpha: float = EMA_ALPHA) -> int:
    return max(1, min(5, round(alpha * evidence_level + (1 - alpha) * previous)))


async def _apply_interview_evidence(db: AsyncSession, user: User, scores: dict[str, list[float]]) -> list[ProficiencyUpdate]:
    """Move proficiency of skills the user already has towards what the interview showed.

    Skills the user does not have are left alone: they are already gaps, and inventing a level for them would
    make them look *less* urgent (partial instead of missing).
    """
    owned = await user_skill_map(db, user.id)
    updates: list[ProficiencyUpdate] = []
    for skill_name, values in scores.items():
        us: UserSkill | None = owned.get(skill_name)
        if us is None or us.proficiency is None or not values:
            continue
        avg = sum(values) / len(values)
        new = ema_level(us.proficiency, score_to_level(avg))
        if new == us.proficiency:
            continue
        evidence = f"mock interview scored {avg:.1f}/10"
        db.add(ProgressRecord(user_id=user.id, record_type="skill_assessment", skill_id=us.skill_id,
                              skill_name=skill_name, proficiency=new, previous_proficiency=us.proficiency,
                              assessment_method="interview", notes=evidence))
        updates.append(ProficiencyUpdate(skill_name=skill_name, before=us.proficiency, after=new, evidence=evidence))
        us.proficiency, us.last_assessed_at = new, utcnow()
        if us.source == "resume":
            us.source = "assessment"
    if updates:
        await db.commit()
    return updates


async def adapt(
    db: AsyncSession, llm: LLMClient, user: User, *, trigger: str,
    interview_scores: dict[str, list[float]] | None = None, changed_skills: set[str] | None = None,
) -> AdaptationOut:
    """Update proficiency from evidence, recompute gaps and (if warranted) propose an adjusted plan."""
    try:
        return await _adapt(db, llm, user, trigger, interview_scores or {}, set(changed_skills or ()))
    except AppError as exc:
        logger.info("Adaptation skipped (%s): %s", trigger, exc)
        return AdaptationOut(trigger=trigger, message=f"No plan change proposed: {exc.message}")
    except Exception:  # noqa: BLE001 - the triggering request already succeeded; never fail it here
        logger.exception("Adaptation failed (%s)", trigger)
        await db.rollback()
        return AdaptationOut(trigger=trigger, message="Automatic plan check failed; use 'Recalculate plan' manually.")


async def _adapt(db, llm, user, trigger, scores, changed) -> AdaptationOut:
    updates = await _apply_interview_evidence(db, user, scores) if scores else []
    changed |= {u.skill_name for u in updates}

    plan: LearningPlan | None = await plan_service.get_active_plan(db, user)
    if plan is None:
        return AdaptationOut(trigger=trigger, proficiency_updates=updates,
                             message="Proficiency updated. No active plan to adjust.")

    # --- recompute gaps from the same job descriptions, deterministically (no extra LLM call) ---
    gaps_recomputed, mastered, regressed = False, set(), set()
    previous = await gap_service.latest_analysis(db, user)
    if changed and previous is not None:
        analysis = await gap_service.analyze(db, orchestrator.NoLLM(), user, AnalyzeRequest(
            job_description_ids=previous.job_description_ids, target_role=previous.target_role))
        gaps_recomputed = True
        level = {i.skill_name: i.gap_level for i in analysis.items}
        mastered = {s for s in changed if level.get(s) == "none"}
        regressed = {s for s in changed if level.get(s) in {"partial", "missing"}}

    _, snapshot, _ = await progress_service._collect(db, user)  # noqa: SLF001 - same package
    struggles = detect_struggles(snapshot)
    plan_skills = {t.skill_name for t in plan.tasks if t.status != "completed"}
    struggling = {s.skill_name for s in struggles if s.skill_name}
    # Skills that fell back into the gap but the plan no longer covers get added as focus.
    focus = sorted(s for s in regressed if s not in plan_skills)
    struggling_in_plan = {s for s in struggling if s in plan_skills}
    drop = {s for s in mastered if s in plan_skills}

    hours = None
    if any(s.signal == "consistency" for s in struggles):
        hours = max(2, round(plan.weekly_hours * 0.75))
    if not (struggling_in_plan or focus or drop or hours):
        return AdaptationOut(trigger=trigger, proficiency_updates=updates, gaps_recomputed=gaps_recomputed,
                             message="Plan still fits your progress; no change proposed.")

    reasons_by_skill = {s.skill_name: s.evidence for s in struggles if s.skill_name}
    for u in updates:
        reasons_by_skill[u.skill_name] = f"{u.evidence}, level {u.before} to {u.after}/5"
    for s in mastered:
        reasons_by_skill[s] = "now at or above the level the jobs ask for"
    signature = hashlib.sha1(json.dumps([sorted(struggling_in_plan), focus, sorted(drop), hours,
                                         sorted(reasons_by_skill.items())]).encode()).hexdigest()[:16]
    for p in await plan_service.list_plans(db, user, "proposed"):
        if (p.change_summary or {}).get("auto_signature") == signature:
            return AdaptationOut(trigger=trigger, proficiency_updates=updates, gaps_recomputed=gaps_recomputed,
                                 proposal_plan_id=p.id, reasons=(p.change_summary or {}).get("reasons", []),
                                 message="A matching plan proposal is already waiting for your review.")

    proposed = await plan_service.propose_adjustment(
        db, llm, user, plan, reason=None, struggling=struggling_in_plan, focus=focus, drop=drop,
        weekly_hours=hours, skill_reasons=reasons_by_skill,
        extra_change_info={"triggered_by": f"auto:{trigger}", "auto_signature": signature,
                           "proficiency_updates": [u.model_dump() for u in updates],
                           "signals": [{"area": s.area, "signal": s.signal, "evidence": s.evidence} for s in struggles]},
    )
    reasons = proposed.change_summary.get("reasons", [])
    return AdaptationOut(trigger=trigger, proficiency_updates=updates, gaps_recomputed=gaps_recomputed,
                         proposal_plan_id=proposed.id, reasons=reasons,
                         message="Your progress changed the picture, so a new plan version was proposed for your review.")
