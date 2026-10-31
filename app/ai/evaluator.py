"""Interview Evaluator: scores an answer against a fixed 5-criterion rubric.

Consistency measures:
* fixed rubric text with anchored score bands, temperature 0,
* the overall score is computed here (mean of criteria), never taken from the LLM,
* when no LLM is available a transparent heuristic is used and labelled as such.
"""
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.ai.client import LLMClient, LLMError, wrap_untrusted
from app.ai.schemas import AnswerEvaluation, RubricScores

logger = logging.getLogger(__name__)

RUBRIC_PATH = Path(__file__).resolve().parents[2] / "data" / "rubric.json"
RUBRIC_DATA: dict = json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))
RUBRIC_VERSION: str = RUBRIC_DATA["version"]
CRITERIA: list[str] = [c["id"] for c in RUBRIC_DATA["criteria"]]
LEVELS: list[dict] = RUBRIC_DATA["levels"]
MAX_QUOTE_CHARS = 240


def level_of(score: float) -> int:
    """1-5 level of a 0-10 score, per the bands in data/rubric.json."""
    for lv in LEVELS:
        if score <= lv["max"] + 0.999:      # bands are integer ranges; fractional (averaged) scores belong to the lower band
            return lv["level"]
    return LEVELS[-1]["level"]


def _build_prompt() -> str:
    bands = ", ".join(f"level {lv['level']} = {lv['min']}-{lv['max']}" for lv in LEVELS)
    lines = [f"Score each criterion as an integer {RUBRIC_DATA['scale']['min']}-{RUBRIC_DATA['scale']['max']} using these "
             f"anchored levels ({bands}):"]
    for c in RUBRIC_DATA["criteria"]:
        lines.append(f"- {c['id']}: {c['question']}")
        lines += [f"    level {lv}: {text}" for lv, text in c["anchors"].items()]
    lines += RUBRIC_DATA["rules"]
    lines.append("Also return `evidence`: for each criterion, a SHORT quote (at most 200 characters) copied EXACTLY from "
                 "the candidate's answer that justifies the score. Omit a criterion if no sentence of the answer supports it. "
                 "Never invent or paraphrase a quote.")
    return "\n".join(lines)


RUBRIC = _build_prompt()


@dataclass
class QAInput:
    question: str
    answer: str
    category: str
    skill_name: str | None
    key_points: list[str]
    target_role: str
    experience_level: str | None


def overall(scores: RubricScores) -> float:
    return round(sum(getattr(scores, c) for c in CRITERIA) / len(CRITERIA), 1)


