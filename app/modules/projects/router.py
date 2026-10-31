from typing import Literal

from fastapi import APIRouter, Depends, status

from app.core.deps import LLM, CurrentUser, DbSession
from app.core.rate_limit import ai_rate_limit
from app.modules.projects import service
from app.modules.projects.schemas import ProjectOut, ProjectUpdate, RecommendRequest

router = APIRouter(prefix="/projects", tags=["Portfolio Projects"])


@router.post("/recommend", response_model=list[ProjectOut], status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(ai_rate_limit)])
async def recommend(body: RecommendRequest, user: CurrentUser, db: DbSession, llm: LLM):
    return await service.recommend(db, llm, user, body)


@router.get("", response_model=list[ProjectOut])
async def list_projects(user: CurrentUser, db: DbSession,
                        status: Literal["recommended", "in_progress", "completed", "dismissed"] | None = None):
    return await service.list_projects(db, user, status)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: int, user: CurrentUser, db: DbSession):
    return await service.get_project(db, user, project_id)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(project_id: int, body: ProjectUpdate, user: CurrentUser, db: DbSession):
    return await service.update_project(db, user, project_id, body)
