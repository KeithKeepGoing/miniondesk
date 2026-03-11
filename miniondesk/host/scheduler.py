"""Task scheduler for MinionDesk."""
from __future__ import annotations
import asyncio
import logging
import time
import uuid
from croniter import croniter  # type: ignore

from . import config, db

logger = logging.getLogger(__name__)


def _compute_next_run(schedule_type: str, schedule_value: str, now: float | None = None) -> int | None:
    now = now or time.time()
    if schedule_type == "cron":
        try:
            return int(croniter(schedule_value, now).get_next())
        except Exception:
            return None
    elif schedule_type == "interval":
        try:
            return int(now + int(schedule_value) / 1000)
        except Exception:
            return None
    elif schedule_type == "once":
        try:
            import datetime
            dt = datetime.datetime.fromisoformat(schedule_value)
            return int(dt.timestamp())
        except Exception:
            return None
    return None


async def add_task(group_jid: str, payload: dict) -> str:
    task_id = payload.get("id") or str(uuid.uuid4())
    schedule_type  = payload.get("schedule_type", "once")
    schedule_value = payload.get("schedule_value", "")
    next_run = _compute_next_run(schedule_type, schedule_value)
    db.upsert_task({
        "id": task_id,
        "group_jid": group_jid,
        "prompt": payload.get("prompt", ""),
        "schedule_type": schedule_type,
        "schedule_value": schedule_value,
        "next_run": next_run,
        "status": "active",
    })
    logger.info("Scheduled task %s for group %s (next_run=%s)", task_id, group_jid, next_run)
    return task_id


async def run_scheduler(dispatch_fn) -> None:
    """Poll DB for due tasks and dispatch them."""
    logger.info("Scheduler started")
    while True:
        try:
            due = db.get_due_tasks()
            for task in due:
                logger.info("Dispatching task %s for group %s", task["id"], task["group_jid"])

                def _on_task_done(t: asyncio.Task, task_id: str = task["id"]) -> None:
                    exc = t.exception() if not t.cancelled() else None
                    if exc:
                        logger.error("Scheduler task %s dispatch failed: %s", task_id, exc)

                _task = asyncio.create_task(dispatch_fn(task["group_jid"], task["prompt"]))
                _task.add_done_callback(_on_task_done)
                if task["schedule_type"] == "once":
                    db.delete_task(task["id"])
                else:
                    next_run = _compute_next_run(task["schedule_type"], task["schedule_value"])
                    db.update_task_run(task["id"], next_run or int(time.time()) + 3600)
        except Exception as exc:
            logger.error("Scheduler error: %s", exc)
        await asyncio.sleep(10)
