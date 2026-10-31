"""Market job postings for a target role: live (JSearch / Adzuna) with a DB cache, else curated seed data.

Order of preference: fresh cache -> JSearch -> Adzuna -> seed postings in data/jds/. A missing key or a failed
call never raises to the user; the result records which source was used and why a fallback happened.
"""
import json
import logging
import math
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import as_utc, utcnow
from app.models import MarketJobCache

logger = logging.getLogger(__name__)

SEED_DIR = Path(__file__).resolve().parents[3] / "data" / "jds"

# role family -> title keywords (first match wins, so more specific families come first)
ROLE_FAMILIES: list[tuple[str, tuple[str, ...]]] = [
    ("ml_engineer", ("machine learning", "ml engineer", "mlops", "ai engineer", "applied scientist", "data scientist",
                     "research engineer", "deep learning")),
    ("product_manager", ("product manager", "product owner", "product management", "product marketing", "apm")),
    ("data_analyst", ("data analyst", "business analyst", "bi analyst", "analytics", "business intelligence",
                      "reporting analyst", "product analyst", "marketing analyst", "operations analyst")),
]
FAMILY_LABELS = {"data_analyst": "Data Analyst", "product_manager": "Product Manager", "ml_engineer": "Machine Learning Engineer"}


def role_family_of(title: str | None) -> str | None:
    t = (title or "").lower()
    for family, keywords in ROLE_FAMILIES:
        if any(k in t for k in keywords):
            return family
    return None


@dataclass
class Posting:
    title: str
    company: str | None
    text: str
    url: str | None = None
    location: str | None = None
    external_id: str | None = None


@dataclass
class MarketResult:
    source: str                      # seed | jsearch | adzuna
    postings: list[Posting]
    cached: bool = False
    fallback_reason: str | None = None
    notes: list[str] = field(default_factory=list)


# --- seed data ------------------------------------------------------------------------------------
def load_seed(role_family: str | None) -> list[Posting]:
    if not role_family:
        return []
    path = SEED_DIR / f"{role_family}.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Posting(title=p["title"], company=p.get("company"), text=p["text"], url=p.get("url"),
                    location=p.get("location"), external_id=p.get("id")) for p in data["postings"]]


