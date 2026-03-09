"""
Messaging tools: send_message, schedule_task.
Uses file-based IPC to communicate with host.
"""
from __future__ import annotations
import json
import os
import uuid
from datetime import datetime
from . import Tool, ToolContext


def _send_message(args: dict, ctx: ToolContext) -> str:
    text = args.get("text", "")
    sender = args.get("sender", ctx.minion_name)

    msg = {
        "id": str(uuid.uuid4()),
        "chat_jid": ctx.chat_jid,
        "sender": sender,
        "text": text,
        "timestamp": datetime.utcnow().isoformat(),
    }

    ipc_messages = os.path.join(ctx.ipc_dir, "messages")
    os.makedirs(ipc_messages, exist_ok=True)
    path = os.path.join(ipc_messages, f"{msg['id']}.json")
    with open(path, "w") as f:
        json.dump(msg, f)

    return f"Message queued: {text[:50]}..."


def _schedule_task(args: dict, ctx: ToolContext) -> str:
    prompt = args.get("prompt", "")
    schedule_type = args.get("schedule_type", "once")
    schedule_value = args.get("schedule_value", "")

    task = {
        "id": str(uuid.uuid4()),
        "chat_jid": ctx.chat_jid,
        "minion_name": ctx.minion_name,
        "prompt": prompt,
        "schedule_type": schedule_type,
        "schedule_value": schedule_value,
        "created_at": datetime.utcnow().isoformat(),
    }

    ipc_tasks = os.path.join(ctx.ipc_dir, "tasks")
    os.makedirs(ipc_tasks, exist_ok=True)
    path = os.path.join(ipc_tasks, f"{task['id']}.json")
    with open(path, "w") as f:
        json.dump(task, f)

    return f"Task scheduled: {schedule_type} {schedule_value}"


def get_messaging_tools() -> list[Tool]:
    return [
        Tool(
            name="send_message",
            description="Send a message to the current chat. Use for progress updates.",
            schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The message text to send"},
                    "sender": {"type": "string", "description": "Sender name (optional)"},
                },
                "required": ["text"],
            },
            execute=_send_message,
        ),
        Tool(
            name="schedule_task",
            description="Schedule a recurring or one-time task.",
            schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Task prompt"},
                    "schedule_type": {
                        "type": "string",
                        "enum": ["once", "cron", "interval"],
                        "description": "Schedule type",
                    },
                    "schedule_value": {
                        "type": "string",
                        "description": "Cron expression, ISO timestamp, or milliseconds",
                    },
                },
                "required": ["prompt", "schedule_type", "schedule_value"],
            },
            execute=_schedule_task,
        ),
    ]
