"""Department initialization — register minion groups for each department."""
from __future__ import annotations
import logging

from .. import db

logger = logging.getLogger(__name__)


def init_departments(
    dept_jids: dict[str, str],  # dept_name → jid
    dept_folders: dict[str, str],  # dept_name → folder
) -> None:
    """Register department groups in the database."""
    dept_minion_map = {
        "hr":      ("kevin", "@Kevin"),
        "it":      ("stuart", "@Stuart"),
        "finance": ("bob",    "@Bob"),
        "general": ("mini",   "@Mini"),
    }
    for dept, jid in dept_jids.items():
        folder = dept_folders.get(dept, dept)
        minion, trigger = dept_minion_map.get(dept, ("mini", "@Mini"))
        db.register_group(
            jid=jid,
            folder=folder,
            name=dept.capitalize(),
            minion=minion,
            trigger=trigger,
        )
        logger.info("Initialized department '%s': jid=%s minion=%s", dept, jid, minion)
