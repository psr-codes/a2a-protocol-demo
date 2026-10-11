"""Shared helpers used by every service: config, Gemini client, A2A server bootstrap."""

import asyncio
import inspect
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

import httpx
import uvicorn
from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types
from starlette.applications import Starlette

from a2a.client import A2ACardResolver, ClientConfig, create_client
from a2a.helpers import get_data_parts, get_message_text, get_text_parts, new_text_message
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Artifact,
    Role,
    SendMessageRequest,
    TaskState,
)

load_dotenv()

# ---------------------------------------------------------------- config
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

HOST = "localhost"
REGISTRY_URL = f"http://{HOST}:8000"
PORTS = {
    "add": 8001,
    "sub": 8002,
    "mul": 8003,
    "div": 8004,
    "orchestrator": 8010,
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s", datefmt="%H:%M:%S")
# Keep the console readable: hide per-request HTTP noise.
logging.getLogger("httpx").setLevel(logging.WARNING)
for noisy in ("a2a", "google_genai", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.ERROR)


def gemini() -> genai.Client:
    """Return a Gemini client using the key from .env. Retries 429/503 with backoff (free tier is ~5 req/min)."""
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your-api-key-here":
        raise RuntimeError("Set GEMINI_API_KEY in .env")
    retry = genai_types.HttpRetryOptions(
        attempts=6, initial_delay=8, max_delay=30, exp_base=1.5, http_status_codes=[429, 503]
    )
    return genai.Client(api_key=GEMINI_API_KEY, http_options=genai_types.HttpOptions(retry_options=retry))


# ---------------------------------------------------------------- agent card
def build_card(name: str, description: str, port: int, skills: list[AgentSkill]) -> AgentCard:
    """Build an A2A Agent Card served at /.well-known/agent-card.json."""
    return AgentCard(
        name=name,
        description=description,
        version="1.0.0",
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain", "application/json"],
        capabilities=AgentCapabilities(streaming=True),
        # Where (and how) the agent can be reached: JSON-RPC over HTTP, A2A spec 1.0
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=f"http://{HOST}:{port}", protocol_version="1.0")
        ],
        skills=skills,
    )


# ---------------------------------------------------------------- server
def serve_agent(card: AgentCard, executor: AgentExecutor, port: int) -> None:
    """Run an A2A server for `executor` and self-register it with the registry."""
    log = logging.getLogger(card.name)
    base_url = f"http://{HOST}:{port}"

    @asynccontextmanager
    async def lifespan(_app):
        await _register(base_url, log)
        yield
        await _deregister(base_url, log)

    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = [
        *create_agent_card_routes(card),  # GET /.well-known/agent-card.json
        *create_jsonrpc_routes(handler, "/"),  # POST / (JSON-RPC: SendMessage, GetTask, ...)
    ]
    app = Starlette(routes=routes, lifespan=lifespan)
    log.info("Serving A2A agent at %s", base_url)
    uvicorn.run(app, host=HOST, port=port, log_level="warning")


async def _register(base_url: str, log: logging.Logger) -> None:
    # The server isn't accepting connections yet during lifespan startup, but the
    # registry fetches our card asynchronously after a short delay, so this is fine.
    for attempt in range(10):
        try:
            async with httpx.AsyncClient(timeout=10) as http:
                r = await http.post(f"{REGISTRY_URL}/register", json={"url": base_url})
                r.raise_for_status()
            log.info("Registered with registry (%s)", REGISTRY_URL)
            return
        except httpx.HTTPError as e:
            log.warning("Registry not reachable (%s), retry %d/10", e.__class__.__name__, attempt + 1)
            await asyncio.sleep(1)
    log.error("Could not register with registry; continuing without it")


async def _deregister(base_url: str, log: logging.Logger) -> None:
    try:
        async with httpx.AsyncClient(timeout=3) as http:
            await http.request("DELETE", f"{REGISTRY_URL}/register", params={"url": base_url})
        log.info("Deregistered from registry")
    except httpx.HTTPError:
        pass


# ---------------------------------------------------------------- client
async def send_a2a_message(
    agent_url: str,
    text: str,
    on_status: Callable[[str], Awaitable[None] | None] | None = None,
    caller: str = "Client",
) -> dict[str, Any]:
    """Send `text` to the A2A agent at `agent_url` and wait for the final result.

    1. Discover: fetch the Agent Card from /.well-known/agent-card.json
    2. Connect:  build a client for the interface advertised in the card
    3. Send:     SendMessage (streaming) and consume Task / status / artifact events

    Returns {"agent", "task_id", "state", "text", "data", "error"}.
    """
    clog = logging.getLogger(caller)
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=120) as http:
        clog.info("1/3 DISCOVER  GET %s/.well-known/agent-card.json", agent_url)
        card = await A2ACardResolver(httpx_client=http, base_url=agent_url).get_agent_card()
        clog.info("    got card '%s' (skills: %s)", card.name, ", ".join(s.id for s in card.skills))
        client = await create_client(agent=card, client_config=ClientConfig(streaming=True, httpx_client=http))

        request = SendMessageRequest(message=new_text_message(text, role=Role.ROLE_USER))
        clog.info("2/3 SEND      SendMessage -> %s: %r", card.name, text)
        task_id, state, status_text = "", TaskState.TASK_STATE_SUBMITTED, ""
        artifacts: list[Artifact] = []

        async for event in client.send_message(request):
            if event.HasField("task"):
                task_id, state = event.task.id, event.task.status.state
                clog.info("3/3 RECEIVE   Task %s [%s]", task_id[:8], TaskState.Name(state).removeprefix("TASK_STATE_"))
                artifacts = list(event.task.artifacts) or artifacts
                if event.task.status.HasField("message"):
                    status_text = get_message_text(event.task.status.message)
            elif event.HasField("status_update"):
                task_id, state = event.status_update.task_id, event.status_update.status.state
                clog.info("    status   [%s] %s", TaskState.Name(state).removeprefix("TASK_STATE_"),
                          get_message_text(event.status_update.status.message)
                          if event.status_update.status.HasField("message") else "")
                if event.status_update.status.HasField("message"):
                    status_text = get_message_text(event.status_update.status.message)
                    if on_status:
                        maybe = on_status(status_text)
                        if inspect.isawaitable(maybe):
                            await maybe
            elif event.HasField("artifact_update"):
                art = event.artifact_update.artifact
                clog.info("    artifact '%s' = %s", art.name, " | ".join(get_text_parts(art.parts)))
                artifacts.append(art)
            elif event.HasField("message"):  # agent replied with a plain Message, no Task
                return {"agent": card.name, "task_id": "", "state": "MESSAGE",
                        "text": get_message_text(event.message), "data": None, "error": None}
        await client.close()
    clog.info("    done in %.1fs", time.monotonic() - t0)

    artifacts = list({a.artifact_id: a for a in artifacts}.values())  # dedupe
    text_out = "\n".join(t for a in artifacts for t in get_text_parts(a.parts))
    data_out = next((d for a in artifacts for d in get_data_parts(a.parts)), None)
    ok = state == TaskState.TASK_STATE_COMPLETED
    return {
        "agent": card.name,
        "task_id": task_id,
        "state": TaskState.Name(state),
        "text": text_out,
        "data": data_out,
        "error": None if ok else (status_text or "task did not complete"),
    }

