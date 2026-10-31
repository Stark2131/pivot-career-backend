"""The closed loop: interview / assessment / task evidence -> proficiency -> gaps -> auto plan proposal."""
from app.modules.progress.adaptation import ema_level, score_to_level
from tests.helpers import analyze, generate_plan, setup_profile_and_jobs


def test_score_mapping_and_ema():
    assert score_to_level(0.2) == 1.0 and score_to_level(10) == 5.0 and score_to_level(6) == 3.0
    assert ema_level(3, 1.0) == 2          # 0.4*1 + 0.6*3 = 2.2
    assert ema_level(4, 1.0) == 3          # one bad interview does not wipe out a strong skill
    assert ema_level(1, 1.0) == 1 and ema_level(5, 5.0) == 5


async def _interview(client, auth, skills, answer="no idea"):
    iv = (await client.post("/api/interviews", headers=auth,
                            json={"interview_type": "technical", "num_questions": len(skills), "focus_skills": skills})).json()
    for q in iv["questions"]:
        await client.post(f"/api/interviews/{iv['id']}/answer", headers=auth,
                          json={"question_id": q["id"], "answer_text": answer})
    r = await client.post(f"/api/interviews/{iv['id']}/evaluate", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


async def _active_plan(client, auth):
    plans = (await client.get("/api/plans", headers=auth)).json()
    return next(p for p in plans if p["status"] == "active")


async def _proposals(client, auth):
    return (await client.get("/api/plans?status=proposed", headers=auth)).json()


async def _skill_level(client, auth, name):
    skills = (await client.get("/api/profile", headers=auth)).json()["skills"]
    return next(s["proficiency"] for s in skills if s["name"] == name)


async def test_bad_interview_on_planned_skill_adds_time_with_reason(client, auth):
    """Acceptance: a bad interview on skill X -> a new proposal appears that adds time for X, with a reason."""
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)
    plan = await generate_plan(client, auth)
    planned = plan["weeks"][0]["tasks"][0]["skill_name"]
    before = sum(t["estimated_hours"] for w in plan["weeks"] for t in w["tasks"] if t["skill_name"] == planned)
    assert await _proposals(client, auth) == []

    out = await _interview(client, auth, [planned])
    ad = out["adaptation"]
    assert ad["trigger"] == "interview" and ad["proposal_plan_id"]
    assert any(planned in r and "mock-interview" in r and "+" in r for r in ad["reasons"]), ad["reasons"]

    [proposal] = await _proposals(client, auth)
    assert proposal["id"] == ad["proposal_plan_id"]
    full = (await client.get(f"/api/plans/{proposal['id']}", headers=auth)).json()
    after = sum(t["estimated_hours"] for w in full["weeks"] for t in w["tasks"] if t["skill_name"] == planned)
    assert after > before
    assert full["change_summary"]["triggered_by"] == "auto:interview"
    assert full["change_summary"]["hours_changes"][planned]["after"] > full["change_summary"]["hours_changes"][planned]["before"]
    assert planned in full["adjustment_reason"]
    assert (await client.get(f"/api/plans/{plan['id']}", headers=auth)).json()["status"] == "active"  # never auto-applied


async def test_bad_interview_lowers_owned_skill_and_recomputes_gap(client, auth):
    await setup_profile_and_jobs(client, auth)
    await client.put("/api/profile", headers=auth, json={
        "current_role": "Analyst", "target_role": "Machine Learning Engineer", "experience_level": "mid", "weekly_hours": 10,
        "skills": [{"name": "Python", "proficiency": 3}, {"name": "SQL", "proficiency": 3}]})
    first = await analyze(client, auth)
    assert next(i for i in first["items"] if i["skill_name"] == "SQL")["gap_level"] == "none"
    await generate_plan(client, auth)

    out = await _interview(client, auth, ["SQL"])
    ad = out["adaptation"]
    assert ad["gaps_recomputed"] is True
    assert [(u["skill_name"], u["before"], u["after"]) for u in ad["proficiency_updates"]] == [("SQL", 3, 2)]
    assert await _skill_level(client, auth, "SQL") == 2
    latest = (await client.get("/api/skill-gap", headers=auth)).json()[0]
    detail = (await client.get(f"/api/skill-gap/{latest['id']}", headers=auth)).json()
    assert next(i for i in detail["items"] if i["skill_name"] == "SQL")["gap_level"] == "partial"
    # SQL was not in the plan any more -> it is added back, with the evidence as the reason
    assert any(r.startswith("SQL:") and "added" in r for r in ad["reasons"]), ad["reasons"]
    # the change is visible in the progress history
    prog = (await client.get("/api/progress", headers=auth)).json()
    assert any(s["skill_name"] == "SQL" and s["change"] == -1 for s in prog["skills"])


async def test_skill_user_does_not_have_is_not_invented(client, auth):
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)
    plan = await generate_plan(client, auth)
    planned = plan["weeks"][0]["tasks"][0]["skill_name"]
    out = await _interview(client, auth, [planned])
    assert out["adaptation"]["proficiency_updates"] == []   # missing skills stay missing (not 'partial')
    skills = (await client.get("/api/profile", headers=auth)).json()["skills"]
    assert planned not in {s["name"] for s in skills}


async def test_mastered_skill_is_removed_from_proposal(client, auth):
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)
    plan = await generate_plan(client, auth)
    planned = plan["weeks"][0]["tasks"][0]["skill_name"]
    r = await client.post("/api/progress/assessments", headers=auth, json={"skill_name": planned, "proficiency": 5})
    assert r.status_code == 201, r.text
    ad = r.json()["adaptation"]
    assert ad["gaps_recomputed"] and ad["proposal_plan_id"]
    assert any(x.startswith(f"{planned}:") and "removed" in x for x in ad["reasons"]), ad["reasons"]
    full = (await client.get(f"/api/plans/{ad['proposal_plan_id']}", headers=auth)).json()
    assert planned in full["change_summary"]["dropped_skills"]
    assert planned not in {s for w in full["weeks"] for s in w["skills"]}


async def test_same_evidence_does_not_spam_proposals(client, auth):
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)
    plan = await generate_plan(client, auth)
    planned = plan["weeks"][0]["tasks"][0]["skill_name"]
    first = (await _interview(client, auth, [planned]))["adaptation"]["proposal_plan_id"]
    # an assessment of a skill no job asks for fires the loop again with identical signals -> proposal is reused
    again = (await client.post("/api/progress/assessments", headers=auth,
                               json={"skill_name": "Photoshop", "proficiency": 3})).json()["adaptation"]
    props = await _proposals(client, auth)
    assert [p["id"] for p in props] == [first] and again["proposal_plan_id"] == first


async def test_skipping_a_task_proposes_a_plan(client, auth):
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)
    plan = await generate_plan(client, auth)
    task = plan["weeks"][0]["tasks"][0]
    r = await client.patch(f"/api/plans/{plan['id']}/tasks/{task['id']}", headers=auth, json={"status": "skipped"})
    assert r.status_code == 200
    [proposal] = await _proposals(client, auth)
    full = (await client.get(f"/api/plans/{proposal['id']}", headers=auth)).json()
    assert full["change_summary"]["triggered_by"] == "auto:task"
    assert any(task["skill_name"] in r and "skipped" in r for r in full["change_summary"]["reasons"])


async def test_no_active_plan_is_harmless(client, auth):
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)
    out = await _interview(client, auth, ["Docker"])
    assert out["adaptation"]["proposal_plan_id"] is None
    assert "No active plan" in out["adaptation"]["message"]
