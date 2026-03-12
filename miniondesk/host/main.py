"""MinionDesk host — main async orchestrator."""
from __future__ import annotations
import asyncio
import logging
import os
import signal
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from .. import __version__
from . import config, db
from .channels import register_channel, find_channel, all_channels
from .channels.telegram import TelegramChannel
from .channels.discord import DiscordChannel
from .ipc import watch_ipc
from .queue import get_queue
from .scheduler import run_scheduler
from .runner import run_minion
from .evolution import evolution_loop
from .immune import is_allowed, record_message
from .dashboard import run_dashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Message routing ──────────────────────────────────────────────────────────

async def route_message(jid: str, text: str, sender: str = "") -> None:
    """Send a text message to the appropriate channel."""
    ch = find_channel(jid)
    if ch is None:
        logger.warning("route_message: no channel for jid=%s", jid)
        return
    await ch.send_message(jid, text, sender)


async def route_file(jid: str, file_path: str, caption: str = "") -> None:
    """Send a file to the appropriate channel."""
    ch = find_channel(jid)
    if ch is None:
        logger.warning("route_file: no channel for jid=%s", jid)
        return
    await ch.send_file(jid, file_path, caption)


# ─── Inbound message handler ──────────────────────────────────────────────────

async def handle_inbound(jid: str, text: str, trigger: str) -> None:
    """Route an inbound user message to the correct minion."""
    # Find registered group
    group = db.get_group(jid)
    if not group:
        logger.debug("Unregistered group: %s", jid)
        return

    # Immune / rate-limit check
    sender_jid = trigger or jid
    record_message(sender_jid, jid)
    if not is_allowed(sender_jid, jid):
        logger.warning("Rate-limited or blocked sender: %s in %s", sender_jid, jid)
        return

    # Check trigger word
    trigger_word = group.get("trigger", "@Mini").lower()
    if trigger_word not in text.lower():
        return

    minion = group.get("minion", "mini")
    folder = group["folder"]

    # Input sanitization: truncate oversized prompts
    if len(text) > config.MAX_PROMPT_LENGTH:
        logger.warning(
            "Prompt truncated from %d to %d chars for group %s",
            len(text), config.MAX_PROMPT_LENGTH, jid,
        )
        text = text[:config.MAX_PROMPT_LENGTH]

    # Generate request_id for log correlation
    request_id = uuid.uuid4().hex[:8]
    logger.info(
        "[%s] Dispatching to minion '%s' for group %s",
        request_id, minion, jid,
    )
    db.add_message(jid, "user", text)

    # Serialize per group via GroupQueue
    queue = get_queue()
    queue.submit(jid, _run_and_reply(jid, folder, minion, text, request_id))


async def _run_and_reply(
    jid: str,
    folder: str,
    minion: str,
    text: str,
    request_id: str = "",
) -> None:
    start_ms = time.time() * 1000
    logger.info("[%s] Container run starting for group %s", request_id, jid)
    result = await run_minion(
        group_jid=jid,
        group_folder=folder,
        minion_name=minion,
        prompt=text,
        chat_jid=jid,
        request_id=request_id,
    )
    elapsed_ms = int(time.time() * 1000 - start_ms)
    success = result.get("status") != "error"
    logger.info(
        "[%s] Container run finished: status=%s elapsed_ms=%d",
        request_id, result.get("status", "unknown"), elapsed_ms,
    )

    # Record run for evolution
    try:
        db.record_evolution_run(jid, success, elapsed_ms)
    except Exception:
        pass

    reply = result.get("result", "")
    if reply:
        await route_message(jid, reply)
        db.add_message(jid, "assistant", reply)


async def _dispatch_task(group_jid: str, prompt: str) -> None:
    """Dispatch a scheduled task."""
    group = db.get_group(group_jid)
    if not group:
        return
    await _run_and_reply(group_jid, group["folder"], group.get("minion", "mini"), prompt)


# ─── Health monitor ───────────────────────────────────────────────────────────

