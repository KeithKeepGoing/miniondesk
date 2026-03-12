"""MinionDesk immune system — rate limiting and sender blocking."""
from __future__ import annotations
import logging
import time
from collections import defaultdict

from . import db

logger = logging.getLogger(__name__)

# Rate limit: max messages per sender per minute
MAX_MSGS_PER_MINUTE = 15
BLOCK_THRESHOLD = 30  # Auto-block after this many messages in 60s

# In-memory sliding window (supplement to DB)
_sender_timestamps: dict[str, list[float]] = defaultdict(list)


def is_allowed(sender_jid: str, group_jid: str) -> bool:
    """
    Return True if this sender is allowed to send a message.
    Checks: DB block status, then rate limit.
    """
    # DB block check
    if not db.immune_check(sender_jid, group_jid):
        logger.warning("Blocked sender: %s in %s", sender_jid, group_jid)
        return False

    # In-memory rate limit (sliding window, 60s)
    now = time.time()
    window_key = f"{sender_jid}:{group_jid}"
    timestamps = _sender_timestamps[window_key]

    # Remove old entries; delete the key entirely when empty to prevent unbounded dict growth
    fresh = [t for t in timestamps if now - t < 60]
    fresh.append(now)
    if fresh:
        _sender_timestamps[window_key] = fresh
    elif window_key in _sender_timestamps:
        del _sender_timestamps[window_key]
    count = len(fresh)

    if count > BLOCK_THRESHOLD:
        db.immune_block(sender_jid, group_jid)
        logger.warning(
            "Auto-blocked sender %s in %s: %d msgs/min", sender_jid, group_jid, count
        )
        return False

    if count > MAX_MSGS_PER_MINUTE:
        logger.info("Rate limited sender %s: %d msgs/min", sender_jid, count)
        return False

    return True


def record_message(sender_jid: str, group_jid: str) -> None:
    """Record a message from a sender (for DB tracking)."""
    try:
        db.immune_record(sender_jid, group_jid)
    except Exception as exc:
        logger.debug("immune_record error: %s", exc)
