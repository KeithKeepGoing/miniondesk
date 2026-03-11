"""
MinionDesk Minion Runner — model-agnostic agentic loop.

Reads a JSON payload from stdin:
{
    "prompt":       str,
    "personaMd":    str,       # persona markdown
    "hints":        str,       # optional extra instructions
    "chatJid":      str,
    "enabledTools": [str],     # null = all tools
}

Writes a JSON result to stdout:
{
    "status":  "ok" | "error",
    "result":  str,
    "turns":   int,
}
"""
from __future__ import annotations
import asyncio
import json
import sys
import os
import datetime as _dt
from pathlib import Path

# Add repo root to path for imports
_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_ROOT))


def _log(tag: str, msg: str = "") -> None:
    ts = _dt.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {tag} {msg}", file=sys.stderr, flush=True)


def _load_dynamic_tools() -> None:
    """
    Auto-import Python tool files from /app/dynamic_tools/ (mounted volume).
    Each file should call register_tool() at module level.
    This allows DevEngine-generated skills to add new tools without rebuilding the image.
    """
    import importlib.util
    dynamic_dir = Path("/app/dynamic_tools")
    if not dynamic_dir.exists():
        return
    for py_file in sorted(dynamic_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(
                f"dynamic_tools.{py_file.stem}", py_file
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _log("🔌 DYNAMIC TOOL", f"loaded {py_file.name}")
        except Exception as exc:
            _log("⚠️ DYNAMIC TOOL", f"failed to load {py_file.name}: {exc}")


async def run_minion(stdin_data: dict) -> dict:
    from providers.auto import get_provider
    from providers import Message
    from tools import get_registry
    import tools.filesystem  # noqa: register filesystem tools
    import tools.messaging   # noqa: register messaging tools
    import tools.enterprise  # noqa: register enterprise tools

    _load_dynamic_tools()  # Hot-load any skill-installed tools from mounted volume

    assistant_name = stdin_data.get("assistantName", "Mini")
    _log("🚀 RUNNER", f"starting minion as {assistant_name}")

    # Setup context
    context = {
        "chat_jid":       stdin_data.get("chatJid", ""),
        "persona":        stdin_data.get("personaMd", ""),
        "assistant_name": assistant_name,
    }

    # Provider
    _log("🤖 PROVIDER", "loading...")
    provider = get_provider()
    _log(f"🤖 PROVIDER", f"using {provider.name}")

    # Tools
    registry = get_registry().get(stdin_data.get("enabledTools"))
    _log("🔧 TOOLS", f"available: {registry.all_names()}")

    # System prompt — persona + hints + CLAUDE.md injections
    system_parts = [stdin_data.get("personaMd", "")]
    if stdin_data.get("globalClaudeMd"):
        system_parts.append("\n\n---\n## Global Instructions\n" + stdin_data["globalClaudeMd"])
    if stdin_data.get("groupClaudeMd"):
        system_parts.append("\n\n---\n## Group Instructions\n" + stdin_data["groupClaudeMd"])
    if stdin_data.get("hints"):
        system_parts.append("\n\n---\n## Behavioral Hints\n" + stdin_data["hints"])
    if stdin_data.get("skillDocs"):
        system_parts.append("\n\n---\n## Installed Superpowers Skills\n" + stdin_data["skillDocs"])
    system = "\n".join(system_parts)

    # Track whether agent sent a message via send_message tool (avoid double-send)
    _sent_via_tool: list[bool] = [False]
    original_execute = registry.execute

    def _execute_and_track(name: str, args: dict, ctx: dict):
        result = original_execute(name, args, ctx)
        if name == "send_message":
            _sent_via_tool[0] = True
        return result

    registry.execute = _execute_and_track

    # Agentic loop (max 30 turns)
    # Build message history: inject conversation history before current user message
    history = []
    for h in stdin_data.get("conversationHistory", []):
        history.append(Message(role=h["role"], content=h["content"]))
    history.append(Message(role="user", content=stdin_data["prompt"]))
    max_turns = int(os.getenv("MAX_TURNS", "30"))
    final_content = ""

    for turn in range(max_turns):
        _log(f"🔄 TURN {turn+1}/{max_turns}", "calling LLM...")
        try:
            resp = await provider.complete(history, registry.schemas(), system)
        except Exception as exc:
            _log(f"❌ LLM ERROR", str(exc))
            return {"status": "error", "result": f"LLM error: {exc}", "turns": turn}

        _log(f"📝 LLM", f"finish_reason={resp.finish_reason} content={len(resp.content)}chars tools={len(resp.tool_calls)}")

        if resp.finish_reason == "stop":
            final_content = resp.content
            _log("✅ DONE", f"completed in {turn+1} turns (sent_via_tool={_sent_via_tool[0]})")
            # Dual-output prevention: if already sent via send_message, don't echo again
            result_text = "" if _sent_via_tool[0] else final_content
            return {"status": "ok", "result": result_text, "turns": turn + 1}

        # Append assistant message with tool calls
        from providers import Message
        history.append(Message(
            role="assistant",
            content=resp.content,
            tool_calls=resp.tool_calls,
        ))

        # Execute all tool calls
        for tc in resp.tool_calls:
            _log(f"🔧 TOOL", f"calling {tc.name}({json.dumps(tc.args)[:100]})")
            result = _execute_and_track(tc.name, tc.args, context)
            _log(f"🔧 TOOL RESULT", f"{tc.name} → {str(result)[:100]}")
            history.append(Message(
                role="tool",
                content=str(result),
                tool_call_id=tc.id,
            ))

    _log("⚠️ MAX TURNS", f"reached {max_turns} turns")
    return {
        "status": "error",
        "result": f"Reached max turns ({max_turns}) without finishing.",
        "turns": max_turns,
    }


async def main():
    _log("📥 STDIN", "reading...")
    raw = sys.stdin.read()
    _log("📥 STDIN", f"read {len(raw)} bytes")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        result = {"status": "error", "result": f"Invalid JSON input: {exc}", "turns": 0}
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(1)

    result = await run_minion(payload)

    print("<<<MINIONDESK_OUTPUT_START>>>")
    print(json.dumps(result, ensure_ascii=False))
    print("<<<MINIONDESK_OUTPUT_END>>>")
    _log("📤 OUTPUT", "written to stdout")


if __name__ == "__main__":
    asyncio.run(main())
