"""
MinionDesk Provider Abstraction Layer
Model-agnostic LLM interface inspired by openclaw gateway pattern.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Message:
    role: str  # "user" | "assistant" | "tool"
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None


@dataclass
class Response:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"  # "stop" | "tool_calls" | "error"


class BaseProvider:
    """Base class for all LLM providers."""
    name: str = "base"

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict],
        system: str = "",
    ) -> Response:
        raise NotImplementedError