# --- live providers ---------------------------------------------------------------------------------
async def _fetch_jsearch(client: httpx.AsyncClient, role: str, country: str, limit: int, key: str) -> list[Posting]:
    r = await client.get(
        "https://jsearch.p.rapidapi.com/search-v2",  # the old /search endpoint now returns 404
        params={"query": f"{role} jobs in {country}", "page": 1, "num_pages": max(1, min(3, math.ceil(limit / 10))),
                "date_posted": "month"},
        headers={"X-RapidAPI-Key": key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"},
    )
    r.raise_for_status()
    data = r.json().get("data") or []
    jobs = data.get("jobs") if isinstance(data, dict) else data      # search-v2 nests the list; v1 returned it directly
    out = []
    for j in jobs or []:
        text = (j.get("job_description") or "").strip()
        if len(text) < 50:
            continue
        place = ", ".join(x for x in (j.get("job_city"), j.get("job_state"), j.get("job_country")) if x)
        out.append(Posting(title=j.get("job_title") or role, company=j.get("employer_name"), text=text,
                           url=j.get("job_apply_link"), location=place or None, external_id=j.get("job_id")))
    return out[:limit]


async def _fetch_adzuna(client: httpx.AsyncClient, role: str, country: str, limit: int, app_id: str, app_key: str) -> list[Posting]:
    r = await client.get(
        f"https://api.adzuna.com/v1/api/jobs/{country.lower()}/search/1",
        params={"app_id": app_id, "app_key": app_key, "what": role, "results_per_page": min(limit, 50),
                "content-type": "application/json"},
    )
    r.raise_for_status()
    out = []
    for j in r.json().get("results") or []:
        # Adzuna returns a truncated description snippet; that is all the text we have.
        text = (j.get("description") or "").strip()
        if len(text) < 50:
            continue
        out.append(Posting(title=j.get("title") or role, company=(j.get("company") or {}).get("display_name"),
                           text=f"{j.get('title') or role}\n\n{text}", url=j.get("redirect_url"),
                           location=(j.get("location") or {}).get("display_name"), external_id=str(j.get("id"))))
    return out[:limit]


def _providers() -> list[str]:
    s = get_settings()
    out = []
    if s.jsearch_api_key and s.jsearch_api_key.get_secret_value():
        out.append("jsearch")
    if s.adzuna_app_id and s.adzuna_app_key and s.adzuna_app_key.get_secret_value():
        out.append("adzuna")
    return out


async def _cached(db: AsyncSession, key: str) -> list[Posting] | None:
    row = await db.scalar(select(MarketJobCache).where(MarketJobCache.cache_key == key))
    if row is None:
        return None
    if utcnow() - as_utc(row.fetched_at) > timedelta(hours=get_settings().market_cache_hours):
        return None
    return [Posting(**p) for p in row.payload]


async def _store(db: AsyncSession, provider: str, key: str, postings: list[Posting]) -> None:
    payload = [p.__dict__ for p in postings]
    row = await db.scalar(select(MarketJobCache).where(MarketJobCache.cache_key == key))
    if row is None:
        db.add(MarketJobCache(provider=provider, cache_key=key, payload=payload, fetched_at=utcnow()))
    else:
        row.payload, row.fetched_at = payload, utcnow()
    await db.commit()


async def fetch_postings(
    db: AsyncSession, role: str, *, country: str = "us", limit: int = 20, refresh: bool = False,
    transport: httpx.AsyncBaseTransport | None = None, source: str = "auto",
) -> MarketResult:
    """Best available postings for `role`. Never raises for provider problems. source="seed" never goes online."""
    settings = get_settings()
    family = role_family_of(role)
    providers = [] if source == "seed" else _providers()
    reason = None
    if source == "seed":
        reason = "Sample postings were requested explicitly (source=seed)."
    elif not providers:
        reason = "No job-board API key configured (set JSEARCH_API_KEY or ADZUNA_APP_ID/ADZUNA_APP_KEY)."
    secrets = {"jsearch": settings.jsearch_api_key, "adzuna": settings.adzuna_app_key}
    async with httpx.AsyncClient(timeout=settings.market_timeout_seconds, transport=transport) as client:
        for provider in providers:
            key = f"{provider}|{family or role.lower()}|{country.lower()}|{limit}"
            if not refresh:
                hit = await _cached(db, key)
                if hit:
                    return MarketResult(source=provider, postings=hit, cached=True)
            try:
                if provider == "jsearch":
                    postings = await _fetch_jsearch(client, role, country, limit, secrets["jsearch"].get_secret_value())
                else:
                    postings = await _fetch_adzuna(client, role, country, limit, settings.adzuna_app_id,
                                                   secrets["adzuna"].get_secret_value())
            except httpx.HTTPStatusError as exc:
                # Status code only: neither the request URL nor the response body is logged or returned (keys).
                code = exc.response.status_code
                logger.warning("Live job fetch via %s failed: HTTP %s", provider, code)
                hint = " Check the API key, your subscription to that API, and the endpoint." if code in {401, 403, 404} else ""
                reason = f"{provider} returned HTTP {code}; used the next source.{hint}"
                continue
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("Live job fetch via %s failed: %s", provider, type(exc).__name__)
                reason = f"{provider} request failed ({type(exc).__name__}); used the next source."
                continue
            if not postings:
                reason = f"{provider} returned no usable postings for '{role}'."
                continue
            await _store(db, provider, key, postings)
            return MarketResult(source=provider, postings=postings)
    seed = load_seed(family)
    notes = []
    if seed:
        notes.append("Seed postings are synthetic sample data, not real job-market data.")
    return MarketResult(source="seed", postings=seed[:limit], fallback_reason=reason, notes=notes)
