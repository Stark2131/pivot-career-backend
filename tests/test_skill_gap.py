from app.ai.skill_analyzer import JobInput, Requirement, UserSkillInfo, compute_gaps
from tests.conftest import register_and_login
from tests.helpers import analyze, setup_profile_and_jobs


def _req(i, name, t="required", lvl=None):
    return Requirement(skill_id=i, skill_name=name, category="x", requirement_type=t, required_proficiency=lvl, evidence=None)


def test_compute_gaps_logic():
    jobs = [
        JobInput(1, "A", None, [_req(1, "Python", lvl=4), _req(2, "Docker"), _req(3, "PostgreSQL")]),
        JobInput(2, "B", None, [_req(1, "Python"), _req(2, "Docker"), _req(4, "PyTorch", "preferred")]),
    ]
    user = {"Python": UserSkillInfo(3, True, "self_reported"), "MySQL": UserSkillInfo(4, True, "self_reported")}
    report = compute_gaps(user, jobs)
    items = {i.skill_name: i for i in report.items}
    assert items["Python"].gap_level == "partial"  # level 3 < required 4
    assert items["Docker"].gap_level == "missing" and items["Docker"].importance == 1.0
    # MySQL is related to PostgreSQL => partial, never "none"
    assert items["PostgreSQL"].gap_level == "partial"
    assert "does not count as having PostgreSQL" in items["PostgreSQL"].explanation
    assert items["PostgreSQL"].current_proficiency is None
    assert items["PyTorch"].importance == 0.25 and items["PyTorch"].importance_label == "medium"
    assert report.items[0].skill_name == "Docker"  # highest importance x gap first
    assert len(items["Docker"].job_references) == 2
    assert 0 < report.match_score < 100


async def test_analyze_endpoint(client, auth):
    await setup_profile_and_jobs(client, auth)
    report = await analyze(client, auth)
    items = {i["skill_name"]: i for i in report["items"]}
    assert items["Python"]["gap_level"] == "none"
    assert items["Docker"]["gap_level"] == "missing"
    assert items["Docker"]["importance_label"] == "critical"  # required in both JDs
    assert items["Docker"]["is_priority"] is True
    assert items["PostgreSQL"]["gap_level"] == "partial"  # user has MySQL only
    assert report["generated_by"] == "rule_based"
    assert {r["job_id"] for r in items["Docker"]["job_references"]} == set(report["job_description_ids"])

    lst = (await client.get("/api/skill-gap", headers=auth)).json()
    assert lst[0]["id"] == report["id"]
    assert (await client.get(f"/api/skill-gap/{report['id']}", headers=auth)).status_code == 200


async def test_analyze_llm_cannot_change_facts(client, auth, fake_llm):
    await setup_profile_and_jobs(client, auth)
    fake_llm.on("gap_explain", {"summary": "LLM summary", "explanations": [
        {"skill_name": "Docker", "explanation": "Docker is essential; start with containers basics."},
        {"skill_name": "NotASkill", "explanation": "ignored"}]})
    report = await analyze(client, auth)
    items = {i["skill_name"]: i for i in report["items"]}
    assert report["summary"] == "LLM summary" and report["generated_by"] == "llm"
    assert items["Docker"]["explanation"].startswith("Docker is essential")
    assert items["Docker"]["gap_level"] == "missing"


async def test_analyze_requires_jobs_and_isolation(client, auth):
    r = await client.post("/api/skill-gap/analyze", headers=auth, json={})
    assert r.status_code == 422
    j1, _ = await setup_profile_and_jobs(client, auth)
    other = await register_and_login(client, "eve@example.com")
    r = await client.post("/api/skill-gap/analyze", headers=other, json={"job_description_ids": [j1["id"]]})
    assert r.status_code == 404  # cannot analyse someone else's JD
