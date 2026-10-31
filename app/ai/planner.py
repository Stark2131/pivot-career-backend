"""Learning Planner.

Two steps, on purpose:
1. `build_schedule` (deterministic) decides WHICH skills go in WHICH week and for
   how many hours, based on gap priority and the user's weekly availability.
   This is what keeps plans realistic - the LLM cannot overload a week.
2. `fill_content` asks the LLM for topics/activities/exercises for exactly that
   skeleton. Output for any task that does not match the skeleton is replaced
   with template content.
"""
import json
import logging
import math
from dataclasses import dataclass, field

from app.ai.client import LLMClient, LLMError
from app.ai import resources
from app.ai.schemas import PlanContent
from app.utils.skills_taxonomy import category_of, learning_hours, topics_for

logger = logging.getLogger(__name__)

LEVEL_MULTIPLIER = {"entry": 1.25, "junior": 1.1, "mid": 1.0, "senior": 0.85, "lead": 0.85}
MAX_SKILLS_PER_WEEK = 3
MIN_BLOCK_HOURS = 1.0


@dataclass
class SkillNeed:
    skill_name: str
    hours: float
    gap_level: str = "missing"
    reason: str = ""


@dataclass
class ScheduledTask:
    week_number: int
    skill_name: str
    hours: float
    part: int  # 1-based part index for multi-week skills
    parts: int
    title: str = ""
    topics: list[str] = field(default_factory=list)
    activities: list[str] = field(default_factory=list)
    exercises: list[str] = field(default_factory=list)
    expected_outcome: str = ""
    resources: list[dict] = field(default_factory=list)


def estimate_hours(skill_name: str, gap_level: str, experience_level: str | None) -> float:
    base = learning_hours(skill_name)
    factor = 0.5 if gap_level == "partial" else 1.0
    return round(base * factor * LEVEL_MULTIPLIER.get(experience_level or "mid", 1.0), 1)


def build_schedule(needs: list[SkillNeed], weekly_hours: int, max_weeks: int) -> tuple[list[ScheduledTask], list[str]]:
    """Greedy packing of skills (in priority order) into weeks.

    Returns (tasks, deferred_skill_names). A skill may span several weeks; a week
    holds at most MAX_SKILLS_PER_WEEK skills and never more than `weekly_hours`.
    """
    tasks: list[ScheduledTask] = []
    deferred: list[str] = []
    week, used, skills_this_week = 1, 0.0, 0
    for need in needs:
        remaining = need.hours
        blocks: list[tuple[int, float]] = []
        while remaining > 0.05:
            capacity = weekly_hours - used
            if capacity < MIN_BLOCK_HOURS or skills_this_week >= MAX_SKILLS_PER_WEEK:
                week, used, skills_this_week = week + 1, 0.0, 0
                continue
            if week > max_weeks:
                break
            chunk = round(min(remaining, capacity), 1)
            blocks.append((week, chunk))
            used += chunk
            skills_this_week += 1
            remaining = round(remaining - chunk, 1)
            if remaining > 0.05:  # skill continues next week
                week, used, skills_this_week = week + 1, 0.0, 0
        if remaining > 0.05:
            # Did not fit within max_weeks: keep nothing half-done beyond the horizon.
            if not blocks:
                deferred.append(need.skill_name)
                continue
            deferred.append(f"{need.skill_name} (remaining ~{math.ceil(remaining)}h)")
        for idx, (w, h) in enumerate(blocks, start=1):
            tasks.append(ScheduledTask(week_number=w, skill_name=need.skill_name, hours=h, part=idx, parts=len(blocks)))
    return tasks, deferred


_ACTIVITIES = {
    "programming_language": ["Work through the official {s} tutorial sections for these topics", "Solve 3-5 small coding problems in {s}"],
    "backend": ["Read the official {s} documentation for these topics", "Code along with a short {s} tutorial and commit it to Git"],
    "frontend": ["Follow the official {s} docs/tutorial for these topics", "Rebuild a small UI component from scratch with {s}"],
    "database": ["Practise queries against a sample database in {s}", "Read about indexing and query plans in {s}"],
    "data": ["Follow a hands-on notebook using {s} on a public dataset", "Summarise what you learned in a short write-up"],
    "ml_ai": ["Study the concepts with a reputable course chapter or docs on {s}", "Implement a small {s} example in a notebook"],
    "cloud": ["Use the {s} free tier to try the services covered", "Read the {s} well-architected / best-practice guide sections"],
    "devops": ["Follow the official {s} getting-started guide", "Apply {s} to one of your existing projects"],
    "soft_skill": ["Read one practical guide on {s}", "Practise {s} in a real or simulated scenario and ask for feedback"],
}
_DEFAULT_ACTIVITIES = ["Study the official documentation for {s}", "Do a hands-on tutorial on {s} and take notes"]


