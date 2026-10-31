from typing import Literal

from fastapi import APIRouter, Depends, status

from app.core.deps import LLM, CurrentUser, DbSession
from app.core.rate_limit import ai_rate_limit
from app.modules.learning_plans import service
from app.modules.learning_plans.schemas import (
    AdjustPlanRequest,
    GeneratePlanRequest,
    PlanOut,
    PlanSummaryOut,
    TaskUpdate,
    WeeklyTaskOut,
)

router = APIRouter(prefix="/plans", tags=["Learning Plans"])


@router.post("/generate", response_model=PlanOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(ai_rate_limit)],
             summary="Generate a week-by-week plan (becomes 'proposed' if an active plan already exists)")
async def generate(body: GeneratePlanRequest, user: CurrentUser, db: DbSession, llm: LLM):
    return service.to_out(await service.generate_plan(db, llm, user, body))


@router.get("", response_model=list[PlanSummaryOut])
async def list_plans(user: CurrentUser, db: DbSession,
                     status: Literal["active", "proposed", "archived", "rejected", "superseded"] | None = None):
    return [service.to_summary(p) for p in await service.list_plans(db, user, status)]


@router.get("/{plan_id}", response_model=PlanOut)
async def get_plan(plan_id: int, user: CurrentUser, db: DbSession):
    return service.to_out(await service.get_plan(db, user, plan_id))


@router.patch("/{plan_id}/tasks/{task_id}", response_model=WeeklyTaskOut)
async def update_task(plan_id: int, task_id: int, body: TaskUpdate, user: CurrentUser, db: DbSession):
    return await service.update_task(db, user, plan_id, task_id, body)


@router.post("/{plan_id}/adjust", response_model=PlanOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(ai_rate_limit)],
             summary="Propose an adjusted version (the original plan is preserved)")
async def adjust(plan_id: int, body: AdjustPlanRequest, user: CurrentUser, db: DbSession, llm: LLM):
    return service.to_out(await service.adjust_plan(db, llm, user, plan_id, body))


@router.post("/{plan_id}/accept", response_model=PlanOut, summary="Accept a proposed plan (archives the current one)")
async def accept(plan_id: int, user: CurrentUser, db: DbSession):
    return service.to_out(await service.accept_plan(db, user, plan_id))


@router.post("/{plan_id}/reject", response_model=PlanOut, summary="Reject a proposed plan")
async def reject(plan_id: int, user: CurrentUser, db: DbSession):
    return service.to_out(await service.reject_plan(db, user, plan_id))
