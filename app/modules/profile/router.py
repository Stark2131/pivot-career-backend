from fastapi import APIRouter, Depends, File, UploadFile, status

from app.core.config import get_settings
from app.core.deps import LLM, CurrentUser, DbSession
from app.core.rate_limit import ai_rate_limit
from app.modules.profile import service
from app.modules.profile.schemas import ProfileOut, ProfileUpdate, ResumeOut

router = APIRouter(prefix="/profile", tags=["Profile & Resume"])


@router.post(
    "/resume",
    response_model=ResumeOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(ai_rate_limit)],
    summary="Upload a PDF or DOCX resume; text is extracted and parsed into structured data for review",
)
async def upload_resume(user: CurrentUser, db: DbSession, llm: LLM, file: UploadFile = File(...)):
    # Read at most limit+1 bytes so huge uploads are rejected without loading them fully.
    data = await file.read(get_settings().max_resume_bytes + 1)
    return await service.upload_resume(
        db, llm, user, filename=file.filename, content_type=file.content_type, data=data
    )


@router.get("", response_model=ProfileOut)
async def get_profile(user: CurrentUser, db: DbSession):
    return await service.get_profile(db, user)


@router.put("", response_model=ProfileOut, summary="Update intake details and review/correct extracted data")
async def update_profile(body: ProfileUpdate, user: CurrentUser, db: DbSession):
    return await service.update_profile(db, user, body)


@router.get("/resumes", response_model=list[ResumeOut])
async def list_resumes(user: CurrentUser, db: DbSession):
    return await service.list_resumes(db, user)


@router.get("/resumes/{resume_id}", response_model=ResumeOut)
async def get_resume(resume_id: int, user: CurrentUser, db: DbSession):
    return await service.get_resume(db, user, resume_id)
