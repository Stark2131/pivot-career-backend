from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class AnalyzeRequest(BaseModel):
    job_description_ids: list[int] | None = Field(
        default=None, max_length=50, description="Defaults to all of your saved job descriptions"
    )
    target_role: str | None = Field(default=None, max_length=200, description="Defaults to profile target role")


class SkillGapItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    skill_id: int
    skill_name: str
    category: str
    current_proficiency: int | None
    required_proficiency: int | None
    gap_level: str
    importance: float
    importance_label: str
    frequency: int
    required_count: int
    preferred_count: int
    priority_rank: int
    is_priority: bool
    explanation: str
    job_references: list[dict]


class SkillGapReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_role: str | None
    job_description_ids: list[int]
    match_score: float
    summary: str | None
    generated_by: str | None
    created_at: datetime
    items: list[SkillGapItemOut]


class SkillGapSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_role: str | None
    job_description_ids: list[int]
    match_score: float
    created_at: datetime
