from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field


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
    job_count: int = Field(description="Number of job postings this report is based on")
    job_sources: dict[str, int] = Field(description="Postings per source, e.g. {'seed': 20} or {'jsearch': 18, 'pasted': 2}")
    role_family: str | None
    match_score: float
    summary: str | None
    generated_by: str | None
    created_at: datetime
    items: list[SkillGapItemOut]

    @computed_field
    @property
    def based_on(self) -> str:
        n = self.job_count or len(self.job_description_ids)
        src = ", ".join(f"{v} {k}" for k, v in sorted(self.job_sources.items(), key=lambda kv: -kv[1]))
        return f"Based on {n} job posting{'s' if n != 1 else ''}" + (f" ({src})" if src else "")


class SkillGapSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_role: str | None
    job_description_ids: list[int]
    job_count: int = 0
    match_score: float
    created_at: datetime
