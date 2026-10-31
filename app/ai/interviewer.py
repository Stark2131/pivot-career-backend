"""Interviewer: generates role-relevant mock interview questions."""
import json
import logging
from dataclasses import dataclass

from app.ai.client import LLMClient, LLMError
from app.ai.schemas import GeneratedQuestion, QuestionSet
from app.utils.skills_taxonomy import category_of, normalize_skill

logger = logging.getLogger(__name__)


@dataclass
class InterviewContext:
    target_role: str
    experience_level: str | None
    interview_type: str  # technical | behavioral | mixed
    num_questions: int
    focus_skills: list[str]  # gap skills first, then a few known skills
    known_skills: list[str]


_TECH_TEMPLATES = {
    "default": [
        ("Explain the core concepts of {s} to a teammate who has never used it. When would you choose it and when not?",
         ["Accurate definition of {s}", "Main use cases", "Limitations or alternatives", "Concrete example"]),
        ("Walk me through how you would use {s} to solve a realistic problem in a {role} role.",
         ["Clear problem framing", "Step-by-step approach using {s}", "Trade-offs considered", "How results are validated"]),
        ("What are common mistakes or pitfalls when working with {s}, and how do you avoid them?",
         ["At least two real pitfalls", "Why they happen", "Prevention or debugging approach"]),
    ],
    "ml_ai": [
        ("How would you evaluate whether a {s} solution is good enough to ship? Which metrics and checks would you use?",
         ["Appropriate metrics", "Train/validation/test split or offline vs online evaluation", "Overfitting / data leakage", "Business impact"]),
    ],
    "database": [
        ("A query in {s} has become slow as data grew. How do you investigate and fix it?",
         ["Use EXPLAIN / query plan", "Indexes", "Query rewriting", "Measure before and after"]),
    ],
    "devops": [
        ("Describe how you would use {s} in a deployment pipeline for a small web service.",
         ["Concrete pipeline steps", "Configuration and secrets handling", "Rollback or failure handling"]),
    ],
    "cloud": [
        ("How would you deploy and secure a simple API on {s}? Which services would you use and why?",
         ["Appropriate managed services", "Networking / IAM basics", "Cost awareness", "Monitoring"]),
    ],
}
_BEHAVIORAL = [
    ("Tell me about a time you had to learn a new technology quickly to deliver something. What did you do?",
     ["Situation and task", "Specific learning actions", "Outcome with evidence", "Reflection"]),
    ("Why are you moving into a {role} role, and how does your previous experience help you?",
     ["Clear motivation", "Transferable skills with examples", "Awareness of gaps and plan"]),
    ("Describe a disagreement with a colleague or stakeholder about a technical decision. How was it resolved?",
     ["Context", "How they listened and communicated", "Resolution", "What they learned"]),
    ("Tell me about a project you're proud of. What was your specific contribution?",
     ["Concrete project", "Personal contribution (I, not we)", "Impact/metrics", "Challenges overcome"]),
]


def _difficulty(level: str | None) -> str:
    return {"entry": "easy", "junior": "easy", "senior": "hard", "lead": "hard"}.get(level or "", "medium")


def template_questions(ctx: InterviewContext) -> list[GeneratedQuestion]:
    n = ctx.num_questions
    n_beh = {"technical": 0, "behavioral": n}.get(ctx.interview_type, max(1, n // 3))
    n_tech = n - n_beh
    out: list[GeneratedQuestion] = []
    skills = [s for s in ctx.focus_skills if category_of(s) != "soft_skill"] or ["problem solving"]
    i = 0
    while len(out) < n_tech:
        s = skills[i % len(skills)]
        bank = _TECH_TEMPLATES.get(category_of(s), []) + _TECH_TEMPLATES["default"]
        q, kp = bank[(i // len(skills)) % len(bank)]
        out.append(GeneratedQuestion(question_text=q.format(s=s, role=ctx.target_role), skill_name=s,
                                     category="technical", difficulty=_difficulty(ctx.experience_level),
                                     key_points=[k.format(s=s) for k in kp]))
        i += 1
    for j in range(n_beh):
        q, kp = _BEHAVIORAL[j % len(_BEHAVIORAL)]
        out.append(GeneratedQuestion(question_text=q.format(role=ctx.target_role), skill_name="Communication",
                                     category="behavioral", difficulty="medium", key_points=kp))
    return out


async def generate_questions(llm: LLMClient, ctx: InterviewContext) -> tuple[list[GeneratedQuestion], str]:
    if llm.available:
        system = (
            "You are an experienced technical interviewer. Write interview questions for the target role, focusing on "
            "the listed focus skills (the candidate's weaker areas) and calibrated to the experience level. For each "
            "question provide 3-5 key_points a strong answer would cover. Return exactly the requested number of questions."
        )
        user = json.dumps({"target_role": ctx.target_role, "experience_level": ctx.experience_level,
                           "interview_type": ctx.interview_type, "num_questions": ctx.num_questions,
                           "focus_skills": ctx.focus_skills[:8], "known_skills": ctx.known_skills[:20]})
        try:
            result = await llm.generate_json(task="interview_questions", system=system, user=user,
                                             schema=QuestionSet, temperature=0.6)
            qs = []
            for q in result.questions[: ctx.num_questions]:
                norm = normalize_skill(q.skill_name) if q.skill_name else None
                qs.append(q.model_copy(update={"skill_name": norm.name if norm else None}))
            if ctx.interview_type == "technical":
                qs = [q for q in qs if q.category != "behavioral"] or qs
            if len(qs) >= max(1, ctx.num_questions // 2):
                # Top up with template questions if the model returned too few.
                if len(qs) < ctx.num_questions:
                    qs += template_questions(ctx)[len(qs): ctx.num_questions]
                return qs, "llm"
        except LLMError as exc:
            logger.warning("Question generation failed, using question bank: %s", exc)
    return template_questions(ctx), "rule_based"
