"""
Filesystem tools: Bash, Read, Write, Edit.
"""
from __future__ import annotations
import os
import re
import subprocess
from pathlib import Path
from . import Tool, ToolContext

BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/",          # rm -rf /
    r">\s*/etc/",              # overwrite system files
    r"mkfs",                   # format filesystem
    r"dd\s+.*of=/dev/",       # write to block device
    r"chmod\s+777\s+/",       # world-writable root
    r"curl.*\|\s*bash",        # pipe to bash
    r"wget.*\|\s*bash",
]


def _validate_bash_cmd(cmd: str) -> str | None:
    """Returns error message if command is blocked, None if ok."""
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return f"Command blocked by security policy: matches pattern '{pattern}'"
    return None


def _check_path(path: str, ctx: "ToolContext") -> str | None:
    """
    Validate that path is within allowed_paths (if configured).
    Returns error message if blocked, None if allowed.
    """
    if not ctx.allowed_paths:
        return None  # No restrictions

    try:
        resolved = Path(path).resolve()
    except Exception:
        return f"Invalid path: {path}"

    for allowed in ctx.allowed_paths:
        try:
            resolved.relative_to(Path(allowed).resolve())
            return None  # Path is within an allowed directory
        except ValueError:
            continue

    return f"Access denied: {path} is outside allowed directories ({', '.join(ctx.allowed_paths)})"


def _bash(args: dict, ctx: ToolContext) -> str:
    cmd = args.get("command", "")
    timeout = int(args.get("timeout", 30))
    err = _validate_bash_cmd(cmd)
    if err:
        return err
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout
    )
    output = result.stdout
    if result.stderr:
        output += "\n[stderr]\n" + result.stderr
    if result.returncode != 0:
        output += f"\n[exit code: {result.returncode}]"
    return output or "(no output)"


def _read(args: dict, ctx: ToolContext) -> str:
    path = args.get("file_path", "")
    err = _check_path(path, ctx)
    if err:
        return err
    offset = args.get("offset", 0)
    limit = args.get("limit", 2000)
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        selected = lines[offset : offset + limit]
        return "".join(
            f"{offset + i + 1}\t{line}" for i, line in enumerate(selected)
        )
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except Exception as e:
        return f"Error reading {path}: {e}"


def _write(args: dict, ctx: ToolContext) -> str:
    path = args.get("file_path", "")
    err = _check_path(path, ctx)
    if err:
        return err
    content = args.get("content", "")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written {len(content)} bytes to {path}"
    except Exception as e:
        return f"Error writing {path}: {e}"


def _edit(args: dict, ctx: ToolContext) -> str:
    path = args.get("file_path", "")
    err = _check_path(path, ctx)
    if err:
        return err
    old = args.get("old_string", "")
    new = args.get("new_string", "")
    replace_all = args.get("replace_all", False)
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        if old not in content:
            return f"Error: old_string not found in {path}"
        if replace_all:
            updated = content.replace(old, new)
        else:
            updated = content.replace(old, new, 1)
        with open(path, "w", encoding="utf-8") as f:
            f.write(updated)
        count = content.count(old)
        replaced = count if replace_all else 1
        return f"Replaced {replaced} occurrence(s) in {path}"
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except Exception as e:
        return f"Error editing {path}: {e}"


def get_filesystem_tools() -> list[Tool]:
    return [
        Tool(
            name="Bash",
            description="Execute a bash command and return its output.",
            schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The bash command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)"},
                },
                "required": ["command"],
            },
            execute=_bash,
        ),
        Tool(
            name="Read",
            description="Read a file and return its contents with line numbers.",
            schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the file"},
                    "offset": {"type": "integer", "description": "Line offset to start from"},
                    "limit": {"type": "integer", "description": "Max lines to read"},
                },
                "required": ["file_path"],
            },
            execute=_read,
        ),
        Tool(
            name="Write",
            description="Write content to a file, overwriting if it exists.",
            schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to write to"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["file_path", "content"],
            },
            execute=_write,
        ),
        Tool(
            name="Edit",
            description="Edit a file by replacing old_string with new_string.",
            schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the file"},
                    "old_string": {"type": "string", "description": "Exact text to replace"},
                    "new_string": {"type": "string", "description": "Replacement text"},
                    "replace_all": {"type": "boolean", "description": "Replace all occurrences"},
                },
                "required": ["file_path", "old_string", "new_string"],
            },
            execute=_edit,
        ),
    ]
