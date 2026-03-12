"""Model-agnostic tool system."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Any
import json


@dataclass
class Tool:
    name: str
    description: str
    schema: dict          # JSON Schema for parameters
    execute: Callable     # (args: dict, context: dict) -> str


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, names: list[str] | None = None) -> "ToolRegistry":
        """Return a new registry with only the named tools (or all if names is None)."""
        if names is None:
            return self
        sub = ToolRegistry()
        for name in names:
            if name in self._tools:
                sub._tools[name] = self._tools[name]
        return sub

    def schemas(self) -> list[dict]:
        """Return JSON Schema tool definitions (model-agnostic format)."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.schema,
            }
            for t in self._tools.values()
        ]

    def execute(self, name: str, args: dict, context: dict = {}) -> str:
        if name not in self._tools:
            return f"Error: unknown tool '{name}'"
        try:
            return self._tools[name].execute(args, context)
        except Exception as exc:
            return f"Error executing {name}: {exc}"

    def all_names(self) -> list[str]:
        return list(self._tools.keys())


# Global default registry
_default_registry = ToolRegistry()


def register_tool(tool: Tool) -> None:
    _default_registry.register(tool)


def get_registry() -> ToolRegistry:
    return _default_registry
