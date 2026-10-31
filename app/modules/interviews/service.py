"""Text-based mock interviews: generate questions, collect answers, evaluate with a fixed rubric."""
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import orchestrator
from app.ai.client import LLMClient
from app.ai.evaluator import CRITERIA, RUBRIC_DATA, RUBRIC_VERSION, QAInput, level_of, overall
from app.ai.interviewer import InterviewContext
from app.core.errors import ConflictError, NotFoundError, ValidationFailed
from app.models import InterviewAnswer, InterviewEvaluation, InterviewQuestion, MockInterview, User, UserProfile
from app.modules.interviews.schemas import (
    AnswerSubmit,
    EvaluateRequest,
    EvaluationOut,
    InterviewCreate,
    InterviewOut,
    InterviewSummaryOut,
    QuestionOut,
)
from app.modules.profile.skill_service import list_user_skills
from app.modules.skill_gap.service import latest_analysis
from app.utils.skills_taxonomy import normalize_skill


async def create_interview(db: AsyncSession, llm: LLMClient, user: User, body: InterviewCreate) -> MockInterview:
    profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    target_role = body.target_role or (profile.target_role if profile else None)
    if not target_role:
        raise ValidationFailed("Set a target role in your profile or pass `target_role`.")
    known = [us.skill.name for us in await list_user_skills(db, user.id)]
    focus = [n.name for n in (normalize_skill(s) for s in body.focus_skills) if n]
    if not focus:
        analysis = await latest_analysis(db, user)
        if analysis:
            focus = [i.skill_name for i in analysis.items if i.gap_level != "none"][:5]
            # Also probe a couple of skills the role needs that the user already has.
            focus += [i.skill_name for i in analysis.items if i.gap_level == "none"][:2]
    if not focus:
        focus = known[:5]
    ctx = InterviewContext(target_role=target_role, experience_level=profile.experience_level if profile else None,
                           interview_type=body.interview_type, num_questions=body.num_questions,
                           focus_skills=focus, known_skills=known)
    questions, generated_by = await orchestrator.generate_interview_questions(llm, ctx)
    interview = MockInterview(
        user_id=user.id, target_role=target_role, interview_type=body.interview_type, status="in_progress",
        generated_by=generated_by,
        questions=[
            InterviewQuestion(order_index=i, question_text=q.question_text, skill_name=q.skill_name,
                              category=q.category, difficulty=q.difficulty, key_points=q.key_points)
            for i, q in enumerate(questions, start=1)
        ],
    )
    db.add(interview)
    await db.commit()
    return await get_interview(db, user, interview.id)


async def get_interview(db: AsyncSession, user: User, interview_id: int) -> MockInterview:
    stmt = select(MockInterview).where(MockInterview.id == interview_id, MockInterview.user_id == user.id)
    interview = await db.scalar(stmt.execution_options(populate_existing=True))
    if interview is None:
        raise NotFoundError("Interview not found.")
    return interview


async def list_interviews(db: AsyncSession, user: User) -> list[MockInterview]:
    rows = await db.scalars(select(MockInterview).where(MockInterview.user_id == user.id).order_by(MockInterview.id.desc()))
    return list(rows)


async def submit_answer(db: AsyncSession, user: User, interview_id: int, body: AnswerSubmit) -> MockInterview:
    interview = await get_interview(db, user, interview_id)
    q = next((q for q in interview.questions if q.id == body.question_id), None)
    if q is None:
        raise NotFoundError("Question not found in this interview.")
    if q.answer is None:
        q.answer = InterviewAnswer(answer_text=body.answer_text)
    else:
        q.answer.answer_text = body.answer_text
        q.evaluation = None  # answer changed -> previous evaluation no longer applies
    interview.status = "in_progress"
    await db.commit()
    return await get_interview(db, user, interview_id)


