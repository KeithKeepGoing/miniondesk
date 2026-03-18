"""
RBAC — Role-Based Access Control for MinionDesk — Phase 3 Enhanced.
Extends original employee/manager/admin with Permission enum + operation gates.
"""
from __future__ import annotations
from enum import Enum
from typing import Set, Optional, List
import time as _time
import logging
from .. import db

logger = logging.getLogger(__name__)

# ── Legacy role hierarchy (backward compatible) ──────────────────────────────
ROLE_HIERARCHY = {"employee": 0, "manager": 1, "admin": 2}

# ── Phase 3: Permission enum ──────────────────────────────────────────────────
class Permission(str, Enum):
    MEMORY_READ    = "memory:read"
    MEMORY_WRITE   = "memory:write"
    MEMORY_DELETE  = "memory:delete"
    AGENT_SPAWN    = "agent:spawn"
    AGENT_KILL     = "agent:kill"
    AGENT_LIST     = "agent:list"
    TASK_SUBMIT    = "task:submit"
    TASK_CANCEL    = "task:cancel"
    REGISTRY_READ  = "registry:read"
    REGISTRY_WRITE = "registry:write"
    RBAC_GRANT     = "rbac:grant"
    RBAC_REVOKE    = "rbac:revoke"
    # Enterprise
    JIRA_READ      = "jira:read"
    JIRA_WRITE     = "jira:write"
    LDAP_READ      = "ldap:read"
    HPC_SUBMIT     = "hpc:submit"
    WORKFLOW_RUN   = "workflow:run"


ROLE_PERMISSIONS = {
    "admin": set(Permission),
    "manager": {
        Permission.MEMORY_READ, Permission.MEMORY_WRITE,
        Permission.AGENT_SPAWN, Permission.AGENT_KILL, Permission.AGENT_LIST,
        Permission.TASK_SUBMIT, Permission.TASK_CANCEL,
        Permission.REGISTRY_READ,
        Permission.JIRA_READ, Permission.JIRA_WRITE,
        Permission.LDAP_READ, Permission.HPC_SUBMIT, Permission.WORKFLOW_RUN,
    },
    "employee": {
        Permission.MEMORY_READ,
        Permission.AGENT_LIST, Permission.TASK_SUBMIT,
        Permission.REGISTRY_READ,
        Permission.JIRA_READ, Permission.WORKFLOW_RUN,
    },
}

# ── Role cache ────────────────────────────────────────────────────────────────
_role_cache: dict = {}  # {jid: (role, fetched_at)}
_CACHE_TTL = 60.0


def _get_cached_role(jid: str) -> Optional[str]:
    entry = _role_cache.get(jid)
    if entry and (_time.time() - entry[1]) < _CACHE_TTL:
        return entry[0]
    return None


def _invalidate_role_cache(jid: str) -> None:
    _role_cache.pop(jid, None)


def get_role(jid: str) -> str:
    cached = _get_cached_role(jid)
    if cached is not None:
        return cached
    conn = db.get_conn()
    row = conn.execute("SELECT role FROM employees WHERE jid = ?", (jid,)).fetchone()
    role = row[0] if row else "employee"
    _role_cache[jid] = (role, _time.time())
    return role


def check_permission(jid: str, required_role: str) -> bool:
    """Legacy role check (backward compatible)."""
    user_role = get_role(jid)
    return ROLE_HIERARCHY.get(user_role, 0) >= ROLE_HIERARCHY.get(required_role, 0)


def has_permission(jid: str, permission: Permission) -> bool:
    """Phase 3: fine-grained permission check."""
    role = get_role(jid)
    return permission in ROLE_PERMISSIONS.get(role, set())


def require_permission(jid: str, permission: Permission) -> bool:
    """Raise PermissionError if jid lacks permission."""
    if not has_permission(jid, permission):
        raise PermissionError(f"{jid} lacks permission: {permission.value}")
    return True


def register_employee(jid: str, name: str, dept: str, role: str = "employee") -> None:
    conn = db.get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO employees (jid, name, dept, role) VALUES (?, ?, ?, ?)",
        (jid, name, dept, role),
    )
    conn.commit()
    _invalidate_role_cache(jid)
    logger.info(f"Registered employee: {name} ({jid}) as {role} in {dept}")
