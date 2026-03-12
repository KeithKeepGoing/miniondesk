"""
web_search — DuckDuckGo search tool for MinionDesk containers.
Installed by the web-search Skill. Auto-loaded from /app/dynamic_tools/.
No API key required.

NOTE: Containers run with --network none, so direct HTTP from the container
is impossible. This tool routes the search request through the IPC mechanism
to the host process, which has network access and performs the actual HTTP
call. The result is returned as the tool's return value via a synchronous
IPC round-trip (write IPC file → host executes → host writes result file →
container reads result).

Because the container has no network, we write a web_search IPC request and
poll for a result file that the host writes back to /workspace/group/.ipc/
with a matching request_id. If the result does not arrive within the timeout
we return an error.
"""
import json
import os
import time
import uuid
from pathlib import Path

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
try:
    from tools import Tool, register_tool
except ImportError:
    Tool = None
    register_tool = None

IPC_DIR = Path(os.getenv("IPC_DIR", "/workspace/group/.ipc"))
_RESULT_POLL_INTERVAL = 0.2   # seconds between polls
_RESULT_TIMEOUT = 10.0         # seconds to wait for host response


def _web_search(args: dict, ctx: dict) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return json.dumps({"error": "query is required"})

    request_id = uuid.uuid4().hex[:12]
    IPC_DIR.mkdir(parents=True, exist_ok=True)

    # Write request via IPC (atomic rename)
    payload = {"type": "web_search", "query": query, "request_id": request_id}
    ts = int(time.time() * 1000)
    pid = os.getpid()
    req_fname = IPC_DIR / f"ws_{ts}_{pid}.json"
    tmp = req_fname.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.rename(req_fname)

    # Poll for result file written by host
    result_fname = IPC_DIR / f"ws_result_{request_id}.json"
    deadline = time.monotonic() + _RESULT_TIMEOUT
    while time.monotonic() < deadline:
        if result_fname.exists():
            try:
                data = json.loads(result_fname.read_text(encoding="utf-8"))
                result_fname.unlink(missing_ok=True)
                return json.dumps(data, ensure_ascii=False)
            except Exception as exc:
                return json.dumps({"error": f"Failed to read result: {exc}"})
        time.sleep(_RESULT_POLL_INTERVAL)

    return json.dumps({"error": "Web search timed out — host did not respond in time."})


if Tool and register_tool:
    register_tool(Tool(
        name="web_search",
        description="Search the web using DuckDuckGo. Returns instant answers and related topics. Use for current events, facts, and live data.",
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query. Be specific and concise.",
                }
            },
            "required": ["query"],
        },
        execute=_web_search,
    ))
