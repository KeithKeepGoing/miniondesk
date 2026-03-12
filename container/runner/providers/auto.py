"""Auto-detect and return the best available LLM provider."""
from __future__ import annotations
import os
from . import BaseProvider


def get_provider() -> BaseProvider:
    """Return the first available provider based on env vars.

    Priority: Gemini → Claude → OpenAI → Ollama → vLLM/LM Studio
    """
    if os.getenv("GOOGLE_API_KEY"):
        from .gemini import GeminiProvider
        return GeminiProvider()

    if os.getenv("ANTHROPIC_API_KEY"):
        from .claude import ClaudeProvider
        return ClaudeProvider()

    if os.getenv("OPENAI_API_KEY"):
        from .openai_compat import OpenAICompatProvider
        return OpenAICompatProvider()

    if os.getenv("OPENAI_BASE_URL"):
        from .openai_compat import OpenAICompatProvider
        return OpenAICompatProvider()

    if os.getenv("OLLAMA_URL"):
        from .openai_compat import OllamaProvider
        return OllamaProvider()

    # No LLM credentials configured at all — fail fast with a clear message
    # rather than silently trying localhost:11434 (which is almost never correct
    # inside a Docker container and produces confusing connection-refused errors).
    raise RuntimeError(
        "No LLM provider configured. Set one of: GOOGLE_API_KEY, ANTHROPIC_API_KEY, "
        "OPENAI_API_KEY, OPENAI_BASE_URL, or OLLAMA_URL."
    )
