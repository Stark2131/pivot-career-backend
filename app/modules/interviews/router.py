from fastapi import APIRouter, Depends, status

from app.core.deps import LLM, CurrentUser, DbSession
from app.core.rate_limit import ai_rate_limit
from app.modules.interviews import service
from app.modules.progress import adaptation
from app.modules.interviews.schemas import (
    AnswerSubmit,
    EvaluateRequest,
    InterviewCreate,
    InterviewOut,
    InterviewSummaryOut,
    RubricOut,
)

router = APIRouter(prefix="/interviews", tags=["Mock Interviews"])


@router.post("", response_model=InterviewOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(ai_rate_limit)])
async def create_interview(body: InterviewCreate, user: CurrentUser, db: DbSession, llm: LLM):
    return service.to_out(await service.create_interview(db, llm, user, body))


@router.get("", response_model=list[InterviewSummaryOut])
async def list_interviews(user: CurrentUser, db: DbSession):
    return [service.to_summary(i) for i in await service.list_interviews(db, user)]


# Declared before /{interview_id} so "rubric" is not parsed as an id.
@router.get("/rubric", response_model=RubricOut, summary="The scoring rubric: dimensions, 1-5 levels and anchor descriptions")
async def get_rubric(user: CurrentUser):
    return service.rubric()


@router.get("/{interview_id}", response_model=InterviewOut)
async def get_interview(interview_id: int, user: CurrentUser, db: DbSession):
    return service.to_out(await service.get_interview(db, user, interview_id))


@router.post("/{interview_id}/answer", response_model=InterviewOut)
async def submit_answer(interview_id: int, body: AnswerSubmit, user: CurrentUser, db: DbSession):
    return service.to_out(await service.submit_answer(db, user, interview_id, body))


@router.post("/{interview_id}/evaluate", response_model=InterviewOut, dependencies=[Depends(ai_rate_limit)])
async def evaluate(interview_id: int, user: CurrentUser, db: DbSession, llm: LLM, body: EvaluateRequest | None = None):
    interview, new_scores = await service.evaluate(db, llm, user, interview_id, body or EvaluateRequest())
    out = service.to_out(interview)
    # Closed loop: scores -> proficiency -> gaps -> (maybe) a proposed plan. Never fails the request.
    out.adaptation = await adaptation.adapt(db, llm, user, trigger="interview", interview_scores=new_scores)
    return out
