# A2A Calculator Demo

source .venv/bin/activate

chmod +x start_all.sh ./start_all.sh

python client.py

A multi-agent calculator built on the **A2A protocol (spec 1.0, `a2a-sdk` 1.2)** with **Gemini** in every agent.

```
client.py ──A2A──▶ Orchestrator :8010 ──GET /search──▶ Registry :8000
                        │                                 ▲
                        └──A2A──▶ Add :8001 / Sub :8002 / Mul :8003 / Div :8004
                                  (each self-registers on startup)
```

| File                | Role                                                                                                                       |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `common.py`         | Config from `.env`, Gemini client, Agent Card builder, A2A server runner (+ registry self-registration), A2A client helper |
| `registry.py`       | Agent catalog. Fetches each card from `/.well-known/agent-card.json`, keyword `/search`                                    |
| `agents/base.py`    | Shared math executor: Gemini extracts operands via function calling, Python computes                                       |
| `agents/*_agent.py` | The 4 standalone math agents (one A2A server each)                                                                         |
| `orchestrator.py`   | A2A server + client. Gemini plans and uses `find_agents` / `delegate_task` tools                                           |
| `client.py`         | CLI A2A client                                                                                                             |

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install "a2a-sdk[http-server]>=1.2,<2" google-genai fastapi uvicorn httpx python-dotenv
# put your key in .env  →  GEMINI_API_KEY=...
```

## Run

```bash
./start_all.sh                      # terminal 1: everything (Ctrl+C stops all)
.venv/bin/python client.py "5 + 7 * 6"          # terminal 2
.venv/bin/python client.py "(10 - 4) / 2"
.venv/bin/python client.py "8 / 0"
.venv/bin/python client.py --agent http://localhost:8003 "seven times six"   # talk to one agent directly
```

Or start services individually (like separate deployments):

```bash
.venv/bin/python registry.py
.venv/bin/python -m agents.add_agent
.venv/bin/python orchestrator.py
```

## Poke at the protocol

```bash
curl localhost:8003/.well-known/agent-card.json   # Agent Card
curl localhost:8000/agents                         # registry catalog
curl "localhost:8000/search?q=divide"              # discovery
```
# a2a-protocol-demo
