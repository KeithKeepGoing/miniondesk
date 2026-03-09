"""
MinionQueue: Ensures at most one container per chat_jid runs at a time.
"""
from __future__ import annotations
import asyncio
from collections import defaultdict

_locks: dict[str, asyncio.Lock] = {}
_lock_order: list[str] = []

MAX_LOCK_ENTRIES = 1000


def _evict_locks() -> None:
    while len(_locks) >= MAX_LOCK_ENTRIES:
        oldest = _lock_order.pop(0)
        _locks.pop(oldest, None)


async def get_lock(chat_jid: str) -> asyncio.Lock:
    if chat_jid not in _locks:
        _evict_locks()
        _locks[chat_jid] = asyncio.Lock()
        _lock_order.append(chat_jid)
    return _locks[chat_jid]
