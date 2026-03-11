"""SQLite database for MinionDesk — groups, messages, tasks, genome."""
from __future__ import annotations
import asyncio
import json
import os
import sqlite3
import threading
import time
from pathlib import Path

_DB_PATH: Path | None = None
_local = threading.local()


def init(db_path: str | Path) -> None:
    global _DB_PATH
    _DB_PATH = Path(db_path)
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _migrate()


def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


def _migrate() -> None:
    conn = _conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS groups (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        jid         TEXT NOT NULL UNIQUE,
        folder      TEXT NOT NULL UNIQUE,
        name        TEXT NOT NULL,
        minion      TEXT NOT NULL DEFAULT 'mini',
        trigger     TEXT NOT NULL DEFAULT '@Mini',
        created_at  INTEGER NOT NULL DEFAULT (strftime('%s','now'))
    );

    CREATE TABLE IF NOT EXISTS messages (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        group_jid   TEXT NOT NULL,
        role        TEXT NOT NULL,  -- 'user' | 'assistant'
        content     TEXT NOT NULL,
        created_at  INTEGER NOT NULL DEFAULT (strftime('%s','now'))
    );
    CREATE INDEX IF NOT EXISTS idx_messages_group ON messages(group_jid, created_at);

    CREATE TABLE IF NOT EXISTS tasks (
        id              TEXT PRIMARY KEY,
        group_jid       TEXT NOT NULL,
        prompt          TEXT NOT NULL,
        schedule_type   TEXT NOT NULL,
        schedule_value  TEXT NOT NULL,
        next_run        INTEGER,
        last_run        INTEGER,
        status          TEXT NOT NULL DEFAULT 'active',
        created_at      INTEGER NOT NULL DEFAULT (strftime('%s','now'))
    );

    CREATE TABLE IF NOT EXISTS genome (
        group_jid       TEXT PRIMARY KEY,
        response_style  TEXT NOT NULL DEFAULT 'balanced',
        formality       REAL NOT NULL DEFAULT 0.5,
        technical_depth REAL NOT NULL DEFAULT 0.5,
        fitness_score   REAL NOT NULL DEFAULT 0.5,
        updated_at      INTEGER NOT NULL DEFAULT (strftime('%s','now'))
    );

    CREATE TABLE IF NOT EXISTS knowledge (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        title       TEXT NOT NULL,
        content     TEXT NOT NULL,
        source      TEXT,
        dept        TEXT,
        created_at  INTEGER NOT NULL DEFAULT (strftime('%s','now'))
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts
    USING fts5(title, content, content=knowledge, content_rowid=id);

    CREATE TABLE IF NOT EXISTS evolution_runs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        group_jid   TEXT NOT NULL,
        success     INTEGER NOT NULL,
        response_ms INTEGER NOT NULL,
        created_at  INTEGER NOT NULL DEFAULT (strftime('%s','now'))
    );
    CREATE INDEX IF NOT EXISTS idx_evol_group ON evolution_runs(group_jid, created_at);

    CREATE TABLE IF NOT EXISTS evolution_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        group_jid       TEXT NOT NULL,
        generation      INTEGER NOT NULL DEFAULT 0,
        fitness_score   REAL NOT NULL,
        avg_response_ms REAL NOT NULL,
        genome_before   TEXT NOT NULL,
        genome_after    TEXT NOT NULL,
        created_at      INTEGER NOT NULL DEFAULT (strftime('%s','now'))
    );

    CREATE TABLE IF NOT EXISTS immune_threats (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_jid  TEXT NOT NULL,
        group_jid   TEXT NOT NULL,
        count       INTEGER NOT NULL DEFAULT 1,
        blocked     INTEGER NOT NULL DEFAULT 0,
        last_seen   INTEGER NOT NULL DEFAULT (strftime('%s','now')),
        UNIQUE(sender_jid, group_jid)
    );
    CREATE INDEX IF NOT EXISTS idx_immune ON immune_threats(sender_jid, group_jid);
    """)
    conn.commit()


# ─── Groups ──────────────────────────────────────────────────────────────────

def register_group(jid: str, folder: str, name: str, minion: str = "mini", trigger: str = "") -> dict:
    conn = _conn()
    if not trigger:
        trigger = f"@{minion.capitalize()}"
    conn.execute(
        """INSERT INTO groups(jid, folder, name, minion, trigger)
           VALUES(?,?,?,?,?)
           ON CONFLICT(jid) DO UPDATE SET
               folder=excluded.folder, name=excluded.name,
               minion=excluded.minion, trigger=excluded.trigger""",
        (jid, folder, name, minion, trigger),
    )
    conn.commit()
    return get_group(jid)


def get_group(jid: str) -> dict | None:
    row = _conn().execute("SELECT * FROM groups WHERE jid=?", (jid,)).fetchone()
    return dict(row) if row else None


def get_all_groups() -> list[dict]:
    rows = _conn().execute("SELECT * FROM groups").fetchall()
    return [dict(r) for r in rows]


def delete_group(jid: str) -> None:
    _conn().execute("DELETE FROM groups WHERE jid=?", (jid,))
    _conn().commit()


# ─── Messages ────────────────────────────────────────────────────────────────

def add_message(group_jid: str, role: str, content: str) -> None:
    _conn().execute(
        "INSERT INTO messages(group_jid, role, content) VALUES(?,?,?)",
        (group_jid, role, content),
    )
    _conn().commit()


def get_history(group_jid: str, limit: int = 20) -> list[dict]:
    rows = _conn().execute(
        "SELECT role, content FROM messages WHERE group_jid=? ORDER BY created_at DESC LIMIT ?",
        (group_jid, limit),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


# ─── Tasks ───────────────────────────────────────────────────────────────────

def upsert_task(task: dict) -> None:
    conn = _conn()
    conn.execute(
        """INSERT INTO tasks(id, group_jid, prompt, schedule_type, schedule_value, next_run, status)
           VALUES(:id,:group_jid,:prompt,:schedule_type,:schedule_value,:next_run,:status)
           ON CONFLICT(id) DO UPDATE SET
               prompt=excluded.prompt, schedule_type=excluded.schedule_type,
               schedule_value=excluded.schedule_value, next_run=excluded.next_run,
               status=excluded.status""",
        task,
    )
    conn.commit()


def get_due_tasks() -> list[dict]:
    now = int(time.time())
    rows = _conn().execute(
        "SELECT * FROM tasks WHERE status='active' AND next_run<=?", (now,)
    ).fetchall()
    return [dict(r) for r in rows]


def update_task_run(task_id: str, next_run: int) -> None:
    _conn().execute(
        "UPDATE tasks SET last_run=?, next_run=? WHERE id=?",
        (int(time.time()), next_run, task_id),
    )
    _conn().commit()


def delete_task(task_id: str) -> None:
    _conn().execute("DELETE FROM tasks WHERE id=?", (task_id,))
    _conn().commit()


def get_tasks_for_group(group_jid: str) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM tasks WHERE group_jid=?", (group_jid,)
    ).fetchall()
    return [dict(r) for r in rows]


# ─── Genome ───────────────────────────────────────────────────────────────────

def get_genome(group_jid: str) -> dict:
    row = _conn().execute("SELECT * FROM genome WHERE group_jid=?", (group_jid,)).fetchone()
    if row:
        return dict(row)
    return {
        "group_jid": group_jid,
        "response_style": "balanced",
        "formality": 0.5,
        "technical_depth": 0.5,
        "fitness_score": 0.5,
    }


def update_genome(group_jid: str, data: dict) -> None:
    conn = _conn()
    now = int(time.time())
    conn.execute(
        """INSERT INTO genome(group_jid, response_style, formality, technical_depth, fitness_score, updated_at)
           VALUES(
               :group_jid,
               COALESCE(:response_style, 'balanced'),
               COALESCE(:formality, 0.5),
               COALESCE(:technical_depth, 0.5),
               COALESCE(:fitness_score, 0.5),
               :updated_at
           )
           ON CONFLICT(group_jid) DO UPDATE SET
               response_style=COALESCE(:response_style, response_style),
               formality=COALESCE(:formality, formality),
               technical_depth=COALESCE(:technical_depth, technical_depth),
               fitness_score=COALESCE(:fitness_score, fitness_score),
               updated_at=:updated_at""",
        {
            "group_jid": group_jid,
            "response_style": data.get("response_style"),
            "formality": data.get("formality"),
            "technical_depth": data.get("technical_depth"),
            "fitness_score": data.get("fitness_score"),
            "updated_at": now,
        },
    )
    conn.commit()


# ─── Knowledge Base ───────────────────────────────────────────────────────────

def kb_add(title: str, content: str, source: str = "", dept: str = "") -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO knowledge(title, content, source, dept) VALUES(?,?,?,?)",
        (title, content, source, dept),
    )
    rowid = cur.lastrowid
    conn.execute(
        "INSERT INTO knowledge_fts(rowid, title, content) VALUES(?,?,?)",
        (rowid, title, content),
    )
    conn.commit()
    return rowid


def kb_search(query: str, limit: int = 5, dept: str = "") -> list[dict]:
    conn = _conn()
    try:
        # FTS5 search
        if dept:
            rows = conn.execute(
                """SELECT k.* FROM knowledge k
                   JOIN knowledge_fts f ON k.id=f.rowid
                   WHERE f.knowledge_fts MATCH ? AND k.dept=?
                   ORDER BY rank LIMIT ?""",
                (query, dept, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT k.* FROM knowledge k
                   JOIN knowledge_fts f ON k.id=f.rowid
                   WHERE f.knowledge_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (query, limit),
            ).fetchall()
    except sqlite3.OperationalError:
        # Fallback to LIKE
        rows = conn.execute(
            "SELECT * FROM knowledge WHERE title LIKE ? OR content LIKE ? LIMIT ?",
            (f"%{query}%", f"%{query}%", limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ─── Evolution runs ───────────────────────────────────────────────────────────

def record_evolution_run(group_jid: str, success: bool, response_ms: int) -> None:
    _conn().execute(
        "INSERT INTO evolution_runs(group_jid, success, response_ms) VALUES(?,?,?)",
        (group_jid, int(success), response_ms),
    )
    _conn().commit()


def get_recent_evolution_runs(group_jid: str, limit: int = 20) -> list[dict]:
    rows = _conn().execute(
        "SELECT success, response_ms, created_at FROM evolution_runs WHERE group_jid=? ORDER BY created_at DESC LIMIT ?",
        (group_jid, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def log_evolution(
    group_jid: str,
    generation: int,
    fitness: float,
    avg_ms: float,
    before: dict,
    after: dict,
) -> None:
    import json as _json
    _conn().execute(
        """INSERT INTO evolution_log(group_jid, generation, fitness_score, avg_response_ms, genome_before, genome_after)
           VALUES(?,?,?,?,?,?)""",
        (group_jid, generation, fitness, avg_ms,
         _json.dumps(before, ensure_ascii=False),
         _json.dumps(after, ensure_ascii=False)),
    )
    _conn().commit()


# ─── Immune system ────────────────────────────────────────────────────────────

def immune_check(sender_jid: str, group_jid: str) -> bool:
    """Return True if sender is allowed (not blocked)."""
    row = _conn().execute(
        "SELECT blocked FROM immune_threats WHERE sender_jid=? AND group_jid=?",
        (sender_jid, group_jid),
    ).fetchone()
    return row is None or not row["blocked"]


def immune_record(sender_jid: str, group_jid: str) -> int:
    """Record a message and return current count for this sender."""
    conn = _conn()
    conn.execute(
        """INSERT INTO immune_threats(sender_jid, group_jid, count, last_seen)
           VALUES(?,?,1,strftime('%s','now'))
           ON CONFLICT(sender_jid, group_jid) DO UPDATE SET
               count=count+1, last_seen=strftime('%s','now')""",
        (sender_jid, group_jid),
    )
    conn.commit()
    row = conn.execute(
        "SELECT count FROM immune_threats WHERE sender_jid=? AND group_jid=?",
        (sender_jid, group_jid),
    ).fetchone()
    return row["count"] if row else 1


def immune_block(sender_jid: str, group_jid: str) -> None:
    """Block a sender."""
    _conn().execute(
        "UPDATE immune_threats SET blocked=1 WHERE sender_jid=? AND group_jid=?",
        (sender_jid, group_jid),
    )
    _conn().commit()


def immune_unblock(sender_jid: str, group_jid: str) -> None:
    """Unblock a sender."""
    _conn().execute(
        "UPDATE immune_threats SET blocked=0, count=0 WHERE sender_jid=? AND group_jid=?",
        (sender_jid, group_jid),
    )
    _conn().commit()


# ─── Dev sessions ─────────────────────────────────────────────────────────────

def get_dev_sessions(group_jid: str, limit: int = 20) -> list[dict]:
    import json as _json
    rows = _conn().execute(
        "SELECT session_id, status, current_stage, prompt, created_at FROM dev_sessions WHERE group_jid=? ORDER BY created_at DESC LIMIT ?",
        (group_jid, limit),
    ).fetchall()
    return [dict(r) for r in rows]


import atexit

def _close_connections() -> None:
    """Close all thread-local DB connections on shutdown."""
    if hasattr(_local, "conn") and _local.conn is not None:
        try:
            _local.conn.close()
        except Exception:
            pass
        _local.conn = None

atexit.register(_close_connections)
