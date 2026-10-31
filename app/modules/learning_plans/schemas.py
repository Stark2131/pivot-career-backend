from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal["pending", "in_progress", "completed", "skipped"]


class GeneratePlanRequest(BaseModel):
    analysis_id: int | None = Field(default=None, description="Defaults to your latest skill-gap analysis")
    weekly_hours: int | None = Field(default=None, ge=1, le=60, description="Defaults to profile weekly_hours")
    max_weeks: int = Field(default=12, ge=1, le=26)
    start_date: date | None = None


class AdjustPlanRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)
    weekly_hours: int | None = Field(default=None, ge=1, le=60)
    max_weeks: int | None = Field(default=None, ge=1, le=26)
    focus_skills: list[str] = Field(default_factory=list, max_length=10)
    struggling_skills: list[str] = Field(default_factory=list, max_length=10)


class TaskUpdate(BaseModel):
    status: TaskStatus | None = None
    notes: str | None = Field(default=None, max_length=2000)
    difficulty_rating: int | None = Field(default=None, ge=1, le=5, description="1=easy .. 5=very hard")
    title: str | None = Field(default=None, min_length=2, max_length=255)
    estimated_hours: float | None = Field(default=None, gt=0, le=60)


class ResourceOut(BaseModel):
    """A link from the curated list (data/resources.json), or a labelled search link when a skill has none."""
    id: str
    title: str
    url: str
    type: str
    hours: float | None = None
    provider: str | None = None


class WeeklyTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    week_number: int
    skill_name: str
    title: str
    topics: list[str]
    activities: list[str]
    exercises: list[str]
    resources: list[ResourceOut] = []
    estimated_hours: float
    expected_outcome: str
    status: str
    completed_at: datetime | None
    difficulty_rating: int | None
    notes: str | None


class PlanWeekOut(BaseModel):
    week_number: int
    start_date: date
    total_hours: float
    skills: list[str]
    tasks: list[WeeklyTaskOut]


class PlanProgress(BaseModel):
    total_tasks: int
    completed_tasks: int
    percent_complete: float


class PlanSummaryOut(BaseModel):
    id: int
    version: int
    status: str
    title: str
    target_role: str | None
    weekly_hours: int
    total_weeks: int
    start_date: date
    parent_plan_id: int | None
    generated_by: str | None
    progress: PlanProgress
    created_at: datetime


class PlanOut(PlanSummaryOut):
    analysis_id: int | None
    summary: str | None
    adjustment_reason: str | None
    change_summary: dict
    weeks: list[PlanWeekOut]
