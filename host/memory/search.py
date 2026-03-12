"""Memory search — hybrid FTS5 + recency scoring."""
from __future__ import annotations
import logging
import time
from typing import Any
from .. import db

log = logging.getLogger(__name__)
MAX_RESULTS = 5


def memory_search(jid: str, query: str, limit: int = MAX_RESULTS) -> list[dict[str, Any]]:
    if not query or not query.strip():
        return []
    try:
        results = db.memory_fts_search(jid, query.strip(), limit=limit * 2)
        now = time.time()
        scored = []
        for row in results:
            age_days = max(0, (now - row.get("created_at", now)) / 86400)
            recency = max(0.0, 1.0 - age_days / 30)
            fts = row.get("fts_score", 0.0)
            scored.append({**row, "score": round(fts * 0.7 + recency * 0.3, 4)})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]
    except Exception as exc:
        log.error("memory_search failed for jid=%s: %s", jid, exc)
        return []
