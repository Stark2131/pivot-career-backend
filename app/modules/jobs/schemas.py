from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class JobCreate(BaseModel):
    """Provide pasted `text`, a `source_url`, or (manual entry) a list of `required_skills`."""

    title: str = Field(min_length=2, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, min_length=50, max_length=50_000)
    source_url: HttpUrl | None = None
    required_skills: list[str] = Field(default_factory=list, max_length=60, description="Manual entry")
    preferred_skills: list[str] = Field(default_factory=list, max_length=60, description="Manual entry")

    @model_validator(mode="after")
    def _need_some_input(self):
        if not self.text and not self.source_url and not self.required_skills:
            raise ValueError("Provide job description `text`, a `source_url`, or manual `required_skills`.")
        return self


class JobRequirementOut(BaseModel):
    skill_id: int
    skill_name: str
    category: str
    requirement_type: Literal["required", "preferred"]
    kind: str
    required_proficiency: int | None
    evidence: str | None


class JobSummaryOut(BaseModel):
    id: int
    title: str
    company: str | None
    source_type: str
    source_url: str | None
    generated_by: str | None
    required_count: int
    preferred_count: int
    created_at: datetime


class JobOut(BaseModel):
    id: int
    title: str
    company: str | None
    source_type: str
    source_url: str | None
    raw_text: str
    structured_data: dict
    extracted_at: datetime | None
    generated_by: str | None
    extraction_warnings: list[str]
    requirements: list[JobRequirementOut]
    created_at: datetime
