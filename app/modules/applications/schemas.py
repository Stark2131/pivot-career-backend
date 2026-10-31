from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.ai.schemas import ApplicationNarrative

AppStatus = Literal["applied", "interview", "rejected", "offer"]
ExperienceLevel = Literal["entry", "junior", "mid", "senior", "lead"]
CompanySize = Literal["1-10", "11-50", "51-200", "201-1000", "1001+"]
Channel = Literal["referral", "direct", "job_board", "recruiter", "other"]
WorkMode = Literal["remote", "hybrid", "onsite"]


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
    posting_url: HttpUrl | None = Field(default=None, description="Link to the posting (stored, never fetched)")
    role_family: str | None = Field(default=None, max_length=40, description="Defaults to a family derived from role_title")
    industry: str | None = Field(default=None, max_length=60)
    company_size: CompanySize | None = None
    channel: Channel | None = Field(default=None, description="How you applied; the tracker compares channels")
    resume_version: str | None = Field(default=None, max_length=60, description="Label of the resume you sent, e.g. 'v2-analytics'")
    work_mode: WorkMode | None = None
    location: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=5000)


class ApplicationUpdate(BaseModel):
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    role_title: str | None = Field(default=None, min_length=1, max_length=200)
    status: AppStatus | None = None
    reached_interview: bool | None = Field(default=None, description="Set true if you were interviewed before a rejection")
    experience_level: ExperienceLevel | None = None
    skills_highlighted: list[str] | None = Field(default=None, max_length=30)
    posting_url: HttpUrl | None = None
    role_family: str | None = Field(default=None, max_length=40)
    industry: str | None = Field(default=None, max_length=60)
    company_size: CompanySize | None = None
    channel: Channel | None = None
    resume_version: str | None = Field(default=None, max_length=60)
    work_mode: WorkMode | None = None
    location: str | None = Field(default=None, max_length=120)
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
    posting_url: str | None = None
    role_family: str | None = None
    industry: str | None = None
    company_size: str | None = None
    channel: str | None = None
    resume_version: str | None = None
    work_mode: str | None = None
    location: str | None = None
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


class Insight(BaseModel):
    dimension: str
    dimension_label: str
    group: str
    label: str
    direction: Literal["higher", "lower"]
    confidence: Literal["reliable", "early_signal"]
    n: int
    responses: int
    response_rate: float
    ci95: tuple[float, float]
    rest_n: int
    rest_response_rate: float
    rest_ci95: tuple[float, float]
    difference: float
    text: str
    suggestion: str


class Recommendations(BaseModel):
    n_applications: int
    n_counted: int
    excluded_recent_pending: int
    baseline_response_rate: float | None
    baseline_ci95: tuple[float, float] | None
    sufficient_data: bool
    message: str
    insights: list[Insight]
    disclaimer: str
