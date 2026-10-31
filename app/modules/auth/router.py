from fastapi import APIRouter, Depends, status

from app.core.deps import CurrentUser, DbSession
from app.core.rate_limit import auth_rate_limit
from app.modules.auth import service
from app.modules.auth.schemas import LoginRequest, RegisterRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register", response_model=UserOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(auth_rate_limit)]
)
async def register(body: RegisterRequest, db: DbSession):
    return await service.register_user(db, body.email, body.password, body.full_name)


@router.post("/login", response_model=TokenResponse, dependencies=[Depends(auth_rate_limit)])
async def login(body: LoginRequest, db: DbSession):
    token, expires_in = await service.authenticate(db, body.email, body.password)
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser):
    return user
