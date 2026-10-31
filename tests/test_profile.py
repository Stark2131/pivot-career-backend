from tests.conftest import make_pdf
from tests.sample_data import RESUME_TEXT


async def upload(client, auth, data=None, name="resume.pdf", ctype="application/pdf"):
    data = data if data is not None else make_pdf(RESUME_TEXT)
    return await client.post("/api/profile/resume", headers=auth, files={"file": (name, data, ctype)})


async def test_resume_upload_rule_based_fallback(client, auth):
    r = await upload(client, auth)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["generated_by"] == "rule_based"
    names = {s["name"] for s in body["parsed_data"]["technical_skills"]}
    assert {"SQL", "Python", "Pandas", "Tableau", "PostgreSQL", "scikit-learn"} <= names
    assert body["parsed_data"]["years_experience"] == 4

    profile = (await client.get("/api/profile", headers=auth)).json()
    assert profile["needs_review"] is True  # resume skills are unconfirmed until reviewed
    assert "Communication" in profile["soft_skills"]
    assert profile["education"]


async def test_resume_upload_with_llm_drops_hallucinated_skills(client, auth, fake_llm):
    fake_llm.on("resume_parse", {
        "current_role": "Data Analyst",
        "years_experience": 4,
        "technical_skills": [
            {"name": "python", "evidence": "Automated weekly reports with Python"},
            {"name": "Kubernetes", "evidence": "invented"},  # NOT in resume -> must be dropped
        ],
        "soft_skills": ["communication", "leadership"],  # leadership not in resume -> dropped
        "work_experience": [{"title": "Data Analyst", "company": "Acme Retail", "highlights": []}],
    })
    r = await upload(client, auth)
    assert r.status_code == 201
    body = r.json()
    assert body["generated_by"] == "llm"
    names = {s["name"] for s in body["parsed_data"]["technical_skills"]}
    assert "Python" in names and "Kubernetes" not in names
    assert any("Kubernetes" in w for w in body["validation_warnings"])
    assert body["parsed_data"]["soft_skills"] == ["Communication"]


async def test_invalid_llm_json_falls_back(client, auth, fake_llm):
    fake_llm.on("resume_parse", "this is not json")
    r = await upload(client, auth)
    assert r.status_code == 201
    assert r.json()["generated_by"] == "rule_based"
    assert fake_llm.calls.count("resume_parse") == 2  # one corrective retry


async def test_upload_rejects_non_pdf_and_large_files(client, auth):
    r = await upload(client, auth, data=b"hello world" * 10, name="resume.pdf")
    assert r.status_code == 422
    r = await upload(client, auth, data=b"%PDF-" + b"0" * (6 * 1024 * 1024))
    assert r.status_code == 422
    r = await upload(client, auth, name="resume.exe", ctype="application/octet-stream")
    assert r.status_code == 422


async def test_user_reviews_and_corrects_profile(client, auth):
    await upload(client, auth)
    r = await client.put("/api/profile", headers=auth, json={
        "target_role": "Machine Learning Engineer",
        "experience_level": "mid",
        "weekly_hours": 10,
        "skills": [{"name": "python", "proficiency": 4}, {"name": "SQL", "proficiency": 4}, {"name": "Pandas"}],
    })
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["target_role"] == "Machine Learning Engineer"
    assert p["needs_review"] is False
    assert {s["name"] for s in p["skills"]} == {"Python", "SQL", "Pandas"}
    assert next(s for s in p["skills"] if s["name"] == "Python")["proficiency"] == 4


async def test_profile_validation(client, auth):
    r = await client.put("/api/profile", headers=auth, json={"weekly_hours": 500})
    assert r.status_code == 422
    r = await client.put("/api/profile", headers=auth, json={"experience_level": "wizard"})
    assert r.status_code == 422
