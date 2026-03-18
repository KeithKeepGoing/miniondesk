"""
RBAC — Role-Based Access Control for MinionDesk — Phase 3 Enhanced.
Extends original employee/manager/admin with Permission enum + operation gates.
"""
from __future__ import annotations
from enum import Enum
from typing import Set, Optional, List
import time
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


def get_role(jid: str) -> str:
    conn = db.get_conn()
    row = conn.execute("SELECT role FROM employees WHERE jid = ?", (jid,)).fetchone()
    return row[0] if row else "employee"


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
    logger.info(f"Registered employee: {name} ({jid}) as {role} in {dept}")
