#!/usr/bin/env python3
"""
MinionDesk Container Runner
Reads JSON from stdin, runs agentic loop, writes JSON to stdout.
Uses MinionDesk's isolated container pattern.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re as _re
import sys
import traceback
from pathlib import Path

MAX_TURNS = 30

_TOOL_TIMEOUT = float(os.getenv("TOOL_TIMEOUT_SECONDS", "60"))

_ALLOWED_SECRET_KEYS = _re.compile(
    r'^(OPENAI_API_KEY|ANTHROPIC_API_KEY|GOOGLE_API_KEY|NETAPP_PASSWORD|GPFS_PASSWORD|'
    r'CONFLUENCE_TOKEN|SHAREPOINT_TOKEN|JIRA_TOKEN|LDAP_PASSWORD|'
    r'SMTP_PASSWORD|EMAIL_PASSWORD|TELEGRAM_TOKEN|DISCORD_TOKEN|'
    r'DOMINO_PASSWORD|DOMINO_AUTH_TOKEN|OLLAMA_URL|OLLAMA_MODEL|'
    r'LLM_PROVIDER|CLAUDE_MODEL|GEMINI_MODEL|OPENAI_MODEL|OPENAI_BASE_URL|'
    r'GITHUB_TOKEN|GH_TOKEN)$'
)

log = logging.getLogger(__name__)

def _slog(tag: str, msg: str = "") -> None:
    """Structured stderr log with emoji tags (mirrors EvoClaw _log style)."""
    import time as _time
    ts = _time.strftime('%H:%M:%S') + f'.{int(_time.time() * 1000) % 1000:03d}'
    print(f"[{ts}] {tag} {msg}", file=sys.stderr, flush=True)

# Module-level secrets store — avoids writing secrets into os.environ where
# they are visible to all subprocesses and may be logged inadvertently.
# Tools should call get_secret(key) instead of os.getenv(key).
_secrets: dict[str, str] = {}


def get_secret(key: str) -> str:
    """Retrieve a secret by key from the in-process secrets store."""
    return _secrets.get(key, "")


async def run(inp: dict) -> dict:
    # Load secrets into module-level dict rather than os.environ to limit
    # exposure. Only keys matching the allowlist are accepted.
    # TODO: migrate tool implementations to call get_secret() instead of
    # os.getenv() so that os.environ writes below can be removed entirely.
    _secrets.clear()
    for key, val in inp.get("secrets", {}).items():
        if not _ALLOWED_SECRET_KEYS.match(key):
            continue
        if not isinstance(val, str):
            continue
        _secrets[key] = val
        # Keep os.environ in sync only for keys that tools currently read via
        # os.getenv(). The set written is strictly limited to _ALLOWED_SECRET_KEYS.
        os.environ[key] = val

    # ── Auto-authenticate gh CLI + git credential helper ─────────────────────
    # gh auth login  → authenticates gh CLI (gh repo create, gh pr create, etc.)
    # gh auth setup-git → configures git credential helper so git push via HTTPS works
    _gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN", "")
    if _gh_token:
        import subprocess as _subprocess
        try:
            _gh_result = _subprocess.run(
                ["gh", "auth", "login", "--with-token"],
                input=_gh_token.encode(),
                capture_output=True,
                timeout=10,
            )
            if _gh_result.returncode == 0:
                _slog("🔑 GH AUTH", "gh CLI authenticated ✓")
                # Configure git credential helper so git push/pull via HTTPS uses the token
                _subprocess.run(["gh", "auth", "setup-git"], capture_output=True, timeout=10)
                _slog("🔑 GH AUTH", "git credential helper configured ✓")
                # Set git identity so commits don't fail with "Please tell me who you are"
                _subprocess.run(["git", "config", "--global", "user.email", "minion@miniondesk.local"], capture_output=True)
                _subprocess.run(["git", "config", "--global", "user.name", "MinionDesk Agent"], capture_output=True)
            else:
                _slog("⚠️ GH AUTH", f"gh auth failed: {_gh_result.stderr.decode(errors='replace')[:200]}")
        except FileNotFoundError:
            _slog("⚠️ GH AUTH", "gh CLI not installed in container")
        except Exception as _gh_exc:
            _slog("⚠️ GH AUTH", f"gh auth error: {_gh_exc}")
    else:
        _slog("⚠️ GH AUTH", "no GITHUB_TOKEN in secrets — gh CLI unauthenticated")

    from providers.auto import get_provider
    from tools import build_registry, ToolContext

    provider = get_provider()
    registry = build_registry(inp.get("enabledTools", []))

    ctx = ToolContext(
        chat_jid=inp.get("chatJid", ""),
        minion_name=inp.get("minionName", "phil"),
        ipc_dir=inp.get("ipcDir", "/workspace/ipc"),
        data_dir=inp.get("dataDir", "/workspace/data"),
        sender_jid=inp.get("senderJid", ""),
        allowed_paths=inp.get("allowedPaths", ["/workspace"]),
        scheduled_tasks=inp.get("scheduledTasks", []),
    )

    system = inp.get("personaMd", "You are a helpful assistant.")

    # ── CRITICAL tool usage rules (appended to every persona) ─────────────────
    system += (
        "\n\n## CRITICAL: Tool Usage Rules\n"
        "NEVER write bash/shell code blocks (```bash ... ```) in your response. This does NOTHING — the code will not be executed.\n"
        "NEVER write fake status lines like *(正在執行...)*, *(running...)*, *(executing...)*, [正在處理...] etc. — these are pure text and DO NOTHING.\n"
        "NEVER narrate or describe what you plan to do. Just DO it immediately by calling the appropriate tool.\n"
        "ALWAYS call the Bash tool directly to run any shell command. Every command you want to run MUST be a Bash tool call.\n"
        "If you need to run multiple commands, make multiple Bash tool calls. Do not describe what you would do — DO IT."
    )

    # Prepend conversation history to system prompt
    conv_history = inp.get("conversationHistory", "")
    if conv_history:
        system += f"\n\n## 近期對話記錄\n{conv_history}"

    hints = inp.get("hints", "")
    if hints:
        system += "\n\n---\n" + hints

    _slog("🚀 START", f"minion={inp.get('personaName', 'unknown')}")
    _slog("💬 USER", str(inp.get('prompt', ''))[:400])
    _slog("📋 SYSTEM", f"{len(system)} chars")
    # Log first 600 chars of system (persona)
    for _line in system[:600].split('\n'):
        if _line.strip():
            _slog("📋", _line[:120])
    # Log conversation history
    conv = inp.get('conversationHistory', [])
    _slog("📚 HISTORY", f"{len(conv)} turns")
    for _hmsg in (conv[-3:] if conv else []):
        _slog(f"📚 [{str(_hmsg.get('role','?')).upper()}]", str(_hmsg.get('content',''))[:200])

    from providers import Message
    history: list[Message] = [
        Message(role="user", content=inp.get("prompt", ""))
    ]

    schemas = registry.schemas()

    final_response = None
    for turn in range(MAX_TURNS):
        try:
            _slog("🧠 LLM →", f"turn={turn}")
            resp = await provider.complete(history, schemas, system)
            _slog("🧠 LLM ←", f"stop={getattr(resp, 'stop_reason', 'done')}")
        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"Provider error on turn {turn}: {tb}")
            return {
                "status": "error",
                "error": f"Provider error on turn {turn}: {type(e).__name__}: {e}",
            }

        if resp.finish_reason == "stop" or not resp.tool_calls:
            # ── Fallback: detect bash code blocks the model forgot to run ─────
            # Some models output ```bash blocks as text instead of calling the
            # Bash tool. Auto-execute them and feed results back.
            import re as _re_cb
            _content = resp.content or ""
            _code_blocks = _re_cb.findall(r'```(?:bash|sh|shell)?\n([\s\S]*?)```', _content)
            _runnable = [b.strip() for b in _code_blocks if b.strip()]
            if _runnable and turn < MAX_TURNS - 1:
                _slog("⚠️ AUTO-EXEC", f"model output {len(_runnable)} code block(s) as text — auto-executing")
                _exec_outputs = []
                for _cmd in _runnable:
                    _slog("🔧 TOOL", f"Bash (fallback) args={_cmd[:300]}")
                    try:
                        _res = await asyncio.wait_for(
                            asyncio.to_thread(registry.execute, "Bash", {"command": _cmd}, ctx),
                            timeout=_TOOL_TIMEOUT,
                        )
                    except Exception as _exec_e:
                        _res = f"Error: {_exec_e}"
                    _slog("🔧 RESULT", str(_res)[:1500])
                    _exec_outputs.append(f"$ {_cmd[:200]}\n{_res}")
                _combined = "\n\n".join(_exec_outputs)
                history.append(Message(
                    role="user",
                    content=f"[系統自動執行了 {len(_runnable)} 個指令]\n{_combined}\n\n請根據以上輸出，繼續任務並回報最終結果。",
                ))
                continue

            # ── Fallback 2: detect fake status lines *(正在...)* etc. ──────────
            # Some models write *(正在執行...)* / *(running...)* as pure text instead
            # of calling tools. Re-prompt them to actually use tools. (Fix #161)
            _FAKE_STATUS_RE = _re_cb.compile(r'\*\([^)]*\)\*|\*\[[^\]]*\]\*', _re_cb.DOTALL)
            _fake_hits = _FAKE_STATUS_RE.findall(_content)
            if _fake_hits and turn < MAX_TURNS - 1:
                _slog("⚠️ FAKE-STATUS", f"model wrote {len(_fake_hits)} fake status line(s) — re-prompting")
                history.append(Message(
                    role="user",
                    content=(
                        "【系統警告】你剛才的回覆包含假狀態行（例如 *(正在執行...)* ），"
                        "這些純文字根本沒有執行任何命令。\n"
                        "請停止用文字描述或模擬動作，立即直接呼叫 Bash tool（或其他工具）實際執行所需命令。\n"
                        "記住：只有呼叫工具才能執行任何操作，文字描述對系統沒有任何作用。"
                    ),
                ))
                continue

            # No code blocks, no fake status — model is genuinely done
            final_response = _content
            _slog("📤 REPLY", str(final_response)[:600] if final_response is not None else '')
            _slog("🏁 DONE", "success=True")
            return {"status": "ok", "result": resp.content}

        # Append assistant message with tool calls
        history.append(Message(
            role="assistant",
            content=resp.content,
            tool_calls=resp.tool_calls,
        ))

        # Execute each tool call
        for tc in resp.tool_calls:
            _slog("🔧 TOOL", f"{tc.name} args={str(getattr(tc, 'arguments', tc.args))[:1500]}")
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(registry.execute, tc.name, tc.args, ctx),
                    timeout=_TOOL_TIMEOUT,
                )
            except asyncio.TimeoutError:
                result = f"Error: tool '{tc.name}' timed out after {_TOOL_TIMEOUT}s"
            except Exception as e:
                tb = traceback.format_exc()
                log.error("Tool '%s' raised an exception: %s", tc.name, tb)
                result = f"Error: tool '{tc.name}' raised {type(e).__name__}: {e}"
            _slog("🔧 RESULT", str(result)[:1500])
            history.append(Message(role="tool", content=result, tool_call_id=tc.id))

    _slog("📤 REPLY", str(final_response)[:600] if final_response is not None else '')
    _slog("🏁 DONE", "success=False max_turns_reached")
    return {
        "status": "error",
        "error": f"Max turns ({MAX_TURNS}) reached without completion.",
    }


def main():
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.DEBUG,
        format='[%(asctime)s.%(msecs)03d] %(levelname)s %(message)s',
        datefmt='%H:%M:%S',
        force=True,
    )
    raw = sys.stdin.read()
    try:
        inp = json.loads(raw)
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "error", "error": f"Invalid JSON input: {e}"}))
        sys.exit(1)

    if not isinstance(inp, dict):
        print(json.dumps({"status": "error", "error": f"Expected JSON object, got {type(inp).__name__}"}))
        sys.exit(1)

    result = asyncio.run(run(inp))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
