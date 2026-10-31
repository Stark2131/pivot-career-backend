import pytest

from app.core.rate_limit import SlidingWindowLimiter
from app.core.errors import RateLimitedError
from tests.conftest import register_and_login



async def test_register_login_me(client):
    headers = await register_and_login(client, "Bob@Example.com")
    r = await client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["email"] == "bob@example.com"  # normalised to lowercase
    assert "password_hash" not in r.json()


async def test_duplicate_registration_conflicts(client):
    await register_and_login(client)
    r = await client.post("/api/auth/register", json={"email": "alice@example.com", "password": "Passw0rd!"})
    assert r.status_code == 409


async def test_weak_password_rejected(client):
    r = await client.post("/api/auth/register", json={"email": "x@example.com", "password": "short"})
    assert r.status_code == 422
    r = await client.post("/api/auth/register", json={"email": "x@example.com", "password": "onlyletters"})
    assert r.status_code == 422


async def test_wrong_password(client):
    await register_and_login(client)
    r = await client.post("/api/auth/login", json={"email": "alice@example.com", "password": "Wrong123"})
    assert r.status_code == 401
    r = await client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "Wrong123"})
    assert r.status_code == 401


async def test_protected_routes_require_token(client):
    assert (await client.get("/api/auth/me")).status_code == 401
    r = await client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_rate_limiter_blocks_after_limit():
    limiter = SlidingWindowLimiter()
    for _ in range(3):
        limiter.check("k", limit=3)
    with pytest.raises(RateLimitedError):
        limiter.check("k", limit=3)
