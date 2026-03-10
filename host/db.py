"""
MinionDesk SQLite Database Layer
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime
from pathlib import Path

_conn: sqlite3.Connection | None = None


def init(db_path: Path) -> None:
    global _conn
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(str(db_path), check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL")
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
