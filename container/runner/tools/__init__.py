"""
MinionDesk Tool System - Model-agnostic tool registry.
Tools are defined as JSON Schema and converted to provider-specific format.
"""
from __future__ import annotations
import traceback
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class ToolContext:
    chat_jid: str
    minion_name: str
    ipc_dir: str
    data_dir: str
    sender_jid: str = ""
    allowed_paths: list[str] = field(default_factory=list)


@dataclass
class Tool:
    name: str
    description: str
    schema: dict  # JSON Schema for parameters
    execute: Callable[[dict, ToolContext], str]

    def to_schema_dict(self) -> dict:
        """Return provider-neutral JSON Schema dict."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.schema,
        }


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict]:
        """Return all tool schemas in provider-neutral format."""
        return [t.to_schema_dict() for t in self._tools.values()]

    def execute(self, name: str, args: dict, ctx: ToolContext) -> str:
        if name not in self._tools:
            return f"Error: Unknown tool '{name}'"
        try:
            return str(self._tools[name].execute(args, ctx))
        except Exception as e:
            return f"Error executing {name}: {e}\n{traceback.format_exc()}"


def build_registry(enabled_tools: list[str]) -> ToolRegistry:
    """Build a ToolRegistry with the specified tools enabled."""
    registry = ToolRegistry()

    from .filesystem import get_filesystem_tools
    from .messaging import get_messaging_tools
    from .enterprise import get_enterprise_tools
    from .hpc import get_hpc_tools
    from .integrations import get_integration_tools
    from .email_tools import get_email_tools
    from .nas import get_nas_deep_tools

    all_tools: list[Tool] = []
    all_tools.extend(get_filesystem_tools())
    all_tools.extend(get_messaging_tools())
    all_tools.extend(get_enterprise_tools())
    all_tools.extend(get_hpc_tools())
    all_tools.extend(get_integration_tools())
    all_tools.extend(get_email_tools())
    all_tools.extend(get_nas_deep_tools())

    for tool in all_tools:
        if tool.name in enabled_tools:
            registry.register(tool)

    return registry
