"""Application Analyst: turns pre-computed statistics into a short narrative.

The LLM never computes numbers. It receives the statistics JSON and must only
restate what is there, respecting the data-sufficiency flags.
"""
import json
import logging

from app.ai.client import LLMClient, LLMError
from app.ai.schemas import ApplicationNarrative
from app.modules.applications.analytics import rule_based_observations

logger = logging.getLogger(__name__)


async def summarize(llm: LLMClient, stats: dict) -> tuple[ApplicationNarrative, str]:
    fallback = ApplicationNarrative(
        summary=stats["data_sufficiency"]["message"] + " " + stats["disclaimer"],
        observations=rule_based_observations(stats),
    )
    if not llm.available or stats["total_applications"] == 0:
        return fallback, "rule_based"
    system = ("You summarise a job seeker's application statistics. Use ONLY numbers present in the JSON. "
              "If data_sufficiency.sufficient is false, or a group has sufficient_data=false, say the pattern is not "
              "reliable yet. Never claim causation. Offer 1-3 practical suggestions framed as hypotheses to test.")
    try:
        narrative = await llm.generate_json(task="application_analysis", system=system, user=json.dumps(stats),
                                            schema=ApplicationNarrative, temperature=0.2)
        return narrative, "llm"
    except LLMError as exc:
        logger.warning("Application narrative failed, using rules: %s", exc)
        return fallback, "rule_based"