_STOP = set("the a an and or of to in on for with is are be by as at it this that how what why when your you "
            "would use from into their them they can do does which who".split())


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-zA-Z][a-zA-Z0-9+#.-]*", text.lower()) if w not in _STOP and len(w) > 2]


def heuristic_evaluate(qa: QAInput) -> AnswerEvaluation:
    """Keyword/structure heuristic. It cannot judge correctness; scores are capped and clearly labelled."""
    ans_words = _words(qa.answer)
    ans_set = set(ans_words)
    n = len(qa.answer.split())

    def coverage(text: str) -> float:
        ws = set(_words(text))
        return len(ws & ans_set) / len(ws) if ws else 0.0

    kp_cov = sum(coverage(k) for k in qa.key_points) / len(qa.key_points) if qa.key_points else 0.0
    q_cov = coverage(qa.question)
    length = min(1.0, n / 80)  # ~80+ words for a full answer
    structure = sum(1 for m in ["first", "then", "because", "trade-off", "tradeoff", "for example", "e.g", "however",
                                "finally", "result", "measure", "test"] if m in qa.answer.lower())
    sentences = max(1, len(re.findall(r"[.!?]", qa.answer)))

    def clamp(x: float) -> int:
        return max(0, min(8, round(x)))  # heuristic never awards 9-10

    if n < 5:
        scores = RubricScores(technical_correctness=0, conceptual_understanding=0, problem_solving=0, communication=1, relevance=0)
    else:
        scores = RubricScores(
            technical_correctness=clamp(1 + 7 * kp_cov * length + 1.5 * length),
            conceptual_understanding=clamp(1 + 6 * kp_cov * length + min(2, structure * 0.5)),
            problem_solving=clamp(1 + min(5, structure * 1.2) + 2 * length),
            communication=clamp(2 + 4 * length + (2 if 2 <= sentences <= 20 else 0) - (2 if n > 500 else 0)),
            relevance=clamp(1 + 5 * q_cov + 3 * kp_cov),
        )
    missing = [k for k in qa.key_points if coverage(k) < 0.34]
    covered = [k for k in qa.key_points if k not in missing]
    return AnswerEvaluation(
        scores=scores,
        strengths=([f"Covered: {k}" for k in covered[:3]] or (["Answer is well developed"] if length >= 1 else [])),
        improvements=[f"Address: {k}" for k in missing[:4]] + ([] if n >= 60 else ["Give a more complete answer with a concrete example"]),
        suggested_answer_improvements=(
            "Heuristic feedback (no AI evaluator configured; correctness was NOT verified). Structure your answer as: "
            "definition -> approach -> example -> trade-offs. Make sure to cover: " + "; ".join(qa.key_points)
        ),
        topics_to_revise=([qa.skill_name] if qa.skill_name and missing else []) + missing[:3],
        evidence=heuristic_evidence(qa),
    )


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
    return [re.sub(r"\s+", " ", p).strip() for p in parts if len(p.split()) >= 3]


def _quote(sentence: str) -> str:
    return sentence[:MAX_QUOTE_CHARS].rstrip()


def heuristic_evidence(qa: QAInput) -> dict[str, str]:
    """Pick, per criterion, the sentence of the answer that best supports the heuristic score (always a real quote)."""
    sents = _sentences(qa.answer)
    if len(qa.answer.split()) < 5 or not sents:
        return {}

    def overlap(sentence: str, text: str) -> float:
        ws = set(_words(text))
        return len(ws & set(_words(sentence))) / len(ws) if ws else 0.0

    def best(score) -> str | None:
        ranked = sorted(sents, key=score, reverse=True)
        return ranked[0] if ranked and score(ranked[0]) > 0 else None

    kp = " ".join(qa.key_points)
    why = ("because", "so that", "therefore", "which means", "in order to", "since ", "as a result")
    markers = ("first", "then", "trade-off", "tradeoff", "however", "finally", "measure", "test", "for example", "e.g")
    picks = {
        "technical_correctness": best(lambda x: overlap(x, kp)),
        "conceptual_understanding": best(lambda x: sum(m in x.lower() for m in why) + 0.1 * overlap(x, kp)),
        "problem_solving": best(lambda x: sum(m in x.lower() for m in markers)),
        "communication": sents[0],
        "relevance": best(lambda x: overlap(x, qa.question)),
    }
    return {c: _quote(v) for c, v in picks.items() if v and c in CRITERIA}


def ground_evidence(evidence: dict[str, str], answer: str) -> dict[str, str]:
    """Keep only quotes that really occur in the answer (whitespace/case-insensitive). Others are dropped."""
    norm = lambda t: re.sub(r"\s+", " ", t).strip().lower()  # noqa: E731
    haystack = norm(answer)
    kept = {}
    for criterion, quote in evidence.items():
        needle = norm(quote).strip(" .\"'\u201c\u201d\u2018\u2019\u2026")
        if criterion in CRITERIA and len(needle) >= 8 and needle in haystack:
            kept[criterion] = quote.strip()[:MAX_QUOTE_CHARS]
    return kept


async def evaluate_answer(llm: LLMClient, qa: QAInput) -> tuple[AnswerEvaluation, str]:
    """Returns (evaluation, evaluator_name)."""
    if llm.available and qa.answer.strip():
        system = f"You are a strict but fair interview evaluator.\n{RUBRIC}"
        user = json.dumps({
            "target_role": qa.target_role, "experience_level": qa.experience_level, "question_category": qa.category,
            "skill": qa.skill_name, "question": qa.question, "key_points_expected": qa.key_points,
        }) + "\n\nCandidate answer:\n" + wrap_untrusted("ANSWER", qa.answer)
        try:
            ev = await llm.generate_json(task="evaluate_answer", system=system, user=user,
                                         schema=AnswerEvaluation, temperature=0.0)
            ev.evidence = ground_evidence(ev.evidence, qa.answer)
            return ev, "llm"
        except LLMError as exc:
            logger.warning("LLM evaluation failed, using heuristic: %s", exc)
    return heuristic_evaluate(qa), "heuristic_fallback"
