"""Task scheduler for MinionDesk."""
from __future__ import annotations
import asyncio
import datetime
import logging
import time
import uuid
from croniter import croniter  # type: ignore

from . import config, db

logger = logging.getLogger(__name__)

# Suspend a recurring task after this many consecutive dispatch failures
_MAX_CONSECUTIVE_FAILURES = 5

# Maximum years in the future for a "once" schedule
_ONCE_MAX_YEARS = 10


def _validate_cron(expr: str) -> bool:
    """Validate cron expression has sane field values to prevent ReDoS."""
    if not croniter.is_valid(expr):
        return False
    parts = expr.split()
    if len(parts) < 5:
        return False
    # Check each field is within normal bounds (no huge numbers)
    limits = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
    for i, part in enumerate(parts[:5]):
        for token in part.replace(',', ' ').replace('-', ' ').replace('/', ' ').split():
            if token == '*':
                continue
            try:
                val = int(token)
                lo, hi = limits[i]
                if not (lo <= val <= hi):
                    return False
            except ValueError:
                pass  # named values like MON, JAN are ok
    return True


def _compute_next_run(schedule_type: str, schedule_value: str, now: float | None = None) -> int | None:
    now = now or time.time()
    if schedule_type == "cron":
        try:
            if not _validate_cron(schedule_value):
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
            dt = datetime.datetime.fromisoformat(schedule_value)
            ts = int(dt.timestamp())
            # Reject datetimes more than _ONCE_MAX_YEARS in the future
            max_ts = int(time.time()) + _ONCE_MAX_YEARS * 365 * 24 * 3600
            if ts > max_ts:
                logger.warning(
                    "Scheduler: 'once' schedule %r is more than %d years in the future — rejected",
                    schedule_value, _ONCE_MAX_YEARS,
                )
                return None
            return ts
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


async def run_scheduler(dispatch_fn, notify_fn=None) -> None:
    """Poll DB for due tasks and dispatch them.

    notify_fn: optional async callable(group_jid, text) used to send failure
    notifications to the group when a once-task dispatch raises an exception.
    Without it, failures are only logged and the user has no visibility.
    """
    logger.info("Scheduler started")
    # In-memory consecutive failure counter per task_id
    _fail_counts: dict[str, int] = {}
    # In-flight set: task_ids currently being dispatched.
    # Prevents double-firing when a container is slower than the task interval.
    _in_flight: set[str] = set()
    _in_flight_since: dict[str, float] = {}  # task_id → time.monotonic() when added
    _IN_FLIGHT_MAX_AGE = 3600.0  # 1 hour max
    cycle_count = 0

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
                _in_flight_since[task_id] = time.monotonic()

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
                    _prompt: str = task.get("prompt", ""),
                ) -> None:
                    _in_flight.discard(_task_id)
                    _in_flight_since.pop(_task_id, None)
                    exc = t.exception() if not t.cancelled() else None
                    if exc:
                        _fail_counts[_task_id] = _fail_counts.get(_task_id, 0) + 1
                        consecutive = _fail_counts[_task_id]
                        logger.error(
                            "Scheduler task %s dispatch failed (consecutive=%d): %s",
                            _task_id, consecutive, exc,
                        )
                        if _schedule_type != "once":
                            # Exponential backoff: 10s, 20s, 40s, ... up to 3600s
                            backoff_seconds = min(10 * (2 ** consecutive), 3600)
                            next_run_ts = int(time.time()) + backoff_seconds
                            try:
                                db.update_task_run(_task_id, next_run_ts)
                                logger.info(
                                    "Scheduler task %s backoff: next retry in %ds (failure #%d)",
                                    _task_id, backoff_seconds, consecutive,
                                )
                            except Exception as db_exc:
                                logger.error("Failed to update backoff for task %s: %s", _task_id, db_exc)
                        if _schedule_type == "once":
                            # Notify the group that the once-task failed so the user
                            # is not left wondering what happened to their scheduled task.
                            if notify_fn:
                                asyncio.get_event_loop().call_soon_threadsafe(
                                    asyncio.ensure_future,
                                    notify_fn(
                                        _group_jid,
                                        f"⚠️ Scheduled task failed: {exc}\nPrompt: {_prompt[:80]}",
                                    ),
                                )
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
                            if notify_fn:
                                asyncio.get_event_loop().call_soon_threadsafe(
                                    asyncio.ensure_future,
                                    notify_fn(
                                        _group_jid,
                                        f"⚠️ Recurring task suspended after {consecutive} consecutive failures. "
                                        f"Task ID: {_task_id}. Last error: {exc}",
                                    ),
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

            # Prune stale _fail_counts entries every 100 cycles to prevent memory leak
            cycle_count += 1
            if cycle_count % 100 == 0:
                existing_ids = {t["id"] for t in db.get_all_tasks()}
                stale = [k for k in _fail_counts if k not in existing_ids]
                for k in stale:
                    del _fail_counts[k]
                if stale:
                    logger.debug("Scheduler: pruned %d stale _fail_counts entries", len(stale))
                # Periodic cleanup of stale in-flight entries (tasks stuck > 1 hour)
                now_mono = time.monotonic()
                stale_inflight = [tid for tid, ts in _in_flight_since.items() if now_mono - ts > _IN_FLIGHT_MAX_AGE]
                for tid in stale_inflight:
                    logger.warning("scheduler: clearing stale in-flight task %s (>%.0fs)", tid, _IN_FLIGHT_MAX_AGE)
                    _in_flight.discard(tid)
                    _in_flight_since.pop(tid, None)
            # Cap dict size: if too large, clear oldest entries (largest fail counts first)
            if len(_fail_counts) > 1000:
                excess = len(_fail_counts) - 1000
                oldest_keys = sorted(_fail_counts, key=lambda k: _fail_counts[k])[:excess]
                for k in oldest_keys:
                    del _fail_counts[k]
                logger.warning("Scheduler: _fail_counts exceeded 1000 entries, pruned %d oldest", excess)
        except Exception as exc:
            logger.error("Scheduler error: %s", exc)
        await asyncio.sleep(10)
