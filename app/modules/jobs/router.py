from fastapi import APIRouter, Depends, Response, status

from app.core.deps import LLM, CurrentUser, DbSession
from app.core.rate_limit import ai_rate_limit
from app.modules.jobs import service
from app.modules.jobs.schemas import JobCreate, JobOut, JobSummaryOut

router = APIRouter(prefix="/jobs", tags=["Job Descriptions"])


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(ai_rate_limit)])
async def create_job(body: JobCreate, user: CurrentUser, db: DbSession, llm: LLM):
    return service.to_out(await service.create_job(db, llm, user, body))


@router.get("", response_model=list[JobSummaryOut])
async def list_jobs(user: CurrentUser, db: DbSession):
    return [service.to_summary(j) for j in await service.list_jobs(db, user)]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(job_id: int, user: CurrentUser, db: DbSession):
    return service.to_out(await service.get_job(db, user, job_id))


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(job_id: int, user: CurrentUser, db: DbSession):
    await service.delete_job(db, user, job_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
