"""Seed the DEMO account: Maya, a maths teacher moving into data analysis. Everything here is fictional.

    python -m scripts.seed_demo            # create the demo user + all demo data
    python -m scripts.seed_demo --reset    # delete the demo user (and all their data) first, then recreate

It drives the real API in-process, so every number you see (match score, plan hours, interview scores, the
tracker's insights) is computed by the actual application logic. In order it:

    1. registers the demo user and uploads a resume (rule-based parsing, or your LLM if configured)
    2. confirms the profile: target role Data Analyst, a few skills with honest levels
    3. imports the 20 sample Data Analyst postings and runs the skill-gap analysis ("based on 20 job postings")
    4. generates the learning plan (started two weeks ago, some tasks done) and recommends projects
    5. records one past mock interview and one self-assessment
    6. adds 50 synthetic applications with built-in patterns, so the tracker has something to say
    7. clears any plan proposal the seeding itself triggered, so the live demo starts from a clean slate
"""
import argparse
import asyncio
from datetime import date, timedelta

import httpx
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.main import app
from app.models import User
from scripts.demo_data import DEMO_RESUME, DEMO_USER, make_pdf
from scripts.seed_applications import seed as seed_applications
from scripts.seed_jds import import_roles

# Honest starting levels for a teacher with a data-flavoured side hustle. SQL is deliberately weak: it is the
# skill the demo's "bad interview" will hit, and a weak-but-present skill is what makes the plan adapt.
LEVELS = {"Excel": 4, "Statistics": 3, "Communication": 4, "Leadership": 3, "Tableau": 2, "SQL": 2, "Problem Solving": 4}

PAST_ANSWER = (
    "Excel pivot tables let me summarise a large table by dropping fields into rows, columns and values. First I "
    "clean the data and check for blanks, then build the pivot, because a wrong header or a duplicate row changes "
    "every total. For example, I used one to compare homework completion by class and week. The trade-off versus "
    "a formula is speed against traceability, so I document the source range and check the totals with a test."
)


async def _reset() -> None:
    async with SessionLocal() as db:
        await db.execute(delete(User).where(User.email == DEMO_USER["email"]))
        await db.commit()


async def main(reset: bool) -> None:
    if reset:
        await _reset()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://seed", timeout=300) as c:
        r = await c.post("/api/auth/register", json=DEMO_USER)
        if r.status_code == 409:
            print("Demo user already exists. Re-run with --reset to recreate it.")
            return
        r.raise_for_status()
        token = (await c.post("/api/auth/login", json={k: DEMO_USER[k] for k in ("email", "password")})).json()["access_token"]
        h = {"Authorization": f"Bearer {token}"}

        # 1-2. resume -> reviewed profile
        (await c.post("/api/profile/resume", headers=h,
                      files={"file": ("maya_chen_resume.pdf", make_pdf(DEMO_RESUME), "application/pdf")})).raise_for_status()
        profile = (await c.get("/api/profile", headers=h)).json()
        skills = {s["name"]: LEVELS.get(s["name"], 3) for s in profile["skills"]} | {k: v for k, v in LEVELS.items()}
        (await c.put("/api/profile", headers=h, json={
            "current_role": "Mathematics Teacher", "target_role": "Data Analyst", "experience_level": "junior",
            "weekly_hours": 8, "skills": [{"name": n, "proficiency": lv} for n, lv in skills.items()]})).raise_for_status()

        # 3. real(istic) postings -> skill-gap map
        imported = (await import_roles(c, h, ["data_analyst"]))["data_analyst"]
        report = (await c.post("/api/skill-gap/analyze", headers=h, json={})).json()

        # 4. plan (two weeks in) + projects
        plan = (await c.post("/api/plans/generate", headers=h, json={
            "max_weeks": 12, "start_date": (date.today() - timedelta(weeks=2)).isoformat()})).json()
        tasks = [t for w in plan["weeks"] for t in w["tasks"]]
        for t in tasks[:3]:
            await c.patch(f"/api/plans/{plan['id']}/tasks/{t['id']}", headers=h,
                          json={"status": "completed", "difficulty_rating": 2, "notes": "DEMO"})
        projects = (await c.post("/api/projects/recommend", headers=h, json={"count": 3})).json()

        # 5. one past interview (a decent Excel answer) + a self-assessment
        iv = (await c.post("/api/interviews", headers=h, json={
            "num_questions": 2, "interview_type": "technical", "focus_skills": ["Excel"]})).json()
        for q in iv["questions"]:
            await c.post(f"/api/interviews/{iv['id']}/answer", headers=h, json={"question_id": q["id"], "answer_text": PAST_ANSWER})
        evaluated = (await c.post(f"/api/interviews/{iv['id']}/evaluate", headers=h)).json()
        await c.post("/api/progress/assessments", headers=h, json={"skill_name": "Tableau", "proficiency": 3, "notes": "DEMO: finished a course"})

        # 6. the tracker's history
        n_apps = await seed_applications(c, h, reset=False)

        # 7. start the live demo from a clean slate: no pending proposal left over from seeding
        for p in (await c.get("/api/plans?status=proposed", headers=h)).json():
            await c.post(f"/api/plans/{p['id']}/reject", headers=h)

        recs = (await c.get("/api/applications/recommendations", headers=h)).json()
        print("Demo data created (all fictional).")
        print(f"  login:        {DEMO_USER['email']} / {DEMO_USER['password']}")
        print(f"  skill gap:    {report['based_on']}; match score {report['match_score']}% (imported {imported['imported']} postings)")
        print(f"  plan:         {plan['total_weeks']} weeks, {len(tasks)} tasks, first 3 completed | projects: {len(projects)}")
        print(f"  interview:    {evaluated['overall_score']}/10 (heuristic scoring unless an LLM key is set)")
        print(f"  tracker:      {n_apps} applications; {len(recs['insights'])} insight(s), e.g. {recs['insights'][0]['text'] if recs['insights'] else 'none yet'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="delete and recreate the demo user")
    asyncio.run(main(parser.parse_args().reset))
