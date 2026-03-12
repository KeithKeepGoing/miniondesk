"""Filesystem tools: Bash, Read, Write, Edit."""
from __future__ import annotations
import subprocess
import os
from pathlib import Path
from . import Tool, register_tool


def _bash(args: dict, ctx: dict) -> str:
    cmd = args.get("command", "")
    timeout = int(args.get("timeout", 30))
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
        )
        out = result.stdout
        if result.stderr:
            out += "\n[stderr]\n" + result.stderr
        if result.returncode != 0:
            out += f"\n[exit code: {result.returncode}]"
        return out or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: command timed out after {timeout}s"
    except Exception as exc:
        return f"Error: {exc}"


def _read(args: dict, ctx: dict) -> str:
    path = args.get("file_path", "")
    offset = int(args.get("offset", 0))
    limit = args.get("limit")
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        if offset:
            lines = lines[offset:]
        if limit:
            lines = lines[:int(limit)]
        numbered = [f"{i+1+offset}\t{line}" for i, line in enumerate(lines)]
        return "\n".join(numbered)
    except FileNotFoundError:
        return f"Error: file not found: {path}"
    except Exception as exc:
        return f"Error: {exc}"


def _write(args: dict, ctx: dict) -> str:
    path = args.get("file_path", "")
    content = args.get("content", "")
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} bytes to {path}"
    except Exception as exc:
        return f"Error: {exc}"


def _edit(args: dict, ctx: dict) -> str:
    path = args.get("file_path", "")
    old_str = args.get("old_string", "")
    new_str = args.get("new_string", "")
    try:
        p = Path(path)
        text = p.read_text(encoding="utf-8")
        if old_str not in text:
            return f"Error: old_string not found in {path}"
        updated = text.replace(old_str, new_str, 1)
        p.write_text(updated, encoding="utf-8")
        return f"Edited {path}: replaced {len(old_str)} chars"
    except Exception as exc:
        return f"Error: {exc}"


# Register all filesystem tools
register_tool(Tool(
    name="Bash",
    description="Execute a shell command and return stdout+stderr.",
    schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
        },
        "required": ["command"],
    },
    execute=_bash,
))

register_tool(Tool(
    name="Read",
    description="Read a file and return its contents with line numbers.",
    schema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to file"},
            "offset": {"type": "integer", "description": "Line to start from (0-indexed)"},
            "limit": {"type": "integer", "description": "Max lines to return"},
        },
        "required": ["file_path"],
    },
    execute=_read,
))

register_tool(Tool(
    name="Write",
    description="Write content to a file, creating directories as needed.",
    schema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["file_path", "content"],
    },
    execute=_write,
))

register_tool(Tool(
    name="Edit",
    description="Replace an exact string in a file.",
    schema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "old_string": {"type": "string", "description": "Exact text to find"},
            "new_string": {"type": "string", "description": "Text to replace it with"},
        },
        "required": ["file_path", "old_string", "new_string"],
    },
    execute=_edit,
))
