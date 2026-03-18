"""
MemorySummarizer — Phase 2
LLM-powered compression of conversation history into MEMORY.md bullets.
Supports Gemini/Claude/OpenAI-compatible, graceful fallback.
"""
import os
import json
import time
import logging
from typing import List, Optional, Dict
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_HOT_BYTES = 6 * 1024   # 6KB threshold for compression
TARGET_HOT_BYTES = 4 * 1024  # compress down to ~4KB


class MemorySummarizer:
    """LLM-powered memory summarizer for MinionDesk agents."""

    def __init__(self, llm_provider: Optional[str] = None):
        self.provider = llm_provider or os.getenv("LLM_PROVIDER", "gemini")
        self.api_key = (
            os.getenv("GEMINI_API_KEY") or
            os.getenv("ANTHROPIC_API_KEY") or
            os.getenv("OPENAI_API_KEY") or ""
        )

    def summarize_session(
        self,
        messages: List[Dict],
        agent_name: str = "minion",
        max_bullets: int = 10,
    ) -> str:
        """
        Compress a list of messages into bullet-point memory entries.
        Returns markdown bullet string for appending to MEMORY.md.
        """
        if not messages:
            return ""
        conversation = "\n".join(
            f"{m.get('role','user').upper()}: {m.get('content','')}"
            for m in messages[-40:]  # last 40 messages
        )
        prompt = (
            f"You are summarizing a conversation for agent '{agent_name}'.\n"
            f"Extract {max_bullets} key facts, decisions, or context items as concise bullet points.\n"
            f"Format: '- [timestamp] fact'\n\n"
            f"CONVERSATION:\n{conversation}\n\nBULLETS:"
        )
        result = self._call_llm(prompt)
        if result:
            return result
        # Fallback: extract last N messages as simple bullets
        bullets = []
        ts = time.strftime("%Y-%m-%d")
        for m in messages[-max_bullets:]:
            content = str(m.get("content", ""))[:120]
            role = m.get("role", "user")
            if content.strip():
                bullets.append(f"- [{ts}] {role}: {content}")
        return "\n".join(bullets)

    def compress_memory(self, memory_path: str, agent_name: str = "minion") -> bool:
        """
        Compress MEMORY.md if it exceeds MAX_HOT_BYTES.
        Returns True if compression was performed.
        """
        path = Path(memory_path)
        if not path.exists():
            return False
        content = path.read_text(encoding="utf-8")
        if len(content.encode()) < MAX_HOT_BYTES:
            return False
        prompt = (
            f"Compress this MEMORY.md for agent '{agent_name}' to under 4KB.\n"
            f"Keep only the most important facts. Use bullet points.\n\n"
            f"CURRENT MEMORY:\n{content}\n\nCOMPRESSED:"
        )
        compressed = self._call_llm(prompt)
        if compressed and len(compressed.encode()) < len(content.encode()):
            # Keep header
            header = f"# {agent_name} Memory\n_Auto-compressed {time.strftime('%Y-%m-%d %H:%M')}_\n\n"
            path.write_text(header + compressed, encoding="utf-8")
            logger.info(f"Memory compressed: {memory_path} ({len(content)} -> {len(compressed)} bytes)")
            return True
        return False

    def _call_llm(self, prompt: str) -> Optional[str]:
        """Call LLM API with graceful fallback."""
        if not self.api_key:
            return None
        try:
            if self.provider == "gemini":
                return self._call_gemini(prompt)
            elif self.provider in ("claude", "anthropic"):
                return self._call_claude(prompt)
            elif self.provider == "openai":
                return self._call_openai(prompt)
        except Exception as e:
            logger.warning(f"LLM call failed ({self.provider}): {e}")
        return None

    def _call_gemini(self, prompt: str) -> Optional[str]:
        import urllib.request
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.0-flash:generateContent?key={self.api_key}"
        )
        body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["candidates"][0]["content"]["parts"][0]["text"]

    def _call_claude(self, prompt: str) -> Optional[str]:
        import urllib.request
        url = "https://api.anthropic.com/v1/messages"
        body = json.dumps({
            "model": "claude-3-haiku-20240307",
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["content"][0]["text"]

    def _call_openai(self, prompt: str) -> Optional[str]:
        import urllib.request
        url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com") + "/v1/chat/completions"
        body = json.dumps({
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
        }).encode()
        req = urllib.request.Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["choices"][0]["message"]["content"]
