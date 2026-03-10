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


def _list_tasks(args: dict, ctx: "ToolContext") -> str:
    """List scheduled tasks for this chat (injected by host at startup)."""
    tasks = ctx.scheduled_tasks if hasattr(ctx, "scheduled_tasks") else []
    if not tasks:
        return "No scheduled tasks found."
    lines = []
    for t in tasks:
        lines.append(f"ID: {t.get('id', '?')[:8]}... | {t.get('schedule_type')} {t.get('schedule_value')} | last_run: {t.get('last_run') or 'never'} | status: {t.get('status', 'active')}")
    return "\n".join(lines)


def _cancel_task(args: dict, ctx: "ToolContext") -> str:
    """Cancel a scheduled task by its ID."""
    task_id = args.get("task_id", "").strip()
    if not task_id:
        return "Error: task_id is required."
    try:
        import os, json, time, random, string
        ipc_tasks = os.path.join(ctx.ipc_dir, "tasks")
        os.makedirs(ipc_tasks, exist_ok=True)
        uid = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
        path = os.path.join(ipc_tasks, f"cancel_{int(time.time()*1000)}_{uid}.json")
        with open(path, "w") as f:
            json.dump({"action": "cancel", "task_id": task_id}, f)
        return f"Cancellation request sent for task {task_id}"
    except Exception as e:
        return f"Error: {e}"


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
        Tool(
            name="list_tasks",
            description="List scheduled tasks for this chat.",
            schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
            execute=_list_tasks,
        ),
        Tool(
            name="cancel_task",
            description="Cancel a scheduled task by its ID.",
            schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "The task ID to cancel"},
                },
                "required": ["task_id"],
            },
            execute=_cancel_task,
        ),
    ]
