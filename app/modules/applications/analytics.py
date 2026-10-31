"""Transparent application statistics (no ML, no causal claims).

* "Response" = the application reached the interview stage (status interview/offer,
  or rejected after an interview).
* Every rate comes with its sample size and a 95% Wilson confidence interval.
* Groups smaller than MIN_GROUP_SIZE are reported but flagged as insufficient.
"""
import math
from dataclasses import dataclass
from datetime import date, timedelta
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
    role_family: str | None = None
    industry: str | None = None
    company_size: str | None = None
    channel: str | None = None
    resume_version: str | None = None
    work_mode: str | None = None
    applied_date: date | None = None


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
        "by_role_family": group(lambda a: a.role_family),
        "by_industry": group(lambda a: (a.industry or "").strip().lower()),
        "by_company_size": group(lambda a: a.company_size),
        "by_channel": group(lambda a: a.channel),
        "by_resume_version": group(lambda a: a.resume_version),
        "by_work_mode": group(lambda a: a.work_mode),
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


# --- recommendations ------------------------------------------------------------------------------
PENDING_DAYS = 14          # an unanswered application younger than this may still get a reply -> not counted yet
MIN_EARLY_DIFF = 0.15      # smallest rate difference worth mentioning as an "early signal"
MAX_INSIGHTS = 5

# dimension -> (human label, getter, action wording for a higher / lower response rate)
_DIMENSIONS = {
    "channel": ("How you applied", lambda a: a.channel,
                "Prioritise {label} where you can.", "Do not rely on {label}; try other channels alongside."),
    "role_family": ("Role type", lambda a: a.role_family,
                    "Aim more applications at {label} roles.", "{label} roles respond less; check your resume fit before applying."),
    "experience_level": ("Seniority", lambda a: a.experience_level,
                         "{label}-level postings are a good fit for you; apply to more of them.",
                         "{label}-level postings respond less; consider aiming a level closer to your experience."),
    "industry": ("Industry", lambda a: (a.industry or "").strip().lower() or None,
                 "Focus on the {label} industry.", "The {label} industry responds less; test a tailored resume or deprioritise."),
    "company_size": ("Company size", lambda a: a.company_size,
                     "Companies of size {label} respond well; target more of them.",
                     "Companies of size {label} respond less; try other sizes."),
    "resume_version": ("Resume version", lambda a: a.resume_version,
                       "Resume '{label}' is working; use it as the base for new applications.",
                       "Resume '{label}' is underperforming; revise it or stop sending it."),
    "work_mode": ("Work mode", lambda a: a.work_mode,
                  "{label} roles respond well; look for more of them.", "{label} roles respond less."),
}
_PRETTY = {"job_board": "job boards", "referral": "referrals", "direct": "direct applications",
           "recruiter": "recruiter contacts", "other": "other channels", "onsite": "on-site",
           "data_analyst": "data analyst", "product_manager": "product manager", "ml_engineer": "ML engineer"}


def _pretty(value: str) -> str:
    return _PRETTY.get(value, value.replace("_", " "))


def _lead(dimension: str, value: str, label: str) -> str:
    """How an insight names its group, so it reads naturally ("Resume 'v2-data'", "Mid-level postings")."""
    return {
        "skill": f"Highlighting {label}",
        "resume_version": f"Resume '{value}'",
        "experience_level": f"{value.capitalize()}-level postings",
        "industry": f"The {label} industry",
        "company_size": f"Companies with {value} employees",
        "work_mode": f"{label.capitalize()} roles",
        "role_family": f"{label.capitalize()} roles",
    }.get(dimension, label.capitalize())


def _overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return not (a[1] < b[0] or b[1] < a[0])


def _pct(x: float) -> str:
    return f"{round(100 * x)}%"


