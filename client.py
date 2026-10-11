"""CLI client: sends a prompt to an A2A agent (the orchestrator by default).

Usage:
  python client.py "5 + 7 * 6"                               # ask the orchestrator
  python client.py --agent http://localhost:8003 "7 * 6"     # talk to one agent directly
  python client.py                                           # interactive mode
"""

import argparse
import asyncio
import json

from a2a.client import AgentCardResolutionError

from common import HOST, PORTS, send_a2a_message

DEFAULT_AGENT = f"http://{HOST}:{PORTS['orchestrator']}"


async def ask(agent_url: str, prompt: str) -> None:
    print(f"\n→ {prompt}")
    try:
        res = await send_a2a_message(agent_url, prompt, caller="Client")
    except AgentCardResolutionError:
        print(f"✗ Can't reach an agent at {agent_url}. Is it running?  →  ./start_all.sh")
        return

    print(f"\nAgent : {res['agent']}")
    print(f"Task  : {res['task_id']}  [{res['state']}]")
    if res["error"]:
        print(f"Error : {res['error']}")
    if res["text"]:
        print(f"Result: {res['text']}")
    if res["data"]:
        print("Data  :", json.dumps(res["data"], indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="A2A CLI client")
    parser.add_argument("prompt", nargs="?", help="e.g. '5 + 7 * 6'")
    parser.add_argument("--agent", default=DEFAULT_AGENT, help=f"agent base URL (default {DEFAULT_AGENT})")
    args = parser.parse_args()

    if args.prompt:
        asyncio.run(ask(args.agent, args.prompt))
        return

    print(f"Interactive A2A client → {args.agent}  (type 'exit' to quit)")
    while (prompt := input("\nyou > ").strip()) not in ("", "exit", "quit"):
        asyncio.run(ask(args.agent, prompt))


if __name__ == "__main__":
    main()
