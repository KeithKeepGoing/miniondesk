"""Task scheduler for MinionDesk."""
from __future__ import annotations
import asyncio
import logging
import time
import uuid
from croniter import croniter  # type: ignore

from . import config, db

logger = logging.getLogger(__name__)

# Suspend a recurring task after this many consecutive dispatch failures
_MAX_CONSECUTIVE_FAILURES = 5


def _compute_next_run(schedule_type: str, schedule_value: str, now: float | None = None) -> int | None:
    now = now or time.time()
    if schedule_type == "cron":
        try:
            if not croniter.is_valid(schedule_value):
                return None
            return int(croniter(schedule_value, now).get_next())
        except Exception:
            return None
    elif schedule_type == "interval":
        try:
            ms = int(schedule_value)
            if ms <= 0:
                return None
            return int(now + ms / 1000)
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
    """Schedule a task. Raises ValueError if the schedule expression is invalid."""
    task_id = payload.get("id") or str(uuid.uuid4())
    schedule_type  = payload.get("schedule_type", "once")
    schedule_value = payload.get("schedule_value", "")
    next_run = _compute_next_run(schedule_type, schedule_value)
    if next_run is None:
        raise ValueError(
            f"Invalid schedule: type={schedule_type!r} value={schedule_value!r}. "
            "Task not saved."
        )
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
    # In-memory consecutive failure counter per task_id
    _fail_counts: dict[str, int] = {}
    # In-flight set: task_ids currently being dispatched.
    # Prevents double-firing when a container is slower than the task interval.
    _in_flight: set[str] = set()

    while True:
        try:
            due = db.get_due_tasks()
            for task in due:
                task_id = task["id"]

                # Skip if already dispatched and still running (short-interval guard)
                if task_id in _in_flight:
                    logger.debug("Scheduler task %s already in-flight — skipping", task_id)
                    continue

                logger.info("Dispatching task %s for group %s", task_id, task["group_jid"])
                _in_flight.add(task_id)

                # For recurring tasks, advance next_run immediately so the DB
                # query won't re-select it on the next poll cycle. The in-flight
                # set provides an additional guard during the current run.
                if task["schedule_type"] != "once":
                    next_run = _compute_next_run(task["schedule_type"], task["schedule_value"])
                    db.update_task_run(task_id, next_run or int(time.time()) + 3600)

                def _on_task_done(
                    t: asyncio.Task,
                    _task_id: str = task_id,
                    _group_jid: str = task["group_jid"],
                    _schedule_type: str = task["schedule_type"],
                ) -> None:
                    _in_flight.discard(_task_id)
                    exc = t.exception() if not t.cancelled() else None
                    if exc:
                        _fail_counts[_task_id] = _fail_counts.get(_task_id, 0) + 1
                        consecutive = _fail_counts[_task_id]
                        logger.error(
                            "Scheduler task %s dispatch failed (consecutive=%d): %s",
                            _task_id, consecutive, exc,
                        )
                        if _schedule_type == "once":
                            # Delete the once-task on failure too — there is no
                            # next_run to update and retrying infinitely would be wrong.
                            try:
                                db.delete_task(_task_id)
                            except Exception as db_exc:
                                logger.error("Failed to delete failed once-task %s: %s", _task_id, db_exc)
                        elif consecutive >= _MAX_CONSECUTIVE_FAILURES:
                            logger.warning(
                                "Suspending task %s after %d consecutive failures",
                                _task_id, consecutive,
                            )
                            try:
                                db.suspend_task(_task_id, str(exc))
                            except Exception as db_exc:
                                logger.error("Failed to suspend task %s: %s", _task_id, db_exc)
                    else:
                        # Reset on success
                        _fail_counts.pop(_task_id, None)
                        # Delete once-tasks only after successful dispatch so a
                        # transient container failure doesn't permanently lose the task.
                        if _schedule_type == "once":
                            try:
                                db.delete_task(_task_id)
                            except Exception as db_exc:
                                logger.error("Failed to delete completed once-task %s: %s", _task_id, db_exc)

                _task = asyncio.create_task(dispatch_fn(task["group_jid"], task["prompt"]))
                _task.add_done_callback(_on_task_done)
        except Exception as exc:
            logger.error("Scheduler error: %s", exc)
        await asyncio.sleep(10)
