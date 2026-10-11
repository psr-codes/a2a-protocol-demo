"""Orchestrator Agent: A2A server on :8010 and A2A client to the math agents.

Gemini plans the calculation and uses two tools:
  - find_agents(query):              discovery via the registry
  - delegate_task(agent_url, task):  A2A SendMessage to the chosen agent
The orchestrator never does arithmetic itself; every operation is delegated.

Run: python orchestrator.py
"""

import logging
import time

import httpx
from google.genai import types

from a2a.helpers import get_message_text, new_data_part, new_task_from_user_message, new_text_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.types import AgentSkill, TaskState

from common import GEMINI_MODEL, HOST, PORTS, REGISTRY_URL, build_card, gemini, send_a2a_message, serve_agent

log = logging.getLogger("Orchestrator")
PORT = PORTS["orchestrator"]
SELF_URL = f"http://{HOST}:{PORT}"

SYSTEM_PROMPT = """You are an orchestrator agent that solves arithmetic problems by delegating
to specialist agents. You MUST NOT compute any arithmetic yourself; not even trivial steps.

Procedure:
1. Break the problem into binary operations (two operands each), respecting standard operator
   precedence: parentheses first, then * and / (left to right), then + and - (left to right).
2. For each operation, in the correct order:
   a. Call `find_agents` with a short keyword for the capability (e.g. "multiply", "add",
      "subtract", "divide"). Pick the best matching agent from the results.
   b. Call `delegate_task` with that agent's url and a short instruction such as "7 * 6".
   c. Use the returned result as an operand in later steps.
3. If a delegation fails (e.g. division by zero) or no agent is found, stop and explain the error.
4. When done, reply with one short line: "Answer: <number>" (or "Error: <reason>")."""


class OrchestratorExecutor(AgentExecutor):
    def __init__(self):
        self.llm = gemini()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        if not task:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)

        prompt = get_message_text(context.message)
        log.info("RECEIVED  task %s: %r", task.id[:8], prompt)
        await updater.start_work(new_text_message(f"Planning: {prompt}"))

        steps: list[dict] = []  # execution trace returned to the caller

        async def status(text: str) -> None:
            log.info("  %s", text)
            await updater.update_status(state=TaskState.TASK_STATE_WORKING, message=new_text_message(text))

        # ---- Tools exposed to Gemini (closures so each request has its own trace) ----
        async def find_agents(query: str) -> list[dict]:
            """Search the agent registry for agents matching a capability keyword.

            Args:
                query: A short capability keyword, e.g. "multiply", "add", "subtract", "divide".

            Returns:
                Matching agents (best first), each with name, url, description and skills.
            """
            async with httpx.AsyncClient(timeout=10) as http:
                r = await http.get(f"{REGISTRY_URL}/search", params={"q": query})
                r.raise_for_status()
            matches = [
                {
                    "name": m["card"]["name"],
                    "url": m["url"],
                    "description": m["card"].get("description", ""),
                    "skills": [s.get("name") for s in m["card"].get("skills", [])],
                }
                for m in r.json()
                if m["url"] != SELF_URL
            ]
            await status(f"🔎 registry search '{query}' → {[m['name'] for m in matches] or 'no match'}")
            return matches

        async def delegate_task(agent_url: str, instruction: str) -> dict:
            """Delegate one operation to a remote agent over the A2A protocol.

            Args:
                agent_url: The base url of the agent (from find_agents).
                instruction: The operation to perform, e.g. "7 * 6".

            Returns:
                {"state", "result", "error"}: result is the agent's answer when state is COMPLETED.
            """
            await status(f"📨 delegating '{instruction}' → {agent_url}")
            try:
                res = await send_a2a_message(agent_url, instruction, caller="Orchestrator")
            except Exception as e:
                res = {"agent": agent_url, "task_id": "", "state": "UNREACHABLE", "text": "", "error": str(e)}
            steps.append({
                "agent": res["agent"],
                "instruction": instruction,
                "task_id": res["task_id"],
                "state": res["state"],
                "result": res["text"],
                "error": res["error"],
            })
            await status(f"✅ {res['agent']}: {instruction} = {res['text']}" if not res["error"]
                         else f"❌ {res['agent']}: {res['error']}")
            return {"state": res["state"], "result": res["text"], "error": res["error"]}

        # ---- Gemini agentic loop (automatic function calling runs the tools) ----
        log.info("🤖 Gemini (%s) is planning; it will call find_agents / delegate_task...", GEMINI_MODEL)
        t0 = time.monotonic()
        try:
            response = await self.llm.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    tools=[find_agents, delegate_task],
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(maximum_remote_calls=20),
                    temperature=0,
                ),
            )
            answer = (response.text or "").strip() or "Error: no answer produced"
        except Exception as e:
            log.exception("Planning failed")
            await updater.failed(new_text_message(f"Orchestrator error: {e}"))
            return

        log.info("🏁 task %s finished in %.1fs → %s", task.id[:8], time.monotonic() - t0, answer)
        await updater.add_artifact(
            name="final_answer",
            parts=[new_text_part(answer, media_type="text/plain"), new_data_part({"prompt": prompt, "steps": steps})],
        )
        if answer.lower().startswith("error"):
            await updater.failed(new_text_message(answer))
        else:
            await updater.complete(new_text_message(answer))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancel is not supported.")


if __name__ == "__main__":
    card = build_card(
        name="Orchestrator Agent",
        description="Solves arithmetic expressions by discovering and delegating to specialist math agents via A2A.",
        port=PORT,
        skills=[
            AgentSkill(
                id="solve_expression",
                name="Solve expression",
                description="Evaluates arithmetic expressions or word problems by delegating each operation.",
                tags=["orchestrator", "expression", "calculator", "planner"],
                examples=["5 + 7 * 6", "(10 - 4) / 2", "what is ten divided by four plus one"],
            )
        ],
    )
    serve_agent(card, OrchestratorExecutor(), PORT)
