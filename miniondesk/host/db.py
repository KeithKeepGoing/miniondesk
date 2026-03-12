"""SQLite database for MinionDesk — groups, messages, tasks, genome."""
from __future__ import annotations
import asyncio
import json
import os
import pathlib
import shutil
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

    CREATE INDEX IF NOT EXISTS idx_tasks_status
    ON tasks(status);

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

    CREATE TABLE IF NOT EXISTS group_hot_memory (
        jid         TEXT PRIMARY KEY,
        content     TEXT NOT NULL DEFAULT '',
        updated_at  REAL NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS group_warm_logs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        jid         TEXT NOT NULL,
        log_date    TEXT NOT NULL,
        content     TEXT NOT NULL,
        created_at  REAL NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_warm_logs_jid_date ON group_warm_logs(jid, log_date);

    CREATE TABLE IF NOT EXISTS group_memory_sync (
        jid                  TEXT PRIMARY KEY,
        last_micro_sync      REAL NOT NULL DEFAULT 0,
        last_weekly_compound REAL NOT NULL DEFAULT 0
    );
    """)
    conn.commit()
    # FTS5 virtual table must be created outside executescript (DDL isolation)
    try:
        conn.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS group_warm_logs_fts USING fts5(
                jid UNINDEXED,
                log_date,
                content,
                content='group_warm_logs',
                content_rowid='id'
            )"""
        )
        conn.commit()
    except Exception as _fts_exc:
        import logging as _log
        _log.getLogger(__name__).warning("group_warm_logs_fts creation failed: %s", _fts_exc)


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
    """Delete a group and ALL related data (messages, tasks, genome, evolution, immune) atomically."""
    import logging as _logging
    _log = _logging.getLogger(__name__)
    conn = _conn()
    # Look up the folder before deletion so we can clean up the filesystem afterward
    row = conn.execute("SELECT folder FROM groups WHERE jid=?", (jid,)).fetchone()
    folder = row["folder"] if row else None
    # Use a savepoint so the transaction is re-entrant-safe even if a parent
    # transaction is already open (avoids "cannot start a transaction within a
    # transaction" OperationalError from raw BEGIN strings).
    conn.execute("SAVEPOINT delete_group")
    try:
        for table in (
            "messages", "tasks", "genome", "evolution_runs",
            "evolution_log", "immune_threats",
        ):
            conn.execute(f"DELETE FROM {table} WHERE group_jid=?", (jid,))
        # dev_sessions table may not exist yet (created lazily by DevEngine)
        try:
            conn.execute("DELETE FROM dev_sessions WHERE group_jid=?", (jid,))
        except Exception:
            pass
        conn.execute("DELETE FROM groups WHERE jid=?", (jid,))
        conn.execute("RELEASE SAVEPOINT delete_group")
        conn.commit()
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT delete_group")
        conn.execute("RELEASE SAVEPOINT delete_group")
        raise
    # Clean up group folder after successful DB deletion
    if folder:
        groups_dir = pathlib.Path(os.environ.get("GROUPS_DIR", "groups"))
        group_path = groups_dir / folder
        if group_path.exists() and group_path.is_dir():
            try:
                shutil.rmtree(group_path)
                _log.info("Deleted group folder: %s", group_path)
            except Exception as e:
                _log.warning("Could not delete group folder %s: %s", group_path, e)


# ─── Messages ────────────────────────────────────────────────────────────────

def add_message(group_jid: str, role: str, content: str) -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO messages(group_jid, role, content) VALUES(?,?,?)",
        (group_jid, role, content),
    )
    conn.commit()


def get_history(group_jid: str, limit: int = 20) -> list[dict]:
    # Validate that the group_jid belongs to a registered group before returning
    # any history rows, preventing cross-group data leakage via unvalidated JIDs.
    if not group_jid or not get_group(group_jid):
        return []
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
    conn = _conn()
    conn.execute(
        "UPDATE tasks SET last_run=?, next_run=? WHERE id=?",
        (int(time.time()), next_run, task_id),
    )
    conn.commit()


def delete_task(task_id: str) -> None:
    conn = _conn()
    conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    conn.commit()


def suspend_task(task_id: str, last_error: str = "") -> None:
    """Suspend a task after repeated failures (sets status='suspended')."""
    conn = _conn()
    conn.execute(
        "UPDATE tasks SET status='suspended' WHERE id=?",
        (task_id,),
    )
    conn.commit()


