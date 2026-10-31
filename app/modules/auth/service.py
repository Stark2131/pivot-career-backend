from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AuthError, ConflictError
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User, UserProfile

# Pre-computed hash used to keep login timing similar for unknown emails.
_DUMMY_HASH = hash_password("dummy-password-for-timing-1")


async def register_user(db: AsyncSession, email: str, password: str, full_name: str | None) -> User:
    email = email.lower().strip()
    existing = await db.scalar(select(User).where(User.email == email))
    if existing:
        raise ConflictError("An account with this email already exists.")
    user = User(email=email, password_hash=hash_password(password), full_name=full_name)
    user.profile = UserProfile()  # every user gets an (empty) profile
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate(db: AsyncSession, email: str, password: str) -> tuple[str, int]:
    user = await db.scalar(select(User).where(User.email == email.lower().strip()))
    if user is None:
        verify_password(password, _DUMMY_HASH)
        raise AuthError("Incorrect email or password.")
    if not verify_password(password, user.password_hash) or not user.is_active:
        raise AuthError("Incorrect email or password.")
    return create_access_token(user.id)
