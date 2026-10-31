"""A tiny in-memory sliding-window rate limiter.

Good enough for a single-process hackathon deployment. For multiple workers,
swap the storage for Redis (same interface).
"""
import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import RateLimitedError


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_seconds: float = 60.0) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > window_seconds:
            hits.popleft()
        if len(hits) >= limit:
            raise RateLimitedError("Too many requests. Please slow down and try again shortly.")
        hits.append(now)

    def reset(self) -> None:
        self._hits.clear()


limiter = SlidingWindowLimiter()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def auth_rate_limit(request: Request) -> None:
    settings = get_settings()
    if settings.rate_limit_enabled:
        limiter.check(f"auth:{_client_ip(request)}", settings.auth_rate_limit_per_minute)


async def ai_rate_limit(request: Request) -> None:
    """Applied to endpoints that may call the LLM (they cost money)."""
    settings = get_settings()
    if settings.rate_limit_enabled:
        limiter.check(f"ai:{_client_ip(request)}", settings.ai_rate_limit_per_minute)
