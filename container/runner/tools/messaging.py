"""
Messaging tools: send_message, schedule_task, run_agent.
Uses file-based IPC to communicate with host.
"""
from __future__ import annotations
import json
import os
import time
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


def _run_agent(args: dict, ctx: ToolContext) -> str:
    """
    Spawn a sub-agent in an isolated container to handle a subtask.
    Blocks until complete (up to 300s) and returns the sub-agent's output.
    Writes a spawn_agent IPC request and polls the results dir for the response.
    """
    prompt = args.get("prompt", "").strip()
    if not prompt:
        return "Error: prompt is required."

    request_id = str(uuid.uuid4())
    ipc_tasks = os.path.join(ctx.ipc_dir, "tasks")
    ipc_results = os.path.join(ctx.ipc_dir, "results")
    os.makedirs(ipc_tasks, exist_ok=True)
    os.makedirs(ipc_results, exist_ok=True)

    spawn_payload = {
        "type": "spawn_agent",
        "requestId": request_id,
        "chat_jid": ctx.chat_jid,
        "minion_name": ctx.minion_name,
        "prompt": prompt,
    }
    fname = os.path.join(ipc_tasks, f"{int(time.time() * 1000)}-spawn.json")
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(spawn_payload, f, ensure_ascii=False)

    # Poll for result (up to 300 seconds)
    output_path = os.path.join(ipc_results, f"{request_id}.json")
    for _ in range(300):
        if os.path.exists(output_path):
            try:
                with open(output_path, encoding="utf-8") as f:
                    data = json.load(f)
                try:
                    os.unlink(output_path)
                except Exception:
                    pass
                return data.get("output", "(no output)")
            except Exception as e:
                return f"Error reading subagent result: {e}"
        time.sleep(1)

    return "Error: subagent timed out after 300s"


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
        Tool(
            name="run_agent",
            description=(
                "Spawn a sub-agent in an isolated container to handle a subtask. "
                "Blocks until complete (up to 300s) and returns its output. "
                "Use for Level B (complex) tasks that benefit from isolated execution."
            ),
            schema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "The task for the sub-agent. Must be self-contained and include all context. "
                            "Start with '/reasoning on' to enable deeper reasoning."
                        ),
                    },
                },
                "required": ["prompt"],
            },
            execute=_run_agent,
        ),
    ]
