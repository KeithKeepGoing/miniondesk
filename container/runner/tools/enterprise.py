"""Enterprise tools: knowledge base, workflow, calendar."""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from . import Tool, register_tool

IPC_DIR = Path(os.getenv("IPC_DIR", "/workspace/group/.ipc"))


def _ipc_write(payload: dict) -> str:
    IPC_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    pid = os.getpid()
    fname = IPC_DIR / f"ent_{ts}_{pid}.json"
    # Write atomically: write to .tmp then rename so the host never reads a
    # partially-written file (TOCTOU race fix).
    tmp = fname.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.rename(fname)
    return fname.name


def _kb_search(args: dict, ctx: dict) -> str:
    payload = {"type": "kb_search", "query": args.get("query", ""), "limit": args.get("limit", 5)}
    _ipc_write(payload)
    return json.dumps({"status": "queued", "query": args.get("query", "")})


def _workflow_trigger(args: dict, ctx: dict) -> str:
    payload = {
        "type": "workflow_trigger",
        "workflow": args.get("workflow", ""),
        "data": args.get("data", {}),
        "chat_jid": ctx.get("chat_jid", ""),
    }
    _ipc_write(payload)
    return f"Workflow '{args.get('workflow')}' triggered"


def _calendar_check(args: dict, ctx: dict) -> str:
    payload = {
        "type": "calendar_check",
        "user": args.get("user", ""),
        "date": args.get("date", ""),
    }
    _ipc_write(payload)
    return "Calendar check queued"


register_tool(Tool(
    name="kb_search",
    description="Search the enterprise knowledge base.",
    schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "description": "Max results (default 5)"},
        },
        "required": ["query"],
    },
    execute=_kb_search,
))

register_tool(Tool(
    name="workflow_trigger",
    description="Trigger an enterprise workflow (e.g. leave_request, expense_report, it_ticket).",
    schema={
        "type": "object",
        "properties": {
            "workflow": {"type": "string", "description": "Workflow name"},
            "data": {"type": "object", "description": "Workflow input data"},
        },
        "required": ["workflow"],
    },
    execute=_workflow_trigger,
))

register_tool(Tool(
    name="calendar_check",
    description="Check a user's calendar availability.",
    schema={
        "type": "object",
        "properties": {
            "user": {"type": "string"},
            "date": {"type": "string", "description": "Date (YYYY-MM-DD)"},
        },
        "required": ["user", "date"],
    },
    execute=_calendar_check,
))
