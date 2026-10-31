"""Skill gaps from many postings: role scoping, seed data, live fetch + cache, fallback, taxonomy."""
import json

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.core.database import SessionLocal
from app.modules.jobs import market
from app.utils.skills_taxonomy import _T, normalize_skill
from tests.sample_data import JD_ML_ENGINEER

FAMILIES = ["data_analyst", "product_manager", "ml_engineer"]


def test_role_family_detection():
    assert market.role_family_of("Senior Data Analyst") == "data_analyst"
    assert market.role_family_of("Product Marketing Manager") == "product_manager"
    assert market.role_family_of("Machine Learning Engineer") == "ml_engineer"
    assert market.role_family_of("Pastry Chef") is None and market.role_family_of(None) is None


@pytest.mark.parametrize("family", FAMILIES)
def test_seed_files_are_complete_and_labelled(family):
    data = json.loads((market.SEED_DIR / f"{family}.json").read_text(encoding="utf-8"))
    posts = data["postings"]
    assert data["source"] == "seed" and len(posts) == 20
    assert len({p["id"] for p in posts}) == 20 and len({(p["title"], p["company"]) for p in posts}) == 20
    assert all(p["source"] == "seed" and len(p["text"]) > 400 and p["role_family"] == family for p in posts)


def test_taxonomy_size_and_fuzzy_matching():
    assert len(_T) >= 150
    assert normalize_skill("tableu").name == "Tableau" and normalize_skill("kuberentes").name == "Kubernetes"
    assert normalize_skill("a/b tests").name == "A/B Testing"
    assert normalize_skill("Underwater Basket Weaving").in_taxonomy is False   # fuzzy never invents skills
    assert normalize_skill("go").name == "Go" and normalize_skill("Rocket").in_taxonomy is False


async def _profile(client, auth, role):
    r = await client.put("/api/profile", headers=auth, json={
        "current_role": "Teacher", "target_role": role, "experience_level": "junior", "weekly_hours": 8,
        "skills": [{"name": "Excel", "proficiency": 3}, {"name": "Communication", "proficiency": 4}]})
    assert r.status_code == 200, r.text


async def test_import_seed_postings_then_gap_map_says_how_many(client, auth):
    await _profile(client, auth, "Data Analyst")
    r = await client.post("/api/jobs/import-market", headers=auth, json={})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["source"] == "seed" and out["imported"] == 20 and out["role_family"] == "data_analyst"
    assert "API key" in out["fallback_reason"] and any("synthetic" in n.lower() for n in out["notes"])

    again = (await client.post("/api/jobs/import-market", headers=auth, json={})).json()
    assert again["imported"] == 0 and again["skipped_duplicates"] == 20          # idempotent

    jobs = (await client.get("/api/jobs", headers=auth)).json()
    assert len(jobs) == 20 and {j["source_provider"] for j in jobs} == {"seed"}
    assert {j["role_family"] for j in jobs} == {"data_analyst"}

    gap = (await client.post("/api/skill-gap/analyze", headers=auth, json={})).json()
    assert gap["job_count"] == 20 and gap["job_sources"] == {"seed": 20}
    assert gap["based_on"] == "Based on 20 job postings (20 seed)" and gap["role_family"] == "data_analyst"
    by = {i["skill_name"]: i for i in gap["items"]}
    # importance is the share of postings that mention the skill
    assert by["SQL"]["frequency"] >= 18 and by["SQL"]["importance"] >= 0.9
    assert by["SQL"]["gap_level"] == "missing" and by["Excel"]["gap_level"] in {"none", "partial"}
    assert gap["items"][0]["priority_rank"] == 1


async def test_other_role_postings_do_not_dilute_the_target_role(client, auth):
    await _profile(client, auth, "Data Analyst")
    await client.post("/api/jobs/import-market", headers=auth, json={"target_role": "Data Analyst"})
    await client.post("/api/jobs/import-market", headers=auth, json={"target_role": "Machine Learning Engineer", "limit": 5})
    await client.post("/api/jobs", headers=auth, json={"title": "Pastry Chef", "text": JD_ML_ENGINEER})
    assert len((await client.get("/api/jobs", headers=auth)).json()) == 26
    gap = (await client.post("/api/skill-gap/analyze", headers=auth, json={})).json()
    assert gap["job_count"] == 20 and gap["role_family"] == "data_analyst"
    explicit = (await client.post("/api/skill-gap/analyze", headers=auth,
                                  json={"job_description_ids": gap["job_description_ids"][:3]})).json()
    assert explicit["job_count"] == 3


