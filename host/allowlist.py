"""
Allowlist management: controls which JIDs can interact with minions.
"""
from __future__ import annotations
import json
from pathlib import Path
from . import config

_allowlist: set[str] = set()
_allowlist_path: Path = config.DATA_DIR / "allowlist.json"


def load_allowlist() -> None:
    global _allowlist
    if _allowlist_path.exists():
        data = json.loads(_allowlist_path.read_text())
        _allowlist = set(data.get("jids", []))
    else:
        _allowlist = set()


def is_allowed(jid: str) -> bool:
    if not _allowlist:
        return True  # Open if no allowlist configured
    return jid in _allowlist


def add_jid(jid: str) -> None:
    _allowlist.add(jid)
    _save()


def remove_jid(jid: str) -> None:
    _allowlist.discard(jid)
    _save()


def _save() -> None:
    _allowlist_path.parent.mkdir(parents=True, exist_ok=True)
    _allowlist_path.write_text(json.dumps({"jids": list(_allowlist)}, indent=2))
