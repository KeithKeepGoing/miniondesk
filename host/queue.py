"""
MinionQueue: Ensures at most one container per chat_jid runs at a time.
"""
from __future__ import annotations
import asyncio
from collections import OrderedDict

_locks: OrderedDict[str, asyncio.Lock] = OrderedDict()

MAX_LOCK_ENTRIES = 1000


def _evict_locks() -> None:
    """Evict oldest unlocked locks when capacity is reached."""
    while len(_locks) >= MAX_LOCK_ENTRIES:
        # Find the oldest unlocked lock to evict
        evicted = False
        for jid in list(_locks):
            if not _locks[jid].locked():
                del _locks[jid]
                evicted = True
                break
        if not evicted:
            # All locks are held — cannot evict safely; allow over-capacity
            break


async def get_lock(chat_jid: str) -> asyncio.Lock:
    if chat_jid in _locks:
        # Move to end (LRU: most recently used last)
        _locks.move_to_end(chat_jid)
    else:
        _evict_locks()
        _locks[chat_jid] = asyncio.Lock()
    return _locks[chat_jid]
