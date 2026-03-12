"""OpenAI-compatible provider (OpenAI, Ollama, vLLM, LM Studio)."""
from __future__ import annotations
import json
import os
from . import BaseProvider, Message, Response, ToolCall


class OpenAICompatProvider(BaseProvider):
    name = "openai"

    def __init__(self):
        from openai import AsyncOpenAI
        base_url = os.getenv("OPENAI_BASE_URL")
        api_key = os.getenv("OPENAI_API_KEY", "ollama")  # Ollama ignores key
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    def _schema_to_openai(self, tools: list[dict]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                },
            }
            for t in tools
        ]

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict],
        system: str = "",
    ) -> Response:
        oai_msgs = []
        if system:
            oai_msgs.append({"role": "system", "content": system})
        for m in messages:
            if m.role == "user":
                oai_msgs.append({"role": "user", "content": m.content})
            elif m.role == "assistant":
                msg: dict = {"role": "assistant", "content": m.content or ""}
                if m.tool_calls:
                    msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": json.dumps(tc.args)},
                        }
                        for tc in m.tool_calls
                    ]
                oai_msgs.append(msg)
            elif m.role == "tool":
                oai_msgs.append({
                    "role": "tool",
                    "tool_call_id": m.tool_call_id,
                    "content": m.content,
                })

        kwargs: dict = dict(model=self._model, messages=oai_msgs)
        if tools:
            kwargs["tools"] = self._schema_to_openai(tools)
            kwargs["tool_choice"] = "auto"

        resp = await self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        msg = choice.message

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    args=json.loads(tc.function.arguments or "{}"),
                ))

        finish = "tool_calls" if tool_calls else "stop"
        return Response(
            content=msg.content or "",
            tool_calls=tool_calls,
            finish_reason=finish,
        )


class OllamaProvider(OpenAICompatProvider):
    """Ollama local model — wraps OpenAI-compat with Ollama defaults."""
    name = "ollama"

    def __init__(self):
        from openai import AsyncOpenAI
        base_url = os.getenv("OLLAMA_URL", "http://localhost:11434") + "/v1"
        self._client = AsyncOpenAI(api_key="ollama", base_url=base_url)
        self._model = os.getenv("OLLAMA_MODEL", "llama3.2")
