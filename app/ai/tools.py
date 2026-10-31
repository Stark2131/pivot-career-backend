"""Minimal, provider-agnostic tool calling with strict validation.

The LLM can only *request* a tool by name with JSON arguments. We:
1. check the name against an explicit allow-list (the registry),
2. validate the arguments with the tool's Pydantic model,
3. run the tool - which is a pure, READ-ONLY function over data we already
   loaded for the current user (no DB session, no network, no code execution),
4. validate/truncate the result before showing it to the model.

This is intentionally simple: a JSON "step" protocol works the same for OpenAI
and Gemini and is easy to test with a fake client.
"""
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, ValidationError

from app.ai.client import LLMClient, LLMError

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=BaseModel)
MAX_RESULT_CHARS = 4000


@dataclass
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    func: Callable[[BaseModel], Any]


class ToolRegistry:
    def __init__(self, tools: list[Tool]):
        self.tools = {t.name: t for t in tools}

    def catalog(self) -> list[dict]:
        return [{"name": t.name, "description": t.description, "arguments_schema": t.args_model.model_json_schema()}
                for t in self.tools.values()]

    def run(self, name: str | None, arguments: dict) -> str:
        """Execute a validated tool call; always returns a JSON string (errors included)."""
        tool = self.tools.get(name or "")
        if tool is None:
            return json.dumps({"error": f"Unknown tool '{name}'. Allowed: {sorted(self.tools)}"})
        try:
            args = tool.args_model.model_validate(arguments or {})
        except ValidationError as exc:
            return json.dumps({"error": "Invalid arguments", "details": exc.errors(include_url=False)[:5]}, default=str)
        try:
            result = tool.func(args)
            text = json.dumps(result, default=str)
        except Exception as exc:  # a tool bug must not crash the request
            logger.exception("Tool %s failed", name)
            return json.dumps({"error": f"Tool failed: {type(exc).__name__}"})
        return text[:MAX_RESULT_CHARS]


class AgentStep(BaseModel, Generic[F]):
    action: Literal["call_tool", "final_answer"]
    tool_name: str | None = None
    arguments: dict = Field(default_factory=dict)
    final_answer: F | None = None


async def run_tool_loop(
    llm: LLMClient, *, task: str, system: str, user: str, registry: ToolRegistry, final_schema: type[F], max_steps: int = 4
) -> tuple[F, list[dict]]:
    """Let the model call tools until it produces a final answer. Returns (answer, trace)."""
    step_schema = AgentStep[final_schema]  # type: ignore[valid-type]
    trace: list[dict] = []
    protocol = (
        "You may call read-only tools to gather facts before answering. Respond with JSON: "
        '{"action": "call_tool", "tool_name": ..., "arguments": {...}} to call a tool, or '
        '{"action": "final_answer", "final_answer": {...}} when done. Only use facts returned by tools.\n'
        f"Available tools: {json.dumps(registry.catalog())}"
    )
    for step in range(max_steps):
        transcript = "\n".join(f"TOOL CALL {t['tool']}({json.dumps(t['arguments'])}) -> {t['result']}" for t in trace)
        force = "\nYou have no tool calls left: give your final_answer now." if step == max_steps - 1 else ""
        prompt = f"{user}\n\nPrevious tool results:\n{transcript or '(none yet)'}{force}"
        result = await llm.generate_json(task=task, system=f"{system}\n\n{protocol}", user=prompt, schema=step_schema)
        if result.action == "final_answer" and result.final_answer is not None:
            return result.final_answer, trace
        if result.action == "call_tool":
            trace.append({"tool": result.tool_name, "arguments": result.arguments,
                          "result": registry.run(result.tool_name, result.arguments)})
            continue
        trace.append({"tool": None, "arguments": {}, "result": '{"error": "final_answer missing"}'})
    raise LLMError("Tool loop ended without a final answer.")
