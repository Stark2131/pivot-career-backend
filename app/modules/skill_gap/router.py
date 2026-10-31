from fastapi import APIRouter, Depends, status

from app.core.deps import LLM, CurrentUser, DbSession
from app.core.rate_limit import ai_rate_limit
from app.modules.skill_gap import service
from app.modules.skill_gap.schemas import AnalyzeRequest, SkillGapReportOut, SkillGapSummaryOut

router = APIRouter(prefix="/skill-gap", tags=["Skill Gap Analysis"])


@router.post("/analyze", response_model=SkillGapReportOut, status_code=status.HTTP_201_CREATED,
             dependencies=[Depends(ai_rate_limit)])
async def analyze(body: AnalyzeRequest, user: CurrentUser, db: DbSession, llm: LLM):
    return await service.analyze(db, llm, user, body)


@router.get("", response_model=list[SkillGapSummaryOut])
async def list_analyses(user: CurrentUser, db: DbSession):
    return await service.list_analyses(db, user)


@router.get("/{analysis_id}", response_model=SkillGapReportOut)
async def get_analysis(analysis_id: int, user: CurrentUser, db: DbSession):
    return await service.get_analysis(db, user, analysis_id)
