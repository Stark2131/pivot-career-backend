"""Curated resources (no invented links) and template-backed, gap-ranked project recommendations."""
import json
import re

from app.ai import resources
from app.ai.project_recommender import TEMPLATES, ProjectContext, rank_templates
from app.utils.skills_taxonomy import _T
from tests.helpers import analyze, generate_plan, setup_profile_and_jobs


# --- data files ------------------------------------------------------------------------------------
def test_resources_file_is_well_formed():
    data = json.loads(resources.RESOURCES_PATH.read_text(encoding="utf-8"))
    assert len(data["skills"]) >= 80 and data["verified_on"]
    ids = set()
    for skill, items in data["skills"].items():
        assert skill in _T, skill                                     # keyed by canonical taxonomy names
        assert 1 <= len(items) <= 3
        for r in items:
            assert re.fullmatch(r"https://[^\s]+", r["url"]) and r["title"] and r["type"] in {
                "docs", "course", "interactive", "book", "video", "article"}, r
            assert r["id"] not in ids
            ids.add(r["id"])


def test_templates_are_tagged_with_real_taxonomy_skills():
    assert 28 <= len(TEMPLATES) <= 40
    for t in TEMPLATES:
        assert t["skills"] and all(s in _T for s in t["skills"]), t["id"]
        assert t["difficulty"] in {"beginner", "intermediate", "advanced"} and t["estimated_hours"] > 0
        assert t["core_features"] and t["deliverables"] and t["role_families"]


def test_model_can_only_choose_listed_resources():
    sql_ids = [r["id"] for r in resources.resources_for("SQL")]
    docker_id = resources.resources_for("Docker")[0]["id"]
    picked = resources.choose("SQL", [sql_ids[1], "made-up-1", docker_id, sql_ids[1], sql_ids[0]])
    assert [r["id"] for r in picked] == [sql_ids[1], sql_ids[0]]       # unknown, other-skill and duplicate ids dropped
    assert resources.choose("SQL", ["https://evil.example.com/x"]) == []


def test_unknown_skills_get_a_labelled_search_link_not_an_invented_course():
    r = resources.default_for_part("Underwater Basket Weaving", 1, 1)
    assert len(r) == 1 and r[0]["type"] == "search" and r[0]["url"].startswith("https://www.google.com/search?q=")
    multi = resources.default_for_part("SQL", 2, 3)
    assert len(multi) == 1 and multi[0]["id"] == resources.resources_for("SQL")[1]["id"]    # multi-week skills rotate


# --- plans ------------------------------------------------------------------------------------------
async def test_every_plan_task_carries_curated_links(client, auth):
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)
    plan = await generate_plan(client, auth)
    known_urls = {r["url"] for items in json.loads(resources.RESOURCES_PATH.read_text(encoding="utf-8"))["skills"].values() for r in items}
    tasks = [t for w in plan["weeks"] for t in w["tasks"]]
    assert tasks and all(t["resources"] for t in tasks)
    for t in tasks:
        for r in t["resources"]:
            assert r["url"] in known_urls or r["type"] == "search", r


async def test_llm_cannot_inject_links_into_a_plan(client, auth, fake_llm):
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)

    def plan_content(prompt: str):
        sched = json.loads(prompt)["schedule"]
        weeks = []
        for w in sched:
            tasks = []
            for t in w["tasks"]:
                avail = [r["id"] for r in t["available_resources"]]
                tasks.append({"skill_name": t["skill_name"], "title": "t", "topics": ["a"], "activities": ["see https://evil.example.com"],
                              "exercises": ["e"], "expected_outcome": "o",
                              "resource_ids": ["https://evil.example.com/pwn", "fake-id-9"] + avail[-1:]})
            weeks.append({"week_number": w["week_number"], "tasks": tasks})
        return {"summary": "s", "weeks": weeks}

    fake_llm.on("plan_content", plan_content)
    plan = await generate_plan(client, auth)
    assert plan["generated_by"] == "llm"
    for t in (t for w in plan["weeks"] for t in w["tasks"]):
        assert t["resources"] and all(r["url"] != "https://evil.example.com/pwn" for r in t["resources"])
        if resources.has_curated(t["skill_name"]):
            assert [r["id"] for r in t["resources"]] == [resources.resources_for(t["skill_name"])[-1]["id"]]   # the valid pick won


# --- projects ---------------------------------------------------------------------------------------
def ctx(gaps, **kw):
    return ProjectContext(target_role="Machine Learning Engineer", experience_level="mid", gap_skills=gaps,
                          known_skills=["Python"], responsibilities=[], role_family="ml_engineer", **kw)


