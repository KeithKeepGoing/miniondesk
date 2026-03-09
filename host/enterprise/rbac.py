"""
RBAC: Role-Based Access Control for MinionDesk.
"""
from __future__ import annotations
from .. import db

ROLE_HIERARCHY = {"employee": 0, "manager": 1, "admin": 2}


def get_role(jid: str) -> str:
    conn = db.get_conn()
    row = conn.execute("SELECT role FROM employees WHERE jid = ?", (jid,)).fetchone()
    return row[0] if row else "employee"


def check_permission(jid: str, required_role: str) -> bool:
    user_role = get_role(jid)
    return ROLE_HIERARCHY.get(user_role, 0) >= ROLE_HIERARCHY.get(required_role, 0)


def register_employee(jid: str, name: str, dept: str, role: str = "employee") -> None:
    conn = db.get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO employees (jid, name, dept, role) VALUES (?, ?, ?, ?)",
        (jid, name, dept, role),
    )
    conn.commit()
