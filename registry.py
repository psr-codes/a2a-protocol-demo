"""Agent Registry: a tiny catalog of A2A Agent Cards.

Agents register by sending only their base URL. The registry does NOT trust
self-reported metadata: it fetches the card itself from the standard
well-known path `/.well-known/agent-card.json`.

Run: python registry.py   (port 8000)
"""

import asyncio
import logging
import re

import httpx
import uvicorn
from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel

from common import HOST

log = logging.getLogger("Registry")
app = FastAPI(title="A2A Agent Registry")

CARD_PATH = "/.well-known/agent-card.json"
agents: dict[str, dict] = {}  # base_url -> agent card (JSON)


class RegisterRequest(BaseModel):
    url: str


async def fetch_and_store_card(url: str) -> None:
    """Fetch the agent card from the agent itself (retrying while it boots)."""
    async with httpx.AsyncClient(timeout=5) as http:
        for _ in range(20):
            try:
                r = await http.get(f"{url}{CARD_PATH}")
                r.raise_for_status()
                card = r.json()
                agents[url] = card
                log.info("Registered '%s' at %s", card.get("name"), url)
                return
            except httpx.HTTPError:
                await asyncio.sleep(0.5)
    log.warning("Could not fetch agent card from %s", url)


@app.get("/health")
def health():
    return {"status": "ok", "agents": len(agents)}


@app.post("/register", status_code=202)
def register(req: RegisterRequest, background: BackgroundTasks):
    background.add_task(fetch_and_store_card, req.url.rstrip("/"))
    return {"status": "accepted", "url": req.url}


@app.delete("/register")
def deregister(url: str):
    card = agents.pop(url.rstrip("/"), None)
    if card:
        log.info("Deregistered '%s'", card.get("name"))
    return {"removed": bool(card)}


@app.get("/agents")
def list_agents():
    return [{"url": url, "card": card} for url, card in agents.items()]


@app.get("/search")
def search(q: str):
    """Keyword search over name, description and skills (name/description/tags/examples)."""
    terms = [t for t in re.findall(r"[a-z0-9]+", q.lower()) if len(t) > 1]
    results = []
    for url, card in agents.items():
        skills = card.get("skills", [])
        name_desc = f"{card.get('name', '')} {card.get('description', '')}".lower()
        skill_text = " ".join(
            " ".join([s.get("name", ""), s.get("description", ""), *s.get("tags", []), *s.get("examples", [])])
            for s in skills
        ).lower()
        # Tags/skills weigh more than free-text description.
        score = sum(3 * skill_text.count(t) + name_desc.count(t) for t in terms)
        if score:
            results.append({"url": url, "score": score, "card": card})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results


if __name__ == "__main__":
    log.info("Registry listening on http://%s:8000", HOST)
    uvicorn.run(app, host=HOST, port=8000, log_level="warning")
