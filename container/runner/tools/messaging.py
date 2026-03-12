"""Messaging tools: send_message, schedule_task."""
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
    fname = IPC_DIR / f"msg_{ts}_{pid}.json"
    # Write atomically: write to .tmp then rename so the host never reads a
    # partially-written file (TOCTOU race fix).
    tmp = fname.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.rename(fname)
    return fname.name


def _send_message(args: dict, ctx: dict) -> str:
    text = args.get("text", "")
    sender = args.get("sender", "")
    chat_jid = args.get("chat_jid", ctx.get("chat_jid", ""))
    payload = {"type": "message", "text": text, "sender": sender, "chatJid": chat_jid}
    _ipc_write(payload)
    return f"Message queued ({len(text)} chars)"


def _send_file(args: dict, ctx: dict) -> str:
    file_path = args.get("file_path", "")
    caption = args.get("caption", "")
    chat_jid = args.get("chat_jid", ctx.get("chat_jid", ""))
    # Ensure output dir exists
    p = Path(file_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "send_file",
        "filePath": file_path,
        "caption": caption,
        "chatJid": chat_jid,
    }
    _ipc_write(payload)
    return f"File queued: {p.name}"


def _schedule_task(args: dict, ctx: dict) -> str:
    payload = {"type": "schedule_task", **args}
    _ipc_write(payload)
    return "Task scheduled"


register_tool(Tool(
    name="send_message",
    description="Send a message to the user via the chat channel.",
    schema={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Message text"},
            "sender": {"type": "string", "description": "Display name for the sender bot"},
            "chat_jid": {"type": "string", "description": "Chat JID (auto-detected if omitted)"},
        },
        "required": ["text"],
    },
    execute=_send_message,
))

register_tool(Tool(
    name="send_file",
    description="Send a file to the user. The file must be written to /workspace/group/output/ first.",
    schema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Path to file (e.g. /workspace/group/output/report.pdf)"},
            "caption": {"type": "string", "description": "Optional caption"},
            "chat_jid": {"type": "string"},
        },
        "required": ["file_path"],
    },
    execute=_send_file,
))

register_tool(Tool(
    name="schedule_task",
    description="Schedule a recurring or one-time task.",
    schema={
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "schedule_type": {"type": "string", "enum": ["cron", "interval", "once"]},
            "schedule_value": {"type": "string"},
        },
        "required": ["prompt", "schedule_type", "schedule_value"],
    },
    execute=_schedule_task,
))
