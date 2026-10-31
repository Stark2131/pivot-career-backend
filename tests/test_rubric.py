"""Rubric from data/rubric.json, 1-5 levels, and evidence quotes that are really in the answer."""
import re

from app.ai.evaluator import RUBRIC, QAInput, ground_evidence, heuristic_evaluate, level_of
from tests.helpers import analyze, setup_profile_and_jobs
from tests.test_interviews import GOOD_ANSWER

CRITERIA = ["technical_correctness", "conceptual_understanding", "problem_solving", "communication", "relevance"]


def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", t).strip().lower()


def qa(answer: str) -> QAInput:
    return QAInput(question="Explain how Docker images and containers work.", answer=answer, category="technical",
                   skill_name="Docker", key_points=["image layers", "isolated container", "Dockerfile"],
                   target_role="Machine Learning Engineer", experience_level="mid")


async def test_rubric_endpoint_describes_dimensions_levels_and_anchors(client, auth):
    r = await client.get("/api/interviews/rubric", headers=auth)
    assert r.status_code == 200, r.text
    rub = r.json()
    assert [c["id"] for c in rub["criteria"]] == CRITERIA
    assert [lv["level"] for lv in rub["levels"]] == [1, 2, 3, 4, 5]
    assert all(set(c["anchors"]) == {"1", "2", "3", "4", "5"} and all(c["anchors"].values()) for c in rub["criteria"])
    assert rub["scale"] == {"min": 0, "max": 10} and rub["rules"] and rub["notes"]
    assert (await client.get("/api/interviews/rubric")).status_code == 401           # needs auth like every other endpoint


def test_prompt_is_built_from_the_same_rubric_file():
    for lv in range(1, 6):
        assert f"level {lv}" in RUBRIC
    assert "technical_correctness" in RUBRIC and "copied EXACTLY" in RUBRIC


def test_level_bands():
    assert [level_of(s) for s in (0, 2, 3, 4, 5, 6, 7, 8, 9, 10)] == [1, 1, 2, 2, 3, 3, 4, 4, 5, 5]
    assert level_of(8.4) == 4 and level_of(9.0) == 5


def test_heuristic_evidence_is_always_a_real_quote_from_the_answer():
    ev = heuristic_evaluate(qa(GOOD_ANSWER))
    assert ev.evidence and set(ev.evidence) <= set(CRITERIA)
    for criterion, quote in ev.evidence.items():
        assert _norm(quote) in _norm(GOOD_ANSWER), (criterion, quote)
    assert max(ev.scores.model_dump().values()) <= 8                                  # heuristic never reaches level 5


def test_no_evidence_for_empty_or_tiny_answers():
    assert heuristic_evaluate(qa("no idea")).evidence == {}
    assert heuristic_evaluate(qa("")).evidence == {}


def test_fabricated_quotes_are_dropped():
    answer = "I would first profile the query, then add an index on the join column and measure again."
    kept = ground_evidence({
        "problem_solving": "first profile the query, then add an index",             # real (substring)
        "communication": "I used Redis Cluster with 12 shards for caching",           # invented
        "relevance": "profile the QUERY, then   add an index",                        # real, different case/whitespace
        "made_up_criterion": "profile the query",                                    # unknown criterion
        "technical_correctness": "x",                                                # too short to be evidence
    }, answer)
    assert set(kept) == {"problem_solving", "relevance"}


async def test_llm_evidence_is_grounded_and_levels_are_returned(client, auth, fake_llm):
    real = "First I write a Dockerfile with a slim base image"
    fake_llm.on("evaluate_answer", {
        "scores": {"technical_correctness": 8, "conceptual_understanding": 7, "problem_solving": 9, "communication": 4, "relevance": 10},
        "evidence": {"problem_solving": real, "communication": "I have ten years of Kubernetes experience", "relevance": "x"}})
    await setup_profile_and_jobs(client, auth)
    await analyze(client, auth)
    iv = (await client.post("/api/interviews", headers=auth, json={"num_questions": 1})).json()
    q = iv["questions"][0]
    await client.post(f"/api/interviews/{iv['id']}/answer", headers=auth, json={"question_id": q["id"], "answer_text": GOOD_ANSWER})
    out = (await client.post(f"/api/interviews/{iv['id']}/evaluate", headers=auth)).json()
    ev = out["questions"][0]["evaluation"]
    assert ev["evaluator"] == "llm" and ev["rubric_version"] == "v2"
    assert ev["evidence"] == {"problem_solving": real}                                # invented / too-short quotes removed
    assert ev["levels"] == {"technical_correctness": 4, "conceptual_understanding": 4, "problem_solving": 5,
                            "communication": 2, "relevance": 5}
    again = (await client.get(f"/api/interviews/{iv['id']}", headers=auth)).json()
    assert again["questions"][0]["evaluation"]["evidence"] == {"problem_solving": real}   # persisted
