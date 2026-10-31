"""Domain errors and their mapping to HTTP responses.

Services raise these instead of FastAPI's HTTPException so business logic stays
independent from the web layer.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict = {}


class ErrorResponse(BaseModel):
    """Shape of every non-validation error returned by the API."""

    error: ErrorBody


COMMON_ERROR_RESPONSES = {
    401: {"model": ErrorResponse, "description": "Missing/invalid token or bad credentials"},
    404: {"model": ErrorResponse, "description": "Resource not found (or owned by another user)"},
    409: {"model": ErrorResponse, "description": "Conflict with current state"},
    429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    502: {"model": ErrorResponse, "description": "Upstream (job URL) failure"},
}


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_failed"


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"


class RateLimitedError(AppError):
    status_code = 429
    code = "rate_limited"


class UpstreamError(AppError):
    """An external dependency (e.g. a job posting URL) failed."""

    status_code = 502
    code = "upstream_error"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError):
        headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, AuthError) else None
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        # Log the type and message only; never dump request bodies (they may contain resumes/passwords).
        logger.exception("Unhandled error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "An unexpected error occurred.", "details": {}}},
        )
