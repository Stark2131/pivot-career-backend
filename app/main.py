"""FastAPI application entry point.

Run locally:  uvicorn app.main:app --reload
Swagger UI:   http://localhost:8000/docs
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.errors import register_exception_handlers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=(
            "AI-powered backend that helps users pivot into a new role: resume intake, job-description "
            "analysis, skill-gap reports, learning plans, portfolio projects, mock interviews, progress "
            "tracking and application analytics. Authenticate via `POST /api/auth/login`, then click "
            "**Authorize** and paste the access token."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/health", tags=["Health"])
    async def health():
        return {
            "status": "ok",
            "llm_provider": settings.llm_provider,
            "llm_configured": settings.llm_provider != "none",
        }

    return app


app = create_app()
