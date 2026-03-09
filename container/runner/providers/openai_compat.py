"""
OpenAI-compatible provider for MinionDesk.
Supports: OpenAI, Ollama, vLLM, LM Studio, Azure OpenAI.
"""
from __future__ import annotations
import json
import os
from . import BaseProvider, Message, Response, ToolCall


class OpenAICompatProvider(BaseProvider):
    name = "openai"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ):
        from openai import AsyncOpenAI
        resolved_key = api_key or os.getenv("OPENAI_API_KEY") or os.getenv("OLLAMA_API_KEY", "")
        if not resolved_key:
            raise RuntimeError(
                "OpenAI/Ollama provider requires OPENAI_API_KEY or OLLAMA_API_KEY to be set. "
                "For Ollama, set OLLAMA_API_KEY=ollama and OPENAI_BASE_URL=http://localhost:11434/v1"
            )
        self._client = AsyncOpenAI(
            api_key=resolved_key,
            base_url=base_url or os.getenv("OPENAI_BASE_URL"),
        )
        self._model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict],
        system: str = "",
    ) -> Response:
        # Convert messages
        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": system})

        for msg in messages:
            if msg.role == "user":
                oai_messages.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                m: dict = {"role": "assistant", "content": msg.content or ""}
                if msg.tool_calls:
                    m["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.args),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                oai_messages.append(m)
            elif msg.role == "tool":
                oai_messages.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id or "",
                    "content": msg.content,
                })

        # Convert tools
        oai_tools = []
        for t in tools:
            oai_tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                },
            })

        kwargs = dict(
            model=self._model,
            messages=oai_messages,
            max_tokens=4096,
        )
        if oai_tools:
            kwargs["tools"] = oai_tools
            kwargs["tool_choice"] = "auto"

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg_out = choice.message

        tool_calls = []
        if msg_out.tool_calls:
            for tc in msg_out.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    args=json.loads(tc.function.arguments or "{}"),
                ))

        finish_reason = "tool_calls" if tool_calls else "stop"
        return Response(
            content=msg_out.content or "",
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )
