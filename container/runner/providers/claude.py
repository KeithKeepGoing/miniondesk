"""Anthropic Claude provider."""
from __future__ import annotations
import json
import os
from . import BaseProvider, Message, Response, ToolCall


class ClaudeProvider(BaseProvider):
    name = "claude"

    def __init__(self):
        import anthropic
        self._client = anthropic.AsyncAnthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"]
        )
        self._model = os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022")

    def _schema_to_claude(self, tools: list[dict]) -> list[dict]:
        return [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
            }
            for t in tools
        ]

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict],
        system: str = "",
    ) -> Response:
        claude_msgs = []
        for m in messages:
            if m.role == "user":
                claude_msgs.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                content = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    content.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.args,
                    })
                claude_msgs.append({"role": "assistant", "content": content})
            elif m.role == "tool":
                claude_msgs.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": m.tool_call_id,
                        "content": m.content,
                    }],
                })

        kwargs = dict(
            model=self._model,
            max_tokens=4096,
            messages=claude_msgs,
        )
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._schema_to_claude(tools)

        resp = await self._client.messages.create(**kwargs)

        tool_calls = []
        text_parts = []
        for block in resp.content:
            if block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, args=block.input))
            elif block.type == "text":
                text_parts.append(block.text)

        finish = "tool_calls" if tool_calls else "stop"
        return Response(
            content="\n".join(text_parts),
            tool_calls=tool_calls,
            finish_reason=finish,
        )
