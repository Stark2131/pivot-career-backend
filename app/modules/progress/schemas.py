from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas import ProgressInsights
from app.modules.learning_plans.schemas import PlanOut


class AssessmentCreate(BaseModel):
    skill_name: str = Field(min_length=1, max_length=120)
    proficiency: int = Field(ge=1, le=5, description="1=aware .. 5=expert")
    method: Literal["self", "quiz", "mentor"] = "self"
    notes: str | None = Field(default=None, max_length=2000)


class AssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    skill_name: str | None
    proficiency: int | None
    previous_proficiency: int | None
    assessment_method: str | None
    notes: str | None
    created_at: datetime


class StruggleOut(BaseModel):
    area: str
    signal: str
    evidence: str
    recommendation: str
    skill_name: str | None


class PlanProgressOut(BaseModel):
    plan_id: int | None
    total_tasks: int = 0
    completed: int = 0
    pending: int = 0
    in_progress: int = 0
    skipped: int = 0
    overdue: int = 0
    percent_complete: float = 0.0
    hours_completed: float = 0.0
    hours_total: float = 0.0


class ConsistencyOut(BaseModel):
    weeks_elapsed: int
    active_weeks: int
    consistency_rate: float | None = Field(description="Share of elapsed plan weeks with >=1 completed task")
    current_streak_weeks: int
    last_activity_at: datetime | None


class SkillProgressOut(BaseModel):
    skill_name: str
    first_level: int
    latest_level: int
    change: int
    assessments: int


class InterviewProgressOut(BaseModel):
    interviews_evaluated: int
    average_score: float | None
    trend: list[dict]
    score_by_skill: dict[str, float]


class ProgressOverview(BaseModel):
    plan: PlanProgressOut
    consistency: ConsistencyOut
    skills: list[SkillProgressOut]
    interviews: InterviewProgressOut
    projects: dict[str, int]
    struggling_areas: list[StruggleOut]
    insights: ProgressInsights | None = None
    insights_generated_by: str | None = None


class RecalculateRequest(BaseModel):
    reason: str = Field(default="Adjusting plan based on recent progress", max_length=1000)
    weekly_hours: int | None = Field(default=None, ge=1, le=60)


class RecalculateOut(BaseModel):
    struggling_areas: list[StruggleOut]
    proposed_plan: PlanOut
    note: str
