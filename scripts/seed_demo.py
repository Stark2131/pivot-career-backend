"""Seed a DEMO account by driving the real API in-process (same validation & logic as production).

    python -m scripts.seed_demo            # uses DATABASE_URL / LLM settings from .env
    python -m scripts.seed_demo --reset    # delete the demo user first

Everything created is fictional and labelled DEMO.
"""
import argparse
import asyncio
from datetime import date, timedelta

import httpx
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.main import app
from app.models import User
from scripts.demo_data import DEMO_APPLICATIONS, DEMO_JOBS, DEMO_RESUME, DEMO_USER, make_pdf


async def _reset() -> None:
    async with SessionLocal() as db:
        await db.execute(delete(User).where(User.email == DEMO_USER["email"]))
        await db.commit()


async def main(reset: bool) -> None:
    if reset:
        await _reset()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://seed", timeout=120) as c:
        r = await c.post("/api/auth/register", json=DEMO_USER)
        if r.status_code == 409:
            print("Demo user already exists. Re-run with --reset to recreate it.")
            return
        r.raise_for_status()
        token = (await c.post("/api/auth/login", json={k: DEMO_USER[k] for k in ("email", "password")})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        (await c.post("/api/profile/resume", headers=h,
                      files={"file": ("demo_resume.pdf", make_pdf(DEMO_RESUME), "application/pdf")})).raise_for_status()
        profile = (await c.get("/api/profile", headers=h)).json()
        levels = {"Python": 4, "SQL": 4, "Pandas": 4, "Tableau": 4, "Excel": 4, "Statistics": 3, "Git": 2}
        skills = [{"name": s["name"], "proficiency": levels.get(s["name"], 3)} for s in profile["skills"]]
        (await c.put("/api/profile", headers=h, json={
            "target_role": "Machine Learning Engineer", "experience_level": "mid", "weekly_hours": 8,
            "skills": skills})).raise_for_status()

        job_ids = []
        for job in DEMO_JOBS:
            r = await c.post("/api/jobs", headers=h, json=job)
            r.raise_for_status()
            job_ids.append(r.json()["id"])

        report = (await c.post("/api/skill-gap/analyze", headers=h, json={})).json()
        plan = (await c.post("/api/plans/generate", headers=h, json={
            "max_weeks": 12, "start_date": (date.today() - timedelta(weeks=2)).isoformat()})).json()
        tasks = [t for w in plan["weeks"] for t in w["tasks"]]
        if tasks:
            await c.patch(f"/api/plans/{plan['id']}/tasks/{tasks[0]['id']}", headers=h,
                          json={"status": "completed", "difficulty_rating": 2, "notes": "DEMO"})
        if len(tasks) > 1:
            await c.patch(f"/api/plans/{plan['id']}/tasks/{tasks[1]['id']}", headers=h,
                          json={"status": "in_progress", "difficulty_rating": 4, "notes": "DEMO: finding this hard"})
        await c.post("/api/projects/recommend", headers=h, json={"count": 3})

        iv = (await c.post("/api/interviews", headers=h, json={"num_questions": 3, "interview_type": "mixed"})).json()
        sample_answers = [
            "Docker packages an app and its dependencies into an image that runs as a container. First I write a "
            "Dockerfile, pin dependency versions, then build and test the image in CI. The trade-off versus VMs is "
            "weaker isolation but much faster startup. (DEMO answer)",
            "I would start by checking the data, then train a baseline model and compare metrics. (DEMO answer)",
        ]
        for q, a in zip(iv["questions"], sample_answers):
            await c.post(f"/api/interviews/{iv['id']}/answer", headers=h, json={"question_id": q["id"], "answer_text": a})
        await c.post(f"/api/interviews/{iv['id']}/evaluate", headers=h)

        await c.post("/api/progress/assessments", headers=h, json={"skill_name": "Docker", "proficiency": 2, "notes": "DEMO"})

        for company, role, status, reached, level, skills_h, days in DEMO_APPLICATIONS:
            r = await c.post("/api/applications", headers=h, json={
                "company_name": company, "role_title": role, "applied_date": (date.today() - timedelta(days=days)).isoformat(),
                "status": status, "experience_level": level, "skills_highlighted": skills_h,
                "notes": "DEMO DATA - fictional application"})
            r.raise_for_status()
            if reached and status == "rejected":
                await c.patch(f"/api/applications/{r.json()['id']}", headers=h, json={
                    "reached_interview": True, "interview_feedback": "DEMO: wanted more production ML experience"})

        print("Demo data created (fictional).")
        print(f"  login: {DEMO_USER['email']} / {DEMO_USER['password']}")
        print(f"  skill-gap match score: {report['match_score']}%  |  plan weeks: {plan['total_weeks']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="delete and recreate the demo user")
    asyncio.run(main(parser.parse_args().reset))
