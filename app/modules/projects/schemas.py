from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

ProjectStatus = Literal["recommended", "in_progress", "completed", "dismissed"]


class RecommendRequest(BaseModel):
    analysis_id: int | None = Field(default=None, description="Defaults to your latest skill-gap analysis")
    count: int = Field(default=3, ge=1, le=5)


class ProjectUpdate(BaseModel):
    status: ProjectStatus | None = None
    repo_url: HttpUrl | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_id: int | None
    title: str
    problem_statement: str
    description: str
    skills_covered: list[str]
    tech_stack: list[str]
    core_features: list[str]
    difficulty: str
    deliverables: list[str]
    estimated_hours: int | None
    status: str
    repo_url: str | None
    notes: str | None
    generated_by: str | None
    completed_at: datetime | None
    created_at: datetime
