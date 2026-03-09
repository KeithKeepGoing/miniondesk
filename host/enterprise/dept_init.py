"""
Department Init: registers department minion groups on startup.
"""
from __future__ import annotations
from pathlib import Path

from .. import db
from .. import config

# Use centralized dept→minion map from config
DEPT_MINIONS = config.DEPT_MINION_MAP


def init_department_groups(project_root: Path) -> None:
    """Register default department groups if not already registered."""
    for dept, minion in DEPT_MINIONS.items():
        chat_jid = f"dept:{dept}"
        existing = db.get_minion(chat_jid)
        if not existing:
            db.register_minion(chat_jid, minion, "internal")


def get_dept_minion(dept: str) -> str:
    return DEPT_MINIONS.get(dept, "phil")