def test_ranking_prefers_templates_covering_the_top_gaps():
    picks = rank_templates(ctx(["Docker", "Kubernetes", "CI/CD", "MLOps", "Model Deployment", "Terraform"]), 3)
    first, covered = picks[0]
    assert len(covered) >= 3 and "Docker" in covered                        # the k8s/model-serving project wins
    assert all(set(t["skills"]) & {"Docker", "Kubernetes", "CI/CD", "MLOps", "Model Deployment", "Terraform"} for t, _ in picks)
    assert len({t["id"] for t, _ in picks}) == 3


def test_ranking_is_varied_and_never_offers_irrelevant_templates():
    picks = rank_templates(ctx(["Docker", "Kubernetes"]), 5)
    assert all(set(t["skills"]) & {"Docker", "Kubernetes"} for t, _ in picks)
    assert rank_templates(ctx(["Underwater Basket Weaving"]), 3) == []


def test_top_gap_outweighs_several_minor_gaps():
    picks = rank_templates(ctx(["Terraform", "Embeddings", "RAG", "LLMs", "REST APIs"]), 1)
    assert "Terraform" in picks[0][1] or {"Embeddings", "RAG", "LLMs"} <= set(picks[0][1])


async def test_recommendations_are_template_backed_and_ranked(client, auth):
    await setup_profile_and_jobs(client, auth)
    report = await analyze(client, auth)
    gaps = [i["skill_name"] for i in sorted(report["items"], key=lambda i: i["priority_rank"]) if i["gap_level"] != "none"]
    projects = (await client.post("/api/projects/recommend", headers=auth, json={"count": 3})).json()
    ids = {t["id"] for t in TEMPLATES}
    assert len(projects) == 3
    for p in projects:
        assert p["template_id"] in ids and p["gaps_covered"] and set(p["gaps_covered"]) <= set(gaps)
        assert set(p["gaps_covered"]) <= set(p["skills_covered"])
    # best coverage of the top gaps first
    first_rank = min(gaps.index(g) for g in projects[0]["gaps_covered"])
    assert first_rank <= 2


async def test_llm_can_reword_a_project_but_not_change_what_it_covers(client, auth, fake_llm):
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)

    def reword(prompt: str):
        sent = json.loads(prompt)["templates"]
        out = [{"template_id": t["template_id"], "title": f"Tailored: {t['title']}", "problem_statement": "Tailored problem",
                "description": "Tailored description for the role", "core_features": [], "deliverables": [],
                "skills": ["Python"], "tech_stack": ["Hacking"], "difficulty": "advanced", "estimated_hours": 1} for t in sent]
        out.append({"template_id": "not-a-template", "title": "x", "problem_statement": "x", "description": "x"})
        return {"projects": out}

    fake_llm.on("project_personalise", reword)
    projects = (await client.post("/api/projects/recommend", headers=auth, json={"count": 2})).json()
    assert len(projects) == 2 and all(p["generated_by"] == "llm" for p in projects)
    by_id = {t["id"]: t for t in TEMPLATES}
    for p in projects:
        t = by_id[p["template_id"]]
        assert p["title"].startswith("Tailored:") and p["description"] == "Tailored description for the role"
        assert p["skills_covered"] == t["skills"] and p["difficulty"] == t["difficulty"]      # AI cannot change these
        assert p["estimated_hours"] == t["estimated_hours"] and "Hacking" not in p["tech_stack"]
        assert p["core_features"] == t["core_features"]                                       # empty list -> template kept


async def test_llm_failure_or_garbage_falls_back_to_template_wording(client, auth, fake_llm):
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)
    fake_llm.on("project_personalise", "this is not json")
    projects = (await client.post("/api/projects/recommend", headers=auth, json={"count": 2})).json()
    assert len(projects) == 2 and all(p["generated_by"] == "rule_based" for p in projects)
    assert all(p["title"] == next(t for t in TEMPLATES if t["id"] == p["template_id"])["title"] for p in projects)


async def test_gaps_without_a_template_get_a_generic_project(client, auth):
    await client.put("/api/profile", headers=auth, json={"target_role": "Machine Learning Engineer", "experience_level": "mid",
                                                          "weekly_hours": 8, "skills": [{"name": "Python", "proficiency": 3}]})
    await client.post("/api/jobs", headers=auth, json={"title": "Machine Learning Engineer (niche)",
                                                       "required_skills": ["Quantum Foam Engineering", "Basket Theory"]})
    assert (await client.post("/api/skill-gap/analyze", headers=auth, json={})).status_code == 201
    projects = (await client.post("/api/projects/recommend", headers=auth, json={"count": 2})).json()
    assert len(projects) == 1 and projects[0]["template_id"] is None
    assert set(projects[0]["skills_covered"]) == {"Quantum Foam Engineering", "Basket Theory"}
