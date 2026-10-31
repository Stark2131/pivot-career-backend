from app.modules.applications.analytics import AppFact, compute_analytics, wilson
from tests.conftest import register_and_login
from tests.helpers import setup_profile_and_jobs


def test_wilson_interval():
    lo, hi = wilson(5, 10)
    assert 0.23 < lo < 0.25 and 0.76 < hi < 0.77
    assert wilson(0, 0) is None


def test_analytics_flags_insufficient_data():
    stats = compute_analytics([AppFact("ML Engineer", "applied", False, "mid", ["Python"])])
    assert stats["data_sufficiency"]["sufficient"] is False
    assert "Only 1 application" in stats["data_sufficiency"]["message"]
    assert stats["skills_vs_response"] == []  # never reported from tiny groups
    assert "cause" in stats["disclaimer"]


def test_analytics_patterns_with_enough_data():
    apps = ([AppFact("ML Engineer", "interview", True, "junior", ["Python", "Docker"]) for _ in range(4)]
            + [AppFact("ML Engineer", "rejected", False, "junior", ["Python", "Docker"])]
            + [AppFact("Data Scientist", "rejected", False, "mid", ["Python"]) for _ in range(5)]
            + [AppFact("Data Scientist", "rejected", True, "mid", ["Python"])])
    stats = compute_analytics(apps)
    assert stats["total_applications"] == 11 and stats["data_sufficiency"]["sufficient"]
    assert stats["by_role"]["ml engineer"]["response_rate"] == 0.8
    assert stats["by_role"]["data scientist"]["response_rate"] == round(1 / 6, 3)
    docker = next(r for r in stats["skills_vs_response"] if r["skill"] == "Docker")
    assert docker["difference"] > 0.6
    assert stats["skill_combinations"][0]["skills"] == ["Docker", "Python"]
    assert stats["conversion"]["application_to_interview"]["responses"] == 5


async def test_application_crud_and_status_tracking(client, auth):
    j1, _ = await setup_profile_and_jobs(client, auth)
    r = await client.post("/api/applications", headers=auth, json={
        "company_name": "Nimbus AI", "role_title": "ML Engineer", "applied_date": "2026-10-01",
        "job_description_id": j1["id"], "experience_level": "mid"})
    assert r.status_code == 201, r.text
    app = r.json()
    assert "Python" in app["skills_highlighted"] and "Docker" not in app["skills_highlighted"]  # only user's matching skills
    assert app["job_description_text"]

    r = await client.patch(f"/api/applications/{app['id']}", headers=auth, json={"status": "interview"})
    assert r.json()["reached_interview"] is True
    r = await client.patch(f"/api/applications/{app['id']}", headers=auth, json={
        "status": "rejected", "interview_feedback": "Needs more MLOps", "outcome": "Rejected after onsite",
        "outcome_date": "2026-10-20"})
    body = r.json()
    assert body["status"] == "rejected" and body["reached_interview"] is True  # sticky
    assert body["interview_feedback"] == "Needs more MLOps"

    assert len((await client.get("/api/applications?status=rejected", headers=auth)).json()) == 1
    analytics = (await client.get("/api/applications/analytics", headers=auth)).json()
    assert analytics["stats"]["total_applications"] == 1
    assert analytics["stats"]["data_sufficiency"]["sufficient"] is False
    assert analytics["generated_by"] == "rule_based"

    other = await register_and_login(client, "oscar@example.com")
    assert (await client.get(f"/api/applications/{app['id']}", headers=other)).status_code == 404
    assert (await client.post("/api/applications", headers=other, json={
        "company_name": "X", "role_title": "Y", "applied_date": "2026-10-01", "job_description_id": j1["id"]})).status_code == 404
    assert (await client.delete(f"/api/applications/{app['id']}", headers=auth)).status_code == 204


async def test_application_analytics_llm_narrative(client, auth, fake_llm):
    await client.post("/api/applications", headers=auth, json={
        "company_name": "A", "role_title": "ML Engineer", "applied_date": "2026-10-01"})
    fake_llm.on("application_analysis", {"summary": "Not enough data yet.", "observations": ["Keep logging applications."]})
    out = (await client.get("/api/applications/analytics", headers=auth)).json()
    assert out["generated_by"] == "llm" and out["narrative"]["summary"] == "Not enough data yet."
    out = (await client.get("/api/applications/analytics?include_ai_summary=false", headers=auth)).json()
    assert out["generated_by"] == "rule_based"
