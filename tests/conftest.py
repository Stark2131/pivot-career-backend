"""Test fixtures.

* Uses SQLite (aiosqlite) by default for speed. Set TEST_DATABASE_URL to run the
  same suite against PostgreSQL, e.g.
  TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost/career_coach_test pytest
* The LLM is always faked: no network calls are made in tests.
"""
import json
import os
from collections.abc import Callable

# Configure the app BEFORE importing it (the engine is created at import time).
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ["LLM_PROVIDER"] = "none"
os.environ["ENVIRONMENT"] = "test"
os.environ["RATE_LIMIT_ENABLED"] = "false"
for _k in ("JSEARCH_API_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY"):  # tests never call live job boards
    os.environ[_k] = ""
os.environ["JWT_SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256-signing"

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import event  # noqa: E402

from app.ai.client import LLMClient, get_llm_client  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.database import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402

if engine.dialect.name == "sqlite":
    # SQLite needs this for ON DELETE CASCADE to work.
    @event.listens_for(engine.sync_engine, "connect")
    def _fk_pragma(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")


class FakeLLMClient(LLMClient):
    """LLM stand-in. Register a handler per task name; handlers receive the user prompt
    and return a dict (serialised to JSON) or a raw string (to test invalid output)."""

    def __init__(self):
        super().__init__(get_settings())
        self.handlers: dict[str, Callable[[str], dict | str]] = {}
        self.calls: list[str] = []

    @property
    def available(self) -> bool:
        return True

    def on(self, task: str, handler: Callable[[str], dict | str] | dict):
        self.handlers[task] = handler if callable(handler) else (lambda _p, h=handler: h)

    async def _raw_completion(self, *, task, system, user, temperature):
        self.calls.append(task)
        if task not in self.handlers:
            from app.ai.client import LLMError

            raise LLMError(f"fake: no handler for {task}")  # behaves like an outage -> fallback
        out = self.handlers[task](user)
        return out if isinstance(out, str) else json.dumps(out)


@pytest_asyncio.fixture(autouse=True)
async def _db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def fake_llm() -> FakeLLMClient:
    fake = FakeLLMClient()
    app.dependency_overrides[get_llm_client] = lambda: fake
    return fake


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def register_and_login(client, email="alice@example.com", password="Passw0rd!") -> dict:
    r = await client.post("/api/auth/register", json={"email": email, "password": password, "full_name": "Test"})
    assert r.status_code == 201, r.text
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest_asyncio.fixture
async def auth(client) -> dict:
    return await register_and_login(client)


from scripts.demo_data import make_pdf  # noqa: E402,F401  (re-exported for tests)
