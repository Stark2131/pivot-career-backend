from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class InterviewCreate(BaseModel):
    target_role: str | None = Field(default=None, max_length=200, description="Defaults to profile target role")
    interview_type: Literal["technical", "behavioral", "mixed"] = "mixed"
    num_questions: int = Field(default=5, ge=1, le=10)
    focus_skills: list[str] = Field(default_factory=list, max_length=10,
                                    description="Defaults to your priority skill gaps")


class AnswerSubmit(BaseModel):
    question_id: int
    answer_text: str = Field(min_length=1, max_length=8000)


class EvaluateRequest(BaseModel):
    question_ids: list[int] | None = Field(default=None, description="Defaults to all answered, unevaluated questions")


class EvaluationOut(BaseModel):
    rubric_version: str
    scores: dict[str, int]
    overall_score: float
    strengths: list[str]
    improvements: list[str]
    suggested_answer_improvements: str
    topics_to_revise: list[str]
    evaluator: str


class QuestionOut(BaseModel):
    id: int
    order_index: int
    question_text: str
    skill_name: str | None
    category: str
    difficulty: str
    key_points: list[str] | None = Field(description="Hidden until the question is evaluated")
    answer_text: str | None
    answered_at: datetime | None
    evaluation: EvaluationOut | None


class InterviewSummaryOut(BaseModel):
    id: int
    target_role: str
    interview_type: str
    status: str
    overall_score: float | None
    question_count: int
    answered_count: int
    evaluated_count: int
    generated_by: str | None
    created_at: datetime


class InterviewOut(InterviewSummaryOut):
    summary: dict
    questions: list[QuestionOut]
