"""
MinionDesk SQLite Database Layer
"""
from __future__ import annotations
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()  # Protects _conn when accessed from multiple threads


def init(db_path: Path) -> None:
    global _conn
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(str(db_path), check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("PRAGMA busy_timeout=5000")  # Wait up to 5s on lock contention
    _conn.execute("PRAGMA foreign_keys=ON")
    _create_tables()


def _create_tables():
    _conn.executescript("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_jid TEXT NOT NULL,
        sender_jid TEXT,
        content TEXT,
        role TEXT DEFAULT 'user',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS registered_minions (
        chat_jid TEXT PRIMARY KEY,
        minion_name TEXT NOT NULL,
        channel TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS scheduled_tasks (
        id TEXT PRIMARY KEY,
        chat_jid TEXT NOT NULL,
        minion_name TEXT NOT NULL,
        prompt TEXT NOT NULL,
        schedule_type TEXT NOT NULL,
        schedule_value TEXT NOT NULL,
        last_run TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS state (
        chat_jid TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT,
        updated_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (chat_jid, key)
    );

    CREATE TABLE IF NOT EXISTS employees (
        jid TEXT PRIMARY KEY,
        name TEXT,
        dept TEXT,
        role TEXT DEFAULT 'employee',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS workflow_instances (
        id TEXT PRIMARY KEY,
        workflow_type TEXT NOT NULL,
        submitter_jid TEXT,
        data_json TEXT DEFAULT '{}',
        status TEXT DEFAULT 'submitted',
        approved_by TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS meetings (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        start_time TEXT,
        end_time TEXT,
        attendees_json TEXT DEFAULT '[]',
        location TEXT,
        organizer_jid TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS pending_notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target_jid TEXT NOT NULL,
        message TEXT NOT NULL,
        sent INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE VIRTUAL TABLE IF NOT EXISTS kb_chunks USING fts5(
        title, content, source, tokenize='trigram'
    );

    CREATE TABLE IF NOT EXISTS kb_chunks_plain (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        content TEXT,
        source TEXT,
        embedding_json TEXT
    );

    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_jid TEXT NOT NULL,
        action TEXT NOT NULL,
        target TEXT,
        detail TEXT,
        ts TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS minion_prefs (
        chat_jid TEXT PRIMARY KEY,
        minion_name TEXT NOT NULL DEFAULT 'phil',
        updated_at TEXT NOT NULL
    );
    """)
    _conn.executescript("""
    -- Performance indexes (safe to run multiple times with IF NOT EXISTS)
    CREATE INDEX IF NOT EXISTS idx_messages_chat_jid ON messages(chat_jid);
    CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_workflow_status ON workflow_instances(status);
    CREATE INDEX IF NOT EXISTS idx_workflow_submitter ON workflow_instances(submitter_jid);
    CREATE INDEX IF NOT EXISTS idx_workflow_created ON workflow_instances(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_employees_role ON employees(role);
    CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);
    CREATE INDEX IF NOT EXISTS idx_notifications_sent ON pending_notifications(sent, created_at);
    CREATE INDEX IF NOT EXISTS idx_minion_prefs ON minion_prefs(chat_jid);
    CREATE INDEX IF NOT EXISTS idx_tasks_type ON scheduled_tasks(schedule_type, last_run);
    """)
    _conn.commit()
    # Migration: add embedding_json if missing (for existing DBs)
    try:
        _conn.execute("ALTER TABLE kb_chunks_plain ADD COLUMN embedding_json TEXT")
        _conn.commit()
    except Exception:
        pass  # Column already exists
    # Migration: add rejected_by column to workflow_instances (for existing DBs)
    try:
        _conn.execute("ALTER TABLE workflow_instances ADD COLUMN rejected_by TEXT")
        _conn.commit()
    except Exception:
        pass  # Column already exists
    # Migration: add status column to scheduled_tasks (for existing DBs)
    try:
        _conn.execute("ALTER TABLE scheduled_tasks ADD COLUMN status TEXT DEFAULT 'active'")
        _conn.commit()
    except Exception:
        pass  # Column already exists

    # ── Memory system tables (three-tier: hot / warm / cold) ─────────────────
    _conn.executescript("""
    CREATE TABLE IF NOT EXISTS group_hot_memory (
        jid TEXT PRIMARY KEY,
        content TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS group_warm_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        jid TEXT NOT NULL,
        log_date TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at REAL NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_warm_logs_jid ON group_warm_logs(jid, log_date);

    CREATE TABLE IF NOT EXISTS group_memory_sync (
        jid TEXT PRIMARY KEY,
        last_micro_sync REAL NOT NULL DEFAULT 0,
        last_weekly_compound REAL NOT NULL DEFAULT 0
    );
    """)
    _conn.commit()

    # FTS5 virtual table must be created outside executescript for WAL mode compatibility
    try:
        _conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS group_warm_logs_fts USING fts5(
            jid UNINDEXED,
            log_date,
            content,
            content='group_warm_logs',
            content_rowid='id',
            tokenize='trigram'
        )""")
        _conn.commit()
    except Exception:
        pass  # May fail if already exists or trigram not available; degrade gracefully

    # Task execution history log
    try:
        _conn.execute("""CREATE TABLE IF NOT EXISTS task_run_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            chat_jid TEXT NOT NULL,
            run_at TEXT NOT NULL DEFAULT (datetime('now')),
            status TEXT NOT NULL DEFAULT 'success',
            result TEXT,
            error TEXT,
            duration_ms INTEGER
        )""")
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_task_run_logs_task_id ON task_run_logs(task_id)")
        _conn.execute("CREATE INDEX IF NOT EXISTS idx_task_run_logs_chat ON task_run_logs(chat_jid)")
        _conn.commit()
    except Exception:
        pass

    # Container execution log
    try:
        _conn.execute("""CREATE TABLE IF NOT EXISTS container_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          TEXT NOT NULL DEFAULT '',
            jid             TEXT NOT NULL,
            minion_name     TEXT NOT NULL DEFAULT '',
            started_at      REAL NOT NULL,
            finished_at     REAL,
            status          TEXT NOT NULL DEFAULT 'running',
            stderr          TEXT,
            stdout_preview  TEXT,
            response_ms     INTEGER
        )""")
        _conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_md_container_logs_jid ON container_logs(jid, started_at DESC)"
        )
        _conn.commit()
    except Exception:
        pass


def get_conn() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError(
            "Database not initialized. Call db.init(path) before using db functions."
        )
    return _conn


def get_minion(chat_jid: str) -> dict | None:
    row = _conn.execute(
        "SELECT chat_jid, minion_name, channel FROM registered_minions WHERE chat_jid = ?",
        (chat_jid,),
    ).fetchone()
    if not row:
        return None
    return {"chat_jid": row[0], "minion_name": row[1], "channel": row[2]}


def register_minion(chat_jid: str, minion_name: str, channel: str) -> None:
    _conn.execute(
        "INSERT OR REPLACE INTO registered_minions (chat_jid, minion_name, channel) VALUES (?, ?, ?)",
        (chat_jid, minion_name, channel),
    )
    _conn.commit()


def get_all_minions() -> list[dict]:
    rows = _conn.execute(
        "SELECT chat_jid, minion_name, channel FROM registered_minions"
    ).fetchall()
    return [{"chat_jid": r[0], "minion_name": r[1], "channel": r[2]} for r in rows]


def save_message(chat_jid: str, sender_jid: str, content: str, role: str = "user") -> int:
    cur = _conn.execute(
        "INSERT INTO messages (chat_jid, sender_jid, content, role) VALUES (?, ?, ?, ?)",
        (chat_jid, sender_jid, content, role),
    )
    _conn.commit()
    return cur.lastrowid


def get_scheduled_tasks() -> list[dict]:
    rows = _conn.execute("SELECT * FROM scheduled_tasks").fetchall()
    cols = ["id", "chat_jid", "minion_name", "prompt", "schedule_type", "schedule_value", "last_run", "created_at"]
    return [dict(zip(cols, r)) for r in rows]


def get_scheduled_tasks_for_chat(chat_jid: str) -> list[dict]:
    """Return active scheduled tasks for a specific chat."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, chat_jid, minion_name, prompt, schedule_type, schedule_value, last_run, status "
        "FROM scheduled_tasks WHERE chat_jid = ? AND (status IS NULL OR status = 'active') "
        "ORDER BY rowid DESC",
        (chat_jid,)
    ).fetchall()
    cols = ["id", "chat_jid", "minion_name", "prompt", "schedule_type", "schedule_value", "last_run", "status"]
    return [dict(zip(cols, r)) for r in rows]


def cancel_scheduled_task(task_id: str) -> bool:
    """Cancel (soft-delete) a scheduled task. Returns True if found."""
    conn = get_conn()
    cur = conn.execute(
        "UPDATE scheduled_tasks SET status = 'cancelled' WHERE id = ?",
        (task_id,)
    )
    conn.commit()
    return cur.rowcount > 0


def mark_task_error(task_id: str, reason: str = "") -> None:
    """Mark a task as errored so it won't be retried."""
    conn = get_conn()
    conn.execute(
        "UPDATE scheduled_tasks SET status = 'error' WHERE id = ?",
        (task_id,)
    )
    conn.commit()


def upsert_scheduled_task(task: dict) -> None:
    _conn.execute(
        """INSERT OR REPLACE INTO scheduled_tasks
           (id, chat_jid, minion_name, prompt, schedule_type, schedule_value, created_at)
           VALUES (:id, :chat_jid, :minion_name, :prompt, :schedule_type, :schedule_value, :created_at)""",
        task,
    )
    _conn.commit()


def update_task_last_run(task_id: str) -> None:
    _conn.execute(
        "UPDATE scheduled_tasks SET last_run = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), task_id),
    )
    _conn.commit()


def get_pending_notifications() -> list[tuple]:
    return _conn.execute(
        "SELECT id, target_jid, message FROM pending_notifications WHERE sent = 0"
    ).fetchall()


def mark_notification_sent(notif_id: int) -> None:
    _conn.execute("UPDATE pending_notifications SET sent = 1 WHERE id = ?", (notif_id,))
    _conn.commit()


def purge_old_notifications(days: int = 7) -> int:
    """Delete sent notifications older than `days` days. Returns rows deleted."""
    cur = _conn.execute(
        "DELETE FROM pending_notifications WHERE sent = 1 AND created_at < datetime('now', ?)",
        (f"-{days} days",),
    )
    _conn.commit()
    return cur.rowcount


def queue_notification(target_jid: str, message: str) -> None:
    _conn.execute(
        "INSERT INTO pending_notifications (target_jid, message) VALUES (?, ?)",
        (target_jid, message),
    )
    _conn.commit()


def get_employees_by_role(role: str) -> list[dict]:
    rows = _conn.execute(
        "SELECT jid, name, dept, role FROM employees WHERE role = ?",
        (role,),
    ).fetchall()
    return [{"jid": r[0], "name": r[1], "dept": r[2], "role": r[3]} for r in rows]


def get_state(chat_jid: str, key: str) -> str | None:
    row = _conn.execute(
        "SELECT value FROM state WHERE chat_jid = ? AND key = ?",
        (chat_jid, key),
    ).fetchone()
    return row[0] if row else None


def set_state(chat_jid: str, key: str, value: str) -> None:
    _conn.execute(
        "INSERT OR REPLACE INTO state (chat_jid, key, value) VALUES (?, ?, ?)",
        (chat_jid, key, value),
    )
    _conn.commit()


# ── Conversation History ──────────────────────────────────────────
def get_conversation_history(chat_jid: str, limit: int = 10) -> list[dict]:
    """Return last N messages for a chat, oldest first."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT sender_jid, content, role, created_at
           FROM messages
           WHERE chat_jid = ?
           ORDER BY created_at DESC
           LIMIT ?""",
        (chat_jid, limit),
    ).fetchall()
    return [
        {"sender_jid": r[0], "content": r[1], "role": r[2] or "user", "ts": r[3]}
        for r in reversed(rows)
    ]


# ── Audit Log ─────────────────────────────────────────────────────
def audit(actor_jid: str, action: str, target: str = "", detail: str = "") -> None:
    """Record an action in the audit log."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO audit_log (actor_jid, action, target, detail, ts) VALUES (?, ?, ?, ?, ?)",
        (actor_jid, action, target, detail, datetime.utcnow().isoformat()),
    )
    conn.commit()


def get_audit_log(limit: int = 50) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT actor_jid, action, target, detail, ts FROM audit_log ORDER BY ts DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [{"actor_jid": r[0], "action": r[1], "target": r[2], "detail": r[3], "ts": r[4]} for r in rows]


# ── Minion Preferences ────────────────────────────────────────────
def get_user_minion(chat_jid: str) -> str:
    """Return the preferred minion for a chat (default: phil)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT minion_name FROM minion_prefs WHERE chat_jid = ?", (chat_jid,)
    ).fetchone()
    return row[0] if row else "phil"


def set_user_minion(chat_jid: str, minion_name: str) -> None:
    """Set the preferred minion for a chat."""
    conn = get_conn()
    conn.execute(
        """INSERT INTO minion_prefs (chat_jid, minion_name, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(chat_jid) DO UPDATE SET minion_name=excluded.minion_name, updated_at=excluded.updated_at""",
        (chat_jid, minion_name, datetime.utcnow().isoformat()),
    )
    conn.commit()


# ── Hot Memory ────────────────────────────────────────────────────────────────

def get_hot_memory(jid: str) -> str:
    row = _conn.execute(
        "SELECT content FROM group_hot_memory WHERE jid = ?", (jid,)
    ).fetchone()
    return row[0] if row else ""


def set_hot_memory(jid: str, content: str) -> None:
    _conn.execute(
        """INSERT INTO group_hot_memory(jid, content, updated_at)
           VALUES(?, ?, datetime('now'))
           ON CONFLICT(jid) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at""",
        (jid, content),
    )
    _conn.commit()


# ── Warm Memory ───────────────────────────────────────────────────────────────

def append_warm_log(jid: str, log_date: str, content: str) -> None:
    import time as _t
    cur = _conn.execute(
        "INSERT INTO group_warm_logs(jid, log_date, content, created_at) VALUES(?, ?, ?, ?)",
        (jid, log_date, content, _t.time()),
    )
    _conn.commit()
    # Try to keep FTS in sync (best effort)
    try:
        _conn.execute(
            "INSERT INTO group_warm_logs_fts(rowid, jid, log_date, content) VALUES(?, ?, ?, ?)",
            (cur.lastrowid, jid, log_date, content),
        )
        _conn.commit()
    except Exception:
        pass


def get_warm_logs_recent(jid: str, days: int = 1) -> list[dict]:
    import time as _t
    cutoff = _t.time() - days * 86400
    rows = _conn.execute(
        "SELECT id, log_date, content, created_at FROM group_warm_logs "
        "WHERE jid = ? AND created_at >= ? ORDER BY created_at DESC",
        (jid, cutoff),
    ).fetchall()
    return [{"id": r[0], "log_date": r[1], "content": r[2], "created_at": r[3]} for r in rows]


def delete_warm_logs_before(jid: str, cutoff_ts: float) -> int:
    cur = _conn.execute(
        "DELETE FROM group_warm_logs WHERE jid = ? AND created_at < ?", (jid, cutoff_ts)
    )
    _conn.commit()
    return cur.rowcount


def memory_fts_search(jid: str, query: str, limit: int = 10) -> list[dict]:
    """Hybrid search across warm memory using FTS5."""
    results = []
    try:
        rows = _conn.execute(
            """SELECT w.id, w.log_date, w.content, w.created_at,
                      bm25(group_warm_logs_fts) AS fs
               FROM group_warm_logs_fts f
               JOIN group_warm_logs w ON w.id = f.rowid
               WHERE f.jid = ? AND group_warm_logs_fts MATCH ?
               ORDER BY fs
               LIMIT ?""",
            (jid, query, limit),
        ).fetchall()
        for r in rows:
            results.append({
                "source": "warm",
                "date": r[1],
                "content": r[2][:500],
                "created_at": r[3],
                "fts_score": abs(r[4]) if r[4] else 0.0,
            })
    except Exception:
        pass  # FTS unavailable or query syntax error
    return results


def record_micro_sync(jid: str) -> None:
    import time as _t
    _conn.execute(
        """INSERT INTO group_memory_sync(jid, last_micro_sync) VALUES(?, ?)
           ON CONFLICT(jid) DO UPDATE SET last_micro_sync=excluded.last_micro_sync""",
        (jid, _t.time()),
    )
    _conn.commit()


def record_weekly_compound(jid: str) -> None:
    import time as _t
    _conn.execute(
        """INSERT INTO group_memory_sync(jid, last_weekly_compound) VALUES(?, ?)
           ON CONFLICT(jid) DO UPDATE SET last_weekly_compound=excluded.last_weekly_compound""",
        (jid, _t.time()),
    )
    _conn.commit()


# ── Task Run Logs ──────────────────────────────────────────────────────────────

def get_task_run_logs(task_id: str = None, chat_jid: str = None, limit: int = 50) -> list[dict]:
    conn = get_conn()
    cols = ["id", "task_id", "chat_jid", "run_at", "status", "result", "error", "duration_ms"]
    if task_id:
        rows = conn.execute(
            "SELECT id, task_id, chat_jid, run_at, status, result, error, duration_ms "
            "FROM task_run_logs WHERE task_id=? ORDER BY run_at DESC LIMIT ?",
            (task_id, limit)
        ).fetchall()
    elif chat_jid:
        rows = conn.execute(
            "SELECT id, task_id, chat_jid, run_at, status, result, error, duration_ms "
            "FROM task_run_logs WHERE chat_jid=? ORDER BY run_at DESC LIMIT ?",
            (chat_jid, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, task_id, chat_jid, run_at, status, result, error, duration_ms "
            "FROM task_run_logs ORDER BY run_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def log_task_run(task_id: str, chat_jid: str, status: str, result: str = None, error: str = None, duration_ms: int = None) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO task_run_logs(task_id, chat_jid, status, result, error, duration_ms) VALUES(?,?,?,?,?,?)",
        (task_id, chat_jid, status, result, error, duration_ms)
    )
    conn.commit()


# ── Knowledge Base ─────────────────────────────────────────────────────────────

def get_kb_docs(search: str = None, limit: int = 20) -> list[dict]:
    conn = get_conn()
    if search:
        try:
            rows = conn.execute(
                "SELECT title, content, source FROM kb_chunks WHERE kb_chunks MATCH ? LIMIT ?",
                (search, limit)
            ).fetchall()
        except Exception:
            rows = []
    else:
        rows = conn.execute(
            "SELECT title, content, source FROM kb_chunks_plain ORDER BY id DESC LIMIT ?",
            (limit,)
        ).fetchall()
    return [{"title": r[0], "content": (r[1] or "")[:300], "source": r[2]} for r in rows]


# ── Container Logs ─────────────────────────────────────────────────────────────

def log_container_start(run_id: str, jid: str, minion_name: str, started_at: float) -> None:
    """Insert a running row when a container starts."""
    try:
        _conn.execute(
            "INSERT INTO container_logs (run_id, jid, minion_name, started_at, status)"
            " VALUES (?, ?, ?, ?, 'running')",
            (run_id, jid, minion_name, started_at),
        )
        _conn.commit()
    except Exception:
        pass


def log_container_finish(
    run_id: str,
    finished_at: float,
    status: str,
    stderr: str,
    stdout_preview: str,
    response_ms: int,
) -> None:
    """Update container_logs row when a container finishes."""
    try:
        _conn.execute(
            "UPDATE container_logs SET finished_at=?, status=?, stderr=?, stdout_preview=?, response_ms=?"
            " WHERE run_id=?",
            (
                finished_at,
                status,
                (stderr or "")[:32768],
                (stdout_preview or "")[:2048],
                response_ms,
                run_id,
            ),
        )
        _conn.commit()
    except Exception:
        pass


def get_container_logs(jid: str = "", limit: int = 50, status: str = "") -> list[dict]:
    """Return recent container run logs."""
    try:
        parts: list[str] = []
        params: list = []
        if jid:
            parts.append("jid = ?")
            params.append(jid)
        if status:
            parts.append("status = ?")
            params.append(status)
        where = ("WHERE " + " AND ".join(parts)) if parts else ""
        params.append(limit)
        cols = ["id", "run_id", "jid", "minion_name", "started_at", "finished_at",
                "status", "stderr", "stdout_preview", "response_ms"]
        rows = _conn.execute(
            f"SELECT id, run_id, jid, minion_name, started_at, finished_at, status,"
            f" stderr, stdout_preview, response_ms"
            f" FROM container_logs {where} ORDER BY started_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return []
