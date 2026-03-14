"""
Docker Container Runner
Spawns minion containers and collects results.
"""
from __future__ import annotations
import asyncio
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Optional

from . import config, db
from .logger import get_logger
from .memory import get_hot_memory, update_hot_memory
_log = get_logger("runner")

_MINION_NAME_RE = re.compile(r'^[a-zA-Z0-9_\-]+$')


async def run_container(
    chat_jid: str,
    minion_name: str,
    prompt: str,
    sender_jid: str = "",
    hints: str = "",
) -> Optional[dict]:
    """Spawn a minion container and return its result."""

    # Validate minion_name against path-safe regex
    if not _MINION_NAME_RE.match(minion_name):
        raise ValueError(f"Invalid minion name: {minion_name!r}")

    # Validate minion_name against allowlist
    # None means "not configured" = allow all; empty list = deny all
    available = getattr(config, 'AVAILABLE_MINIONS', None)
    if available is not None:
        if minion_name not in available:
            raise ValueError(f"Minion {minion_name!r} not in AVAILABLE_MINIONS allowlist")

    # Load persona
    persona_path = config.MINIONS_DIR / f"{minion_name}.md"
    if not persona_path.exists():
        persona_path = config.MINIONS_DIR / "phil.md"
    persona_md = persona_path.read_text(encoding="utf-8")

    # Load conversation history (last 50 messages)
    history = db.get_conversation_history(chat_jid, limit=50)
    history_text = ""
    if history:
        lines = []
        for msg in history:
            role = "User" if msg["role"] == "user" else "Assistant"
            lines.append(f"[{msg['ts'][:16]}] {role}: {msg['content'][:200]}")
        history_text = "\n".join(lines)

    # Load hot memory
    hot_memory = get_hot_memory(chat_jid)

    # Inject scheduled tasks for this chat so agent can list/cancel them
    tasks_for_chat = db.get_scheduled_tasks_for_chat(chat_jid)
    tasks_summary = [
        {"id": t["id"], "schedule_type": t.get("schedule_type"),
         "schedule_value": t.get("schedule_value"), "last_run": t.get("last_run"),
         "status": t.get("status", "active")}
        for t in tasks_for_chat
    ]

    # Build stdin payload
    payload = {
        "chatJid": chat_jid,
        "minionName": minion_name,
        "senderJid": sender_jid,
        "prompt": prompt,
        "personaMd": persona_md,
        "hints": hints,
        "conversationHistory": history_text,
        "hotMemory": hot_memory,
        "scheduledTasks": tasks_summary,
        "enabledTools": config.DEFAULT_TOOLS,
        "ipcDir": str(config.IPC_DIR),
        "dataDir": str(config.DATA_DIR),
        "allowedPaths": [
            str(config.IPC_DIR),
            str(config.DATA_DIR),
            "/workspace",
        ],
        "secrets": config.get_secrets(),
    }
    stdin_json = json.dumps(payload, ensure_ascii=False)

    # Docker command
    cmd = [
        "docker", "run", "--rm",
        "--network", config.DOCKER_NETWORK,
        f"--memory={config.DOCKER_MEMORY}",
        "--memory-swap", config.DOCKER_MEMORY,
        f"--cpus={os.getenv('DOCKER_CPUS', '1.0')}",
        "-i",
        "-v", f"{config.IPC_DIR}:/workspace/ipc",
        "-v", f"{config.DATA_DIR}:/workspace/data",
        config.DOCKER_IMAGE,
    ]

    proc = None
    _run_id = str(uuid.uuid4())[:8]
    _started_at = time.time()
    try:
        db.log_container_start(_run_id, chat_jid, minion_name, _started_at)
    except Exception:
        pass
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(stdin_json.encode()),
            timeout=config.CONTAINER_TIMEOUT,
        )

        _finished_at = time.time()
        _response_ms = int((_finished_at - _started_at) * 1000)
        _stderr_str = stderr.decode(errors="replace") if stderr else ""
        _stdout_preview = stdout.decode(errors="replace")[:200] if stdout else ""

        if stderr:
            _log.warning(f"container stderr [{minion_name}]: {_stderr_str[:500]}")

        if not stdout.strip():
            db.log_container_finish(_run_id, _finished_at, "error", _stderr_str, _stdout_preview, _response_ms)
            return {"status": "error", "error": "Container produced no output"}

        result = json.loads(stdout.decode())
        db.log_container_finish(_run_id, _finished_at, "success", _stderr_str, _stdout_preview, _response_ms)
        if isinstance(result, dict) and result.get("memory_patch"):
            try:
                update_hot_memory(chat_jid, result["memory_patch"])
            except Exception:
                pass
        return result

    except asyncio.TimeoutError:
        if proc is not None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
        db.log_container_finish(_run_id, time.time(), "timeout", "Container timed out", "", int(config.CONTAINER_TIMEOUT * 1000))
        return {"status": "error", "error": f"⏱️ 處理超時（{config.CONTAINER_TIMEOUT}秒），請稍後再試。"}
    except asyncio.CancelledError:
        # shutdown 時 task.cancel() 觸發 — 立即 kill container，不讓 Docker 程序繼續跑
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
        raise  # 必須 re-raise，讓 asyncio 正確完成 cancellation
    except json.JSONDecodeError as e:
        preview = stdout[:200] if stdout else b"(empty)"
        _log.error(f"Container JSON decode error: {e} | stdout preview: {preview!r}")
        _err_str = f"Container output parse error: {e}"
        db.log_container_finish(_run_id, time.time(), "error", _err_str, preview.decode(errors="replace"), int((time.time() - _started_at) * 1000))
        return {"status": "error", "error": _err_str, "raw": preview.decode(errors="replace")}
    except FileNotFoundError:
        db.log_container_finish(_run_id, time.time(), "error", "Docker not found", "", int((time.time() - _started_at) * 1000))
        return {"status": "error", "error": "❌ Docker 未安裝或未啟動，請確認 Docker 服務正在運行。"}
    except Exception as e:
        db.log_container_finish(_run_id, time.time(), "error", str(e), "", int((time.time() - _started_at) * 1000))
        return {"status": "error", "error": f"❌ 系統錯誤：{e}"}
