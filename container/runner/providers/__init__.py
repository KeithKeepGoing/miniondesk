"""
Provider abstraction layer — model-agnostic LLM interface.

Each provider converts JSON Schema tools to its own format and normalizes
responses back to our Message/Response dataclasses.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Message:
    role: str           # "user" | "assistant" | "tool"
    content: str = ""
    tool_calls: list = field(default_factory=list)
    tool_call_id: str = ""   # for role="tool" responses


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Response:
    content: str
    tool_calls: list[ToolCall]
    finish_reason: str   # "stop" | "tool_calls"


class BaseProvider:
    name: str = "base"

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict],   # JSON Schema tool definitions
        system: str = "",
    ) -> Response:
        raise NotImplementedError

    def _json_schema_to_tool_def(self, tool: dict) -> dict:
        """Return tool definition in this provider's native format.
        Override in each provider subclass.
        """
        return tool
