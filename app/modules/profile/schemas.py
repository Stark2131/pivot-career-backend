from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas import Certification, Education, ResumeProject, WorkExperience

ExperienceLevel = Literal["entry", "junior", "mid", "senior", "lead"]


class UserSkillOut(BaseModel):
    skill_id: int
    name: str
    category: str
    proficiency: int | None
    source: str
    confirmed: bool
    evidence: str | None


class UserSkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    proficiency: int | None = Field(default=None, ge=1, le=5, description="1=aware ... 5=expert")


class ResumeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    size_bytes: int
    page_count: int
    parse_status: str
    generated_by: str | None
    parsed_data: dict
    validation_warnings: list[str]
    is_active: bool
    created_at: datetime


class ProfileOut(BaseModel):
    current_role: str | None
    target_role: str | None
    experience_level: str | None
    years_experience: float | None
    weekly_hours: int
    summary: str | None
    experience_notes: str | None
    soft_skills: list[str]
    work_experience: list[dict]
    education: list[dict]
    projects: list[dict]
    certifications: list[dict]
    skills: list[UserSkillOut]
    active_resume: ResumeOut | None
    needs_review: bool = Field(description="True if some resume-extracted skills are not yet confirmed by the user")


class ProfileUpdate(BaseModel):
    """All fields optional; only provided fields are changed.

    `skills`, when provided, REPLACES the user's skill list and marks every skill as confirmed
    (this is how users review/correct what the resume parser extracted).
    """

    current_role: str | None = Field(default=None, max_length=200)
    target_role: str | None = Field(default=None, max_length=200)
    experience_level: ExperienceLevel | None = None
    years_experience: float | None = Field(default=None, ge=0, le=60)
    weekly_hours: int | None = Field(default=None, ge=1, le=80)
    summary: str | None = Field(default=None, max_length=2000)
    experience_notes: str | None = Field(default=None, max_length=5000)
    soft_skills: list[str] | None = Field(default=None, max_length=30)
    work_experience: list[WorkExperience] | None = Field(default=None, max_length=20)
    education: list[Education] | None = Field(default=None, max_length=10)
    projects: list[ResumeProject] | None = Field(default=None, max_length=20)
    certifications: list[Certification] | None = Field(default=None, max_length=20)
    skills: list[UserSkillIn] | None = Field(default=None, max_length=100)
