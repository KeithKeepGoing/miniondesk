#!/usr/bin/env python3
"""
MinionDesk Host - Main Entry Point
Orchestrates channels, containers, IPC, and scheduling.
"""
from __future__ import annotations
import asyncio
import logging
import os
import re
import signal
from pathlib import Path

from .logger import setup_logging, get_logger

_VALID_STYPE = {"interval", "cron", "once"}
_MINION_RE = re.compile(r'^[a-zA-Z0-9_\-]+$')


def _validate_ipc_task(data: dict, log) -> bool:
    """Returns True if task data is safe to insert."""
    stype = data.get("schedule_type", "")
    if stype not in _VALID_STYPE:
        log.warning("IPC task rejected: invalid schedule_type %r", stype)
        return False
    minion = data.get("minion_name", "")
    if minion and not _MINION_RE.match(minion):
        log.warning("IPC task rejected: invalid minion_name %r", minion)
        return False
    prompt = data.get("prompt", "")
    if len(prompt) > 4096:
        log.warning("IPC task rejected: prompt too long (%d chars)", len(prompt))
        return False
    return True


async def main() -> None:
    setup_logging()
    log = get_logger("main")

    from .webportal import start_portal
    from .dashboard import start_dashboard
    from host import config, db, queue, ipc, runner, scheduler
    from host.allowlist import load_allowlist, is_allowed
    from host.enterprise.dept_init import init_department_groups
    from host.enterprise.weekly_report import weekly_report_loop, set_send_callback as set_report_callback
    from host.channels import all_channels
    import host.channels.telegram as tg_chan
    import host.channels.discord as dc_chan
    import host.channels.teams as teams_chan
    from .enterprise import jira_webhook

    # Initialize
    db.init(config.DATA_DIR / "miniondesk.db")
    load_allowlist()
    init_department_groups(config.PROJECT_ROOT)

    # Configure rate limiting
    from . import ratelimit
    ratelimit.configure(max_requests=10, window_seconds=60)
    log.info("Rate limiter: 10 req/min per user")
    log.info("Immune system: active")

    # Only initialize channels that have credentials configured
    if config.TELEGRAM_TOKEN:
        tg_chan.init(config.TELEGRAM_TOKEN)
        log.info("Telegram channel initialized")
    else:
        log.warning("TELEGRAM_TOKEN not set — Telegram channel disabled")

    if config.DISCORD_TOKEN:
        dc_chan.init(config.DISCORD_TOKEN)
        log.info("Discord channel initialized")
    else:
        log.debug("DISCORD_TOKEN not set — Discord channel disabled")

    if config.TEAMS_APP_ID and config.TEAMS_APP_PASSWORD:
        teams_chan.init(config.TEAMS_APP_ID, config.TEAMS_APP_PASSWORD, config.TEAMS_WEBHOOK_PORT)
        log.info("Teams channel initialized")
    else:
        log.debug("TEAMS_APP_ID not set — Teams channel disabled")

    # Web Portal (browser-based chat interface)
    if os.getenv("WEBPORTAL_ENABLED", "false").lower() == "true":
        from host.channels import web as web_chan
        web_chan.init()
        log.info(f"Web portal channel registered (port {os.getenv('WEBPORTAL_PORT', '8082')})")

    log.info(f"Channels registered: {list(all_channels().keys())}")

    # Jira webhook notify callback
    async def _notify_user(jid: str, message: str) -> None:
        minion_info = db.get_minion(jid)
        channel = minion_info["channel"] if minion_info else None
        chan = all_channels().get(channel) if channel else None
        if chan:
            await chan.send_message(jid, message)
        else:
            log.warning(f"Cannot notify {jid}: channel not available")

    jira_webhook.set_notify_callback(_notify_user)
    set_report_callback(_notify_user)

    # Message handler
    async def on_message(chat_jid: str, sender_jid: str, text: str, channel: str) -> None:
        if not is_allowed(sender_jid):
            log.warning("Blocked message from unauthorized sender: %s", sender_jid)
            return

        # Rate limit check (fixes #175)
        allowed, reason = await ratelimit.check(sender_jid)
        if not allowed:
            log.warning("Rate limited sender: %s", sender_jid)
            chan = all_channels().get(channel)
            if chan:
                await chan.send_message(chat_jid, reason)
            return

        # Immune system scan (fixes #176)
        from .immune import scan as immune_scan
        threat = immune_scan(text)
        if threat.blocked:
            log.warning("Blocked message from %s: %s (pattern=%s)", sender_jid, threat.reason, threat.pattern)
            chan = all_channels().get(channel)
            if chan:
                await chan.send_message(chat_jid, threat.reason)
            return
        if threat.reason:
            log.info("DLP warning for %s: %s", sender_jid, threat.reason)

        # Get or assign minion
        minion_info = db.get_minion(chat_jid)
        if not minion_info:
            db.register_minion(chat_jid, config.DEFAULT_MINION, channel)
            minion_info = {"minion_name": config.DEFAULT_MINION, "channel": channel}

        minion_name = minion_info["minion_name"]
        db.save_message(chat_jid, sender_jid, text, role="user")

        # Run container (serialized per chat_jid)
        lock = await queue.get_lock(chat_jid)
        async with lock:
            _run_t0 = __import__("time").time()
            try:
                result = await asyncio.wait_for(
                    runner.run_container(
                        chat_jid=chat_jid,
                        minion_name=minion_name,
                        prompt=text,
                        sender_jid=sender_jid,
                    ),
                    timeout=config.CONTAINER_TIMEOUT + 10,  # fixes #179: use config instead of hardcoded 300s
                )
            except asyncio.TimeoutError:
                log.error(f"Container run timed out for {chat_jid}")
                result = {"status": "ok", "result": "⏰ 處理超時，請稍後再試。"}

        if result and result.get("status") == "ok":
            reply = result.get("result", "")
            if reply:
                chan = all_channels().get(channel)
                if chan:
                    await chan.send_message(chat_jid, reply)
                    db.save_message(chat_jid, minion_name, reply, role="assistant")
                    from .memory import append_warm_log
                    try:
                        append_warm_log(chat_jid, text, reply)
                    except Exception as e:
                        log.warning("Failed to append warm log for %s: %s", chat_jid, e)
            # ── Host Auto-Write Fallback ────────────────────────────────────
            try:
                import datetime as _dt
                _host_memory_path = config.DATA_DIR / "MEMORY.md"
                _mem_mtime = _host_memory_path.stat().st_mtime if _host_memory_path.exists() else 0.0
                if _mem_mtime < _run_t0:
                    _date_str = _dt.datetime.now().strftime("%Y-%m-%d")
                    _prompt_preview = (text or "")[:80].replace("\n", " ")
                    _auto_entry = f"\n[{_date_str}] [auto] Task: {_prompt_preview}. Result: success.\n"
                    with open(_host_memory_path, "a", encoding="utf-8") as _mf:
                        _mf.write(_auto_entry)
                    log.info("host auto-wrote MEMORY.md fallback for %s", chat_jid)
            except Exception as _e:
                log.warning("host auto-write MEMORY.md failed: %s", _e)
        else:
            error = result.get("error", "Unknown error") if result else "No response"
            log.error(f"Container error [{chat_jid}]: {error}")
            # Always notify the user — silent failures are worse than error messages
            chan = all_channels().get(channel)
            if chan:
                error_reply = "🍌 抱歉，處理您的請求時發生了問題。請稍後再試，或換個方式描述您的需求。"
                await chan.send_message(chat_jid, error_reply)
                db.save_message(chat_jid, minion_name, error_reply, role="assistant")

    # IPC handlers
    async def on_ipc_message(data: dict) -> None:
        chat_jid = data.get("chat_jid", "")
        text = data.get("text", "")
        if not (chat_jid and text):
            return
        # Only deliver to JIDs that exist in the DB
        known_jids = {row[0] for row in db.get_conn().execute("SELECT jid FROM employees").fetchall()}
        if chat_jid not in known_jids:
            log.warning("IPC message to unknown JID %r — dropping", chat_jid)
            return
        minion_info = db.get_minion(chat_jid)
        channel = minion_info["channel"] if minion_info else "telegram"
        chan = all_channels().get(channel)
        if chan:
            await chan.send_message(chat_jid, text)

    async def on_ipc_task(data: dict) -> None:
        # Handle sub-agent spawn requests (from run_agent tool inside container)
        if data.get("type") == "spawn_agent":
            request_id = data.get("requestId", "")
            prompt = data.get("prompt", "")
            chat_jid = data.get("chat_jid", "")
            minion_name = data.get("minion_name", "")
            if not (request_id and prompt):
                log.warning("spawn_agent missing requestId or prompt — dropping")
                return
            log.info(f"spawn_agent: requestId={request_id[:8]} minion={minion_name}")
            output = ""
            try:
                result = await asyncio.wait_for(
                    runner.run_container(
                        chat_jid=chat_jid or "system",
                        minion_name=minion_name or "assistant",
                        prompt=prompt,
                    ),
                    timeout=config.CONTAINER_TIMEOUT,
                )
                output = (result or {}).get("response", "") or (result or {}).get("output", "(no response)")
            except asyncio.TimeoutError:
                output = f"Error: subagent timed out after {config.CONTAINER_TIMEOUT}s"
            except Exception as e:
                output = f"Error: {type(e).__name__}: {e}"
            # Write result to IPC results dir so container can pick it up
            results_dir = config.IPC_DIR / "results"
            results_dir.mkdir(parents=True, exist_ok=True)
            result_file = results_dir / f"{request_id}.json"
            result_file.write_text(
                __import__("json").dumps({"output": output}, ensure_ascii=False),
                encoding="utf-8",
            )
            log.info(f"spawn_agent result written: {request_id[:8]} ({len(output)} chars)")
            # Purge stale result files older than 10 minutes to prevent unbounded growth
            try:
                _now = __import__("time").time()
                for _old in results_dir.iterdir():
                    if _old.is_file() and (_now - _old.stat().st_mtime) > 600:
                        _old.unlink(missing_ok=True)
            except Exception:
                pass
            return

        # Handle task cancellation requests
        if data.get("action") == "cancel":
            task_id = data.get("task_id", "")
            if task_id:
                cancelled = db.cancel_scheduled_task(task_id)
                log.info(f"Task cancel request: {task_id} → {'done' if cancelled else 'not found'}")
            return
        if not _validate_ipc_task(data, log):
            return
        db.upsert_scheduled_task(data)

    async def run_scheduled_task(task: dict) -> None:
        chat_jid = task.get("chat_jid", "")
        minion_name = task.get("minion_name", "")
        prompt = task.get("prompt", "")
        if not (chat_jid and minion_name and prompt):
            log.error("Scheduled task missing required fields: %s", list(task.keys()))
            if task.get("id"):
                db.mark_task_error(task["id"], "Missing required fields")
            return
        try:
            result = await asyncio.wait_for(
                runner.run_container(
                    chat_jid=chat_jid,
                    minion_name=minion_name,
                    prompt=prompt,
                ),
                timeout=config.CONTAINER_TIMEOUT,
            )
        except asyncio.TimeoutError:
            log.error("Scheduled task timed out for %s", chat_jid)
            return
        if not result or result.get("status") != "ok":
            error = (result or {}).get("error", "No response")
            log.error("Scheduled task failed for %s: %s", chat_jid, error)

    # Notification loop
    _purge_counter = 0
    async def notification_loop() -> None:
        nonlocal _purge_counter
        while True:
            await asyncio.sleep(30)
            notifs = db.get_pending_notifications()
            for notif_id, target_jid, message in notifs:
                try:
                    minion_info = db.get_minion(target_jid)
                    channel = minion_info["channel"] if minion_info else None
                    chan = all_channels().get(channel) if channel else None
                    if chan:
                        await chan.send_message(target_jid, message)
                        db.mark_notification_sent(notif_id)
                    else:
                        log.warning(f"Cannot notify {target_jid}: channel not available")
                except Exception as e:
                    log.error(f"notification delivery error: {type(e).__name__}: {e}")
            # Purge old sent notifications once per hour (every 120 iterations × 30s)
            _purge_counter += 1
            if _purge_counter >= 120:
                _purge_counter = 0
                try:
                    n = db.purge_old_notifications()
                    if n:
                        log.info("Purged %d old sent notifications", n)
                except Exception:
                    pass

    async def _expiry_loop() -> None:
        """Check workflow expiry and send reminders daily."""
        from .enterprise.workflow import check_expiry_and_reminders
        expiry_log = get_logger("expiry")
        while True:
            await asyncio.sleep(3600)  # Check every hour
            try:
                count = check_expiry_and_reminders()
                if count:
                    expiry_log.info(f"Workflow expiry check: {count} workflows processed")
            except Exception as e:
                expiry_log.error(f"Expiry check failed: {e}")

    # ── Phase 2: MemorySummarizer + SdkApi ─────────────────────────────────
    try:
        from .memory.summarizer import MemorySummarizer as _MemorySummarizer
        _summarizer = _MemorySummarizer()
        log.info("[Phase 2] MemorySummarizer initialized")
    except Exception as _e:
        _summarizer = None
        log.warning(f"[Phase 2] MemorySummarizer unavailable: {_e}")

    try:
        from .sdk_api import SdkApi as _SdkApi
        _memory_bus_ref = None
        try:
            from .memory_bus.memory_bus import MemoryBus as _MB
            _memory_bus_ref = _MB()
        except Exception:
            pass
        _sdk_api = _SdkApi(memory_bus=_memory_bus_ref)
        asyncio.ensure_future(_sdk_api.start())
        log.info("[Phase 2] SdkApi started on port 8770")
    except Exception as _e:
        _sdk_api = None
        log.warning(f"[Phase 2] SdkApi unavailable: {_e}")

    # ── Phase 3: BotRegistry + Matrix channel ──────────────────────────────
    try:
        from .identity.bot_registry import BotRegistry as _BotReg, bootstrap_known_bots as _boot_bots
        _bot_reg = _BotReg()
        _boot_bots(_bot_reg)
        log.info("[Phase 3] BotRegistry initialized — 小白/小Eve/MinionDesk registered")
    except Exception as _e:
        log.warning(f"[Phase 3] BotRegistry unavailable: {_e}")

    if os.getenv("MATRIX_ACCESS_TOKEN"):
        try:
            import host.channels.matrix as matrix_chan
            matrix_chan.init()
            log.info("[Phase 3] Matrix channel initialized")
        except Exception as _e:
            log.warning(f"[Phase 3] Matrix channel unavailable: {_e}")

    # Start all channels
    channel_tasks = []
    for name, chan in all_channels().items():
        channel_tasks.append(chan.start(on_message))

    from .health import start_health_server

    # Graceful shutdown on SIGTERM/SIGINT
    loop = asyncio.get_running_loop()
    _signal_count = [0]  # 用 list 讓雙層 closure 可以 mutate（Fix #159）

    async def _safe_shutdown():
        try:
            await _shutdown()
        except Exception as e:
            log.error(f"Shutdown error: {e}")

    def _make_signal_handler():
        def _handler():
            _signal_count[0] += 1
            if _signal_count[0] >= 2:
                # 第二次 Ctrl+C：強制 kill 所有 miniondesk- container 並立即退出
                log.warning("Force exit (second signal). Killing all containers...")
                import subprocess as _sp
                try:
                    result = _sp.run(
                        ["docker", "ps", "-q", "--filter", "name=miniondesk-"],
                        capture_output=True, timeout=3,
                    )
                    ids = result.stdout.decode().split()
                    if ids:
                        _sp.run(["docker", "kill"] + ids, capture_output=True, timeout=5)
                except Exception:
                    pass
                import os as _os
                _os._exit(1)
            asyncio.create_task(_safe_shutdown())
        return _handler

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _make_signal_handler())

    results = await asyncio.gather(
        *channel_tasks,
        ipc.watch_ipc(config.IPC_DIR, on_ipc_message, on_ipc_task),
        scheduler.run_scheduler(run_scheduled_task),
        notification_loop(),
        start_health_server(port=8080),
        _expiry_loop(),
        weekly_report_loop(),
        *([start_portal(on_message)] if os.getenv("WEBPORTAL_ENABLED", "false").lower() == "true" else []),
        *([jira_webhook.start_jira_webhook()] if os.getenv("JIRA_WEBHOOK_ENABLED", "false").lower() == "true" else []),
        *([start_dashboard()] if os.getenv("DASHBOARD_ENABLED", "false").lower() == "true" else []),
        return_exceptions=True,
    )
    # Log any task failures instead of crashing
    # TODO: add task names for better error attribution
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            log.error(f"Task {i} failed: {type(result).__name__}: {result}", exc_info=True)


_shutting_down = False


async def _shutdown():
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    log = get_logger("main")
    log.info("Shutting down gracefully...")

    # Disconnect channels FIRST so Telegram/Discord can stop cleanly
    # before asyncio tasks are cancelled.  Reversing this order causes
    # python-telegram-bot's update_fetcher_task to be cancelled while
    # app.stop() is still running, producing a misleading CRITICAL log.
    try:
        from host.channels import all_channels
        for name, chan in all_channels().items():
            if hasattr(chan, "disconnect"):
                try:
                    await chan.disconnect()
                except Exception as e:
                    log.warning("Channel %s disconnect error: %s", name, e)
    except Exception as e:
        log.warning("Channel disconnect phase error: %s", e)

    tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    # 加 5 秒 timeout 防止 cleanup 本身卡住（Fix #159）
    try:
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=5.0,
        )
    except asyncio.TimeoutError:
        log.warning("Task cleanup timed out — forcing exit")


if __name__ == "__main__":
    asyncio.run(main())