async def _health_monitor_loop() -> None:
    """Log system health stats every 60 seconds and checkpoint the WAL file."""
    while True:
        try:
            groups = db.get_all_groups()
            active_tasks = len(db.get_due_tasks())
            logger.info(
                "Health: groups=%d active_tasks=%d",
                len(groups), active_tasks,
            )
            # Periodic WAL checkpoint: SQLite WAL files grow without bound when
            # there are always active readers (which is always true for the dashboard
            # and IPC loops). Calling PASSIVE checkpoint encourages compaction without
            # blocking readers or writers.
            try:
                conn = db._conn()
                conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except Exception as wal_exc:
                logger.debug("WAL checkpoint error: %s", wal_exc)
        except Exception as exc:
            # Elevated to WARNING so health errors are visible at default log level
            logger.warning("Health monitor error: %s", exc)
        await asyncio.sleep(60)


# ─── Orphan cleanup ───────────────────────────────────────────────────────────

async def _orphan_cleanup_loop() -> None:
    """Periodically clean up orphaned Docker containers."""
    while True:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "ps", "-q", "--filter", "name=minion-",
                "--filter", "status=exited",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            ids = stdout.decode().strip().splitlines()
            if ids:
                rm_proc = await asyncio.create_subprocess_exec(
                    "docker", "rm", "-f", *ids,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await rm_proc.wait()
                logger.info("Cleaned up %d orphaned containers", len(ids))
        except Exception as exc:
            logger.debug("Orphan cleanup error: %s", exc)
        await asyncio.sleep(300)


# ─── Main ─────────────────────────────────────────────────────────────────────

async def run_host() -> None:
    """Start the MinionDesk host."""
    logger.info("MinionDesk v%s starting...", __version__)

    # Fail fast on bad configuration before starting any services
    config.validate()

    # Init directories and DB
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.GROUPS_DIR.mkdir(parents=True, exist_ok=True)
    (config.GROUPS_DIR / "global").mkdir(parents=True, exist_ok=True)
    db.init(config.DB_PATH)
    logger.info("Database initialized: %s", config.DB_PATH)
    logger.info("Container image: %s", config.CONTAINER_IMAGE)

    # Init channels
    if config.TELEGRAM_TOKEN:
        tg = TelegramChannel(config.TELEGRAM_TOKEN, on_message=handle_inbound)
        register_channel(tg)
        await tg.start()
        logger.info("Telegram channel registered")
    else:
        logger.warning("No TELEGRAM_TOKEN — Telegram channel disabled")

    if config.DISCORD_TOKEN:
        dc = DiscordChannel(config.DISCORD_TOKEN, on_message=handle_inbound)
        register_channel(dc)
        await dc.start()

    # Graceful shutdown
    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def _on_signal():
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            pass  # Windows

    # Run all loops concurrently:
    # 1. IPC watcher  2. Scheduler  3. Evolution  4. Health monitor  5. Orphan cleanup  6. Dashboard  7. Stop event
    # return_exceptions=True prevents one crashing coroutine from cancelling all others.
    # Without it, a transient unhandled exception in any sub-loop (e.g. evolution_loop,
    # watch_ipc) immediately cancels the entire gather — taking down the whole host process.
    results = await asyncio.gather(
        watch_ipc(route_message, route_file),
        run_scheduler(_dispatch_task),
        evolution_loop(),
        _health_monitor_loop(),
        _orphan_cleanup_loop(),
        run_dashboard(),
        stop_event.wait(),
        return_exceptions=True,
    )
    # Log any exceptions returned by sub-coroutines for operator visibility
    coro_names = [
        "watch_ipc", "run_scheduler", "evolution_loop",
        "_health_monitor_loop", "_orphan_cleanup_loop", "run_dashboard", "stop_event",
    ]
    for name, res in zip(coro_names, results):
        if isinstance(res, Exception):
            logger.error("Sub-coroutine '%s' exited with exception: %s", name, res)

    # Cleanup
    logger.info("Stopping channels...")
    for ch in all_channels():
        await ch.stop()
    logger.info("MinionDesk stopped.")
