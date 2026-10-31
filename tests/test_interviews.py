from app.ai.evaluator import QAInput, heuristic_evaluate
from tests.conftest import register_and_login
from tests.helpers import analyze, setup_profile_and_jobs

GOOD_ANSWER = (
    "Docker packages an application and its dependencies into an image, which runs as an isolated container. "
    "First I write a Dockerfile with a slim base image, then install dependencies, copy the code and set the "
    "entrypoint. For example, for a FastAPI model service I pin versions so builds are reproducible. "
    "The trade-off versus a VM is weaker isolation but much faster startup. I test the image in CI and measure size."
)


async def _start(client, auth, **kw):
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)
    r = await client.post("/api/interviews", headers=auth, json={"num_questions": 3, **kw})
    assert r.status_code == 201, r.text
    return r.json()


async def test_interview_flow_with_fallbacks(client, auth):
    iv = await _start(client, auth, interview_type="mixed")
    assert len(iv["questions"]) == 3 and iv["generated_by"] == "rule_based"
    assert any(q["category"] == "behavioral" for q in iv["questions"])
    assert all(q["key_points"] is None for q in iv["questions"])  # hidden before evaluation
    q1, q2 = iv["questions"][0], iv["questions"][1]

    r = await client.post(f"/api/interviews/{iv['id']}/answer", headers=auth,
                          json={"question_id": q1["id"], "answer_text": GOOD_ANSWER})
    assert r.status_code == 200
    await client.post(f"/api/interviews/{iv['id']}/answer", headers=auth,
                      json={"question_id": q2["id"], "answer_text": "no idea"})
    r = await client.post(f"/api/interviews/{iv['id']}/evaluate", headers=auth)
    assert r.status_code == 200, r.text
    out = r.json()
    evals = {q["id"]: q["evaluation"] for q in out["questions"]}
    assert evals[q1["id"]]["evaluator"] == "heuristic_fallback"
    assert evals[q1["id"]]["overall_score"] > evals[q2["id"]]["overall_score"]
    assert set(evals[q1["id"]]["scores"]) == {"technical_correctness", "conceptual_understanding",
                                               "problem_solving", "communication", "relevance"}
    assert out["status"] == "in_progress"  # one question still unanswered
    assert out["summary"]["criteria_averages"] and out["overall_score"] is not None
    assert next(q for q in out["questions"] if q["id"] == q1["id"])["key_points"]


async def test_llm_evaluation_overall_computed_server_side(client, auth, fake_llm):
    fake_llm.on("evaluate_answer", {
        "scores": {"technical_correctness": 8, "conceptual_understanding": 7, "problem_solving": 6,
                   "communication": 9, "relevance": 10},
        "strengths": ["Clear"], "improvements": ["Mention security"], "suggested_answer_improvements": "Add an example",
        "topics_to_revise": ["Docker security"]})
    fake_llm.on("interview_questions", {"questions": [
        {"question_text": "Explain Docker layers and caching.", "skill_name": "docker", "category": "technical",
         "key_points": ["layers", "cache"]}]})
    iv = await _start(client, auth, interview_type="technical")
    assert iv["generated_by"] == "llm"
    assert iv["questions"][0]["skill_name"] == "Docker"
    # Model returned 1 of 3 questions -> the rest is topped up from the question bank
    assert len(iv["questions"]) == 3
    for q in iv["questions"]:
        await client.post(f"/api/interviews/{iv['id']}/answer", headers=auth,
                          json={"question_id": q["id"], "answer_text": GOOD_ANSWER})
    out = (await client.post(f"/api/interviews/{iv['id']}/evaluate", headers=auth)).json()
    ev = out["questions"][0]["evaluation"]
    assert ev["overall_score"] == 8.0 and ev["evaluator"] == "llm"
    assert out["status"] == "completed" and out["overall_score"] == 8.0
    assert "Docker security" in out["summary"]["recommended_topics_to_revise"]


async def test_out_of_range_llm_scores_rejected(client, auth, fake_llm):
    fake_llm.on("evaluate_answer", {"scores": {"technical_correctness": 15, "conceptual_understanding": 7,
                                               "problem_solving": 6, "communication": 9, "relevance": 10}})
    iv = await _start(client, auth)
    q = iv["questions"][0]
    await client.post(f"/api/interviews/{iv['id']}/answer", headers=auth, json={"question_id": q["id"], "answer_text": GOOD_ANSWER})
    out = (await client.post(f"/api/interviews/{iv['id']}/evaluate", headers=auth)).json()
    assert out["questions"][0]["evaluation"]["evaluator"] == "heuristic_fallback"


async def test_reanswer_clears_evaluation_and_isolation(client, auth):
    iv = await _start(client, auth)
    q = iv["questions"][0]
    url = f"/api/interviews/{iv['id']}"
    await client.post(f"{url}/answer", headers=auth, json={"question_id": q["id"], "answer_text": GOOD_ANSWER})
    await client.post(f"{url}/evaluate", headers=auth)
    r = await client.post(f"{url}/answer", headers=auth, json={"question_id": q["id"], "answer_text": "Updated answer text"})
    assert r.json()["questions"][0]["evaluation"] is None
    other = await register_and_login(client, "trudy@example.com")
    assert (await client.get(url, headers=other)).status_code == 404
    assert (await client.post(f"{url}/answer", headers=other, json={"question_id": q["id"], "answer_text": "x"})).status_code == 404


async def test_evaluate_without_answers_conflicts(client, auth):
    iv = await _start(client, auth)
    assert (await client.post(f"/api/interviews/{iv['id']}/evaluate", headers=auth)).status_code == 409


def test_heuristic_never_awards_top_marks_and_penalises_empty():
    qa = QAInput("Explain Docker", GOOD_ANSWER * 3, "technical", "Docker", ["images", "containers"], "MLE", "mid")
    ev = heuristic_evaluate(qa)
    assert max(ev.scores.model_dump().values()) <= 8
    empty = heuristic_evaluate(QAInput("Explain Docker", "idk", "technical", "Docker", ["images"], "MLE", "mid"))
    assert sum(empty.scores.model_dump().values()) <= 2
