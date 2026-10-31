"""Password hashing (bcrypt) and JWT access tokens (PyJWT)."""
from datetime import timedelta

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.database import utcnow

# bcrypt only uses the first 72 bytes of a password; we reject longer ones at the schema level.
BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int) -> tuple[str, int]:
    """Return (token, expires_in_seconds)."""
    settings = get_settings()
    expires = timedelta(minutes=settings.access_token_expire_minutes)
    now = utcnow()
    payload = {"sub": str(user_id), "iat": now, "exp": now + expires, "type": "access"}
    token = jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm=settings.jwt_algorithm)
    return token, int(expires.total_seconds())


def decode_access_token(token: str) -> int | None:
    """Return the user id from a valid token, or None if invalid/expired."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    if payload.get("type") != "access":
        return None
    try:
        return int(payload["sub"])
    except (TypeError, ValueError):
        return None
