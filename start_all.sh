#!/usr/bin/env bash
# Start the registry, the 4 math agents and the orchestrator. Ctrl+C stops everything.
cd "$(dirname "$0")"
PY=${PYTHON:-.venv/bin/python}

pids=()
cleanup() {
  echo -e "\nStopping all services..."
  kill "${pids[@]}" 2>/dev/null || true
  wait 2>/dev/null
}
trap cleanup EXIT INT TERM

echo "▶ Registry      :8000"
$PY registry.py & pids+=($!)
until curl -sf http://localhost:8000/health >/dev/null; do sleep 0.3; done

echo "▶ Math agents   :8001-8004"
for agent in add_agent sub_agent mul_agent div_agent; do
  $PY -m agents.$agent & pids+=($!)
done

echo "▶ Orchestrator  :8010"
$PY orchestrator.py & pids+=($!)

sleep 3
echo -e "\n✅ All services up. Registered agents:"
curl -s http://localhost:8000/agents | $PY -c 'import json,sys; [print("   - %-22s %s" % (a["card"]["name"], a["url"])) for a in json.load(sys.stdin)]'
echo -e "\nTry:  $PY client.py \"5 + 7 * 6\"\n"
wait