def template_content(task: ScheduledTask) -> None:
    """Fill task content from templates (fallback when no LLM)."""
    s = task.skill_name
    all_topics = topics_for(s)
    per = max(1, math.ceil(len(all_topics) / task.parts))
    topics = all_topics[(task.part - 1) * per: task.part * per] or all_topics[-1:]
    acts = _ACTIVITIES.get(category_of(s), _DEFAULT_ACTIVITIES)
    part_txt = f" (part {task.part}/{task.parts})" if task.parts > 1 else ""
    task.title = f"{s}{part_txt}: {topics[0]}"
    task.topics = topics
    task.activities = [a.format(s=s) for a in acts]
    task.exercises = [f"Hands-on exercise: apply '{t}' in a small script or notebook and push it to GitHub" for t in topics[:2]]
    if task.part == task.parts:
        task.exercises.append(f"Mini-checkpoint: explain {s} in your own words and build one small end-to-end example")
    task.expected_outcome = (
        f"You can confidently use {s} for: {', '.join(t.lower() for t in topics)}."
        if task.part == task.parts else f"Solid grasp of: {', '.join(t.lower() for t in topics)}."
    )


async def fill_content(
    llm: LLMClient, tasks: list[ScheduledTask], *, target_role: str | None, experience_level: str | None,
    known_skills: list[str],
) -> tuple[str, str | None]:
    """Returns (generated_by, llm_summary). Every task ends up with content."""
    for t in tasks:
        template_content(t)  # baseline content for every task
        t.resources = resources.default_for_part(t.skill_name, t.part, t.parts)  # curated links only
    if not llm.available or not tasks:
        return "rule_based", None

    skeleton: dict[int, list[dict]] = {}
    for t in tasks:
        skeleton.setdefault(t.week_number, []).append({
            "skill_name": t.skill_name, "hours": t.hours, "part": f"{t.part}/{t.parts}",
            "available_resources": [{"id": r["id"], "title": r["title"], "hours": r["hours"]} for r in resources.resources_for(t.skill_name)],
        })
    system = (
        "You are an expert learning designer. For the given weekly schedule, write concrete topics, learning "
        "activities, practical exercises and an expected outcome for EACH (week, skill) entry. Keep the exact same "
        "weeks and skill names; do not add or remove skills; scope content so it fits the given hours. "
        "Never write URLs. For each task you may list `resource_ids`, choosing ONLY from that task's "
        "`available_resources` (pick the ones that fit the week's hours and topics); leave it empty if none fit."
    )
    user = json.dumps({
        "target_role": target_role, "experience_level": experience_level, "already_known_skills": known_skills[:40],
        "schedule": [{"week_number": w, "tasks": ts} for w, ts in sorted(skeleton.items())],
    })
    try:
        content = await llm.generate_json(task="plan_content", system=system, user=user, schema=PlanContent)
    except LLMError as exc:
        logger.warning("Plan content generation failed, using templates: %s", exc)
        return "rule_based", None

    index = {(t.week_number, t.skill_name.lower()): t for t in tasks}
    matched = 0
    for week in content.weeks:
        for c in week.tasks:
            t = index.get((week.week_number, c.skill_name.strip().lower()))
            if t is None:
                continue  # LLM tried to add something outside the schedule -> ignore
            t.title, t.topics, t.activities = c.title, c.topics, c.activities
            t.exercises, t.expected_outcome = c.exercises, c.expected_outcome
            chosen = resources.choose(t.skill_name, c.resource_ids)
            if chosen:
                t.resources = chosen
            matched += 1
    generated_by = "llm" if matched == len(tasks) else ("llm_partial" if matched else "rule_based")
    return generated_by, content.summary


def adjust_needs(
    remaining: dict[str, float], order: list[str], *, struggling: set[str], focus: list[str],
    experience_level: str | None, drop: set[str] | None = None,
) -> tuple[list[SkillNeed], dict[str, tuple[float, float]]]:
    """Compute the skill list for an adjusted plan.

    * remaining work per skill is carried over (completed work is not repeated),
    * struggling skills get +50% time (min +2h) and move to the front,
    * explicitly requested focus skills come first (added if new),
    * `drop` skills (e.g. now mastered) are removed from the remaining work.
    Returns (needs, hours_changes {skill: (old, new)}).
    """
    changes: dict[str, tuple[float, float]] = {}
    hours = dict(remaining)
    for s in (drop or set()):
        if s in hours:
            changes[s] = (hours.pop(s), 0.0)
    struggling = {s for s in struggling if s not in (drop or set())}
    for s in struggling:
        if s in hours:
            new = round(max(hours[s] * 1.5, hours[s] + 2), 1)
            changes[s] = (hours[s], new)
            hours[s] = new
    for s in focus:
        if s not in hours:
            hours[s] = estimate_hours(s, "missing", experience_level)
            changes[s] = (0.0, hours[s])
    ordered = list(dict.fromkeys(
        [s for s in focus] + [s for s in order if s in struggling] + [s for s in order] + list(hours)
    ))
    needs = [
        SkillNeed(skill_name=s, hours=hours[s], reason="struggling" if s in struggling else "")
        for s in ordered if hours.get(s, 0) > 0.05
    ]
    return needs, changes
