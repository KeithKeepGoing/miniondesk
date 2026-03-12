"""Warm memory management — daily logs + micro sync."""
from __future__ import annotations
import logging
import time
from datetime import datetime

from .. import db

log = logging.getLogger(__name__)
MICRO_SYNC_INTERVAL_SECS = 3 * 3600
WARM_RETENTION_DAYS = 30


def append_warm_log(jid: str, user_msg: str, assistant_msg: str) -> None:
    """Append a conversation summary to today's warm memory log."""
    today = datetime.now().strftime("%Y-%m-%d")
    ts = datetime.now().strftime("%H:%M")
    u_preview = (user_msg or "")[:200].replace("\n", " ")
    a_preview = (assistant_msg or "")[:200].replace("\n", " ")
    entry = f"### {ts}\n👤 {u_preview}\n🤖 {a_preview}\n"
    db.append_warm_log(jid, today, entry)
    log.debug("warm_log: appended for jid=%s date=%s", jid, today)


async def run_micro_sync(jid: str) -> None:
    """Quick sync: update hot memory with latest activity note."""
    try:
        recent = db.get_warm_logs_recent(jid, days=1)
        if not recent:
            return
        from .hot import get_hot_memory, update_hot_memory, HOT_MEMORY_MAX_BYTES
        current = get_hot_memory(jid)
        today = datetime.now().strftime("%Y-%m-%d")
        sync_note = f"\n[Last sync: {today}]\n"
        if sync_note not in current:
            new_hot = current.rstrip() + sync_note
            if len(new_hot.encode()) < HOT_MEMORY_MAX_BYTES:
                update_hot_memory(jid, new_hot)
        db.record_micro_sync(jid)
        log.info("warm: micro_sync complete for jid=%s", jid)
    except Exception as exc:
        log.error("warm: micro_sync failed for jid=%s: %s", jid, exc)


def prune_old_warm_logs(jid: str) -> int:
    cutoff_ts = time.time() - WARM_RETENTION_DAYS * 86400
    removed = db.delete_warm_logs_before(jid, cutoff_ts)
    if removed:
        log.info("warm: pruned %d old log entries for jid=%s", removed, jid)
    return removed
