from datetime import date, timedelta

from app.ai.progress_analyst import ProgressSnapshot, TaskFact, detect_struggles
from app.ai.tools import Tool, ToolRegistry
from pydantic import BaseModel
from tests.helpers import analyze, generate_plan, setup_profile_and_jobs


def test_detect_struggles_rules():
    snap = ProgressSnapshot(
        tasks=[TaskFact("Docker", 1, "completed", 5, 5, False), TaskFact("AWS", 2, "pending", 5, None, True),
               TaskFact("AWS", 3, "pending", 5, None, True), TaskFact("PyTorch", 1, "skipped", 3, None, False)],
        interview_scores_by_skill={"SQL": [3.0, 4.0], "Python": [8.0]},
        assessments_by_skill={"Kubernetes": [2, 2]}, consistency_rate=0.25, weeks_elapsed=4)
    signals = {(s.skill_name, s.signal) for s in detect_struggles(snap)}
    assert ("Docker", "difficulty") in signals and ("AWS", "overdue") in signals
    assert ("PyTorch", "skipped") in signals and ("SQL", "interview") in signals
    assert ("Kubernetes", "assessment") in signals and (None, "consistency") in signals
    assert not any(s == "Python" for s, _ in signals)


def test_tool_registry_validates_names_and_args():
    class Args(BaseModel):
        n: int

    reg = ToolRegistry([Tool("double", "x2", Args, lambda a: {"v": a.n * 2})])
    assert reg.run("double", {"n": 2}) == '{"v": 4}'
    assert "Unknown tool" in reg.run("drop_tables", {})
    assert "Invalid arguments" in reg.run("double", {"n": "abc"})


async def test_progress_overview_and_assessment(client, auth):
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)
    plan = await generate_plan(client, auth)
    t = plan["weeks"][0]["tasks"][0]
    await client.patch(f"/api/plans/{plan['id']}/tasks/{t['id']}", headers=auth, json={"status": "completed"})

    r = await client.post("/api/progress/assessments", headers=auth, json={"skill_name": "docker", "proficiency": 2})
    assert r.status_code == 201 and r.json()["skill_name"] == "Docker"
    await client.post("/api/progress/assessments", headers=auth, json={"skill_name": "Docker", "proficiency": 3, "method": "quiz"})

    p = (await client.get("/api/progress", headers=auth)).json()
    assert p["plan"]["completed"] == 1 and p["plan"]["total_tasks"] == len([x for w in plan["weeks"] for x in w["tasks"]])
    assert p["consistency"]["active_weeks"] == 1 and p["consistency"]["current_streak_weeks"] == 1
    docker = next(s for s in p["skills"] if s["skill_name"] == "Docker")
    assert docker["first_level"] == 2 and docker["latest_level"] == 3 and docker["change"] == 1
    assert p["insights"] is None

    p = (await client.get("/api/progress?include_ai_insights=true", headers=auth)).json()
    assert p["insights_generated_by"] == "rule_based" and p["insights"]["summary"]
    profile = (await client.get("/api/profile", headers=auth)).json()
    assert next(s for s in profile["skills"] if s["name"] == "Docker")["proficiency"] == 3


async def test_progress_analyst_tool_calling(client, auth, fake_llm):
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)
    await generate_plan(client, auth)
    steps = iter([
        {"action": "call_tool", "tool_name": "get_task_summary", "arguments": {}},
        {"action": "call_tool", "tool_name": "run_sql", "arguments": {"q": "DROP TABLE users"}},  # rejected
        {"action": "final_answer", "final_answer": {"summary": "You are on track.", "struggling_areas": [],
                                                    "recommended_adjustments": []}},
    ])
    prompts = []

    def handler(prompt):
        prompts.append(prompt)
        return next(steps)

    fake_llm.on("progress_analysis", handler)
    p = (await client.get("/api/progress?include_ai_insights=true", headers=auth)).json()
    assert p["insights_generated_by"] == "llm_tools" and p["insights"]["summary"] == "You are on track."
    assert "by_skill" in prompts[1]  # real tool result was fed back
    assert "Unknown tool 'run_sql'" in prompts[2]


async def test_recalculate_plan_proposes_without_overwriting(client, auth):
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)
    plan = await generate_plan(client, auth, start_date=(date.today() - timedelta(weeks=3)).isoformat())
    hard = plan["weeks"][0]["tasks"][0]
    await client.patch(f"/api/plans/{plan['id']}/tasks/{hard['id']}", headers=auth, json={"difficulty_rating": 5})

    r = await client.post("/api/progress/recalculate-plan", headers=auth, json={"reason": "Behind schedule"})
    assert r.status_code == 201, r.text
    out = r.json()
    signals = {s["signal"] for s in out["struggling_areas"]}
    assert "difficulty" in signals and "consistency" in signals  # 3 weeks elapsed, no activity
    proposed = out["proposed_plan"]
    assert proposed["status"] == "proposed" and proposed["change_summary"]["triggered_by"] == "progress_recalculation"
    assert proposed["weekly_hours"] < plan["weekly_hours"]  # lighter pace suggested for consistency issues
    assert hard["skill_name"] in proposed["change_summary"]["struggling_skills"]
    assert (await client.get(f"/api/plans/{plan['id']}", headers=auth)).json()["status"] == "active"


async def test_recalculate_requires_active_plan(client, auth):
    assert (await client.post("/api/progress/recalculate-plan", headers=auth)).status_code == 422
