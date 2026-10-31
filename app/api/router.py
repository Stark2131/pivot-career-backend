"""Aggregates every module router under /api."""
from fastapi import APIRouter

from app.core.errors import COMMON_ERROR_RESPONSES

from app.modules.applications.router import router as applications_router
from app.modules.auth.router import router as auth_router
from app.modules.interviews.router import router as interviews_router
from app.modules.jobs.router import router as jobs_router
from app.modules.learning_plans.router import router as plans_router
from app.modules.profile.router import router as profile_router
from app.modules.progress.router import router as progress_router
from app.modules.projects.router import router as projects_router
from app.modules.skill_gap.router import router as skill_gap_router

api_router = APIRouter(prefix="/api", responses=COMMON_ERROR_RESPONSES)
for r in (auth_router, profile_router, jobs_router, skill_gap_router, plans_router, projects_router,
          interviews_router, progress_router, applications_router):
    api_router.include_router(r)
