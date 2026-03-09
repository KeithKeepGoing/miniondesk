"""
IPC Watcher: polls ipc/ directory for messages from containers.
Containers write JSON files; host reads and routes them.
"""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
from typing import Callable
from .logger import get_logger
_log = get_logger("ipc")


async def watch_ipc(
    ipc_dir: Path,
    on_message: Callable,
    on_task: Callable,
) -> None:
    """Poll IPC directories for outbound messages and scheduled tasks."""
    msgs_dir = ipc_dir / "messages"
    tasks_dir = ipc_dir / "tasks"
    routes_dir = ipc_dir / "routes"

    for d in [msgs_dir, tasks_dir, routes_dir]:
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
            except Exception as e:
                _log.error("IPC message error (%s): %s", f.name, type(e).__name__)
                _log.debug("IPC detail: %s", e)
                # Don't delete on failure — leave for retry or manual inspection

        # Process scheduled tasks
        for f in sorted(tasks_dir.glob("*.json")):
            if not f.is_file() or f.is_symlink():
                continue
            try:
                raw = f.read_bytes(1 * 1024 * 1024)  # 1MB cap
                data = json.loads(raw)
                await on_task(data)
                f.unlink(missing_ok=True)  # only delete on success
            except Exception as e:
                _log.error("IPC message error (%s): %s", f.name, type(e).__name__)
                _log.debug("IPC detail: %s", e)
                # Don't delete on failure — leave for retry or manual inspection