def get_tasks_for_group(group_jid: str) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM tasks WHERE group_jid=?", (group_jid,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_tasks() -> list[dict]:
    """Return all tasks (all statuses) as a list of dicts."""
    rows = _conn().execute("SELECT * FROM tasks").fetchall()
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


def cleanup_orphan_genomes() -> int:
    """Delete genome rows for groups that no longer exist. Returns count deleted."""
    conn = _conn()
    cur = conn.execute(
        "DELETE FROM genome WHERE group_jid NOT IN (SELECT jid FROM groups)"
    )
    conn.commit()
    return cur.rowcount


def get_all_genomes() -> dict[str, dict]:
    """Return all genomes as a dict keyed by group_jid.
    Replaces N individual get_genome() calls with a single query (Issue #97).
    """
    cur = _conn().execute(
        "SELECT group_jid, response_style, formality, "
        "       technical_depth, fitness_score "
        "FROM genome"
    )
    return {
        row["group_jid"]: {
            "group_jid":       row["group_jid"],
            "response_style":  row["response_style"],
            "formality":       row["formality"],
            "technical_depth": row["technical_depth"],
            "fitness_score":   row["fitness_score"],
        }
        for row in cur.fetchall()
    }


def _clamp01(value) -> float | None:
    """Clamp a float value to [0.0, 1.0], or return None if value is None."""
    if value is None:
        return None
    return max(0.0, min(1.0, float(value)))


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
            # Clamp all float fields to [0.0, 1.0] to prevent out-of-range values
            # from corrupting dashboard display or evolution math.
            "formality": _clamp01(data.get("formality")),
            "technical_depth": _clamp01(data.get("technical_depth")),
            "fitness_score": _clamp01(data.get("fitness_score")),
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

_EVOLUTION_RUNS_MAX_PER_GROUP = 1000  # keep only the most recent N rows per group
_EVOLUTION_LOG_MAX_PER_GROUP = 100    # keep only the most recent N evolution log entries


