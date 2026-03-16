"""
IPC Watcher: polls ipc/ directory for messages from containers.
Containers write JSON files; host reads and routes them.
"""
from __future__ import annotations
import asyncio
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Callable
from .logger import get_logger
_log = get_logger("ipc")

_MAX_RETRIES = 5
_retry_counts: dict[str, int] = defaultdict(int)


async def watch_ipc(
    ipc_dir: Path,
    on_message: Callable,
    on_task: Callable,
) -> None:
    """Poll IPC directories for outbound messages and scheduled tasks."""
    msgs_dir = ipc_dir / "messages"
    tasks_dir = ipc_dir / "tasks"
    routes_dir = ipc_dir / "routes"
    dead_dir = ipc_dir / "dead_letter"

    for d in [msgs_dir, tasks_dir, routes_dir, dead_dir]:
        d.mkdir(parents=True, exist_ok=True)

    _IPC_MAX_BYTES = 1 * 1024 * 1024  # 1MB

    while True:
        await asyncio.sleep(0.5)

        # Process outbound messages
        for f in sorted(msgs_dir.glob("*.json")):
            if not f.is_file() or f.is_symlink():
                continue
            try:
                raw = f.read_bytes(1 * 1024 * 1024)  # 1MB cap
                data = json.loads(raw)
                await on_message(data)
                f.unlink(missing_ok=True)  # only delete on success
                _retry_counts.pop(str(f), None)
            except Exception as e:
                _retry_counts[str(f)] += 1
                count = _retry_counts[str(f)]
                _log.error("IPC message error (%s): %s (attempt %d/%d)", f.name, type(e).__name__, count, _MAX_RETRIES)
                if count >= _MAX_RETRIES:
                    # Quarantine to dead-letter directory
                    try:
                        f.rename(dead_dir / f.name)
                        _log.warning("IPC: quarantined %s to dead_letter after %d failures", f.name, count)
                    except Exception:
                        f.unlink(missing_ok=True)
                    _retry_counts.pop(str(f), None)

        # Process scheduled tasks
        for f in sorted(tasks_dir.glob("*.json")):
            if not f.is_file() or f.is_symlink():
                continue
            try:
                raw = f.read_bytes(1 * 1024 * 1024)  # 1MB cap
                data = json.loads(raw)
                await on_task(data)
                f.unlink(missing_ok=True)  # only delete on success
                _retry_counts.pop(str(f), None)
            except Exception as e:
                _retry_counts[str(f)] += 1
                count = _retry_counts[str(f)]
                _log.error("IPC task error (%s): %s (attempt %d/%d)", f.name, type(e).__name__, count, _MAX_RETRIES)
                if count >= _MAX_RETRIES:
                    try:
                        f.rename(dead_dir / f.name)
                        _log.warning("IPC: quarantined %s to dead_letter after %d failures", f.name, count)
                    except Exception:
                        f.unlink(missing_ok=True)
                    _retry_counts.pop(str(f), None)
