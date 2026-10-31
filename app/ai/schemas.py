"""Pydantic models describing what each AI component must return.

These are the *contract* with the LLM: output that does not validate is rejected.
Lists are length-capped so a misbehaving model cannot flood the database.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, Field

Score10 = Annotated[int, Field(ge=0, le=10)]
Level = Annotated[int | None, Field(ge=1, le=5)]


# --- Resume parser --------------------------------------------------------------
class ExtractedSkill(BaseModel):
    name: str = Field(max_length=80)
    evidence: str = Field(default="", max_length=300, description="Short verbatim quote from the resume")
    proficiency_hint: Level = None


class WorkExperience(BaseModel):
    title: str = Field(default="", max_length=200)
    company: str = Field(default="", max_length=200)
    start: str | None = Field(default=None, max_length=40)
    end: str | None = Field(default=None, max_length=40)
    highlights: list[str] = Field(default_factory=list, max_length=15)


class Education(BaseModel):
    degree: str = Field(default="", max_length=200)
    institution: str = Field(default="", max_length=200)
    year: str | None = Field(default=None, max_length=20)


class ResumeProject(BaseModel):
    name: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=1000)
    technologies: list[str] = Field(default_factory=list, max_length=20)


class Certification(BaseModel):
    name: str = Field(max_length=200)
    issuer: str | None = Field(default=None, max_length=200)
    year: str | None = Field(default=None, max_length=20)


class ResumeExtraction(BaseModel):
    current_role: str | None = Field(default=None, max_length=200)
    years_experience: float | None = Field(default=None, ge=0, le=60)
    summary: str | None = Field(default=None, max_length=1500)
    technical_skills: list[ExtractedSkill] = Field(default_factory=list, max_length=80)
    soft_skills: list[str] = Field(default_factory=list, max_length=30)
    work_experience: list[WorkExperience] = Field(default_factory=list, max_length=20)
    education: list[Education] = Field(default_factory=list, max_length=10)
    projects: list[ResumeProject] = Field(default_factory=list, max_length=20)
    certifications: list[Certification] = Field(default_factory=list, max_length=20)


# --- Job description extractor -----------------------------------------------------
class JDSkill(BaseModel):
    name: str = Field(max_length=80)
    kind: Literal["skill", "tool"] = "skill"
    required_proficiency: Level = None
    evidence: str = Field(default="", max_length=300)


class JDExtraction(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    required_skills: list[JDSkill] = Field(default_factory=list, max_length=60)
    preferred_skills: list[JDSkill] = Field(default_factory=list, max_length=60)
    experience_requirements: list[str] = Field(default_factory=list, max_length=15)
    experience_years_min: float | None = Field(default=None, ge=0, le=40)
    responsibilities: list[str] = Field(default_factory=list, max_length=30)
    education_requirements: list[str] = Field(default_factory=list, max_length=10)


# --- Skill gap explanations ------------------------------------------------------
class GapExplanation(BaseModel):
    skill_name: str
    explanation: str = Field(max_length=600)


class GapNarrative(BaseModel):
    summary: str = Field(max_length=1500)
    explanations: list[GapExplanation] = Field(default_factory=list, max_length=80)


# --- Learning planner --------------------------------------------------------------
class PlanTaskContent(BaseModel):
    skill_name: str
    title: str = Field(max_length=200)
    topics: list[str] = Field(min_length=1, max_length=8)
    activities: list[str] = Field(min_length=1, max_length=8)
    exercises: list[str] = Field(min_length=1, max_length=6)
    expected_outcome: str = Field(max_length=500)
    # Ids from the curated list offered in the prompt. Anything else is ignored; the model cannot add links.
    resource_ids: list[str] = Field(default_factory=list, max_length=6)


class PlanWeekContent(BaseModel):
    week_number: int = Field(ge=1)
    tasks: list[PlanTaskContent] = Field(min_length=1, max_length=6)


class PlanContent(BaseModel):
    summary: str = Field(max_length=1500)
    weeks: list[PlanWeekContent] = Field(min_length=1, max_length=52)


# --- Project recommender -----------------------------------------------------------
class ProjectIdea(BaseModel):
    title: str = Field(max_length=200)
    problem_statement: str = Field(max_length=1000)
    description: str = Field(max_length=2000)
    skills_covered: list[str] = Field(min_length=1, max_length=12)
    tech_stack: list[str] = Field(min_length=1, max_length=12)
    core_features: list[str] = Field(min_length=1, max_length=10)
    difficulty: Literal["beginner", "intermediate", "advanced"]
    deliverables: list[str] = Field(min_length=1, max_length=8)
    estimated_hours: int | None = Field(default=None, ge=1, le=300)
    template_id: str | None = Field(default=None, description="Id in data/projects.json this idea was built from")
    gaps_covered: list[str] = Field(default_factory=list, description="Which of the user's gaps it addresses, in priority order")


class ProjectList(BaseModel):
    projects: list[ProjectIdea] = Field(min_length=1, max_length=6)


class PersonalisedProject(BaseModel):
    """The only things the model may change about a template: its wording."""
    template_id: str
    title: str = Field(max_length=200)
    problem_statement: str = Field(max_length=1000)
    description: str = Field(max_length=2000)
    core_features: list[str] = Field(default_factory=list, max_length=10)
    deliverables: list[str] = Field(default_factory=list, max_length=8)


class PersonalisedProjects(BaseModel):
    projects: list[PersonalisedProject] = Field(min_length=1, max_length=6)


# --- Interviewer & evaluator ---------------------------------------------------------
class GeneratedQuestion(BaseModel):
    question_text: str = Field(min_length=10, max_length=1000)
    skill_name: str | None = Field(default=None, max_length=120)
    category: Literal["technical", "behavioral", "system_design"] = "technical"
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    key_points: list[str] = Field(default_factory=list, max_length=8, description="What a strong answer covers")


class QuestionSet(BaseModel):
    questions: list[GeneratedQuestion] = Field(min_length=1, max_length=15)


class RubricScores(BaseModel):
    technical_correctness: Score10
    conceptual_understanding: Score10
    problem_solving: Score10
    communication: Score10
    relevance: Score10


class AnswerEvaluation(BaseModel):
    scores: RubricScores
    strengths: list[str] = Field(default_factory=list, max_length=6)
    improvements: list[str] = Field(default_factory=list, max_length=6)
    suggested_answer_improvements: str = Field(default="", max_length=2000)
    topics_to_revise: list[str] = Field(default_factory=list, max_length=8)
    # criterion -> short verbatim quote from the candidate's answer that supports the score.
    # The evaluator discards any quote that is not actually in the answer.
    evidence: dict[str, str] = Field(default_factory=dict)


# --- Progress analyst (tool-calling) ---------------------------------------------------
class StrugglingArea(BaseModel):
    area: str = Field(max_length=120)
    evidence: str = Field(max_length=500)
    recommendation: str = Field(max_length=500)


class ProgressInsights(BaseModel):
    summary: str = Field(max_length=1500)
    struggling_areas: list[StrugglingArea] = Field(default_factory=list, max_length=10)
    recommended_adjustments: list[str] = Field(default_factory=list, max_length=10)


# --- Application analyst ---------------------------------------------------------------
class ApplicationNarrative(BaseModel):
    summary: str = Field(max_length=1500)
    observations: list[str] = Field(default_factory=list, max_length=8)