def record_evolution_run(group_jid: str, success: bool, response_ms: int) -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO evolution_runs(group_jid, success, response_ms) VALUES(?,?,?)",
        (group_jid, int(success), response_ms),
    )
    # Prune old rows to prevent unbounded table growth.
    # Keep only the most recent _EVOLUTION_RUNS_MAX_PER_GROUP rows per group.
    conn.execute(
        """DELETE FROM evolution_runs
           WHERE group_jid=? AND id NOT IN (
               SELECT id FROM evolution_runs
               WHERE group_jid=? ORDER BY created_at DESC LIMIT ?
           )""",
        (group_jid, group_jid, _EVOLUTION_RUNS_MAX_PER_GROUP),
    )
    conn.commit()


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
    conn = _conn()
    conn.execute(
        """INSERT INTO evolution_log(group_jid, generation, fitness_score, avg_response_ms, genome_before, genome_after)
           VALUES(?,?,?,?,?,?)""",
        (group_jid, generation, fitness, avg_ms,
         _json.dumps(before, ensure_ascii=False),
         _json.dumps(after, ensure_ascii=False)),
    )
    # Prune old evolution log entries to prevent unbounded growth
    conn.execute(
        """DELETE FROM evolution_log
           WHERE group_jid=? AND id NOT IN (
               SELECT id FROM evolution_log
               WHERE group_jid=? ORDER BY created_at DESC LIMIT ?
           )""",
        (group_jid, group_jid, _EVOLUTION_LOG_MAX_PER_GROUP),
    )
    conn.commit()


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
    now = int(time.time())
    conn.execute(
        """INSERT INTO immune_threats(sender_jid, group_jid, count, last_seen)
           VALUES(?,?,1,?)
           ON CONFLICT(sender_jid, group_jid) DO UPDATE SET
               count=count+1, last_seen=?""",
        (sender_jid, group_jid, now, now),
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
    conn = _conn()
    conn.execute(
        "UPDATE immune_threats SET blocked=0, count=0 WHERE sender_jid=? AND group_jid=?",
        (sender_jid, group_jid),
    )
    conn.commit()


# Maximum age (seconds) for non-blocked immune_threats rows before they are pruned.
# Blocked rows are retained indefinitely until explicitly unblocked.
_IMMUNE_THREATS_MAX_AGE_SECS = 7 * 86400  # 7 days


def immune_prune_old_rows() -> int:
    """Delete non-blocked immune_threats rows older than _IMMUNE_THREATS_MAX_AGE_SECS.

    Blocked rows are kept until explicitly unblocked.
    Returns the number of rows deleted.
    """
    conn = _conn()
    cutoff = int(time.time()) - _IMMUNE_THREATS_MAX_AGE_SECS
    cur = conn.execute(
        "DELETE FROM immune_threats WHERE blocked=0 AND last_seen < ?",
        (cutoff,),
    )
    deleted = cur.rowcount
    conn.commit()
    return deleted


# ─── Dev sessions ─────────────────────────────────────────────────────────────

def get_dev_sessions(group_jid: str, limit: int = 20) -> list[dict]:
    import json as _json
    rows = _conn().execute(
        "SELECT session_id, status, current_stage, prompt, created_at FROM dev_sessions WHERE group_jid=? ORDER BY created_at DESC LIMIT ?",
        (group_jid, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ─── Hot Memory ──────────────────────────────────────────────────────────────

def get_hot_memory(jid: str) -> str:
    conn = _conn()
    row = conn.execute("SELECT content FROM group_hot_memory WHERE jid=?", (jid,)).fetchone()
    return row[0] if row else ""


def set_hot_memory(jid: str, content: str) -> None:
    conn = _conn()
    conn.execute(
        """INSERT INTO group_hot_memory(jid,content,updated_at) VALUES(?,?,?)
           ON CONFLICT(jid) DO UPDATE SET content=excluded.content,updated_at=excluded.updated_at""",
        (jid, content, time.time()),
    )
    conn.commit()


# ─── Warm Memory ─────────────────────────────────────────────────────────────

def append_warm_log(jid: str, log_date: str, content: str) -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO group_warm_logs(jid,log_date,content,created_at) VALUES(?,?,?,?)",
        (jid, log_date, content, time.time()),
    )
    rowid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    try:
        conn.execute(
            "INSERT INTO group_warm_logs_fts(rowid,jid,log_date,content) VALUES(?,?,?,?)",
            (rowid, jid, log_date, content),
        )
    except Exception:
        pass  # FTS5 may not be available; warm log still persisted
    conn.commit()


def get_warm_logs_recent(jid: str, days: int = 1) -> list[dict]:
    cutoff = time.time() - days * 86400
    conn = _conn()
    rows = conn.execute(
        "SELECT id,log_date,content,created_at FROM group_warm_logs WHERE jid=? AND created_at>=? ORDER BY created_at DESC",
        (jid, cutoff),
    ).fetchall()
    return [{"id": r[0], "log_date": r[1], "content": r[2], "created_at": r[3]} for r in rows]


def delete_warm_logs_before(jid: str, cutoff_ts: float) -> int:
    conn = _conn()
    cur = conn.execute("DELETE FROM group_warm_logs WHERE jid=? AND created_at<?", (jid, cutoff_ts))
    conn.commit()
    return cur.rowcount


def memory_fts_search(jid: str, query: str, limit: int = 10) -> list[dict]:
    results = []
    conn = _conn()
    try:
        rows = conn.execute(
            """SELECT w.id,w.log_date,w.content,w.created_at,bm25(group_warm_logs_fts) as fs
               FROM group_warm_logs_fts f
               JOIN group_warm_logs w ON w.id=f.rowid
               WHERE f.jid=? AND group_warm_logs_fts MATCH ?
               ORDER BY fs LIMIT ?""",
            (jid, query, limit),
        ).fetchall()
        for r in rows:
            results.append({"source": "warm", "date": r[1], "content": r[2][:500],
                             "created_at": r[3], "fts_score": abs(r[4]) if r[4] else 0.0})
    except Exception:
        pass
    return results


def record_micro_sync(jid: str) -> None:
    conn = _conn()
    conn.execute(
        """INSERT INTO group_memory_sync(jid,last_micro_sync) VALUES(?,?)
           ON CONFLICT(jid) DO UPDATE SET last_micro_sync=excluded.last_micro_sync""",
        (jid, time.time()),
    )
    conn.commit()


def record_weekly_compound(jid: str) -> None:
    conn = _conn()
    conn.execute(
        """INSERT INTO group_memory_sync(jid,last_weekly_compound) VALUES(?,?)
           ON CONFLICT(jid) DO UPDATE SET last_weekly_compound=excluded.last_weekly_compound""",
        (jid, time.time()),
    )
    conn.commit()


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
