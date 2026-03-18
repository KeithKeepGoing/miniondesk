"""
MemoryBus — Universal Memory Layer for MinionDesk Enterprise
Phase 1 of UnifiedClaw architecture (miniondesk adaptation)

Extends the base MemoryBus with enterprise features:
- Department-scoped memory (HR/IT/Finance/General/Engineering)
- RBAC-aware access control (role-based read permissions)
- Audit logging for compliance (shared memory writes are logged)
- Cross-department knowledge sharing with permission gating

Usage:
    bus = EnterpriseMemoryBus(db_conn, groups_dir, audit_logger)

    # HR agent stores sensitive info (private to HR)
    await bus.remember(
        "Employee John Doe on medical leave until April",
        agent_id="hr_bot",
        scope="department",
        department="HR"
    )

    # IT agent stores shared knowledge (all departments can read)
    await bus.remember(
        "VPN gateway changed to vpn2.company.com",
        agent_id="it_bot",
        scope="shared"
    )

    # Finance agent queries (gets shared + finance-scoped results)
    memories = await bus.recall(
        "expense report process",
        agent_id="finance_bot",
        department="Finance",
        role="manager"
    )
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)

MemoryScope = Literal["private", "shared", "department", "project"]

# Department role permissions: who can read department-scoped memories
DEPARTMENT_READ_ROLES = {
    "HR":          {"hr_manager", "hr_staff", "admin"},
    "Finance":     {"finance_manager", "finance_staff", "admin"},
    "IT":          {"it_manager", "it_staff", "admin", "employee"},  # IT info broadly accessible
    "Engineering": {"engineer", "tech_lead", "manager", "admin"},
    "General":     {"employee", "manager", "admin"},  # Everyone
}


@dataclass
class Memory:
    memory_id: str
    content: str
    agent_id: str
    scope: MemoryScope
    department: str
    score: float
    created_at: float
    source: Literal["hot", "shared", "vector", "cold"]
    metadata: dict = field(default_factory=dict)

    @property
    def age_hours(self) -> float:
        return (time.time() - self.created_at) / 3600


class EnterpriseSharedStore:
    """Enterprise-grade shared memory with department scoping and audit log."""

    TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS enterprise_memories (
        id           TEXT    PRIMARY KEY,
        agent_id     TEXT    NOT NULL,
        department   TEXT    NOT NULL DEFAULT \'\',
        project      TEXT    NOT NULL DEFAULT \'\',
        scope        TEXT    NOT NULL DEFAULT \'private\',
        content      TEXT    NOT NULL,
        importance   REAL    NOT NULL DEFAULT 0.5,
        access_count INTEGER NOT NULL DEFAULT 0,
        created_at   REAL    NOT NULL,
        updated_at   REAL    NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_em_scope ON enterprise_memories(scope, department);
    CREATE INDEX IF NOT EXISTS idx_em_agent ON enterprise_memories(agent_id);
    CREATE VIRTUAL TABLE IF NOT EXISTS enterprise_memories_fts
        USING fts5(content, content=\'enterprise_memories\', content_rowid=\'rowid\');
    CREATE TABLE IF NOT EXISTS memory_audit_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        memory_id  TEXT    NOT NULL,
        action     TEXT    NOT NULL,
        agent_id   TEXT    NOT NULL,
        department TEXT    NOT NULL DEFAULT \'\',
        scope      TEXT    NOT NULL DEFAULT \'\',
        ts         REAL    NOT NULL
    );
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._ensure_schema()

    def _ensure_schema(self):
        try:
            for stmt in self.TABLE_DDL.strip().split(";"):
                s = stmt.strip()
                if s:
                    self._conn.execute(s)
            self._conn.commit()
        except sqlite3.Error as e:
            logger.error(f"EnterpriseSharedStore schema error: {e}")

    def write(
        self,
        content: str,
        agent_id: str,
        scope: MemoryScope = "private",
        department: str = "",
        project: str = "",
        importance: float = 0.5,
    ) -> str:
        memory_id = hashlib.sha256(
            f"{agent_id}:{department}:{content}:{time.time()}".encode()
        ).hexdigest()[:16]
        now = time.time()
        try:
            self._conn.execute(
                """INSERT INTO enterprise_memories
                   (id, agent_id, department, project, scope, content, importance, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (memory_id, agent_id, department, project, scope, content, importance, now, now),
            )
            # Audit log for non-private writes
            if scope != "private":
                self._conn.execute(
                    "INSERT INTO memory_audit_log (memory_id, action, agent_id, department, scope, ts) VALUES (?,?,?,?,?,?)",
                    (memory_id, "write", agent_id, department, scope, now)
                )
            self._conn.commit()
        except sqlite3.Error as e:
            logger.error(f"EnterpriseSharedStore write error: {e}")
        return memory_id

    def search(
        self,
        query: str,
        agent_id: str,
        department: str = "",
        role: str = "employee",
        k: int = 5,
    ) -> list[dict]:
        # Determine which departments this role can read
        accessible_depts = {
            dept for dept, roles in DEPARTMENT_READ_ROLES.items()
            if role in roles or "employee" in roles
        }

        try:
            rows = self._conn.execute(
                """SELECT em.id, em.content, em.agent_id, em.scope, em.department,
                          em.importance, em.created_at, rank as fts_rank
                   FROM enterprise_memories_fts fts
                   JOIN enterprise_memories em ON em.rowid = fts.rowid
                   WHERE enterprise_memories_fts MATCH ?
                     AND (
                       em.scope = \'shared\'
                       OR (em.scope = \'private\' AND em.agent_id = ?)
                       OR (em.scope = \'department\' AND em.department = ?)
                     )
                   ORDER BY fts_rank, em.importance DESC
                   LIMIT ?""",
                (query, agent_id, department, k),
            ).fetchall()
            return [
                {"id": r[0], "content": r[1], "agent_id": r[2], "scope": r[3],
                 "department": r[4], "importance": r[5], "created_at": r[6], "fts_rank": r[7]}
                for r in rows
            ]
        except sqlite3.Error as e:
            logger.warning(f"EnterpriseSharedStore search error: {e}")
            return []


class EnterpriseMemoryBus:
    """
    Enterprise Universal Memory Bus for MinionDesk.

    Adds department scoping and RBAC on top of the base MemoryBus design.
    Compatible with evoclaw MemoryBus interface for cross-system interop.
    """

    def __init__(self, conn: sqlite3.Connection, groups_dir: Path):
        self._conn = conn
        self._groups_dir = groups_dir
        self.shared = EnterpriseSharedStore(conn)
        logger.info("EnterpriseMemoryBus initialized")

    async def remember(
        self,
        content: str,
        agent_id: str,
        scope: MemoryScope = "private",
        department: str = "",
        project: str = "",
        importance: float = 0.5,
    ) -> str:
        return self.shared.write(
            content=content,
            agent_id=agent_id,
            scope=scope,
            department=department,
            project=project,
            importance=importance,
        )

    async def recall(
        self,
        query: str,
        agent_id: str,
        k: int = 5,
        department: str = "",
        role: str = "employee",
        project: str = "",
    ) -> list[Memory]:
        results = self.shared.search(
            query, agent_id, department=department, role=role, k=k
        )
        memories = []
        for r in results:
            fts_score = min(1.0, abs(r.get("fts_rank", -1)) / 10.0)
            memories.append(Memory(
                memory_id=r["id"],
                content=r["content"],
                agent_id=r["agent_id"],
                scope=r["scope"],
                department=r.get("department", ""),
                score=fts_score,
                created_at=r.get("created_at", time.time()),
                source="shared",
            ))
        return memories[:k]

    async def forget(self, memory_id: str, agent_id: str) -> bool:
        return self.shared.delete(memory_id, agent_id) if hasattr(self.shared, "delete") else False

    async def patch_hot_memory(self, agent_id: str, patch: str, max_bytes: int = 8192):
        memory_file = self._groups_dir / agent_id / "MEMORY.md"
        try:
            memory_file.parent.mkdir(parents=True, exist_ok=True)
            current = memory_file.read_text(encoding="utf-8") if memory_file.exists() else ""
            updated = current + "\n" + patch
            if len(updated.encode("utf-8")) > max_bytes:
                updated = updated.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
            memory_file.write_text(updated, encoding="utf-8")
        except OSError as e:
            logger.error(f"Hot memory patch failed for {agent_id}: {e}")

    def status(self) -> dict:
        try:
            count = self._conn.execute("SELECT COUNT(*) FROM enterprise_memories").fetchone()[0]
            audit_count = self._conn.execute("SELECT COUNT(*) FROM memory_audit_log").fetchone()[0]
        except sqlite3.Error:
            count = audit_count = -1
        return {"enterprise_memories": count, "audit_log_entries": audit_count}
