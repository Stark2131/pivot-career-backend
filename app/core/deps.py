"""Shared FastAPI dependencies: DB session, current user, LLM client."""
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import LLMClient, get_llm_client
from app.core.database import get_db
from app.core.errors import AuthError
from app.core.security import decode_access_token
from app.models import User

_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]
LLM = Annotated[LLMClient, Depends(get_llm_client)]


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthError("Not authenticated.")
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise AuthError("Invalid or expired token.")
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthError("User not found or inactive.")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
