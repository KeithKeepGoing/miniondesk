"""
Auto-select LLM provider based on environment variables.
Priority: LLM_PROVIDER env var > Claude > Gemini > OpenAI > Ollama
"""
from __future__ import annotations
import os
from . import BaseProvider


def get_provider() -> BaseProvider:
    """Return the appropriate provider based on available API keys."""
    forced = os.getenv("LLM_PROVIDER", "").lower()

    if forced == "claude" or (not forced and os.getenv("ANTHROPIC_API_KEY")):
        from .claude import ClaudeProvider
        return ClaudeProvider()

    if forced == "gemini" or (not forced and os.getenv("GOOGLE_API_KEY")):
        from .gemini import GeminiProvider
        return GeminiProvider()

    if forced == "openai" or (not forced and os.getenv("OPENAI_API_KEY")):
        from .openai_compat import OpenAICompatProvider
        return OpenAICompatProvider()

    ollama_url = os.getenv("OLLAMA_URL")
    if forced == "ollama" or (not forced and ollama_url):
        from .openai_compat import OpenAICompatProvider
        model = os.getenv("OLLAMA_MODEL", "llama3.2")
        return OpenAICompatProvider(
            base_url=f"{ollama_url}/v1",
            api_key="ollama",
            model=model,
        )

    vllm_url = os.getenv("OPENAI_BASE_URL")
    if forced == "vllm" or (not forced and vllm_url):
        from .openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(base_url=vllm_url)

    raise EnvironmentError(
        "No LLM provider configured. Set one of: ANTHROPIC_API_KEY, GOOGLE_API_KEY, "
        "OPENAI_API_KEY, OLLAMA_URL, or OPENAI_BASE_URL. "
        "Or force a provider with LLM_PROVIDER=claude|gemini|openai|ollama."
    )
