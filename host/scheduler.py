"""
Task Scheduler: runs scheduled tasks at appropriate times.
"""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Callable

from . import db
from .logger import get_logger
_log = get_logger("scheduler")


def _cron_matches(cron_expr: str, now: datetime) -> bool:
    """Simple cron matcher: minute hour dom month dow."""
    try:
        parts = cron_expr.split()
        if len(parts) != 5:
            return False
        minute, hour, dom, month, dow = parts
        # Convert Python weekday (Mon=0, Sun=6) to cron convention (Sun=0, Sat=6)
        cron_dow = (now.weekday() + 1) % 7
        checks = [
            (minute, now.minute),
            (hour, now.hour),
            (dom, now.day),
            (month, now.month),
            (dow, cron_dow),
        ]
        for pattern, val in checks:
            if pattern == "*":
                continue
            # Handle comma-separated values: "1,3,5"
            if "," in pattern:
                if str(val) not in pattern.split(","):
                    return False
                continue
            # Handle ranges: "1-5"
            if "-" in pattern and "/" not in pattern:
                parts = pattern.split("-")
                if not (int(parts[0]) <= val <= int(parts[1])):
                    return False
                continue
            # Handle steps: "*/5" or "0-30/5"
            if "/" in pattern:
                base, step = pattern.split("/", 1)
                step = int(step)
                if base == "*":
                    if val % step != 0:
                        return False
                else:
                    start = int(base.split("-")[0])
                    if (val - start) % step != 0 or val < start:
                        return False
                continue
            # Exact match
            if str(val) != pattern:
                return False
        return True
    except Exception:
        return False


async def run_scheduler(on_task: Callable) -> None:
    """Check and run due scheduled tasks every 60 seconds."""
    while True:
        await asyncio.sleep(60)
        now = datetime.now(timezone.utc)
        tasks = db.get_scheduled_tasks()
        for task in tasks:
            try:
                # Skip tasks that are not active (cancelled, error, etc.)
                if task.get("status") not in (None, "active"):
                    continue

                stype = task.get("schedule_type", "")
                sval = task.get("schedule_value", "")
                task_id = task.get("id", "<unknown>")

                if not stype or not sval:
                    _log.warning("Scheduler: task %s missing schedule_type or schedule_value — skipping", task_id)
                    continue

                if stype == "cron":
                    if _cron_matches(sval, now):
                        await on_task(task)
                        db.update_task_last_run(task_id)
                elif stype == "once":
                    run_at = datetime.fromisoformat(sval.replace("Z", "+00:00"))
                    if now >= run_at and not task.get("last_run"):
                        await on_task(task)
                        db.update_task_last_run(task_id)
                elif stype == "interval":
                    interval_ms = int(sval)
                    if interval_ms < 1000:
                        _log.error("Task %s has unreasonably small interval %dms (min 1000ms), skipping", task_id, interval_ms)
                        continue
                    last = task.get("last_run")
                    if not last:
                        await on_task(task)
                        db.update_task_last_run(task_id)
                    else:
                        last_dt = datetime.fromisoformat(last)
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=timezone.utc)
                        elapsed_ms = (now - last_dt).total_seconds() * 1000
                        if elapsed_ms >= interval_ms:
                            await on_task(task)
                            db.update_task_last_run(task_id)
            except Exception as e:
                _log.error(f"Error with task {task.get('id', '<unknown>')}: {e}")
