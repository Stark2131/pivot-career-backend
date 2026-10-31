"""Reusable flows for tests."""
from tests.sample_data import JD_ML_ENGINEER, JD_ML_ENGINEER_2


async def setup_profile_and_jobs(client, auth, weekly_hours=10):
    r = await client.put("/api/profile", headers=auth, json={
        "current_role": "Data Analyst", "target_role": "Machine Learning Engineer", "experience_level": "mid",
        "weekly_hours": weekly_hours,
        "skills": [{"name": "Python", "proficiency": 4}, {"name": "SQL", "proficiency": 4},
                   {"name": "Pandas", "proficiency": 4}, {"name": "MySQL", "proficiency": 3},
                   {"name": "Git", "proficiency": 2}],
    })
    assert r.status_code == 200, r.text
    j1 = (await client.post("/api/jobs", headers=auth, json={"title": "ML Engineer", "company": "Nimbus AI", "text": JD_ML_ENGINEER})).json()
    j2 = (await client.post("/api/jobs", headers=auth, json={"title": "Junior ML Engineer", "company": "Orbit Labs", "text": JD_ML_ENGINEER_2})).json()
    return j1, j2


async def analyze(client, auth):
    r = await client.post("/api/skill-gap/analyze", headers=auth, json={})
    assert r.status_code == 201, r.text
    return r.json()


async def generate_plan(client, auth, **kw):
    r = await client.post("/api/plans/generate", headers=auth, json=kw)
    assert r.status_code == 201, r.text
    return r.json()
