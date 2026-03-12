"""Docker container runner for MinionDesk minions."""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import config

# Allowed characters in a minion name (prevent path traversal via DB value)
_MINION_NAME_RE = re.compile(r'^[A-Za-z0-9_-]{1,64}$')

logger = logging.getLogger(__name__)

# Per-group failure tracking (circuit breaker)
_group_fail_counts: dict[str, int] = {}
_group_fail_time: dict[str, float] = {}
_group_lock = threading.Lock()

# Container concurrency semaphore — limits simultaneous Docker runs
# Uses CONTAINER_MAX_CONCURRENT from config (default 4)
# Replaces old global asyncio.Lock which serialized ALL groups
_container_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _container_semaphore
    if _container_semaphore is None:
        _container_semaphore = asyncio.Semaphore(config.CONTAINER_MAX_CONCURRENT)
    return _container_semaphore


# Required keys in container JSON output (schema validation)
_REQUIRED_OUTPUT_KEYS = frozenset({"status", "result"})


def _is_windows() -> bool:
    return sys.platform == "win32"


def _docker_path(path: str) -> str:
    """Convert host path to Docker-compatible path (handles Windows)."""
    if _is_windows():
        # Convert C:\... to /c/...
        p = path.replace("\\", "/")
        if len(p) > 1 and p[1] == ":":
            p = "/" + p[0].lower() + p[2:]
        return p
    return path


async def _stop_container(name: str) -> None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "stop", "--time", "10", name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    except Exception:
        pass