async def test_unknown_role_without_keys_is_a_clear_error(client, auth):
    r = await client.post("/api/jobs/import-market", headers=auth, json={"target_role": "Pastry Chef"})
    assert r.status_code == 422 and "Seed data covers" in r.json()["error"]["message"]
    r = await client.post("/api/jobs/import-market", headers=auth, json={})
    assert r.status_code == 422                                                   # no target role set


def _settings(**kw):
    return Settings(jsearch_api_key=SecretStr("rapid-secret-123"), **kw)


JSEARCH_BODY = {"data": [
    {"job_id": "a1", "job_title": "Data Analyst", "employer_name": "Real Co", "job_city": "Austin", "job_country": "US",
     "job_description": "Requirements: SQL, Excel and Tableau. " * 5, "job_apply_link": "https://example.com/a1"},
    {"job_id": "a2", "job_title": "Tiny", "employer_name": "X", "job_description": "too short"},
]}


async def test_search_v2_nested_response_shape_is_parsed(monkeypatch):
    monkeypatch.setattr(market, "get_settings", lambda: _settings())
    seen = []

    def ok(request: httpx.Request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"status": "OK", "data": {"jobs": JSEARCH_BODY["data"]}})

    async with SessionLocal() as db:
        res = await market.fetch_postings(db, "Product Manager", transport=httpx.MockTransport(ok), refresh=True)
    assert seen == ["/search-v2"] and res.source == "jsearch" and [p.company for p in res.postings] == ["Real Co"]


async def test_jsearch_success_is_cached_and_key_is_sent_as_header(monkeypatch):
    monkeypatch.setattr(market, "get_settings", lambda: _settings())
    seen = []

    def ok(request: httpx.Request):
        seen.append(request)
        return httpx.Response(200, json=JSEARCH_BODY)

    async with SessionLocal() as db:
        first = await market.fetch_postings(db, "Data Analyst", transport=httpx.MockTransport(ok))
        assert first.source == "jsearch" and not first.cached and [p.company for p in first.postings] == ["Real Co"]
        assert seen[0].headers["X-RapidAPI-Key"] == "rapid-secret-123" and "rapid-secret" not in str(seen[0].url)

        def boom(request):
            raise AssertionError("network must not be touched when the cache is fresh")

        second = await market.fetch_postings(db, "Data Analyst", transport=httpx.MockTransport(boom))
        assert second.source == "jsearch" and second.cached and second.postings[0].title == "Data Analyst"


def _timeout(request):
    raise httpx.ConnectTimeout("slow")


@pytest.mark.parametrize("handler", [
    lambda r: httpx.Response(500, json={"message": "rapid-secret-123 exploded"}),
    lambda r: httpx.Response(200, json={"data": []}),
    _timeout,
], ids=["http-500", "no-results", "timeout"])
async def test_live_failure_falls_back_to_seed_without_leaking_the_key(monkeypatch, handler):
    monkeypatch.setattr(market, "get_settings", lambda: _settings())
    async with SessionLocal() as db:
        res = await market.fetch_postings(db, "Data Analyst", transport=httpx.MockTransport(handler))
    assert res.source == "seed" and len(res.postings) == 20 and res.fallback_reason
    assert "rapid-secret" not in res.fallback_reason


@pytest.mark.parametrize("code,hint", [(404, True), (403, True), (401, True), (500, False)])
async def test_http_status_is_reported_so_a_bad_setup_can_be_diagnosed(monkeypatch, code, hint):
    monkeypatch.setattr(market, "get_settings", lambda: _settings())
    handler = lambda r: httpx.Response(code, json={"message": "Endpoint '/search' does not exist rapid-secret-123"})  # noqa: E731
    async with SessionLocal() as db:
        res = await market.fetch_postings(db, "Data Analyst", transport=httpx.MockTransport(handler))
    assert res.source == "seed" and f"HTTP {code}" in res.fallback_reason
    assert ("subscription" in res.fallback_reason) is hint
    assert "rapid-secret" not in res.fallback_reason and "Endpoint" not in res.fallback_reason     # body is never echoed


async def test_source_seed_never_goes_online_even_with_a_key_configured(monkeypatch, client, auth):
    monkeypatch.setattr(market, "get_settings", lambda: _settings())

    def boom(request):
        raise AssertionError("source=seed must not call any job board")

    async with SessionLocal() as db:
        res = await market.fetch_postings(db, "Data Analyst", source="seed", transport=httpx.MockTransport(boom))
    assert res.source == "seed" and len(res.postings) == 20 and "source=seed" in res.fallback_reason

    await _profile(client, auth, "Data Analyst")
    r = await client.post("/api/jobs/import-market", headers=auth, json={"source": "seed"})
    assert r.status_code == 201 and r.json()["source"] == "seed" and r.json()["imported"] == 20
