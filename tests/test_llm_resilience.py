"""The product must stay usable whatever the AI provider does: down, slow, or returning garbage.

`fake_llm` reports itself as available (like a configured API key). With no handler a call fails like an outage;
with a junk handler it returns text that is not valid JSON. Either way every step must succeed using the
rule-based fallback, never a 5xx or an exception, and results must say which engine produced them.
"""
import pytest

from tests.conftest import make_pdf
from tests.sample_data import RESUME_TEXT

TASKS = ["application_analysis", "evaluate_answer", "gap_explain", "interview_questions", "jd_extract", "plan_content",
         "progress_analysis", "project_personalise", "resume_parse"]
RULE_BASED = {"rule_based", "heuristic_fallback", "manual"}


@pytest.fixture(params=["outage", "garbage"])
def broken_llm(request, fake_llm):
    if request.param == "garbage":
        for task in TASKS:
            fake_llm.on(task, "<<< definitely not JSON >>>")
    return fake_llm


async def test_whole_journey_survives_a_broken_llm(client, broken_llm):
    assert broken_llm.available
    await client.post("/api/auth/register", json={"email": "resilient@example.com", "password": "Journey123"})
    token = (await client.post("/api/auth/login", json={"email": "resilient@example.com", "password": "Journey123"})).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    def ok(r, expect=(200, 201)):
        assert r.status_code in expect, f"{r.request.method} {r.request.url.path} -> {r.status_code} {r.text[:300]}"
        return r.json()

    resume = ok(await client.post("/api/profile/resume", headers=h, files={"file": ("cv.pdf", make_pdf(RESUME_TEXT), "application/pdf")}))
    assert resume["generated_by"] in RULE_BASED
    profile = ok(await client.get("/api/profile", headers=h))
    ok(await client.put("/api/profile", headers=h, json={
        "target_role": "Data Analyst", "experience_level": "junior", "weekly_hours": 8,
        "skills": [{"name": s["name"], "proficiency": 2} for s in profile["skills"]]}))

    imported = ok(await client.post("/api/jobs/import-market", headers=h, json={}))
    assert imported["imported"] == 20
    jobs = ok(await client.get("/api/jobs", headers=h))
    assert {j["generated_by"] for j in jobs} <= RULE_BASED

    gap = ok(await client.post("/api/skill-gap/analyze", headers=h, json={}))
    assert gap["job_count"] == 20 and gap["generated_by"] in RULE_BASED and gap["summary"]
    plan = ok(await client.post("/api/plans/generate", headers=h, json={}))
    assert plan["generated_by"] in RULE_BASED and plan["weeks"]
    assert all(t["resources"] and t["topics"] and t["exercises"] for w in plan["weeks"] for t in w["tasks"])

    projects = ok(await client.post("/api/projects/recommend", headers=h, json={"count": 3}))
    assert len(projects) == 3 and {p["generated_by"] for p in projects} <= RULE_BASED

    iv = ok(await client.post("/api/interviews", headers=h, json={"num_questions": 2, "interview_type": "mixed"}))
    assert iv["generated_by"] in RULE_BASED
    for q in iv["questions"]:
        ok(await client.post(f"/api/interviews/{iv['id']}/answer", headers=h, json={"question_id": q["id"], "answer_text": "not sure"}))
    out = ok(await client.post(f"/api/interviews/{iv['id']}/evaluate", headers=h))
    assert {q["evaluation"]["evaluator"] for q in out["questions"]} == {"heuristic_fallback"}
    assert out["adaptation"]["message"]                              # the closed loop ran (or said why not) without erroring

    ok(await client.post("/api/progress/assessments", headers=h, json={"skill_name": "SQL", "proficiency": 1}))
    ok(await client.get("/api/progress?include_ai_insights=true", headers=h))
    for i in range(12):
        ok(await client.post("/api/applications", headers=h, json={
            "company_name": f"Co {i}", "role_title": "Data Analyst", "applied_date": "2026-08-01",
            "status": "interview" if i < 6 else "rejected", "channel": "referral" if i < 6 else "job_board"}))
    analytics = ok(await client.get("/api/applications/analytics", headers=h))
    assert analytics["generated_by"] == "rule_based" and analytics["narrative"]["observations"]
    recs = ok(await client.get("/api/applications/recommendations", headers=h))
    assert recs["sufficient_data"] and recs["insights"]
