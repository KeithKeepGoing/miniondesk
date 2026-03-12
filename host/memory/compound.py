"""Weekly compound — memory pruning + distillation."""
from __future__ import annotations
import logging
from datetime import datetime
from .. import db
from .warm import prune_old_warm_logs
from .hot import get_hot_memory, update_hot_memory

log = logging.getLogger(__name__)
COMPOUND_INTERVAL_SECS = 7 * 86400


async def run_weekly_compound(jid: str) -> None:
    try:
        pruned = prune_old_warm_logs(jid)
        week = datetime.now().strftime("%Y-W%W")
        hot = get_hot_memory(jid)
        note = f"\n[Weekly compound: {week}, pruned {pruned} old entries]\n"
        if note not in hot:
            update_hot_memory(jid, (hot + note).strip())
        db.record_weekly_compound(jid)
        log.info("weekly_compound done for jid=%s (pruned %d)", jid, pruned)
    except Exception as exc:
        log.error("weekly_compound failed for jid=%s: %s", jid, exc)