async def evaluate(db: AsyncSession, llm: LLMClient, user: User, interview_id: int,
                   body: EvaluateRequest) -> tuple[MockInterview, dict[str, list[float]]]:
    """Returns the interview and {skill: [scores]} for answers evaluated for the first time in this call."""
    interview = await get_interview(db, user, interview_id)
    profile = await db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    targets = [q for q in interview.questions if q.answer is not None and q.evaluation is None]
    if body.question_ids:
        wanted = set(body.question_ids)
        if not wanted <= {q.id for q in interview.questions}:
            raise NotFoundError("One or more questions are not in this interview.")
        targets = [q for q in interview.questions if q.id in wanted and q.answer is not None]
    if not targets and not any(q.evaluation for q in interview.questions):
        raise ConflictError("Answer at least one question before requesting an evaluation.")

    first_time = {q.id for q in targets if q.evaluation is None}
    new_scores: dict[str, list[float]] = {}
    for q in targets:
        qa = QAInput(question=q.question_text, answer=q.answer.answer_text, category=q.category,
                     skill_name=q.skill_name, key_points=q.key_points or [], target_role=interview.target_role,
                     experience_level=profile.experience_level if profile else None)
        ev, evaluator = await orchestrator.evaluate_interview_answer(llm, qa)
        q.evaluation = InterviewEvaluation(
            answer_id=q.answer.id, rubric_version=RUBRIC_VERSION,
            **{c: getattr(ev.scores, c) for c in CRITERIA},
            overall_score=overall(ev.scores), strengths=ev.strengths, improvements=ev.improvements,
            suggested_answer_improvements=ev.suggested_answer_improvements,
            topics_to_revise=ev.topics_to_revise, evidence=ev.evidence, evaluator=evaluator,
        )
        if q.id in first_time and q.skill_name:
            new_scores.setdefault(q.skill_name, []).append(q.evaluation.overall_score)
    await db.flush()
    _update_summary(interview)
    await db.commit()
    return await get_interview(db, user, interview_id), new_scores


def _update_summary(interview: MockInterview) -> None:
    evals = [q.evaluation for q in interview.questions if q.evaluation is not None]
    if not evals:
        return
    interview.overall_score = round(sum(e.overall_score for e in evals) / len(evals), 1)
    by_skill: dict[str, list[float]] = {}
    for q in interview.questions:
        if q.evaluation and q.skill_name:
            by_skill.setdefault(q.skill_name, []).append(q.evaluation.overall_score)
    topics = Counter(t for e in evals for t in e.topics_to_revise)
    interview.summary = {
        "evaluated_questions": len(evals),
        "criteria_averages": {c: round(sum(getattr(e, c) for e in evals) / len(evals), 1) for c in CRITERIA},
        "score_by_skill": {s: round(sum(v) / len(v), 1) for s, v in by_skill.items()},
        "weakest_skills": [s for s, v in sorted(by_skill.items(), key=lambda kv: sum(kv[1]) / len(kv[1])) if sum(v) / len(v) < 6][:5],
        "top_strengths": [s for e in evals for s in e.strengths][:5],
        "recommended_topics_to_revise": [t for t, _ in topics.most_common(8)],
        "evaluators_used": sorted({e.evaluator for e in evals}),
    }
    if all(q.evaluation is not None for q in interview.questions):
        interview.status = "completed"


# --- serialisation ------------------------------------------------------------------------
def _q_out(q: InterviewQuestion) -> QuestionOut:
    ev = q.evaluation
    return QuestionOut(
        id=q.id, order_index=q.order_index, question_text=q.question_text, skill_name=q.skill_name,
        category=q.category, difficulty=q.difficulty, key_points=q.key_points if ev else None,
        answer_text=q.answer.answer_text if q.answer else None,
        answered_at=q.answer.updated_at if q.answer else None,
        evaluation=EvaluationOut(
            rubric_version=ev.rubric_version, scores={c: getattr(ev, c) for c in CRITERIA},
            levels={c: level_of(getattr(ev, c)) for c in CRITERIA}, evidence=ev.evidence or {},
            overall_score=ev.overall_score, strengths=ev.strengths, improvements=ev.improvements,
            suggested_answer_improvements=ev.suggested_answer_improvements,
            topics_to_revise=ev.topics_to_revise, evaluator=ev.evaluator,
        ) if ev else None,
    )


def to_summary(i: MockInterview) -> InterviewSummaryOut:
    return InterviewSummaryOut(
        id=i.id, target_role=i.target_role, interview_type=i.interview_type, status=i.status,
        overall_score=i.overall_score, question_count=len(i.questions),
        answered_count=sum(1 for q in i.questions if q.answer), evaluated_count=sum(1 for q in i.questions if q.evaluation),
        generated_by=i.generated_by, created_at=i.created_at,
    )


def to_out(i: MockInterview) -> InterviewOut:
    return InterviewOut(**to_summary(i).model_dump(), summary=i.summary or {}, questions=[_q_out(q) for q in i.questions])


def rubric() -> dict:
    """The rubric shown to the user (same file the evaluator prompts from)."""
    return RUBRIC_DATA
