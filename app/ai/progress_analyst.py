"""Progress Analyst: detects where the user is struggling and suggests adjustments.

`detect_struggles` is rule-based and authoritative (it drives plan
recalculation). The LLM, if available, writes coaching insights after
inspecting the same snapshot through validated read-only tools.
"""
import logging
from dataclasses import asdict, dataclass, field

from pydantic import BaseModel, Field

from app.ai.client import LLMClient, LLMError
from app.ai.schemas import ProgressInsights, StrugglingArea
from app.ai.tools import Tool, ToolRegistry, run_tool_loop

logger = logging.getLogger(__name__)


@dataclass
class TaskFact:
    skill_name: str
    week_number: int
    status: str
    estimated_hours: float
    difficulty_rating: int | None
    overdue: bool


@dataclass
class ProgressSnapshot:
    tasks: list[TaskFact] = field(default_factory=list)
    interview_scores_by_skill: dict[str, list[float]] = field(default_factory=dict)
    assessments_by_skill: dict[str, list[int]] = field(default_factory=dict)  # chronological
    projects_by_status: dict[str, int] = field(default_factory=dict)
    consistency_rate: float | None = None
    weeks_elapsed: int = 0


@dataclass
class Struggle:
    area: str
    signal: str  # difficulty | skipped | overdue | interview | assessment | consistency
    evidence: str
    recommendation: str
    skill_name: str | None = None


def detect_struggles(s: ProgressSnapshot) -> list[Struggle]:
    out: list[Struggle] = []
    by_skill: dict[str, list[TaskFact]] = {}
    for t in s.tasks:
        by_skill.setdefault(t.skill_name, []).append(t)
    for skill, ts in by_skill.items():
        hard = [t for t in ts if (t.difficulty_rating or 0) >= 4]
        skipped = [t for t in ts if t.status == "skipped"]
        overdue = [t for t in ts if t.overdue and t.status != "completed"]
        if hard:
            out.append(Struggle(skill, "difficulty", f"{len(hard)} task(s) rated hard (>=4/5)",
                                f"Allocate more time to {skill} and add easier warm-up material.", skill))
        if skipped:
            out.append(Struggle(skill, "skipped", f"{len(skipped)} task(s) skipped",
                                f"Revisit {skill}: break the work into smaller steps.", skill))
        if len(overdue) >= 2:
            out.append(Struggle(skill, "overdue", f"{len(overdue)} task(s) overdue",
                                f"Reschedule {skill} with a lighter weekly load.", skill))
    for skill, scores in s.interview_scores_by_skill.items():
        avg = sum(scores) / len(scores)
        if avg < 5:
            out.append(Struggle(skill, "interview", f"average mock-interview score {avg:.1f}/10 over {len(scores)} answer(s)",
                                f"Practise explaining {skill} concepts out loud and redo a mock interview.", skill))
    for skill, levels in s.assessments_by_skill.items():
        if len(levels) >= 2 and levels[-1] <= levels[0] and levels[-1] <= 2:
            out.append(Struggle(skill, "assessment", f"self-assessed level stayed at {levels[-1]}/5 across {len(levels)} assessments",
                                f"Change approach for {skill}: try a project-based exercise or a different resource.", skill))
    if s.consistency_rate is not None and s.weeks_elapsed >= 2 and s.consistency_rate < 0.5:
        out.append(Struggle("Learning consistency", "consistency",
                            f"activity in {round(s.consistency_rate * 100)}% of elapsed weeks",
                            "Reduce weekly hours to a sustainable level and schedule fixed study slots."))
    return out


def struggling_skills(struggles: list[Struggle]) -> set[str]:
    return {s.skill_name for s in struggles if s.skill_name}


def rule_based_insights(snapshot: ProgressSnapshot, struggles: list[Struggle]) -> ProgressInsights:
    total = len(snapshot.tasks)
    done = sum(1 for t in snapshot.tasks if t.status == "completed")
    summary = (f"You have completed {done} of {total} planned task(s)." if total else "No learning plan tasks yet.")
    if struggles:
        summary += f" {len(struggles)} area(s) need attention."
    else:
        summary += " No struggle signals detected - keep going."
    adjustments = []
    if struggling_skills(struggles):
        adjustments.append("Recalculate the plan to give struggling skills more time (POST /api/progress/recalculate-plan).")
    if any(s.signal == "consistency" for s in struggles):
        adjustments.append("Lower weekly hours so the plan matches your real availability.")
    return ProgressInsights(
        summary=summary,
        struggling_areas=[StrugglingArea(area=s.area, evidence=s.evidence, recommendation=s.recommendation) for s in struggles][:10],
        recommended_adjustments=adjustments,
    )


# --- read-only tools over the snapshot -----------------------------------------------------
class _NoArgs(BaseModel):
    pass


class _SkillArg(BaseModel):
    skill_name: str = Field(min_length=1, max_length=120)


def build_registry(s: ProgressSnapshot) -> ToolRegistry:
    def task_summary(_: _NoArgs):
        out: dict[str, dict] = {}
        for t in s.tasks:
            d = out.setdefault(t.skill_name, {"total": 0, "completed": 0, "skipped": 0, "overdue": 0, "hard": 0})
            d["total"] += 1
            d["completed"] += t.status == "completed"
            d["skipped"] += t.status == "skipped"
            d["overdue"] += t.overdue and t.status != "completed"
            d["hard"] += (t.difficulty_rating or 0) >= 4
        return {"by_skill": out, "consistency_rate": s.consistency_rate, "weeks_elapsed": s.weeks_elapsed}

    def interview_scores(_: _NoArgs):
        return {k: {"average": round(sum(v) / len(v), 1), "n": len(v)} for k, v in s.interview_scores_by_skill.items()}

    def skill_history(a: _SkillArg):
        key = next((k for k in s.assessments_by_skill if k.lower() == a.skill_name.lower()), None)
        return {"skill": a.skill_name, "assessments": s.assessments_by_skill.get(key, []) if key else []}

    def project_status(_: _NoArgs):
        return s.projects_by_status

    return ToolRegistry([
        Tool("get_task_summary", "Per-skill counts of planned/completed/skipped/overdue/hard tasks + consistency.", _NoArgs, task_summary),
        Tool("get_interview_scores", "Average mock-interview score (0-10) per skill.", _NoArgs, interview_scores),
        Tool("get_skill_assessment_history", "Chronological self/quiz assessment levels (1-5) for one skill.", _SkillArg, skill_history),
        Tool("get_project_status", "Counts of portfolio projects by status.", _NoArgs, project_status),
    ])


async def analyze_progress(llm: LLMClient, snapshot: ProgressSnapshot, target_role: str | None) -> tuple[ProgressInsights, str, list[dict]]:
    """Returns (insights, generated_by, tool_trace)."""
    struggles = detect_struggles(snapshot)
    if llm.available:
        system = ("You are a supportive learning coach for someone pivoting into a new role. Use the tools to inspect "
                  "their progress, then identify where they struggle and recommend concrete plan adjustments. "
                  "Base every claim on tool results; do not invent numbers.")
        user = (f"Target role: {target_role}. Rule-based signals already detected: "
                f"{[asdict(x) for x in struggles]}")
        try:
            insights, trace = await run_tool_loop(llm, task="progress_analysis", system=system, user=user,
                                                  registry=build_registry(snapshot), final_schema=ProgressInsights)
            return insights, "llm_tools", trace
        except LLMError as exc:
            logger.warning("Progress analysis via LLM failed, using rules: %s", exc)
    return rule_based_insights(snapshot, struggles), "rule_based", []
