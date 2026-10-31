"""Load the curated seed job postings (data/jds/*.json, 20 per role) into a user's saved job descriptions.

    python -m scripts.seed_jds                         # demo user, all three roles
    python -m scripts.seed_jds --role data_analyst     # one role
    python -m scripts.seed_jds --email me@example.com --password '...'

The postings are SYNTHETIC (source "seed"): companies are fictional and this is not real job-market data.
It drives the real API in-process (POST /api/jobs/import-market with source="seed", so it never calls a live job
board even if API keys are configured), so extraction, normalisation and the role-family tagging are exactly what a
user would get. Requires `alembic upgrade head` first. Safe to repeat.
"""
import argparse
import asyncio

import httpx

from app.main import app
from app.modules.jobs.market import FAMILY_LABELS
from scripts.demo_data import DEMO_USER


async def login_or_register(client: httpx.AsyncClient, email: str, password: str, full_name: str) -> dict:
    await client.post("/api/auth/register", json={"email": email, "password": password, "full_name": full_name})
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def import_roles(client: httpx.AsyncClient, headers: dict, roles: list[str]) -> dict[str, dict]:
    out = {}
    for family in roles:
        r = await client.post("/api/jobs/import-market", headers=headers,
                              json={"target_role": FAMILY_LABELS[family], "limit": 20, "source": "seed"})
        r.raise_for_status()
        out[family] = r.json()
    return out


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", default=DEMO_USER["email"])
    ap.add_argument("--password", default=DEMO_USER["password"])
    ap.add_argument("--role", choices=[*FAMILY_LABELS, "all"], default="all")
    args = ap.parse_args()
    roles = list(FAMILY_LABELS) if args.role == "all" else [args.role]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://seed", timeout=120) as client:
        headers = await login_or_register(client, args.email, args.password, DEMO_USER["full_name"])
        for family, res in (await import_roles(client, headers, roles)).items():
            print(f"{FAMILY_LABELS[family]:<28} source={res['source']:<6} imported={res['imported']:>2} "
                  f"skipped={res['skipped_duplicates']:>2}")


if __name__ == "__main__":
    asyncio.run(main())
