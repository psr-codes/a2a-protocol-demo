"""Shared logic for the four math agents.

Each math agent = A2A server + Gemini + exactly one deterministic Python tool.
Gemini understands the request ("seven times six", "7*6", "multiply 7 by 6")
and extracts the operands via function calling; Python does the arithmetic,
so the LLM can never hallucinate a wrong result.
"""

import logging
import time
from typing import Callable

from google.genai import types

from a2a.helpers import get_message_text, new_data_part, new_task_from_user_message, new_text_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import AgentSkill

from common import GEMINI_MODEL, PORTS, build_card, gemini, serve_agent


def fmt(n: float) -> str:
    """42.0 -> '42', 2.5 -> '2.5'"""
    return str(int(n)) if float(n).is_integer() else repr(round(n, 10))


class MathAgentExecutor(AgentExecutor):
    def __init__(self, name: str, symbol: str, tool: Callable[[float, float], float]):
        self.name = name
        self.symbol = symbol
        self.tool = tool
        self.llm = gemini()
        self.log = logging.getLogger(name)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # 1. Every request becomes an A2A Task with a lifecycle (submitted -> working -> completed/failed).
        task = context.current_task
        if not task:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        await updater.start_work(new_text_message(f"{self.name} is working..."))

        query = get_message_text(context.message)
        self.log.info("RECEIVED  task %s: %r", task.id[:8], query)

        # 2. Ask Gemini to extract operands by calling our tool (we execute it ourselves).
        self.log.info("  🤖 asking Gemini (%s) to extract operands...", GEMINI_MODEL)
        t0 = time.monotonic()
        try:
            response = await self.llm.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=query,
                config=types.GenerateContentConfig(
                    system_instruction=(
                        f"You are the {self.name}. You can ONLY perform '{self.tool.__name__}' "
                        f"of exactly two numbers. Extract the two operands from the request and call "
                        f"the `{self.tool.__name__}` tool. If the request is not a {self.tool.__name__} "
                        f"of two numbers, do not call the tool; briefly explain why."
                    ),
                    tools=[self.tool],
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    temperature=0,
                ),
            )
        except Exception as e:
            self.log.error("Gemini call failed: %s", e)
            await updater.failed(new_text_message(f"LLM error: {e}"))
            return

        calls = response.function_calls or []
        self.log.info("  🤖 Gemini replied in %.1fs: %s", time.monotonic() - t0,
                      f"{calls[0].name}({dict(calls[0].args)})" if calls else "no tool call")
        if not calls:
            reason = response.text or "Could not understand the request."
            self.log.info("Task %s rejected: %s", task.id[:8], reason)
            await updater.failed(new_text_message(reason))
            return

        # 3. Run the deterministic tool.
        a, b = float(calls[0].args["a"]), float(calls[0].args["b"])
        try:
            result = self.tool(a, b)
        except Exception as e:  # e.g. ZeroDivisionError
            self.log.info("Task %s failed: %s", task.id[:8], e)
            await updater.failed(new_text_message(f"Error computing {fmt(a)} {self.symbol} {fmt(b)}: {e}"))
            return

        expression = f"{fmt(a)} {self.symbol} {fmt(b)}"
        self.log.info("Task %s: %s = %s", task.id[:8], expression, fmt(result))

        # 4. Publish the result as an A2A Artifact (text part + structured data part).
        await updater.add_artifact(
            name="calculation_result",
            parts=[
                new_text_part(fmt(result), media_type="text/plain"),
                new_data_part({"expression": expression, "a": a, "b": b, "result": result}),
            ],
        )
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancel is not supported.")


def run_math_agent(
    *,
    key: str,
    name: str,
    symbol: str,
    tool: Callable[[float, float], float],
    description: str,
    tags: list[str],
    examples: list[str],
) -> None:
    """Build the Agent Card for a math agent and start its A2A server."""
    port = PORTS[key]
    skill = AgentSkill(
        id=tool.__name__,
        name=tool.__name__.capitalize(),
        description=description,
        tags=tags,
        examples=examples,
        input_modes=["text/plain"],
        output_modes=["text/plain", "application/json"],
    )
    card = build_card(name, description, port, [skill])
    serve_agent(card, MathAgentExecutor(name, symbol, tool), port)
