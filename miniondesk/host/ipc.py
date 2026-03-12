"""IPC watcher — reads JSON files from group .ipc directories and routes them."""
from __future__ import annotations
import asyncio
import collections
import functools
import json
import logging
import os
import pathlib
import time
from typing import Callable, Awaitable

from . import config

# Bounded deque used as an LRU cache for processed IPC file paths.
# Prevents the set from growing unbounded on long-running instances.
# Max capacity: 10,000 entries (well above any realistic burst).
_PROCESSED_MAXLEN = 10_000

logger = logging.getLogger(__name__)

RouteMessageFn = Callable[[str, str, str], Awaitable[None]]
RouteFileFn    = Callable[[str, str, str], Awaitable[None]]


def _resolve_container_path(container_path: str, group_folder: str) -> str | None:
    """Map container-side path to host-side path."""
    if not group_folder:
        return None
    p = container_path.replace("\\", "/").strip()
    groups_dir = pathlib.Path(config.GROUPS_DIR)
    if p.startswith("/workspace/group/"):
        rel = p[len("/workspace/group/"):]
        return str(groups_dir / group_folder / rel)
    if p.startswith("/workspace/project/"):
        rel = p[len("/workspace/project/"):]
        return str(pathlib.Path(config.BASE_DIR) / rel)
    # Fallback: return as-is
    return p if os.path.exists(p) else None


async def watch_ipc(
    route_message: RouteMessageFn,
    route_file: RouteFileFn,
) -> None:
    """Continuously poll all group .ipc directories for new IPC messages."""
    logger.info("IPC watcher started")
    # Bounded deque acts as a fixed-size LRU set to prevent unbounded memory growth.
    # Files are deleted after processing so re-processing is only a theoretical risk.
    _processed_deque: collections.deque = collections.deque(maxlen=_PROCESSED_MAXLEN)
    processed: set[str] = set()  # kept in sync with deque for O(1) lookup

    while True:
        try:
            groups_dir = pathlib.Path(config.GROUPS_DIR)
            if groups_dir.exists():
                # Load all groups once per poll cycle (not once per directory — fixes N+1 query)
                from . import db
                all_groups = db.get_all_groups()
                folder_to_group = {g["folder"]: g for g in all_groups}

                for group_dir in groups_dir.iterdir():
                    if not group_dir.is_dir():
                        continue
                    ipc_dir = group_dir / ".ipc"
                    if not ipc_dir.exists():
                        continue
                    folder = group_dir.name

                    # Find group JID from pre-loaded map
                    group = folder_to_group.get(folder)
                    if not group:
                        continue
                    group_jid = group["jid"]

                    for f in sorted(ipc_dir.iterdir()):
                        if not f.name.endswith(".json"):
                            continue
                        if str(f) in processed:
                            continue
                        # Evict oldest entry when deque is full to keep set bounded
                        if len(_processed_deque) == _PROCESSED_MAXLEN:
                            evicted = _processed_deque[0]  # leftmost = oldest
                            processed.discard(evicted)
                        _processed_deque.append(str(f))
                        processed.add(str(f))
                        try:
                            payload = json.loads(f.read_text(encoding="utf-8"))
                            await _handle_ipc(payload, group_jid, folder, route_message, route_file)
                            f.unlink(missing_ok=True)
                        except Exception as exc:
                            logger.error("IPC error processing %s: %s", f.name, exc)

        except Exception as exc:
            logger.error("IPC watcher error: %s", exc)

        await asyncio.sleep(config.IPC_POLL_INTERVAL)


async def _handle_ipc(
    payload: dict,
    group_jid: str,
    group_folder: str,
    route_message: RouteMessageFn,
    route_file: RouteFileFn,
) -> None:
    msg_type = payload.get("type", "message")
    chat_jid = payload.get("chatJid") or group_jid

    if msg_type == "message":
        text = payload.get("text", "")
        sender = payload.get("sender", "")
        await route_message(chat_jid, text, sender)

    elif msg_type == "send_file":
        container_path = payload.get("filePath", "")
        caption = payload.get("caption", "")
        host_path = _resolve_container_path(container_path, group_folder)
        logger.info("send_file: container=%r host=%r", container_path, host_path)
        if host_path and os.path.exists(host_path):
            await route_file(chat_jid, host_path, caption)
        else:
            await route_message(chat_jid, f"⚠️ File not found: {os.path.basename(container_path)}", "")

    elif msg_type == "schedule_task":
        from . import scheduler
        try:
            await scheduler.add_task(group_jid, payload)
        except ValueError as exc:
            logger.error("IPC schedule_task: invalid schedule for group %s: %s", group_jid, exc)
            await route_message(chat_jid, f"⚠️ schedule_task failed: {exc}", "")

    elif msg_type == "dev_task":
        # DevEngine: start a development pipeline
        from . import dev_engine
        from .main import route_message as _route
        prompt = payload.get("prompt", "")
        mode   = payload.get("mode", "auto")
        if prompt:
            def _on_dev_task_done(task: asyncio.Task) -> None:
                exc = task.exception() if not task.cancelled() else None
                if exc:
                    logger.error("IPC dev_task failed for group %s: %s", group_jid, exc)

            task = asyncio.create_task(
                dev_engine.start_dev_session(group_jid, prompt, mode, _route)
            )
            task.add_done_callback(_on_dev_task_done)
        else:
            await route_message(chat_jid, "⚠️ dev_task: missing prompt", "")

    elif msg_type == "apply_skill":
        # Skills Engine: install a skill — run in executor to avoid blocking the event loop
        from .skills_engine import install_skill
        skill_name = payload.get("skill", "")
        if skill_name:
            loop = asyncio.get_event_loop()
            ok, msg = await loop.run_in_executor(None, functools.partial(install_skill, skill_name))
            await route_message(chat_jid, msg, "")
        else:
            await route_message(chat_jid, "⚠️ apply_skill: missing skill name", "")

    elif msg_type == "uninstall_skill":
        from .skills_engine import uninstall_skill
        skill_name = payload.get("skill", "")
        if skill_name:
            loop = asyncio.get_event_loop()
            ok, msg = await loop.run_in_executor(None, functools.partial(uninstall_skill, skill_name))
            await route_message(chat_jid, msg, "")

    elif msg_type == "list_skills":
        from .skills_engine import list_available_skills, list_installed_skills
        mode = payload.get("mode", "available")
        if mode == "installed":
            skills = list_installed_skills()
            lines = [f"• *{s['name']}* v{s['version']} — {s['description']}" for s in skills]
            text = "🔧 *Installed Skills:*\n" + ("\n".join(lines) if lines else "None")
        else:
            skills = list_available_skills()
            lines = [
                f"{'✅' if s['installed'] else '⬜'} *{s['name']}* v{s['version']} — {s['description']}"
                for s in skills
            ]
            text = "🔧 *Available Skills:*\n" + ("\n".join(lines) if lines else "None")
        await route_message(chat_jid, text, "")

    else:
        logger.warning("Unknown IPC type: %s", msg_type)
