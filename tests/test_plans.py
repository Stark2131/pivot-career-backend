from app.ai.planner import SkillNeed, build_schedule
from tests.helpers import analyze, generate_plan, setup_profile_and_jobs


def test_schedule_respects_weekly_hours():
    needs = [SkillNeed("Docker", 12), SkillNeed("AWS", 30), SkillNeed("PyTorch", 5)]
    tasks, deferred = build_schedule(needs, weekly_hours=8, max_weeks=12)
    per_week: dict[int, float] = {}
    for t in tasks:
        per_week[t.week_number] = per_week.get(t.week_number, 0) + t.hours
    assert all(h <= 8.0001 for h in per_week.values())
    assert sum(t.hours for t in tasks if t.skill_name == "AWS") == 30
    assert not deferred
    tasks, deferred = build_schedule(needs, weekly_hours=5, max_weeks=3)
    assert deferred  # does not fit -> reported, not silently crammed in


async def test_generate_plan_and_complete_task(client, auth):
    await setup_profile_and_jobs(client, auth, weekly_hours=10)
    await analyze(client, auth)
    plan = await generate_plan(client, auth)
    assert plan["status"] == "active" and plan["version"] == 1
    assert plan["generated_by"] == "rule_based"
    first_week_skills = plan["weeks"][0]["skills"]
    assert "Docker" in first_week_skills or "Machine Learning" in first_week_skills
    for w in plan["weeks"]:
        assert w["total_hours"] <= 10
        for t in w["tasks"]:
            assert t["topics"] and t["activities"] and t["exercises"] and t["expected_outcome"]

    task = plan["weeks"][0]["tasks"][0]
    r = await client.patch(f"/api/plans/{plan['id']}/tasks/{task['id']}", headers=auth,
                           json={"status": "completed", "difficulty_rating": 2, "notes": "done"})
    assert r.status_code == 200 and r.json()["completed_at"]
    got = (await client.get(f"/api/plans/{plan['id']}", headers=auth)).json()
    assert got["progress"]["completed_tasks"] == 1


async def test_plan_with_llm_content_validated(client, auth, fake_llm):
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)

    def content(prompt):
        import json
        sched = json.loads(prompt)["schedule"]
        return {"summary": "AI summary", "weeks": [
            {"week_number": w["week_number"], "tasks": [
                {"skill_name": t["skill_name"], "title": f"Learn {t['skill_name']}", "topics": ["a"],
                 "activities": ["b"], "exercises": ["c"], "expected_outcome": "d"} for t in w["tasks"]]
             + [{"skill_name": "Injected Skill", "title": "x", "topics": ["x"], "activities": ["x"],
                 "exercises": ["x"], "expected_outcome": "x"}]}
            for w in sched]}

    fake_llm.on("plan_content", content)
    plan = await generate_plan(client, auth)
    assert plan["generated_by"] == "llm"
    all_skills = {t["skill_name"] for w in plan["weeks"] for t in w["tasks"]}
    assert "Injected Skill" not in all_skills
    assert "AI summary" in plan["summary"]


async def test_adjust_creates_proposal_and_preserves_original(client, auth):
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)
    plan = await generate_plan(client, auth)
    tasks = [t for w in plan["weeks"] for t in w["tasks"]]
    hard = tasks[0]
    await client.patch(f"/api/plans/{plan['id']}/tasks/{hard['id']}", headers=auth, json={"difficulty_rating": 5})

    r = await client.post(f"/api/plans/{plan['id']}/adjust", headers=auth,
                          json={"reason": "Finding it hard", "weekly_hours": 6, "focus_skills": ["FastAPI"]})
    assert r.status_code == 201, r.text
    proposal = r.json()
    assert proposal["status"] == "proposed" and proposal["parent_plan_id"] == plan["id"]
    cs = proposal["change_summary"]
    assert hard["skill_name"] in cs["struggling_skills"]
    assert hard["skill_name"] in cs["hours_changes"]
    assert proposal["weeks"][0]["skills"][0] == "FastAPI"  # focus first
    # Original is untouched and still active
    original = (await client.get(f"/api/plans/{plan['id']}", headers=auth)).json()
    assert original["status"] == "active"
    assert [t["id"] for w in original["weeks"] for t in w["tasks"]] == [t["id"] for t in tasks]

    r = await client.post(f"/api/plans/{proposal['id']}/accept", headers=auth)
    assert r.json()["status"] == "active"
    assert (await client.get(f"/api/plans/{plan['id']}", headers=auth)).json()["status"] == "archived"
    assert (await client.post(f"/api/plans/{proposal['id']}/accept", headers=auth)).status_code == 409
    statuses = {p["status"] for p in (await client.get("/api/plans", headers=auth)).json()}
    # rating a task "hard" already auto-proposed a plan (see test_adaptation); the manual /adjust superseded it
    assert statuses == {"active", "archived", "superseded"}


async def test_regenerate_does_not_overwrite_active(client, auth):
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)
    first = await generate_plan(client, auth)
    second = await generate_plan(client, auth)
    assert second["status"] == "proposed" and second["version"] == 2
    r = await client.post(f"/api/plans/{second['id']}/reject", headers=auth)
    assert r.json()["status"] == "rejected"
    assert (await client.get(f"/api/plans/{first['id']}", headers=auth)).json()["status"] == "active"


async def test_project_recommendations(client, auth):
    await setup_profile_and_jobs(client, auth)
    report = await analyze(client, auth)
    gaps = {i["skill_name"] for i in report["items"] if i["gap_level"] != "none"}
    r = await client.post("/api/projects/recommend", headers=auth, json={"count": 3})
    assert r.status_code == 201, r.text
    projects = r.json()
    assert 1 <= len(projects) <= 3
    for p in projects:
        assert set(p["skills_covered"]) & gaps
        assert p["problem_statement"] and p["core_features"] and p["deliverables"] and p["tech_stack"]
    r = await client.patch(f"/api/projects/{projects[0]['id']}", headers=auth,
                           json={"status": "completed", "repo_url": "https://github.com/me/proj"})
    assert r.json()["status"] == "completed" and r.json()["completed_at"]
    assert len((await client.get("/api/projects?status=completed", headers=auth)).json()) == 1
