from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.deps import LLM, CurrentUser, DbSession
from app.core.rate_limit import ai_rate_limit
from app.modules.applications import service
from app.modules.applications.schemas import (
    ApplicationAnalytics,
    ApplicationCreate,
    ApplicationOut,
    ApplicationUpdate,
)

router = APIRouter(prefix="/applications", tags=["Application Tracker"])


@router.post("", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
async def create(body: ApplicationCreate, user: CurrentUser, db: DbSession):
    return await service.create_application(db, user, body)


@router.get("", response_model=list[ApplicationOut])
async def list_apps(user: CurrentUser, db: DbSession,
                    status: Literal["applied", "interview", "rejected", "offer"] | None = None):
    return await service.list_applications(db, user, status)


# Declared before /{application_id} so "analytics" is not parsed as an id.
@router.get("/analytics", response_model=ApplicationAnalytics, dependencies=[Depends(ai_rate_limit)])
async def analytics(user: CurrentUser, db: DbSession, llm: LLM,
                    include_ai_summary: bool = Query(True, description="Use the AI Application Analyst for the narrative")):
    return await service.analytics(db, llm, user, include_ai_summary)


@router.get("/{application_id}", response_model=ApplicationOut)
async def get_app(application_id: int, user: CurrentUser, db: DbSession):
    return await service.get_application(db, user, application_id)


@router.patch("/{application_id}", response_model=ApplicationOut)
async def update(application_id: int, body: ApplicationUpdate, user: CurrentUser, db: DbSession):
    return await service.update_application(db, user, application_id, body)


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(application_id: int, user: CurrentUser, db: DbSession):
    await service.delete_application(db, user, application_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
