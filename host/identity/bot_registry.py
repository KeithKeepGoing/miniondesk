"""
Cross-bot Identity Registry — Phase 3
Shared protocol: crossbot/1.0
Compatible with evoclaw BotRegistry.
"""
import hashlib, json, time, sqlite3, logging
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class BotIdentity:
    bot_id: str
    name: str
    display_name: str
    framework: str
    channel: str
    capabilities: List[str] = field(default_factory=list)
    ws_endpoint: Optional[str] = None
    http_endpoint: Optional[str] = None
    public_key: Optional[str] = None
    registered_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    trusted: bool = False

    @staticmethod
    def make_bot_id(name: str, framework: str, channel: str) -> str:
        raw = f"{name.lower()}:{framework.lower()}:{channel.lower()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BotIdentity":
        valid = {k for k in d if k in cls.__dataclass_fields__}
        return cls(**{k: d[k] for k in valid})


class BotRegistry:
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(Path.home() / ".miniondesk" / "bot_registry.db")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS bots (
                bot_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                display_name TEXT, framework TEXT NOT NULL, channel TEXT NOT NULL,
                capabilities TEXT DEFAULT '[]', ws_endpoint TEXT, http_endpoint TEXT,
                public_key TEXT, registered_at REAL, last_seen REAL, trusted INTEGER DEFAULT 0
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_handshakes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                initiator_bot_id TEXT NOT NULL, target_bot_id TEXT NOT NULL,
                status TEXT DEFAULT 'pending', initiated_at REAL, completed_at REAL, nonce TEXT
            )
        """)
        self._conn.commit()

    def register(self, identity: BotIdentity) -> BotIdentity:
        self._conn.execute("""
            INSERT INTO bots (bot_id,name,display_name,framework,channel,capabilities,
                ws_endpoint,http_endpoint,public_key,registered_at,last_seen,trusted)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(bot_id) DO UPDATE SET
                display_name=excluded.display_name, ws_endpoint=excluded.ws_endpoint,
                http_endpoint=excluded.http_endpoint, last_seen=excluded.last_seen,
                capabilities=excluded.capabilities
        """, (identity.bot_id, identity.name, identity.display_name, identity.framework,
              identity.channel, json.dumps(identity.capabilities), identity.ws_endpoint,
              identity.http_endpoint, identity.public_key, identity.registered_at,
              identity.last_seen, int(identity.trusted)))
        self._conn.commit()
        return identity

    def lookup(self, bot_id: str) -> Optional[BotIdentity]:
        row = self._conn.execute("SELECT * FROM bots WHERE bot_id=?", (bot_id,)).fetchone()
        return self._row_to_identity(row) if row else None

    def lookup_by_name(self, name: str) -> Optional[BotIdentity]:
        row = self._conn.execute(
            "SELECT * FROM bots WHERE lower(name)=lower(?) OR lower(display_name)=lower(?)",
            (name, name)).fetchone()
        return self._row_to_identity(row) if row else None

    def list_all(self) -> List[BotIdentity]:
        rows = self._conn.execute("SELECT * FROM bots ORDER BY registered_at").fetchall()
        return [self._row_to_identity(r) for r in rows]

    def list_trusted(self) -> List[BotIdentity]:
        rows = self._conn.execute("SELECT * FROM bots WHERE trusted=1").fetchall()
        return [self._row_to_identity(r) for r in rows]

    def trust(self, bot_id: str) -> bool:
        cur = self._conn.execute("UPDATE bots SET trusted=1 WHERE bot_id=?", (bot_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def initiate_handshake(self, initiator_id: str, target_id: str) -> str:
        import secrets
        nonce = secrets.token_hex(16)
        self._conn.execute("""
            INSERT INTO bot_handshakes (initiator_bot_id,target_bot_id,status,initiated_at,nonce)
            VALUES (?,?,?,?,?)
        """, (initiator_id, target_id, "pending", time.time(), nonce))
        self._conn.commit()
        return nonce

    def complete_handshake(self, initiator_id: str, target_id: str, nonce: str) -> bool:
        row = self._conn.execute("""
            SELECT id FROM bot_handshakes
            WHERE initiator_bot_id=? AND target_bot_id=? AND nonce=? AND status='pending'
        """, (initiator_id, target_id, nonce)).fetchone()
        if not row:
            return False
        self._conn.execute("UPDATE bot_handshakes SET status='completed', completed_at=? WHERE id=?",
                          (time.time(), row[0]))
        self._conn.execute("UPDATE bots SET trusted=1 WHERE bot_id IN (?,?)", (initiator_id, target_id))
        self._conn.commit()
        return True

    def update_last_seen(self, bot_id: str):
        self._conn.execute("UPDATE bots SET last_seen=? WHERE bot_id=?", (time.time(), bot_id))
        self._conn.commit()

    def _row_to_identity(self, row) -> BotIdentity:
        cols = [d[0] for d in self._conn.execute("SELECT * FROM bots LIMIT 0").description]
        d = dict(zip(cols, row))
        d["capabilities"] = json.loads(d.get("capabilities") or "[]")
        d["trusted"] = bool(d.get("trusted", 0))
        return BotIdentity.from_dict(d)

    def close(self):
        self._conn.close()


KNOWN_BOTS: Dict[str, dict] = {
    "xiao_bai": {"name":"小白","display_name":"Andy","framework":"nanoclaw","channel":"telegram",
                 "capabilities":["memory","code","analysis","multi-channel"]},
    "xiao_eve": {"name":"小Eve","display_name":"Eve","framework":"evoclaw","channel":"discord",
                 "capabilities":["memory","evolution","fitness","enterprise"],"http_endpoint":"http://localhost:8767"},
    "miniondesk": {"name":"MinionDesk","display_name":"MinionDesk","framework":"miniondesk","channel":"telegram",
                   "capabilities":["enterprise","jira","ldap","hpc","workflow","rbac"]},
}


def bootstrap_known_bots(registry: BotRegistry):
    import os
    for key, cfg in KNOWN_BOTS.items():
        bot_id = BotIdentity.make_bot_id(cfg["name"], cfg["framework"], cfg["channel"])
        identity = BotIdentity(
            bot_id=bot_id, name=cfg["name"], display_name=cfg["display_name"],
            framework=cfg["framework"], channel=cfg["channel"],
            capabilities=cfg["capabilities"],
            ws_endpoint=os.getenv(f"{key.upper()}_WS_ENDPOINT"),
            http_endpoint=cfg.get("http_endpoint"),
            trusted=True,
        )
        registry.register(identity)
        logger.info(f"Bootstrapped: {identity.name} -> {bot_id}")
