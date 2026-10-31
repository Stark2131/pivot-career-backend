"""Import every model here so `Base.metadata` (used by Alembic) knows all tables."""
from app.core.database import Base
from app.models.career import (
    JobDescription,
    JobRequirement,
    LearningPlan,
    ProjectRecommendation,
    SkillGapAnalysis,
    SkillGapItem,
    WeeklyTask,
)
from app.models.tracking import (
    InterviewAnswer,
    InterviewEvaluation,
    InterviewQuestion,
    JobApplication,
    MockInterview,
    ProgressRecord,
)
from app.models.user import Resume, Skill, User, UserProfile, UserSkill

__all__ = [
    "Base",
    "User",
    "UserProfile",
    "Resume",
    "Skill",
    "UserSkill",
    "JobDescription",
    "JobRequirement",
    "SkillGapAnalysis",
    "SkillGapItem",
    "LearningPlan",
    "WeeklyTask",
    "ProjectRecommendation",
    "MockInterview",
    "InterviewQuestion",
    "InterviewAnswer",
    "InterviewEvaluation",
    "ProgressRecord",
    "JobApplication",
]
