from fastapi import APIRouter, Depends, Query, status

from app.core.deps import LLM, CurrentUser, DbSession
from app.core.rate_limit import ai_rate_limit
from app.modules.progress import adaptation, service
from app.modules.progress.schemas import (
    AssessmentCreate,
    AssessmentOut,
    ProgressOverview,
    RecalculateOut,
    RecalculateRequest,
)

router = APIRouter(prefix="/progress", tags=["Progress Tracking"])


@router.get("", response_model=ProgressOverview)
async def get_progress(user: CurrentUser, db: DbSession, llm: LLM,
                       include_ai_insights: bool = Query(False, description="Also run the AI Progress Analyst")):
    return await service.get_overview(db, llm, user, include_ai_insights)


@router.post("/assessments", response_model=AssessmentOut, status_code=status.HTTP_201_CREATED)
async def create_assessment(body: AssessmentCreate, user: CurrentUser, db: DbSession, llm: LLM):
    record = await service.record_assessment(db, user, body)
    out = AssessmentOut.model_validate(record)
    out.adaptation = await adaptation.adapt(db, llm, user, trigger="assessment", changed_skills={record.skill_name})
    return out


@router.get("/assessments", response_model=list[AssessmentOut])
async def list_assessments(user: CurrentUser, db: DbSession):
    return await service.list_assessments(db, user)


@router.post("/recalculate-plan", response_model=RecalculateOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(ai_rate_limit)],
             summary="Propose a new plan version based on detected struggles (does not overwrite the current plan)")
async def recalculate(user: CurrentUser, db: DbSession, llm: LLM, body: RecalculateRequest | None = None):
    return await service.recalculate_plan(db, llm, user, body or RecalculateRequest())
