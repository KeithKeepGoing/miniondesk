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
    today = datetime.now().strftime("%Y-%m-%d")
    ts = datetime.now().strftime("%H:%M")
    u = (user_msg or "")[:200].replace("\n", " ")
    a = (assistant_msg or "")[:200].replace("\n", " ")
    entry = f"### {ts}\n👤 {u}\n🤖 {a}\n"
    db.append_warm_log(jid, today, entry)


async def run_micro_sync(jid: str) -> None:
    try:
        recent = db.get_warm_logs_recent(jid, days=1)
        if not recent:
            return
        from .hot import get_hot_memory, update_hot_memory, HOT_MEMORY_MAX_BYTES
        current = get_hot_memory(jid)
        today = datetime.now().strftime("%Y-%m-%d")
        note = f"\n[Last sync: {today}]\n"
        if note not in current:
            new_hot = current.rstrip() + note
            if len(new_hot.encode()) < HOT_MEMORY_MAX_BYTES:
                update_hot_memory(jid, new_hot)
        db.record_micro_sync(jid)
        log.info("micro_sync complete for jid=%s", jid)
    except Exception as exc:
        log.error("micro_sync failed for jid=%s: %s", jid, exc)


def prune_old_warm_logs(jid: str) -> int:
    cutoff = time.time() - WARM_RETENTION_DAYS * 86400
    return db.delete_warm_logs_before(jid, cutoff)
