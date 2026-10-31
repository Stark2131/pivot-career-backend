from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, TimestampMixin


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    profile: Mapped["UserProfile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )


class UserProfile(TimestampMixin, Base):
    """Career intake info + the reviewed/corrected structured resume data."""

    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    current_role: Mapped[str | None] = mapped_column(String(200))
    target_role: Mapped[str | None] = mapped_column(String(200))
    experience_level: Mapped[str | None] = mapped_column(String(20))  # entry/junior/mid/senior/lead
    years_experience: Mapped[float | None] = mapped_column(Float)
    weekly_hours: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    experience_notes: Mapped[str | None] = mapped_column(Text)  # free text the user enters themselves
    soft_skills: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    work_experience: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    education: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    projects: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    certifications: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)

    user: Mapped[User] = relationship(back_populates="profile")


class Resume(TimestampMixin, Base):
    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_data: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    parse_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    generated_by: Mapped[str | None] = mapped_column(String(30))  # "llm" | "rule_based"
    validation_warnings: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Skill(TimestampMixin, Base):
    """Canonical skill taxonomy entry (normalized name)."""

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="other", nullable=False)
    in_taxonomy: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class UserSkill(TimestampMixin, Base):
    __tablename__ = "user_skills"
    __table_args__ = (UniqueConstraint("user_id", "skill_id", name="uq_user_skills_user_skill"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    skill_id: Mapped[int] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"), index=True, nullable=False)
    proficiency: Mapped[int | None] = mapped_column(Integer)  # 1 (aware) .. 5 (expert); None = unknown
    # resume | self_reported | assessment
    source: Mapped[str] = mapped_column(String(30), default="self_reported", nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text)
    last_assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    skill: Mapped[Skill] = relationship(lazy="selectin")
