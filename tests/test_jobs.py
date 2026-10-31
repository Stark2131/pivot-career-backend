import pytest

from app.core.errors import ValidationFailed
from app.utils.url_fetch import fetch_job_text, html_to_text
from tests.conftest import register_and_login
from tests.sample_data import JD_ML_ENGINEER


async def test_create_job_rule_based(client, auth):
    r = await client.post("/api/jobs", headers=auth, json={"title": "ML Engineer", "company": "Nimbus", "text": JD_ML_ENGINEER})
    assert r.status_code == 201, r.text
    job = r.json()
    reqs = {x["skill_name"]: x["requirement_type"] for x in job["requirements"]}
    assert reqs["Python"] == "required"
    assert reqs["Docker"] == "required"
    assert reqs["PyTorch"] == "preferred"
    assert reqs["Kubernetes"] == "preferred"
    assert job["structured_data"]["experience_years_min"] == 3
    assert job["structured_data"]["responsibilities"]
    assert job["structured_data"]["education_requirements"]
    assert job["source_type"] == "pasted" and job["extracted_at"]


async def test_create_job_with_llm_normalises_and_grounds(client, auth, fake_llm):
    fake_llm.on("jd_extract", {
        "required_skills": [{"name": "python3", "evidence": "Python"}, {"name": "k8s"},
                            {"name": "Rust", "evidence": "made up"}],
        "preferred_skills": [{"name": "Python"}, {"name": "pytorch"}],
        "responsibilities": ["Build models"],
        "experience_years_min": 3,
    })
    r = await client.post("/api/jobs", headers=auth, json={"title": "MLE", "text": JD_ML_ENGINEER})
    job = r.json()
    reqs = {x["skill_name"]: x["requirement_type"] for x in job["requirements"]}
    assert reqs == {"Python": "required", "Kubernetes": "required", "PyTorch": "preferred"}
    assert any("Rust" in w for w in job["extraction_warnings"])
    assert job["generated_by"] == "llm"


async def test_manual_job_entry_and_crud(client, auth):
    r = await client.post("/api/jobs", headers=auth, json={"title": "Data Engineer", "required_skills": ["Airflow", "SQL"]})
    assert r.status_code == 201
    job_id = r.json()["id"]
    assert {x["skill_name"] for x in r.json()["requirements"]} == {"Apache Airflow", "SQL"}
    lst = (await client.get("/api/jobs", headers=auth)).json()
    assert lst[0]["required_count"] == 2
    assert (await client.delete(f"/api/jobs/{job_id}", headers=auth)).status_code == 204
    assert (await client.get(f"/api/jobs/{job_id}", headers=auth)).status_code == 404


async def test_job_requires_input(client, auth):
    r = await client.post("/api/jobs", headers=auth, json={"title": "Empty"})
    assert r.status_code == 422


async def test_jobs_are_isolated_between_users(client, auth):
    r = await client.post("/api/jobs", headers=auth, json={"title": "ML Engineer", "text": JD_ML_ENGINEER})
    job_id = r.json()["id"]
    other = await register_and_login(client, "mallory@example.com")
    assert (await client.get(f"/api/jobs/{job_id}", headers=other)).status_code == 404
    assert (await client.delete(f"/api/jobs/{job_id}", headers=other)).status_code == 404
    assert (await client.get("/api/jobs", headers=other)).json() == []


async def test_url_fetch_blocks_private_addresses():
    with pytest.raises(ValidationFailed):
        await fetch_job_text("http://127.0.0.1/admin")
    with pytest.raises(ValidationFailed):
        await fetch_job_text("file:///etc/passwd")


def test_html_to_text_strips_scripts():
    text = html_to_text("<html><head><title>x</title></head><body><script>evil()</script><p>Python</p><li>SQL</li></body></html>")
    assert "evil" not in text and "Python" in text and "SQL" in text
