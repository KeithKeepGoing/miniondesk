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


_WEB_SEARCH_MAX_RESPONSE_BYTES = 512 * 1024  # 512 KB — cap DDG response to prevent host OOM


def _do_web_search(query: str) -> dict:
    """Perform a DuckDuckGo Instant Answer search on the host (has network access).

    Called from an executor so it does not block the event loop.
    Returns a dict suitable for JSON serialisation back to the container.
    """
    import urllib.request
    import urllib.parse
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_redirect=1&no_html=1"
        with urllib.request.urlopen(url, timeout=8) as resp:
            # Cap response size to prevent OOM from a runaway or malicious upstream.
            raw = resp.read(_WEB_SEARCH_MAX_RESPONSE_BYTES)
            data = json.loads(raw.decode("utf-8"))
        results = []
        if data.get("AbstractText"):
            results.append({
                "type": "abstract",
                "text": data["AbstractText"],
                "source": data.get("AbstractSource", ""),
                "url": data.get("AbstractURL", ""),
            })
        for topic in data.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "type": "topic",
                    "text": topic["Text"],
                    "url": topic.get("FirstURL", ""),
                })
        if not results:
            return {"results": [], "note": "No instant answer found. Try a more specific query."}
        return {"results": results}
    except Exception as exc:
        return {"error": str(exc)}


# Bounded deque used as an LRU cache for processed IPC file paths.
# Prevents the set from growing unbounded on long-running instances.
# Max capacity: 10,000 entries (well above any realistic burst).
_PROCESSED_MAXLEN = 10_000

logger = logging.getLogger(__name__)

RouteMessageFn = Callable[[str, str, str], Awaitable[None]]
RouteFileFn    = Callable[[str, str, str], Awaitable[None]]


def _resolve_container_path(container_path: str, group_folder: str) -> str | None:
    """Map container-side path to host-side path.

    Only paths under /workspace/group/ or /workspace/project/ are permitted.
    The previous fallback that returned raw host absolute paths has been removed:
    a container-controlled send_file with an absolute path like /etc/passwd or
    /home/user/.env would have caused arbitrary host file exfiltration via Telegram/Discord.
    """
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
    # Any other path (including absolute host paths) is rejected to prevent
    # container-controlled file exfiltration via IPC send_file payloads.
    logger.warning(
        "IPC send_file: rejected unrecognised container path %r for group %s",
        container_path, group_folder,
    )
    return None


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

    elif msg_type == "kb_search":
        # Handle knowledge base search requested by container enterprise tool
        from .enterprise.knowledge_base import search
        query = payload.get("query", "")
        try:
            limit = max(1, min(50, int(payload.get("limit", 5) or 5)))
        except (ValueError, TypeError):
            limit = 5
        if query:
            try:
                results = search(query, limit=limit)
                if results:
                    lines = [f"• *{r['title']}*: {r['snippet'][:120]}" for r in results]
                    text = f"📚 *KB Results for '{query}':*\n" + "\n".join(lines)
                else:
                    text = f"📚 No KB results found for: {query}"
            except Exception as exc:
                logger.error("IPC kb_search error: %s", exc)
                text = f"⚠️ KB search failed: {exc}"
            await route_message(chat_jid, text, "")
        else:
            await route_message(chat_jid, "⚠️ kb_search: missing query", "")

    elif msg_type == "workflow_trigger":
        # Handle workflow trigger requested by container enterprise tool
        from .enterprise.workflow import trigger_workflow
        workflow_name = payload.get("workflow", "")
        data = payload.get("data", {})
        if workflow_name:
            try:
                result_text = await trigger_workflow(workflow_name, data, group_jid)
                await route_message(chat_jid, result_text, "")
            except Exception as exc:
                logger.error("IPC workflow_trigger error: %s", exc)
                await route_message(chat_jid, f"⚠️ Workflow '{workflow_name}' failed: {exc}", "")
        else:
            await route_message(chat_jid, "⚠️ workflow_trigger: missing workflow name", "")

    elif msg_type == "calendar_check":
        # Handle calendar check requested by container enterprise tool
        from .enterprise.calendar import check_availability
        user = payload.get("user", "")
        date = payload.get("date", "")
        if user and date:
            try:
                result_text = await check_availability(user, date)
                await route_message(chat_jid, result_text, "")
            except Exception as exc:
                logger.error("IPC calendar_check error: %s", exc)
                await route_message(chat_jid, f"⚠️ Calendar check failed: {exc}", "")
        else:
            await route_message(chat_jid, "⚠️ calendar_check: missing user or date", "")

    elif msg_type == "web_search":
        # Web search requested by container web_search tool.
        # Containers run with --network none, so the host performs the HTTP
        # call and writes the result back to the IPC dir for the container to
        # read via polling (see skills/web-search dynamic tool).
        query = payload.get("query", "").strip()
        request_id = payload.get("request_id", "")
        if query and request_id:
            loop = asyncio.get_event_loop()
            result_data = await loop.run_in_executor(None, _do_web_search, query)
            # Write result file into the group's IPC dir for the container to pick up
            ipc_dir = pathlib.Path(config.GROUPS_DIR) / group_folder / ".ipc"
            ipc_dir.mkdir(parents=True, exist_ok=True)
            result_path = ipc_dir / f"ws_result_{request_id}.json"
            try:
                result_path.write_text(
                    json.dumps(result_data, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception as exc:
                logger.error("IPC web_search: failed to write result: %s", exc)
        else:
            logger.warning("IPC web_search: missing query or request_id")

    else:
        logger.warning("Unknown IPC type: %s", msg_type)
