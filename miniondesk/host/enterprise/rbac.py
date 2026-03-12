"""Role-Based Access Control for MinionDesk."""
from __future__ import annotations
import json
import logging
from pathlib import Path

from .. import config

logger = logging.getLogger(__name__)

# Default role permissions
DEFAULT_ROLES: dict[str, list[str]] = {
    "admin": ["*"],
    "manager": ["kb_search", "workflow_trigger", "calendar_check", "send_message"],
    "employee": ["kb_search", "send_message", "schedule_task"],
    "readonly": ["kb_search"],
}


def _load_rbac() -> dict:
    path = Path(config.DATA_DIR) / "rbac.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"roles": DEFAULT_ROLES, "users": {}}


def _save_rbac(data: dict) -> None:
    path = Path(config.DATA_DIR) / "rbac.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_user_role(user_id: str) -> str:
    data = _load_rbac()
    return data["users"].get(user_id, "employee")


def set_user_role(user_id: str, role: str) -> None:
    data = _load_rbac()
    data["users"][user_id] = role
    _save_rbac(data)


def can(user_id: str, action: str) -> bool:
    role = get_user_role(user_id)
    data = _load_rbac()
    perms = data["roles"].get(role, [])
    return "*" in perms or action in perms