async def run_minion(
    group_jid: str,
    group_folder: str,
    minion_name: str,
    prompt: str,
    chat_jid: str,
    enabled_tools: list[str] | None = None,
    request_id: str = "",
) -> dict[str, Any]:
    """
    Spin up a Docker container, run the minion, return result.
    Circuit breaker: 5 failures → 60s cooldown per group.
    """
    # Circuit breaker check
    with _group_lock:
        fail_count = _group_fail_counts.get(group_jid, 0)
        if fail_count >= config.CONTAINER_MAX_FAILS:
            since = time.time() - _group_fail_time.get(group_jid, 0)
            if since < config.CONTAINER_FAIL_COOLDOWN:
                return {
                    "status": "error",
                    "result": f"⚠️ Container circuit breaker open ({fail_count} failures). Retry in {int(config.CONTAINER_FAIL_COOLDOWN - since)}s.",
                }
            else:
                _group_fail_counts[group_jid] = 0

    rid = f"[{request_id}] " if request_id else ""

    # Validate group_folder to prevent path traversal via special characters
    if not re.match(r'^[\w\-]+$', group_folder):
        logger.error(
            "%sInvalid group_folder rejected (potential path traversal): %r",
            rid, group_folder,
        )
        raise ValueError(f"Invalid group_folder {group_folder!r}: must be alphanumeric/hyphens only")

    # Validate minion name to prevent path traversal via DB-stored values
    if not _MINION_NAME_RE.match(minion_name):
        logger.error(
            "%sInvalid minion name rejected (potential path traversal): %r",
            rid, minion_name,
        )
        return {"status": "error", "result": f"Invalid minion name: {minion_name!r}"}

    # Load persona
    persona_path = Path(config.MINIONS_DIR) / f"{minion_name}.md"
    persona_md = persona_path.read_text(encoding="utf-8") if persona_path.exists() else f"You are {minion_name}, a helpful assistant."

    # Load CLAUDE.md — global + per-group (evoclaw-style behavioral injection)
    global_claude_path = Path(config.GROUPS_DIR) / "global" / "CLAUDE.md"
    global_claude_md = global_claude_path.read_text(encoding="utf-8") if global_claude_path.exists() else ""

    group_claude_path = Path(config.GROUPS_DIR) / group_folder / "CLAUDE.md"
    group_claude_md = group_claude_path.read_text(encoding="utf-8") if group_claude_path.exists() else ""

    # Genome-based behavioral hints
    from . import db
    from .evolution import genome_hints
    from .skills_engine import get_installed_skill_docs
    hints = genome_hints(group_jid)

    # Installed Superpowers skill docs (injected into system prompt)
    skill_docs = get_installed_skill_docs()

    # Load conversation history
    conv_history = []
    try:
        raw_history = db.get_history(group_jid, limit=20)
        for h in raw_history:
            role = h.get("role", "user")
            content = str(h.get("content", "")).strip()
            if content:
                conv_history.append({"role": role, "content": content})
    except Exception as exc:
        logger.warning("Failed to load conversation history: %s", exc)

    payload = {
        "prompt": prompt,
        "personaMd": persona_md,
        "globalClaudeMd": global_claude_md,
        "groupClaudeMd": group_claude_md,
        "skillDocs": skill_docs,          # Superpowers skill instructions
        "hints": hints,
        "chatJid": chat_jid,
        "enabledTools": enabled_tools,
        "assistantName": config.ASSISTANT_NAME,
        "conversationHistory": conv_history,
    }

    # Mount dirs
    groups_dir       = _docker_path(str(Path(config.GROUPS_DIR).resolve()))
    group_dir        = _docker_path(str((Path(config.GROUPS_DIR) / group_folder).resolve()))
    base_dir         = _docker_path(str(Path(config.BASE_DIR).resolve()))

    # Dynamic tools dir — skills with container_tools: install here; container auto-imports
    dynamic_tools_host = Path(config.BASE_DIR) / "dynamic_tools"
    dynamic_tools_host.mkdir(parents=True, exist_ok=True)
    dynamic_tools_docker = _docker_path(str(dynamic_tools_host.resolve()))

    # Include milliseconds + short UUID to avoid name collisions when multiple
    # requests for the same group arrive within the same second.
    container_name = f"minion-{group_folder}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:6]}"

    mounts = [
        f"{group_dir}:/workspace/group",
        f"{base_dir}:/workspace/project:ro",
        f"{dynamic_tools_docker}:/app/dynamic_tools:ro",   # hot-swap skill tools
    ]

    # Forward relevant env vars
    env_vars = []
    for key in [
        "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "OLLAMA_URL", "OPENAI_BASE_URL", "OPENAI_MODEL",
        "GEMINI_MODEL", "CLAUDE_MODEL", "OLLAMA_MODEL",
    ]:
        val = os.getenv(key)
        if val:
            env_vars.extend(["-e", f"{key}={val}"])

    # Build docker run command
    cmd = [
        "docker", "run", "--rm",
        "--name", container_name,
        "--network", "none",        # No internet from container
        "--memory", "512m",
        "--cpus", "1.0",
    ]
    for mount in mounts:
        cmd.extend(["-v", mount])
    cmd.extend(env_vars)
    cmd.append(config.CONTAINER_IMAGE)

    logger.info("%sStarting container %s for group %s", rid, container_name, group_jid)

    stdin_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    # Semaphore limits concurrent running Docker containers (configurable, default 4).
    # Held across the FULL container lifetime (spawn + communicate) so that
    # CONTAINER_MAX_CONCURRENT accurately caps how many containers run simultaneously.
    semaphore = _get_semaphore()
    async with semaphore:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:
            logger.error("%sFailed to start container: %s", rid, exc)
            with _group_lock:
                _group_fail_counts[group_jid] = _group_fail_counts.get(group_jid, 0) + 1
                _group_fail_time[group_jid] = time.time()
            return {"status": "error", "result": f"Failed to start container: {exc}"}

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(stdin_data),
                timeout=config.CONTAINER_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error("Container %s timed out after %ds", container_name, config.CONTAINER_TIMEOUT)
            try:
                await _stop_container(container_name)
            except Exception:
                pass
            return {"status": "error", "result": "⏱️ Request timed out. Please try again."}
        except asyncio.CancelledError:
            logger.warning("Container %s cancelled", container_name)
            # Terminate the subprocess handle first (immediate SIGKILL on the
            # docker process), then send docker stop for the named container.
            try:
                proc.kill()
            except Exception:
                pass
            try:
                await _stop_container(container_name)
            except Exception:
                pass
            # Count cancellations against the circuit breaker so repeated
            # cancellations (e.g. from upstream timeouts) are tracked correctly.
            with _group_lock:
                _group_fail_counts[group_jid] = _group_fail_counts.get(group_jid, 0) + 1
                _group_fail_time[group_jid] = time.time()
            raise

    # Guard against runaway containers emitting giant outputs (OOM risk)
    max_bytes = config.CONTAINER_MAX_OUTPUT_BYTES
    if max_bytes > 0 and len(stdout) > max_bytes:
        logger.error(
            "%sContainer %s stdout exceeded size limit: %d > %d bytes — truncating and failing",
            rid, container_name, len(stdout), max_bytes,
        )
        with _group_lock:
            _group_fail_counts[group_jid] = _group_fail_counts.get(group_jid, 0) + 1
            _group_fail_time[group_jid] = time.time()
        return {"status": "error", "result": "Container output exceeded size limit."}

    # Log stderr at INFO level for emoji-tagged lines
    if stderr:
        for line in stderr.decode("utf-8", errors="replace").splitlines():
            if any(e in line for e in ["🚀","🤖","🔧","📥","📤","✅","❌","⚠️","🔄","📝"]):
                logger.info("container[%s]: %s", container_name, line)
            else:
                logger.debug("container[%s]: %s", container_name, line)

    # Parse output
    stdout_str = stdout.decode("utf-8", errors="replace")
    start_marker = "<<<MINIONDESK_OUTPUT_START>>>"
    end_marker   = "<<<MINIONDESK_OUTPUT_END>>>"
    if start_marker in stdout_str and end_marker in stdout_str:
        start = stdout_str.index(start_marker) + len(start_marker)
        end   = stdout_str.index(end_marker)
        json_str = stdout_str[start:end].strip()
        try:
            result = json.loads(json_str)
            # Schema validation: ensure required keys present
            missing = _REQUIRED_OUTPUT_KEYS - result.keys()
            if missing:
                logger.error(
                    "%sContainer output missing required keys %s | output: %.200s",
                    rid, missing, json_str[:200],
                )
                with _group_lock:
                    _group_fail_counts[group_jid] = _group_fail_counts.get(group_jid, 0) + 1
                    _group_fail_time[group_jid] = time.time()
                return {"status": "error", "result": f"Container output schema error: missing {missing}"}
            with _group_lock:
                _group_fail_counts[group_jid] = 0
            return result
        except json.JSONDecodeError as exc:
            logger.error("%sJSON parse error: %s | output: %.200s", rid, exc, stdout_str[-500:])
            with _group_lock:
                _group_fail_counts[group_jid] = _group_fail_counts.get(group_jid, 0) + 1
                _group_fail_time[group_jid] = time.time()
            return {"error": f"JSON parse failed: {exc}", "reply": "⚠️ 處理發生錯誤，請重試。"}
    else:
        logger.error("No output markers in container stdout")

    with _group_lock:
        _group_fail_counts[group_jid] = _group_fail_counts.get(group_jid, 0) + 1
        _group_fail_time[group_jid] = time.time()
    return {"status": "error", "result": "No valid output from container."}
