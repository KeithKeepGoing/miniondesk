"""
Google Gemini provider for MinionDesk.
Uses google-generativeai SDK with function calling support.
"""
from __future__ import annotations
import json
import os
from . import BaseProvider, Message, Response, ToolCall


class GeminiProvider(BaseProvider):
    name = "gemini"

    def __init__(self, model: str | None = None):
        import google.generativeai as genai
        api_key = os.environ["GOOGLE_API_KEY"]
        genai.configure(api_key=api_key)
        self._genai = genai
        self._model_name = model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")

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
        from google.generativeai.types import FunctionDeclaration, Tool as GeminiTool

        # Convert JSON Schema tools to Gemini FunctionDeclarations
        gemini_tools = []
        if tools:
            decls = []
            for t in tools:
                params = t.get("parameters", {})
                # Remove unsupported keys from properties
                props = {}
                for k, v in params.get("properties", {}).items():
                    prop = {kk: vv for kk, vv in v.items() if kk in ("type", "description", "enum")}
                    props[k] = prop
                clean_params = {
                    "type": "object",
                    "properties": props,
                    "required": params.get("required", []),
                }
                decls.append(FunctionDeclaration(
                    name=t["name"],
                    description=t.get("description", ""),
                    parameters=clean_params,
                ))
            gemini_tools = [GeminiTool(function_declarations=decls)]

        model = self._genai.GenerativeModel(
            model_name=self._model_name,
            system_instruction=system or None,
            tools=gemini_tools or None,
        )

        # Convert messages to Gemini format.
        # Gemini's chat API takes history (all turns EXCEPT last user message)
        # and sends the last user message via chat.send_message().
        #
        # Messages format: user → model → function → user → model → ...
        # Tool calls: model sends function_call, we reply with function_response.

        # Separate: history = everything before last user message
        #           current_prompt = last user message content
        last_user_idx = max(
            (i for i, m in enumerate(messages) if m.role == "user"),
            default=-1,
        )

        history = []
        for i, msg in enumerate(messages):
            if i == last_user_idx:
                continue  # This becomes current_prompt below

            if msg.role == "user":
                history.append({"role": "user", "parts": [msg.content or ""]})

            elif msg.role == "assistant":
                parts = []
                if msg.content:
                    parts.append(msg.content)
                for tc in msg.tool_calls:
                    parts.append(self._genai.protos.Part(
                        function_call=self._genai.protos.FunctionCall(
                            name=tc.name,
                            args=tc.args,
                        )
                    ))
                if parts:  # Don't append empty model turns
                    history.append({"role": "model", "parts": parts})

            elif msg.role == "tool":
                # tool_call_id is "funcname_idx" (e.g. "search_0"); strip the index suffix to get the function name
                raw_id = msg.tool_call_id or "tool"
                fn_name = raw_id.rsplit("_", 1)[0] if "_" in raw_id else raw_id
                history.append({
                    "role": "function",
                    "parts": [self._genai.protos.Part(
                        function_response=self._genai.protos.FunctionResponse(
                            name=fn_name,
                            response={"result": msg.content or ""},
                        )
                    )]
                })

        current_prompt = messages[last_user_idx].content if last_user_idx >= 0 else ""

        # Use chat for multi-turn
        chat = model.start_chat(history=history)
        response = chat.send_message(current_prompt)

        # Parse response
        tool_calls = []
        text_parts = []
        for _tc_idx, part in enumerate(response.parts):
            if hasattr(part, "function_call") and part.function_call.name:
                fc = part.function_call
                tool_calls.append(ToolCall(
                    id=f"{fc.name}_{_tc_idx}",
                    name=fc.name,
                    args=dict(fc.args),
                ))
            elif hasattr(part, "text") and part.text:
                text_parts.append(part.text)

        finish_reason = "tool_calls" if tool_calls else "stop"
        return Response(
            content=" ".join(text_parts),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        )