def _compare(dimension: str, dimension_label: str, value: str, group: list[AppFact], rest: list[AppFact],
             up: str, down: str) -> dict | None:
    k_g, n_g = sum(a.reached_interview for a in group), len(group)
    k_r, n_r = sum(a.reached_interview for a in rest), len(rest)
    if n_g < MIN_GROUP_SIZE or n_r < MIN_GROUP_SIZE:
        return None
    r_g, r_r = k_g / n_g, k_r / n_r
    ci_g, ci_r = wilson(k_g, n_g), wilson(k_r, n_r)
    diff = r_g - r_r
    if not _overlap(ci_g, ci_r):
        confidence = "reliable"
    elif abs(diff) >= MIN_EARLY_DIFF:
        confidence = "early_signal"
    else:
        return None                                    # no difference worth reporting
    label = _pretty(value)
    direction = "higher" if diff > 0 else "lower"
    lead = _lead(dimension, value, label)
    text = (f"{lead}: {_pct(r_g)} reached an interview vs {_pct(r_r)} for all other applications "
            f"(n={n_g} vs {n_r})")
    text += "." if confidence == "reliable" else " - early signal, the intervals still overlap."
    return {
        "dimension": dimension, "dimension_label": dimension_label, "group": value, "label": label,
        "direction": direction, "confidence": confidence,
        "n": n_g, "responses": k_g, "response_rate": round(r_g, 3), "ci95": ci_g,
        "rest_n": n_r, "rest_response_rate": round(r_r, 3), "rest_ci95": ci_r, "difference": round(diff, 3),
        "text": text, "suggestion": (up if diff > 0 else down).format(label=label),
        "_score": abs(diff) * math.sqrt(n_g),
    }


def build_recommendations(apps: list[AppFact], today: date | None = None) -> dict:
    """Plain-English, evidence-backed insights. Never states a pattern the data does not support.

    * Applications still unanswered and younger than PENDING_DAYS are left out (a reply may still come).
    * A group is compared with *all other* counted applications using Wilson 95% intervals:
      disjoint intervals -> "reliable"; overlapping but a >=15-point gap with n>=5 on both sides -> "early_signal";
      otherwise nothing is said.
    """
    today = today or date.today()
    cutoff = today - timedelta(days=PENDING_DAYS)
    matured = [a for a in apps if a.reached_interview or a.status != "applied" or a.applied_date is None or a.applied_date <= cutoff]
    n = len(matured)
    k_all = sum(a.reached_interview for a in matured)
    base = {"n_applications": len(apps), "n_counted": n, "excluded_recent_pending": len(apps) - n,
            "baseline_response_rate": round(k_all / n, 3) if n else None, "baseline_ci95": wilson(k_all, n),
            "disclaimer": DISCLAIMER}
    if n < MIN_TOTAL_FOR_PATTERNS:
        return {**base, "sufficient_data": False, "insights": [],
                "message": (f"{n} counted application(s). Log at least {MIN_TOTAL_FOR_PATTERNS} (and give recent ones "
                            f"{PENDING_DAYS} days to get a reply) before the tracker can compare channels, roles or resumes.")}

    found: list[dict] = []
    for dim, (dim_label, getter, up, down) in _DIMENSIONS.items():
        values = sorted({getter(a) for a in matured} - {None})
        items = []
        for v in values:
            group = [a for a in matured if getter(a) == v]
            rest = [a for a in matured if getter(a) != v]
            item = _compare(dim, dim_label, v, group, rest, up, down)
            if item:
                items.append(item)
        # With only two groups "A is higher" and "B is lower" are the same fact: keep the positive one.
        higher = sorted((i for i in items if i["direction"] == "higher"), key=lambda i: -i["_score"])
        lower = sorted((i for i in items if i["direction"] == "lower"), key=lambda i: -i["_score"])
        found += higher[:1] + (lower[:1] if len(values) >= 3 or not higher else [])
    for s in sorted({s for a in matured for s in a.skills}):
        group = [a for a in matured if s in a.skills]
        rest = [a for a in matured if s not in a.skills]
        item = _compare("skill", "Skill highlighted", s, group, rest,
                        "Keep highlighting {label} - applications that did so were answered more often.",
                        "Highlighting {label} did not help; lead with other strengths.")
        if item:
            found.append(item)
    # Two findings that describe the very same split of applications (a resume version and the skill it
    # highlights; "A is higher" and "everything else is lower") are one finding. Keep the clearest wording:
    # a plain dimension before a skill, the positive direction before the negative one.
    best: dict[frozenset, dict] = {}
    for i in found:
        sig = frozenset({(i["n"], i["responses"]), (i["rest_n"], round(i["rest_response_rate"] * i["rest_n"]))})
        rank = (i["dimension"] == "skill", i["direction"] != "higher", -i["_score"])
        if sig not in best or rank < best[sig][0]:
            best[sig] = (rank, i)
    insights = sorted((v[1] for v in best.values()), key=lambda i: (i["confidence"] != "reliable", -i["_score"]))
    insights = insights[:MAX_INSIGHTS]
    for i in insights:
        i.pop("_score")
    message = (f"{len(insights)} pattern(s) found across {n} counted applications." if insights else
               f"No channel, role, resume or skill stands out yet across {n} counted applications. Keep logging outcomes.")
    return {**base, "sufficient_data": True, "insights": insights, "message": message}
