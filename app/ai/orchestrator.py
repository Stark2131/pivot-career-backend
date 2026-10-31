"""AI orchestration facade.

The rest of the backend talks to AI *only* through these functions. Each one
delegates to a focused component that uses the shared LLMClient and returns
validated Pydantic objects / dataclasses, falling back to deterministic logic
when the LLM is unavailable.

| Component            | Module                    | LLM role                         | Deterministic part          |
|----------------------|---------------------------|----------------------------------|-----------------------------|
| Resume Parser        | resume_parser.py          | structured extraction            | grounding check, fallback   |
| JD extraction        | jd_extractor.py           | structured extraction            | grounding check, fallback   |
| Skill Gap Analyst    | skill_analyzer.py         | prose explanations only          | gap levels, importance      |
| Learning Planner     | planner.py                | weekly content                   | schedule & hours            |
| Project Recommender  | project_recommender.py    | project ideas                    | gap-coverage validation     |
| Interviewer          | interviewer.py            | questions                        | question bank fallback      |
| Interview Evaluator  | evaluator.py              | rubric scores + feedback         | overall score, heuristic    |
| Progress Analyst     | progress_analyst.py       | insights via read-only tools     | struggling-area detection   |
| Application Analyst  | application_analyst.py    | narrative over computed stats    | all statistics              |

Components never receive a DB session: plain data in, plain data out.
Persistence stays in the module services, so the LLM can never run SQL,
execute code, or touch another user's data.
"""
from app.ai import application_analyst, evaluator, interviewer, planner, progress_analyst, project_recommender, skill_analyzer
from app.ai.client import LLMClient
from app.ai.jd_extractor import extract_job
from app.ai.resume_parser import parse_resume
from app.ai.schemas import AnswerEvaluation, ApplicationNarrative, GeneratedQuestion, ProgressInsights, ProjectIdea


async def analyze_skill_gaps(
    llm: LLMClient,
    user_skills: dict[str, skill_analyzer.UserSkillInfo],
    jobs: list[skill_analyzer.JobInput],
    target_role: str | None,
) -> tuple[skill_analyzer.GapReport, str]:
    report = skill_analyzer.compute_gaps(user_skills, jobs)
    generated_by = await skill_analyzer.explain_gaps(llm, report, target_role)
    return report, generated_by


async def create_learning_plan(
    llm: LLMClient,
    needs: list[planner.SkillNeed],
    *,
    weekly_hours: int,
    max_weeks: int,
    target_role: str | None,
    experience_level: str | None,
    known_skills: list[str],
) -> tuple[list[planner.ScheduledTask], list[str], str, str | None]:
    """Returns (tasks, deferred_skills, generated_by, llm_summary)."""
    tasks, deferred = planner.build_schedule(needs, weekly_hours, max_weeks)
    generated_by, summary = await planner.fill_content(
        llm, tasks, target_role=target_role, experience_level=experience_level, known_skills=known_skills
    )
    return tasks, deferred, generated_by, summary


adjust_plan_needs = planner.adjust_needs


async def recommend_projects(
    llm: LLMClient, ctx: project_recommender.ProjectContext, count: int
) -> tuple[list[ProjectIdea], str]:
    return await project_recommender.recommend(llm, ctx, count)


async def generate_interview_questions(
    llm: LLMClient, ctx: interviewer.InterviewContext
) -> tuple[list[GeneratedQuestion], str]:
    return await interviewer.generate_questions(llm, ctx)


async def evaluate_interview_answer(llm: LLMClient, qa: evaluator.QAInput) -> tuple[AnswerEvaluation, str]:
    return await evaluator.evaluate_answer(llm, qa)


async def analyze_progress(
    llm: LLMClient, snapshot: progress_analyst.ProgressSnapshot, target_role: str | None
) -> tuple[ProgressInsights, str, list[dict]]:
    return await progress_analyst.analyze_progress(llm, snapshot, target_role)


class _NoLLM(LLMClient):
    """Used when the caller explicitly opts out of AI (e.g. include_ai_summary=false)."""

    def __init__(self):  # noqa: D401 - no settings needed
        self.provider = "none"

    @property
    def available(self) -> bool:
        return False


async def summarize_applications(llm: LLMClient | None, stats: dict) -> tuple[ApplicationNarrative, str]:
    return await application_analyst.summarize(llm or _NoLLM(), stats)


__all__ = [
    "parse_resume",
    "extract_job",
    "analyze_skill_gaps",
    "create_learning_plan",
    "adjust_plan_needs",
    "recommend_projects",
    "generate_interview_questions",
    "evaluate_interview_answer",
    "analyze_progress",
    "summarize_applications",
]
