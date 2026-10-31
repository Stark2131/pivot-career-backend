"""Transparent application statistics (no ML, no causal claims).

* "Response" = the application reached the interview stage (status interview/offer,
  or rejected after an interview).
* Every rate comes with its sample size and a 95% Wilson confidence interval.
* Groups smaller than MIN_GROUP_SIZE are reported but flagged as insufficient.
"""
import math
from dataclasses import dataclass
from itertools import combinations

MIN_TOTAL_FOR_PATTERNS = 10
MIN_GROUP_SIZE = 5
DISCLAIMER = ("These are descriptive correlations from your own applications only. They do not show cause and effect: "
              "timing, company, referrals and many other factors also influence responses.")


@dataclass
class AppFact:
    role_title: str
    status: str
    reached_interview: bool
    experience_level: str | None
    skills: list[str]


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - margin), 3), round(min(1.0, centre + margin), 3)


def _rate(k: int, n: int) -> dict:
    return {"n": n, "responses": k, "response_rate": round(k / n, 3) if n else None,
            "ci95": wilson(k, n), "sufficient_data": n >= MIN_GROUP_SIZE}


def _norm_role(title: str) -> str:
    return " ".join(title.lower().replace("-", " ").split())


def compute_analytics(apps: list[AppFact]) -> dict:
    n = len(apps)
    by_status: dict[str, int] = {}
    for a in apps:
        by_status[a.status] = by_status.get(a.status, 0) + 1
    responses = sum(a.reached_interview for a in apps)
    offers = by_status.get("offer", 0)

    def group(key) -> dict:
        groups: dict[str, list[AppFact]] = {}
        for a in apps:
            groups.setdefault(key(a) or "unspecified", []).append(a)
        return dict(sorted(((g, _rate(sum(x.reached_interview for x in v), len(v))) for g, v in groups.items()),
                           key=lambda kv: -kv[1]["n"]))

    # Skill comparisons: response rate with vs without a skill; only when both sides are big enough.
    skill_rows = []
    all_skills = sorted({s for a in apps for s in a.skills})
    for s in all_skills:
        with_s = [a for a in apps if s in a.skills]
        without = [a for a in apps if s not in a.skills]
        if len(with_s) >= MIN_GROUP_SIZE and len(without) >= MIN_GROUP_SIZE:
            r_with = sum(a.reached_interview for a in with_s) / len(with_s)
            r_without = sum(a.reached_interview for a in without) / len(without)
            skill_rows.append({"skill": s, "with": _rate(sum(a.reached_interview for a in with_s), len(with_s)),
                               "without": _rate(sum(a.reached_interview for a in without), len(without)),
                               "difference": round(r_with - r_without, 3)})
    skill_rows.sort(key=lambda r: -r["difference"])

    combo_rows = []
    for pair in combinations(all_skills, 2):
        subset = [a for a in apps if pair[0] in a.skills and pair[1] in a.skills]
        if len(subset) >= MIN_GROUP_SIZE:
            combo_rows.append({"skills": list(pair), **_rate(sum(a.reached_interview for a in subset), len(subset))})
    combo_rows.sort(key=lambda r: -(r["response_rate"] or 0))

    sufficient = n >= MIN_TOTAL_FOR_PATTERNS
    if n == 0:
        message = "No applications recorded yet."
    elif not sufficient:
        message = (f"Only {n} application(s) recorded. At least {MIN_TOTAL_FOR_PATTERNS} are needed before patterns "
                   "are meaningful; treat all breakdowns below as anecdotal.")
    else:
        message = f"{n} applications recorded. Groups with fewer than {MIN_GROUP_SIZE} applications are flagged as insufficient."

    return {
        "total_applications": n,
        "by_status": by_status,
        "conversion": {
            "application_to_interview": _rate(responses, n),
            "application_to_offer": {"n": n, "offers": offers, "rate": round(offers / n, 3) if n else None, "ci95": wilson(offers, n)},
            "interview_to_offer": {"n": responses, "offers": offers,
                                   "rate": round(offers / responses, 3) if responses else None, "ci95": wilson(offers, responses)},
        },
        "by_role": group(lambda a: _norm_role(a.role_title)),
        "by_experience_level": group(lambda a: a.experience_level),
        "skills_vs_response": skill_rows[:15],
        "skill_combinations": combo_rows[:10],
        "data_sufficiency": {"sufficient": sufficient, "minimum_total": MIN_TOTAL_FOR_PATTERNS,
                             "minimum_group": MIN_GROUP_SIZE, "message": message},
        "disclaimer": DISCLAIMER,
    }


def rule_based_observations(stats: dict) -> list[str]:
    obs = [stats["data_sufficiency"]["message"]]
    conv = stats["conversion"]["application_to_interview"]
    if conv["n"]:
        obs.append(f"Overall, {conv['responses']} of {conv['n']} applications reached an interview "
                   f"({round(100 * conv['response_rate'])}%).")
    reliable_roles = [(r, v) for r, v in stats["by_role"].items() if v["sufficient_data"]]
    if len(reliable_roles) >= 2:
        best = max(reliable_roles, key=lambda kv: kv[1]["response_rate"])
        obs.append(f"'{best[0]}' roles have the highest response rate among roles with enough data "
                   f"({round(100 * best[1]['response_rate'])}% of {best[1]['n']}).")
    if stats["skills_vs_response"]:
        top = stats["skills_vs_response"][0]
        if top["difference"] > 0:
            obs.append(f"Applications highlighting {top['skill']} had a {round(100 * top['difference'])} percentage-point "
                       f"higher response rate (correlation only).")
    return obs
