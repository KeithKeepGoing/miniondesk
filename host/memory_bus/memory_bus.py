"""
MemoryBus — Universal Memory Bus for MinionDesk Phase 1.

Provides three-tier memory architecture:
  - Hot:    per-group MEMORY.md (8KB, fast read)
  - Shared: cross-agent shared key-value store (SQLite)
  - Vector: embedding-based semantic search (sqlite-vec ready)

DB path: ~/.miniondesk/memory.db
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".miniondesk" / "memory.db"
HOT_MAX_BYTES = 8 * 1024  # 8KB


class SharedMemoryStore:
    """Cross-agent shared key-value store backed by SQLite."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lock = threading.Lock()

    def get(self, namespace: str, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM shared_memory WHERE namespace=? AND key=?",
            (namespace, key),
        ).fetchone()
        return row[0] if row else None

    def set(self, namespace: str, key: str, value: str, *, ttl_secs: int = 0) -> None:
        expires_at = (time.time() + ttl_secs) if ttl_secs > 0 else 0
        with self._lock:
            self._conn.execute(
                """INSERT INTO shared_memory (namespace, key, value, expires_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(namespace, key) DO UPDATE
                   SET value=excluded.value, expires_at=excluded.expires_at, updated_at=excluded.updated_at""",
                (namespace, key, value, expires_at, time.time()),
            )
            self._conn.commit()

    def delete(self, namespace: str, key: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM shared_memory WHERE namespace=? AND key=?",
                (namespace, key),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def list_keys(self, namespace: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT key FROM shared_memory WHERE namespace=? AND (expires_at=0 OR expires_at>?)",
            (namespace, time.time()),
        ).fetchall()
        return [r[0] for r in rows]

    def gc(self) -> int:
        """Remove expired entries."""
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM shared_memory WHERE expires_at > 0 AND expires_at < ?",
                (time.time(),),
            )
            self._conn.commit()
            return cur.rowcount


class VectorStore:
    """Embedding-based semantic search store (sqlite-vec ready).

    Currently stores embeddings as JSON blobs. When sqlite-vec is available,
    this will use native vector operations for similarity search.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._lock = threading.Lock()

    def upsert(self, doc_id: str, content: str, embedding: list[float] | None = None,
               metadata: dict | None = None) -> None:
        emb_json = json.dumps(embedding) if embedding else None
        meta_json = json.dumps(metadata) if metadata else "{}"
        with self._lock:
            self._conn.execute(
                """INSERT INTO vector_store (doc_id, content, embedding_json, metadata_json, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(doc_id) DO UPDATE
                   SET content=excluded.content, embedding_json=excluded.embedding_json,
                       metadata_json=excluded.metadata_json, updated_at=excluded.updated_at""",
                (doc_id, content, emb_json, meta_json, time.time()),
            )
            self._conn.commit()

    def search_text(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """FTS5 text search fallback when embeddings are not available."""
        try:
            rows = self._conn.execute(
                """SELECT doc_id, content, metadata_json
                   FROM vector_store_fts
                   WHERE vector_store_fts MATCH ?
                   LIMIT ?""",
                (query, limit),
            ).fetchall()
            return [
                {"doc_id": r[0], "content": r[1], "metadata": json.loads(r[2] or "{}")}
                for r in rows
            ]
        except Exception:
            return []

    def get(self, doc_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT doc_id, content, embedding_json, metadata_json FROM vector_store WHERE doc_id=?",
            (doc_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "doc_id": row[0],
            "content": row[1],
            "embedding": json.loads(row[2]) if row[2] else None,
            "metadata": json.loads(row[3] or "{}"),
        }

    def delete(self, doc_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM vector_store WHERE doc_id=?", (doc_id,))
            self._conn.commit()
            return cur.rowcount > 0


class MemoryBus:
    """Universal Memory Bus — orchestrates hot, shared, and vector tiers.

    Usage:
        bus = MemoryBus()          # uses ~/.miniondesk/memory.db
        bus = MemoryBus(db_path)   # custom path

        # Hot memory (per-group)
        bus.hot_get("group-jid")
        bus.hot_set("group-jid", "content...")

        # Shared memory (cross-agent KV)
        bus.shared.set("agents", "last_sync", "2026-03-18")
        bus.shared.get("agents", "last_sync")

        # Vector store (semantic search)
        bus.vector.upsert("doc-1", "content...", embedding=[...])
        bus.vector.search_text("query")
    """

    def __init__(self, db_path: Path | str | None = None):
        self._db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._create_tables()
        self.shared = SharedMemoryStore(self._conn)
        self.vector = VectorStore(self._conn)
        log.info("MemoryBus initialized: %s", self._db_path)

    def _create_tables(self) -> None:
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS bus_hot_memory (
            jid TEXT PRIMARY KEY,
            content TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS shared_memory (
            namespace TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL DEFAULT '',
            expires_at REAL NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (namespace, key)
        );
        CREATE INDEX IF NOT EXISTS idx_shared_ns ON shared_memory(namespace);

        CREATE TABLE IF NOT EXISTS vector_store (
            doc_id TEXT PRIMARY KEY,
            content TEXT NOT NULL DEFAULT '',
            embedding_json TEXT,
            metadata_json TEXT DEFAULT '{}',
            updated_at REAL NOT NULL DEFAULT 0
        );
        """)
        self._conn.commit()

        # FTS5 for vector_store text search fallback
        try:
            self._conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS vector_store_fts USING fts5(
                    doc_id, content, metadata_json, tokenize='trigram'
                )
            """)
            self._conn.commit()
        except Exception:
            pass

    # ── Hot memory tier ───────────────────────────────────────────

    def hot_get(self, jid: str) -> str:
        row = self._conn.execute(
            "SELECT content FROM bus_hot_memory WHERE jid=?", (jid,)
        ).fetchone()
        return row[0] if row else ""

    def hot_set(self, jid: str, content: str) -> None:
        encoded = content.encode("utf-8")
        if len(encoded) > HOT_MAX_BYTES:
            content = encoded[:HOT_MAX_BYTES].decode("utf-8", errors="ignore")
            log.warning("MemoryBus: hot memory truncated to 8KB for jid=%s", jid)
        self._conn.execute(
            """INSERT INTO bus_hot_memory (jid, content, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(jid) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at""",
            (jid, content, time.time()),
        )
        self._conn.commit()

    # ── Lifecycle ─────────────────────────────────────────────────

    def close(self) -> None:
        self._conn.close()
        log.info("MemoryBus closed")
