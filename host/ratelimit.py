"""
MinionDesk Rate Limiter
Prevents abuse by limiting requests per user per time window.
"""
from __future__ import annotations
import asyncio
import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass
class RateLimitConfig:
    max_requests: int = 10       # max requests per window
    window_seconds: int = 60     # time window in seconds
    cooldown_seconds: int = 30   # cooldown message interval


# Global rate limit config (can be customized)
_config = RateLimitConfig()

# Per-JID timestamp deques
_windows: dict[str, deque] = defaultdict(deque)
_lock = asyncio.Lock()


def configure(max_requests: int = 10, window_seconds: int = 60) -> None:
    """Configure global rate limit settings."""
    global _config
    _config = RateLimitConfig(max_requests=max_requests, window_seconds=window_seconds)


async def check(jid: str) -> tuple[bool, str]:
    """
    Check if a JID is within rate limits.
    Returns (allowed: bool, reason: str).
    """
    async with _lock:
        now = time.monotonic()
        window = _windows[jid]

        # Remove expired timestamps
        while window and (now - window[0]) > _config.window_seconds:
            window.popleft()

        # Clean up empty entries to prevent unbounded memory growth (fixes #180)
        if not window:
            del _windows[jid]
            return True, ""

        if len(window) >= _config.max_requests:
            oldest = window[0]
            wait = int(_config.window_seconds - (now - oldest)) + 1
            return False, f"⏳ 請求太頻繁，請等 {wait} 秒後再試。"

        window.append(now)
        return True, ""


async def get_usage(jid: str) -> dict:
    """Return rate limit usage for a JID."""
    async with _lock:
        now = time.monotonic()
        window = _windows[jid]
        valid = [ts for ts in window if (now - ts) <= _config.window_seconds]
        return {
            "used": len(valid),
            "limit": _config.max_requests,
            "window_seconds": _config.window_seconds,
            "remaining": max(0, _config.max_requests - len(valid)),
        }
