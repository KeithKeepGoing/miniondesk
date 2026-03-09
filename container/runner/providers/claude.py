"""
Anthropic Claude provider for MinionDesk.
Uses anthropic SDK with tool_use support.
"""
from __future__ import annotations
import json
import os
from . import BaseProvider, Message, Response, ToolCall


class ClaudeProvider(BaseProvider):
    name = "claude"

    def __init__(self, model: str | None = None):
        import anthropic
        self._client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self._model = model or os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022")

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict],
        system: str = "",
    ) -> Response:
        import asyncio
        return await asyncio.get_event_loop().run_in_executor(
            None, self._complete_sync, messages, tools, system
        )

    def _complete_sync(self, messages, tools, system):
        # Convert messages to Claude format
        claude_messages = []
        for msg in messages:
            if msg.role == "user":
                claude_messages.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                content = []
                if msg.content:
                    content.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    content.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.args,
                    })
                claude_messages.append({"role": "assistant", "content": content})
            elif msg.role == "tool":
                claude_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.tool_call_id or "",
                        "content": msg.content,
                    }]
                })

        # Convert tools to Claude format
        claude_tools = []
        for t in tools:
            claude_tools.append({
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
            })

        kwargs = dict(
            model=self._model,
            max_tokens=8096,
            messages=claude_messages,
        )
        if system:
            kwargs["system"] = system
        if claude_tools:
            kwargs["tools"] = claude_tools

        response = self._client.messages.create(**kwargs)

        tool_calls = []
        text_parts = []
        for block in response.content:
            if block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    args=block.input,
                ))
            elif block.type == "text":
                text_parts.append(block.text)

        finish_reason = "tool_calls" if tool_calls else "stop"
        return Response(
            content=" ".join(text_parts),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )
