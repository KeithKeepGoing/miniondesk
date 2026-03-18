"""
AgentIdentity — Stable SHA-256 agent identity for MinionDesk Phase 1.

Each agent gets a deterministic ID derived from its name + role + deployment.
Identity persists in ~/.miniondesk/agents.db.

Identity schema:
  agent_id:   SHA-256 hex (deterministic from name+role+deployment)
  name:       Human-readable name (e.g., "phil", "kevin")
  role:       Agent role (e.g., "assistant", "scheduler", "router")
  deployment: Deployment identifier (e.g., "enterprise-prod")
  created_at: First registration timestamp
  last_seen:  Last activity timestamp
  metadata:   JSON blob for extensible properties
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / ".miniondesk" / "agents.db"


@dataclass
class Identity:
    agent_id: str
    name: str
    role: str
    deployment: str
    created_at: float
    last_seen: float
    metadata: dict[str, Any] = field(default_factory=dict)


def _compute_agent_id(name: str, role: str, deployment: str) -> str:
    """Deterministic SHA-256 identity from name + role + deployment."""
    raw = f"{name}:{role}:{deployment}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class AgentIdentity:
    """Manages stable agent identities backed by SQLite.

    Usage:
        registry = AgentIdentity()
        identity = registry.register("phil", "assistant", "enterprise-prod")
        print(identity.agent_id)  # stable SHA-256

        # Lookup
        phil = registry.get_by_name("phil")
        phil = registry.get_by_id(identity.agent_id)

        # Heartbeat
        registry.heartbeat(identity.agent_id)
    """

    def __init__(self, db_path: Path | str | None = None):
        self._db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._create_tables()
        log.info("AgentIdentity initialized: %s", self._db_path)

    def _create_tables(self) -> None:
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            deployment TEXT NOT NULL,
            created_at REAL NOT NULL,
            last_seen REAL NOT NULL,
            metadata_json TEXT DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_agents_name ON agents(name);
        CREATE INDEX IF NOT EXISTS idx_agents_role ON agents(role);
        CREATE INDEX IF NOT EXISTS idx_agents_deployment ON agents(deployment);
        """)
        self._conn.commit()

    def register(self, name: str, role: str, deployment: str,
                 metadata: dict[str, Any] | None = None) -> Identity:
        """Register or re-register an agent. Returns stable Identity."""
        agent_id = _compute_agent_id(name, role, deployment)
        now = time.time()
        meta_json = json.dumps(metadata or {})

        existing = self.get_by_id(agent_id)
        if existing:
            self._conn.execute(
                "UPDATE agents SET last_seen=?, metadata_json=? WHERE agent_id=?",
                (now, meta_json, agent_id),
            )
            self._conn.commit()
            existing.last_seen = now
            existing.metadata = metadata or {}
            log.debug("Agent re-registered: %s (%s)", name, agent_id[:12])
            return existing

        self._conn.execute(
            """INSERT INTO agents (agent_id, name, role, deployment, created_at, last_seen, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (agent_id, name, role, deployment, now, now, meta_json),
        )
        self._conn.commit()
        log.info("Agent registered: %s (%s)", name, agent_id[:12])
        return Identity(
            agent_id=agent_id, name=name, role=role, deployment=deployment,
            created_at=now, last_seen=now, metadata=metadata or {},
        )

    def get_by_id(self, agent_id: str) -> Identity | None:
        row = self._conn.execute(
            "SELECT agent_id, name, role, deployment, created_at, last_seen, metadata_json "
            "FROM agents WHERE agent_id=?",
            (agent_id,),
        ).fetchone()
        if not row:
            return None
        return Identity(
            agent_id=row[0], name=row[1], role=row[2], deployment=row[3],
            created_at=row[4], last_seen=row[5], metadata=json.loads(row[6] or "{}"),
        )

    def get_by_name(self, name: str) -> list[Identity]:
        rows = self._conn.execute(
            "SELECT agent_id, name, role, deployment, created_at, last_seen, metadata_json "
            "FROM agents WHERE name=?",
            (name,),
        ).fetchall()
        return [
            Identity(
                agent_id=r[0], name=r[1], role=r[2], deployment=r[3],
                created_at=r[4], last_seen=r[5], metadata=json.loads(r[6] or "{}"),
            )
            for r in rows
        ]

    def heartbeat(self, agent_id: str) -> bool:
        """Update last_seen timestamp. Returns False if agent not found."""
        cur = self._conn.execute(
            "UPDATE agents SET last_seen=? WHERE agent_id=?",
            (time.time(), agent_id),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def list_agents(self, role: str | None = None, deployment: str | None = None) -> list[Identity]:
        """List agents, optionally filtered by role or deployment."""
        query = "SELECT agent_id, name, role, deployment, created_at, last_seen, metadata_json FROM agents"
        params: list[Any] = []
        clauses: list[str] = []
        if role:
            clauses.append("role=?")
            params.append(role)
        if deployment:
            clauses.append("deployment=?")
            params.append(deployment)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY last_seen DESC"
        rows = self._conn.execute(query, params).fetchall()
        return [
            Identity(
                agent_id=r[0], name=r[1], role=r[2], deployment=r[3],
                created_at=r[4], last_seen=r[5], metadata=json.loads(r[6] or "{}"),
            )
            for r in rows
        ]

    def remove(self, agent_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM agents WHERE agent_id=?", (agent_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()
        log.info("AgentIdentity closed")
