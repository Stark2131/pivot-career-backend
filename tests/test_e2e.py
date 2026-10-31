"""End-to-end: the complete user journey through the public API, with a mocked LLM."""
import json

from tests.conftest import make_pdf
from tests.sample_data import JD_ML_ENGINEER, JD_ML_ENGINEER_2, RESUME_TEXT


def _plan_handler(prompt: str):
    sched = json.loads(prompt)["schedule"]
    return {"summary": "Focus on deployment skills first.", "weeks": [
        {"week_number": w["week_number"], "tasks": [
            {"skill_name": t["skill_name"], "title": f"{t['skill_name']} essentials", "topics": ["Core concepts"],
             "activities": ["Official docs"], "exercises": ["Build a mini project"], "expected_outcome": "Working knowledge"}
            for t in w["tasks"]]} for w in sched]}


async def test_full_user_journey(client, fake_llm):
    # LLM behaviour for the AI steps (resume/JD extraction use the rule-based fallback here,
    # proving the mixed mode works too).
    fake_llm.on("plan_content", _plan_handler)
    fake_llm.on("evaluate_answer", {
        "scores": {"technical_correctness": 6, "conceptual_understanding": 6, "problem_solving": 5,
                   "communication": 7, "relevance": 8},
        "strengths": ["Relevant example"], "improvements": ["Discuss trade-offs"],
        "suggested_answer_improvements": "Explain why", "topics_to_revise": ["Docker networking"]})

    # 1. Register + login
    r = await client.post("/api/auth/register", json={"email": "journey@example.com", "password": "Journey123"})
    assert r.status_code == 201
    token = (await client.post("/api/auth/login", json={"email": "journey@example.com", "password": "Journey123"})).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    # 2. Upload resume, review extracted data, set target role
    r = await client.post("/api/profile/resume", headers=h, files={"file": ("cv.pdf", make_pdf(RESUME_TEXT), "application/pdf")})
    assert r.status_code == 201
    profile = (await client.get("/api/profile", headers=h)).json()
    assert profile["needs_review"]
    reviewed = [{"name": s["name"], "proficiency": 3} for s in profile["skills"]]
    r = await client.put("/api/profile", headers=h, json={"target_role": "Machine Learning Engineer",
                                                           "experience_level": "mid", "weekly_hours": 8, "skills": reviewed})
    assert r.json()["needs_review"] is False

    # 3. Add two job descriptions
    for title, text in (("ML Engineer", JD_ML_ENGINEER), ("Junior ML Engineer", JD_ML_ENGINEER_2)):
        assert (await client.post("/api/jobs", headers=h, json={"title": title, "text": text})).status_code == 201

    # 4. Skill-gap analysis
    report = (await client.post("/api/skill-gap/analyze", headers=h, json={})).json()
    gaps = [i["skill_name"] for i in report["items"] if i["gap_level"] != "none"]
    assert "Docker" in gaps and "Python" not in gaps

    # 5. Learning plan, complete a task
    plan = (await client.post("/api/plans/generate", headers=h, json={"max_weeks": 12})).json()
    assert plan["generated_by"] == "llm" and plan["status"] == "active"
    assert all(w["total_hours"] <= 8 for w in plan["weeks"])
    task = plan["weeks"][0]["tasks"][0]
    r = await client.patch(f"/api/plans/{plan['id']}/tasks/{task['id']}", headers=h, json={"status": "completed"})
    assert r.json()["status"] == "completed"

    # 6. Portfolio projects
    projects = (await client.post("/api/projects/recommend", headers=h, json={"count": 2})).json()
    assert projects and set(projects[0]["skills_covered"]) & set(gaps)

    # 7. Mock interview: answer + evaluate
    iv = (await client.post("/api/interviews", headers=h, json={"num_questions": 2, "interview_type": "technical"})).json()
    for q in iv["questions"]:
        await client.post(f"/api/interviews/{iv['id']}/answer", headers=h,
                          json={"question_id": q["id"], "answer_text": "I would containerise the service with Docker ..."})
    iv = (await client.post(f"/api/interviews/{iv['id']}/evaluate", headers=h)).json()
    assert iv["status"] == "completed" and iv["overall_score"] == 6.4

    # 8. Progress + assessment + adaptive (proposed) plan
    await client.post("/api/progress/assessments", headers=h, json={"skill_name": "Docker", "proficiency": 2})
    progress = (await client.get("/api/progress", headers=h)).json()
    assert progress["plan"]["completed"] == 1 and progress["interviews"]["average_score"] == 6.4
    rec = (await client.post("/api/progress/recalculate-plan", headers=h, json={"reason": "Weekly review"})).json()
    proposal = rec["proposed_plan"]
    assert proposal["status"] == "proposed"
    assert (await client.post(f"/api/plans/{proposal['id']}/accept", headers=h)).json()["status"] == "active"
    versions = {p["version"]: p["status"] for p in (await client.get("/api/plans", headers=h)).json()}
    assert versions == {1: "archived", 2: "active"}

    # 9. Applications + analytics
    jobs = (await client.get("/api/jobs", headers=h)).json()
    app = (await client.post("/api/applications", headers=h, json={
        "company_name": "Nimbus AI", "role_title": "ML Engineer", "applied_date": "2026-10-15",
        "job_description_id": jobs[0]["id"]})).json()
    await client.patch(f"/api/applications/{app['id']}", headers=h, json={"status": "interview"})
    analytics = (await client.get("/api/applications/analytics?include_ai_summary=false", headers=h)).json()
    assert analytics["stats"]["conversion"]["application_to_interview"]["response_rate"] == 1.0
    assert analytics["stats"]["data_sufficiency"]["sufficient"] is False
