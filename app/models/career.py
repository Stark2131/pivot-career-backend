"""Job descriptions, skill-gap analyses, learning plans and project recommendations."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, TimestampMixin
from app.models.user import Skill


class JobDescription(TimestampMixin, Base):
    __tablename__ = "job_descriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    company: Mapped[str | None] = mapped_column(String(200))
    source_type: Mapped[str] = mapped_column(String(20), default="pasted", nullable=False)  # manual|pasted|url
    source_url: Mapped[str | None] = mapped_column(String(2048))
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    # responsibilities, experience_requirements, education_requirements, experience_years_min
    structured_data: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generated_by: Mapped[str | None] = mapped_column(String(30))
    extraction_warnings: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)

    requirements: Mapped[list["JobRequirement"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", lazy="selectin", order_by="JobRequirement.id"
    )


class JobRequirement(TimestampMixin, Base):
    __tablename__ = "job_requirements"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_description_id: Mapped[int] = mapped_column(
        ForeignKey("job_descriptions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False)
    requirement_type: Mapped[str] = mapped_column(String(20), nullable=False)  # required | preferred
    kind: Mapped[str] = mapped_column(String(20), default="skill", nullable=False)  # skill | tool
    required_proficiency: Mapped[int | None] = mapped_column(Integer)  # 1..5 if stated/inferable
    evidence: Mapped[str | None] = mapped_column(Text)  # short quote from the JD

    job: Mapped[JobDescription] = relationship(back_populates="requirements")
    skill: Mapped[Skill] = relationship(lazy="selectin")


class SkillGapAnalysis(TimestampMixin, Base):
    __tablename__ = "skill_gap_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    target_role: Mapped[str | None] = mapped_column(String(200))
    job_description_ids: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    match_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # 0..100
    summary: Mapped[str | None] = mapped_column(Text)
    generated_by: Mapped[str | None] = mapped_column(String(30))

    items: Mapped[list["SkillGapItem"]] = relationship(
        back_populates="analysis", cascade="all, delete-orphan", lazy="selectin", order_by="SkillGapItem.priority_rank"
    )


class SkillGapItem(TimestampMixin, Base):
    __tablename__ = "skill_gap_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(
        ForeignKey("skill_gap_analyses.id", ondelete="CASCADE"), index=True, nullable=False
    )
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), nullable=False)
    skill_name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="other", nullable=False)
    current_proficiency: Mapped[int | None] = mapped_column(Integer)
    required_proficiency: Mapped[int | None] = mapped_column(Integer)
    gap_level: Mapped[str] = mapped_column(String(20), nullable=False)  # none | partial | missing
    importance: Mapped[float] = mapped_column(Float, nullable=False)  # 0..1
    importance_label: Mapped[str] = mapped_column(String(20), nullable=False)  # critical|high|medium|low
    frequency: Mapped[int] = mapped_column(Integer, nullable=False)  # number of JDs mentioning it
    required_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    preferred_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    priority_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    is_priority: Mapped[bool] = mapped_column(default=False, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    job_references: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)

    analysis: Mapped[SkillGapAnalysis] = relationship(back_populates="items")


class LearningPlan(TimestampMixin, Base):
    """A versioned plan. Adjustments create a *new* row (status=proposed) linked via parent_plan_id."""

    __tablename__ = "learning_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("skill_gap_analyses.id", ondelete="SET NULL"))
    parent_plan_id: Mapped[int | None] = mapped_column(ForeignKey("learning_plans.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    target_role: Mapped[str | None] = mapped_column(String(200))
    weekly_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    total_weeks: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    adjustment_reason: Mapped[str | None] = mapped_column(Text)
    change_summary: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    generated_by: Mapped[str | None] = mapped_column(String(30))

    tasks: Mapped[list["WeeklyTask"]] = relationship(
        back_populates="plan",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by=lambda: [WeeklyTask.week_number, WeeklyTask.id],
    )


class WeeklyTask(TimestampMixin, Base):
    """One skill-focused block of work inside a given week."""

    __tablename__ = "weekly_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("learning_plans.id", ondelete="CASCADE"), index=True, nullable=False)
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    skill_name: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    topics: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    activities: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    exercises: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    estimated_hours: Mapped[float] = mapped_column(Float, nullable=False)
    expected_outcome: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    difficulty_rating: Mapped[int | None] = mapped_column(Integer)  # user feedback 1 (easy) .. 5 (very hard)
    notes: Mapped[str | None] = mapped_column(Text)

    plan: Mapped[LearningPlan] = relationship(back_populates="tasks")


class ProjectRecommendation(TimestampMixin, Base):
    __tablename__ = "project_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("skill_gap_analyses.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    problem_statement: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    skills_covered: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    tech_stack: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    core_features: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)  # beginner|intermediate|advanced
    deliverables: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    estimated_hours: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="recommended", nullable=False)
    repo_url: Mapped[str | None] = mapped_column(String(2048))
    notes: Mapped[str | None] = mapped_column(Text)
    generated_by: Mapped[str | None] = mapped_column(String(30))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
