from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas import ApplicationNarrative

AppStatus = Literal["applied", "interview", "rejected", "offer"]
ExperienceLevel = Literal["entry", "junior", "mid", "senior", "lead"]


class ApplicationCreate(BaseModel):
    company_name: str = Field(min_length=1, max_length=200)
    role_title: str = Field(min_length=1, max_length=200)
    applied_date: date
    status: AppStatus = "applied"
    job_description_id: int | None = Field(default=None, description="Link a saved job description")
    job_description_text: str | None = Field(default=None, max_length=50_000)
    experience_level: ExperienceLevel | None = Field(default=None, description="Seniority the posting asked for")
    skills_highlighted: list[str] = Field(default_factory=list, max_length=30,
                                          description="Skills you emphasised; defaults to your skills matching the linked JD")
    notes: str | None = Field(default=None, max_length=5000)


class ApplicationUpdate(BaseModel):
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    role_title: str | None = Field(default=None, min_length=1, max_length=200)
    status: AppStatus | None = None
    reached_interview: bool | None = Field(default=None, description="Set true if you were interviewed before a rejection")
    experience_level: ExperienceLevel | None = None
    skills_highlighted: list[str] | None = Field(default=None, max_length=30)
    notes: str | None = Field(default=None, max_length=5000)
    interview_feedback: str | None = Field(default=None, max_length=5000)
    outcome: str | None = Field(default=None, max_length=2000)
    outcome_date: date | None = None


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    company_name: str
    role_title: str
    job_description_id: int | None
    job_description_text: str | None
    applied_date: date
    status: str
    reached_interview: bool
    experience_level: str | None
    skills_highlighted: list[str]
    notes: str | None
    interview_feedback: str | None
    outcome: str | None
    outcome_date: date | None
    status_changed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ApplicationAnalytics(BaseModel):
    stats: dict
    narrative: ApplicationNarrative
    generated_by: str
