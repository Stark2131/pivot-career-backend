"""Mock interviews, progress records and job applications."""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, JSONType, TimestampMixin


class MockInterview(TimestampMixin, Base):
    __tablename__ = "mock_interviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    target_role: Mapped[str] = mapped_column(String(200), nullable=False)
    interview_type: Mapped[str] = mapped_column(String(20), default="mixed", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="in_progress", nullable=False)
    overall_score: Mapped[float | None] = mapped_column(Float)  # 0..10 mean of evaluated questions
    summary: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    generated_by: Mapped[str | None] = mapped_column(String(30))

    questions: Mapped[list["InterviewQuestion"]] = relationship(
        back_populates="interview",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="InterviewQuestion.order_index",
    )


class InterviewQuestion(TimestampMixin, Base):
    __tablename__ = "interview_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(
        ForeignKey("mock_interviews.id", ondelete="CASCADE"), index=True, nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    skill_name: Mapped[str | None] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(30), default="technical", nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    key_points: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)

    interview: Mapped[MockInterview] = relationship(back_populates="questions")
    answer: Mapped["InterviewAnswer | None"] = relationship(
        back_populates="question", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )
    evaluation: Mapped["InterviewEvaluation | None"] = relationship(
        back_populates="question", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )


class InterviewAnswer(TimestampMixin, Base):
    __tablename__ = "interview_answers"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("interview_questions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)

    question: Mapped[InterviewQuestion] = relationship(back_populates="answer")


class InterviewEvaluation(TimestampMixin, Base):
    __tablename__ = "interview_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("interview_questions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    answer_id: Mapped[int] = mapped_column(ForeignKey("interview_answers.id", ondelete="CASCADE"), nullable=False)
    rubric_version: Mapped[str] = mapped_column(String(20), nullable=False)
    # Rubric criteria, each scored 0..10
    technical_correctness: Mapped[int] = mapped_column(Integer, nullable=False)
    conceptual_understanding: Mapped[int] = mapped_column(Integer, nullable=False)
    problem_solving: Mapped[int] = mapped_column(Integer, nullable=False)
    communication: Mapped[int] = mapped_column(Integer, nullable=False)
    relevance: Mapped[int] = mapped_column(Integer, nullable=False)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)  # computed server-side
    strengths: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    improvements: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    suggested_answer_improvements: Mapped[str] = mapped_column(Text, default="", nullable=False)
    topics_to_revise: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)  # criterion -> quote from the answer
    evaluator: Mapped[str] = mapped_column(String(30), nullable=False)  # llm | heuristic_fallback

    question: Mapped[InterviewQuestion] = relationship(back_populates="evaluation")


class ProgressRecord(TimestampMixin, Base):
    """Append-only log: skill self/quiz assessments and progress-analysis snapshots."""

    __tablename__ = "progress_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    record_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    skill_id: Mapped[int | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"))
    skill_name: Mapped[str | None] = mapped_column(String(120))
    proficiency: Mapped[int | None] = mapped_column(Integer)
    previous_proficiency: Mapped[int | None] = mapped_column(Integer)
    assessment_method: Mapped[str | None] = mapped_column(String(30))  # self | quiz | mentor
    notes: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)


class JobApplication(TimestampMixin, Base):
    __tablename__ = "job_applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role_title: Mapped[str] = mapped_column(String(200), nullable=False)
    job_description_id: Mapped[int | None] = mapped_column(ForeignKey("job_descriptions.id", ondelete="SET NULL"))
    job_description_text: Mapped[str | None] = mapped_column(Text)
    applied_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="applied", index=True, nullable=False)
    # Sticky flag: once an application reached interview stage it stays True even if later rejected.
    reached_interview: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    experience_level: Mapped[str | None] = mapped_column(String(20))
    skills_highlighted: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    # Role attributes the tracker learns from (all optional; analytics bucket missing ones as "unspecified").
    posting_url: Mapped[str | None] = mapped_column(String(2048))
    role_family: Mapped[str | None] = mapped_column(String(40), index=True)   # derived from role_title when known
    industry: Mapped[str | None] = mapped_column(String(60))
    company_size: Mapped[str | None] = mapped_column(String(20))              # 1-10 | 11-50 | 51-200 | 201-1000 | 1001+
    channel: Mapped[str | None] = mapped_column(String(20))                   # referral | direct | job_board | recruiter | other
    resume_version: Mapped[str | None] = mapped_column(String(60))
    work_mode: Mapped[str | None] = mapped_column(String(20))                 # remote | hybrid | onsite
    location: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    interview_feedback: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(Text)
    outcome_date: Mapped[date | None] = mapped_column(Date)
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
