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
        "If you need to run multiple commands, make multiple Bash tool calls. Do not describe what you would do — DO IT.\n"
        "NEVER send a fake progress report via send_message unless you have ACTUALLY run tools (Bash/Read/Write/etc.) in that same turn. Fabricating progress ('I am processing...', '3 minutes remaining...') is strictly forbidden.\n"
        "If you are stuck or do not know how to proceed, call run_agent to delegate the task to a subagent instead of faking progress."
    )

    # ── 靈魂規則 (Soul Rules) — 從 soul.md 讀取 ──────────────────────────────
    # soul.md 與 runner.py 同目錄，更新靈魂規則只需編輯該檔案，無需動 Python code。
    # {{DATA_DIR}} 為執行時替換的佔位符，指向此 minion 的資料目錄。
    _data_dir = inp.get("dataDir", "/workspace/data")
    _soul_path = os.path.join(os.path.dirname(__file__), "soul.md")
    if os.path.exists(_soul_path):
        try:
            with open(_soul_path, encoding="utf-8") as _sf:
                _soul_text = _sf.read().strip()
            _soul_text = _soul_text.replace("{{DATA_DIR}}", str(_data_dir))
            system += "\n\n" + _soul_text
            _slog("🧠 SOUL", f"Injected soul.md ({len(_soul_text)} chars)")
        except Exception as _soul_err:
            _slog("⚠️ SOUL", f"Failed to read soul.md: {_soul_err}")

    # ── MEMORY.md 啟動注入（長期記憶 + 身份）────────────────────────────────────
    # 智慧分割：身份區段永遠完整保留，任務記錄取最後 3000 字元（防止截斷身份）。
    # 若缺少身份區段 → 注入模板 + 填寫指令（身份引導 Bootstrap）。
    import os as _os
    _memory_path = _os.path.join(_data_dir, "MEMORY.md")
    _IDENTITY_MARKER = "## 身份 (Identity)"
    _TASK_MARKER = "## 任務記錄 (Task Log)"
    if _os.path.exists(_memory_path):
        try:
            with open(_memory_path, encoding="utf-8") as _mf:
                _memory_content = _mf.read().strip()
            if _memory_content:
                if _IDENTITY_MARKER in _memory_content and _TASK_MARKER in _memory_content:
                    _id_end = _memory_content.index(_TASK_MARKER)
                    _identity_part = _memory_content[:_id_end].strip()
                    _task_part = _memory_content[_id_end:][-3000:]
                    _memory_snippet = _identity_part + "\n\n" + _task_part
                else:
                    _memory_snippet = _memory_content[-4000:]
                system += (
                    f"\n\n## 長期記憶 (MEMORY.md)\n"
                    f"以下是你在先前 session 中記錄的知識與自我認知：\n\n{_memory_snippet}"
                )
                _slog("🧠 MEMORY", f"Injected {len(_memory_snippet)} chars from MEMORY.md")
                if _IDENTITY_MARKER not in _memory_content:
                    system += (
                        f"\n\n⚠️ 身份引導：你的 MEMORY.md 尚未建立 `{_IDENTITY_MARKER}` 區段。"
                        f"請在本 session 完成主要任務後，在 {_memory_path} 開頭建立身份區段（格式見 soul.md 的 ### 自我認知）。"
                    )
        except Exception as _mem_err:
            _slog("⚠️ MEMORY", f"Failed to read MEMORY.md: {_mem_err}")
    else:
        system += (
            f"\n\n⚠️ 身份引導：這是你的第一次 session，尚無長期記憶。"
            f"請在完成主要任務後，建立 {_memory_path} 並填寫身份資料（格式見 soul.md 的 ### 自我認知）。"
        )

    # ── Level B 啟發式偵測（代碼層面輔助分類）────────────────────────────────
    # 根據 prompt 長度 + 關鍵字分析，代碼層面判斷是否為 Level B 任務。
    _LEVEL_B_KEYWORDS = [
        "debug", "修復", "fix", "配置", "configure", "install", "安裝",
        "optimize", "優化", "implement", "實作", "refactor", "重構",
        "analyze", "分析", "deploy", "部署", "multi-step", "step by step",
        "system", "系統", "migrate", "migration", "architecture", "架構",
    ]
    _prompt_text = inp.get("prompt", "")
    _prompt_lower = _prompt_text.lower()
    _is_level_b = (
        len(_prompt_text) > 200 or
        any(kw in _prompt_lower for kw in _LEVEL_B_KEYWORDS)
    )
    if _is_level_b:
        system += (
            "\n\n⚠️ 系統預分析：本任務可能屬於 Level B（複雜任務）。"
            "請在開始前評估是否需要使用 run_agent 委派給子代理。"
        )
        _slog("🧠 LEVEL-B", f"Heuristic detected Level B (len={len(_prompt_text)}, match={_is_level_b})")

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
    _no_tool_turns = 0  # consecutive turns without any tool call (Fix #163)
    _turns_since_notify = 0  # turns since last send_message call (milestone enforcer)
    _only_notify_turns = 0   # consecutive turns with ONLY send_message (no substantive tools)
    _memory_written = False  # True once agent writes to MEMORY.md this session (Enforcer v3)
    _memory_path_str = _os.path.join(_data_dir, "MEMORY.md")
    # Tools that represent actual work (not just reporting)
    _SUBSTANTIVE_TOOLS = frozenset([
        "Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch",
        "run_agent",
    ])
    for turn in range(MAX_TURNS):
        _force = _no_tool_turns > 0  # escalate to tool_choice="required" (Fix #163)
        if _force:
            _slog("⚠️ FORCE-TOOL", f"no_tool_turns={_no_tool_turns} — escalating to tool_choice='required'")
        try:
            _slog("🧠 LLM →", f"turn={turn} force_tool={_force}")
            resp = await provider.complete(history, schemas, system, force_tool=_force)
            _slog("🧠 LLM ←", f"stop={getattr(resp, 'stop_reason', 'done')}")
        except Exception as e:
            tb = traceback.format_exc()
            log.error(f"Provider error on turn {turn}: {tb}")
            return {
                "status": "error",
                "error": f"Provider error on turn {turn}: {type(e).__name__}: {e}",
            }

        if resp.finish_reason == "stop" or not resp.tool_calls:
            _no_tool_turns += 1  # track consecutive no-tool turns (Fix #163)

            # Hard cap: 3 consecutive turns without tool calls → give up (Fix #163)
            if _no_tool_turns >= 3:
                _slog("❌ NO-TOOL", f"Model made no tool call for {_no_tool_turns} consecutive turns — breaking")
                final_response = resp.content or ""
                break

            # ── Fallback: detect bash code blocks the model forgot to run ─────
            # Some models output ```bash blocks as text instead of calling the
            # Bash tool. Auto-execute them and feed results back.
            import re as _re_cb
            _content = resp.content or ""
            _code_blocks = _re_cb.findall(r'```(?:bash|sh|shell)?\n([\s\S]*?)```', _content)
            _runnable = [b.strip() for b in _code_blocks if b.strip()]
            if _runnable and turn < MAX_TURNS - 1:
                _no_tool_turns = 0  # code blocks count as attempted tool use
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
            # Log detection; real enforcement is tool_choice="required" next turn (Fix #161+#163)
            _FAKE_STATUS_RE = _re_cb.compile(r'\*\([^)]*\)\*|\*\[[^\]]*\]\*', _re_cb.DOTALL)
            _fake_hits = _FAKE_STATUS_RE.findall(_content)
            if _fake_hits and turn < MAX_TURNS - 1:
                _slog("⚠️ FAKE-STATUS", f"model wrote {len(_fake_hits)} fake status line(s) — tool_choice='required' on next turn")
                history.append(Message(
                    role="user",
                    content=(
                        "【系統警告】你剛才的回覆包含假狀態行（例如 *(正在執行...)* ），沒有呼叫任何工具。"
                        "下一輪系統將強制要求你必須呼叫工具，請立刻使用 Bash tool 或其他工具執行所需命令。"
                    ),
                ))
                continue

            # No code blocks, no fake status — model is genuinely done
            final_response = _content
            _slog("📤 REPLY", str(final_response)[:600] if final_response is not None else '')
            _slog("🏁 DONE", "success=True")
            return {"status": "ok", "result": resp.content}

        # Model made tool calls — reset the no-tool counter (Fix #163)
        _no_tool_turns = 0

        # ── 里程碑強制器 v2：區分「假報告」和「真工作」────────────────────────
        # 問題：舊版允許模型只呼叫 send_message 來通過里程碑檢查，
        # 導致模型用假進度報告冒充在工作。
        # 修正：只有「實質工具 + send_message」組合才算真里程碑。
        #       連續多輪「只有 send_message」→ 強硬警告：停止假報告。
        _tool_names_this_turn = {tc.name for tc in resp.tool_calls}
        _sent_message_this_turn = "send_message" in _tool_names_this_turn
        _did_real_work = bool(_tool_names_this_turn & _SUBSTANTIVE_TOOLS)

        if _sent_message_this_turn and _did_real_work:
            # Genuine progress report: real work + notification
            _turns_since_notify = 0
            _only_notify_turns = 0
        elif _sent_message_this_turn and not _did_real_work:
            # Only send_message, no actual work — track fabrication pattern
            _only_notify_turns += 1
            _slog("⚠️ FAKE-PROGRESS", f"Model called only send_message (no real work) — streak={_only_notify_turns}")
            if _only_notify_turns >= 2 and turn < MAX_TURNS - 2:
                _slog("🚨 FAKE-PROGRESS", f"Injecting anti-fabrication warning after {_only_notify_turns} fake-report turns")
                history.append(Message(
                    role="user",
                    content=(
                        "【系統警告】你已連續多輪只呼叫 send_message，沒有呼叫任何實質工具（Bash、Read、Write、run_agent 等）。"
                        "這代表你在發送虛構的進度報告而不是真正執行任務。"
                        "立刻停止假報告。你的下一步必須是：呼叫 Bash tool 執行指令、Read 讀取檔案、或 run_agent 委派任務。"
                        "如果不知道怎麼繼續，使用 run_agent 把任務委派給子代理。"
                    ),
                ))
        else:
            # No send_message — working silently
            _turns_since_notify += 1
            if _turns_since_notify >= 5 and turn < MAX_TURNS - 2:
                _slog("⏰ MILESTONE", f"No send_message for {_turns_since_notify} turns — injecting reminder")
                history.append(Message(
                    role="user",
                    content=(
                        f"⏰ 你已執行 {_turns_since_notify} 輪未向用戶回報進度。"
                        "請在繼續工作的同時，用 send_message 發送一條簡短的進度更新（1-2 句話）。"
                        "注意：只有在呼叫了 Bash/Read/Write 等實質工具之後才需要回報，不要虛報進度。"
                    ),
                ))
                _turns_since_notify = 0

        # Append assistant message with tool calls
        history.append(Message(
            role="assistant",
            content=resp.content,
            tool_calls=resp.tool_calls,
        ))

        # ── Milestone Enforcer v3: MEMORY.md 寫入偵測 ───────────────────────
        if not _memory_written:
            for _tc in resp.tool_calls:
                if _tc.name in {"Write", "Edit", "Bash"}:
                    _tc_args_str = str(getattr(_tc, 'arguments', _tc.args))
                    if "MEMORY.md" in _tc_args_str or _memory_path_str in _tc_args_str:
                        _memory_written = True
                        _slog("🧠 MEMORY-WRITE", f"Agent updated MEMORY.md via {_tc.name} on turn {turn}")
                        break
        if not _memory_written and turn == MAX_TURNS - 2:
            _slog("⚠️ MEMORY-REMIND", f"MEMORY.md not updated by turn {turn} — injecting CRITICAL reminder")
            history.append(Message(
                role="user",
                content=(
                    f"【CRITICAL 系統警告】你在本 session 中尚未更新 MEMORY.md（{_memory_path_str}）。\n"
                    "這是倒數第二輪。你必須在結束前執行以下操作：\n"
                    "1. 使用 Write/Edit 工具更新 MEMORY.md\n"
                    "2. 在 `## 任務記錄 (Task Log)` 區段追加今日任務摘要\n"
                    "3. 若 `## 身份 (Identity)` 有新發現（弱點、原則），同步更新\n"
                    "格式：`[YYYY-MM-DD] <做了什麼、關鍵決策、解決方法>`"
                ),
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
