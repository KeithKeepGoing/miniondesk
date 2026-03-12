"""Google Gemini provider."""
from __future__ import annotations
import json
import os
from . import BaseProvider, Message, Response, ToolCall


class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self):
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        self._genai = genai
        self._model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

    def _schema_to_gemini(self, tools: list[dict]) -> list:
        """Convert JSON Schema tool list → Gemini FunctionDeclaration list."""
        from google.generativeai.types import FunctionDeclaration, Tool as GTool
        decls = []
        for t in tools:
            params = t.get("parameters", {})
            decls.append(FunctionDeclaration(
                name=t["name"],
                description=t.get("description", ""),
                parameters=params,
            ))
        return [GTool(function_declarations=decls)] if decls else []

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict],
        system: str = "",
    ) -> Response:
        import asyncio
        model = self._genai.GenerativeModel(
            self._model_name,
            system_instruction=system or None,
            tools=self._schema_to_gemini(tools) if tools else None,
        )
        # Build Gemini content list
        contents = []
        for m in messages:
            if m.role == "user":
                contents.append({"role": "user", "parts": [{"text": m.content}]})
            elif m.role == "assistant":
                parts = []
                if m.content:
                    parts.append({"text": m.content})
                for tc in m.tool_calls:
                    parts.append({"function_call": {"name": tc.name, "args": tc.args}})
                contents.append({"role": "model", "parts": parts})
            elif m.role == "tool":
                contents.append({
                    "role": "user",
                    "parts": [{"function_response": {
                        "name": m.tool_call_id,
                        "response": {"result": m.content},
                    }}],
                })

        loop = asyncio.get_event_loop()
        chat = model.start_chat(history=contents[:-1] if contents else [])
        last = contents[-1]["parts"] if contents else [{"text": ""}]
        resp = await loop.run_in_executor(None, lambda: chat.send_message(last))

        tool_calls = []
        text_parts = []
        for part in resp.parts:
            if hasattr(part, "function_call") and part.function_call.name:
                fc = part.function_call
                tool_calls.append(ToolCall(
                    id=fc.name,
                    name=fc.name,
                    args=dict(fc.args),
                ))
            elif hasattr(part, "text") and part.text:
                text_parts.append(part.text)

        finish = "tool_calls" if tool_calls else "stop"
        return Response(
            content="\n".join(text_parts),
            tool_calls=tool_calls,
            finish_reason=finish,
        )
