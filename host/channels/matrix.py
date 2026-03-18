"""
Matrix Channel — Phase 3
Matrix.org protocol integration for MinionDesk.
Same interface as telegram.py / discord.py.

Config:
  MATRIX_HOMESERVER    — https://matrix.org
  MATRIX_USER_ID       — @miniondesk:matrix.org
  MATRIX_ACCESS_TOKEN  — bot token
  MATRIX_ROOM_ID       — default room
"""
import os
import asyncio
import logging
from typing import Optional, Callable, List
from dataclasses import dataclass, field
import time

logger = logging.getLogger(__name__)

_send_callback: Optional[Callable] = None
_matrix_channel = None


@dataclass
class MatrixMessage:
    room_id: str
    sender: str
    body: str
    event_id: str = ""
    timestamp: float = field(default_factory=time.time)
    formatted_body: Optional[str] = None


class MatrixClient:
    def __init__(self):
        self.homeserver = os.getenv("MATRIX_HOMESERVER", "").rstrip("/")
        self.user_id = os.getenv("MATRIX_USER_ID", "")
        self.access_token = os.getenv("MATRIX_ACCESS_TOKEN", "")
        self.default_room = os.getenv("MATRIX_ROOM_ID", "")
        self._sync_token: Optional[str] = None
        self._handlers: List[Callable] = []

    def _headers(self):
        return {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"}

    async def send(self, text: str, room_id: Optional[str] = None) -> Optional[str]:
        room = room_id or self.default_room
        if not room or not self.access_token:
            return None
        try:
            import aiohttp, uuid, json
            txn = uuid.uuid4().hex
            url = f"{self.homeserver}/_matrix/client/v3/rooms/{room}/send/m.room.message/{txn}"
            payload = {"msgtype": "m.text", "body": text}
            async with aiohttp.ClientSession() as s:
                async with s.put(url, headers=self._headers(), json=payload) as r:
                    if r.status == 200:
                        data = await r.json()
                        return data.get("event_id")
        except Exception as e:
            logger.error(f"Matrix send error: {e}")
        return None

    async def sync_once(self) -> List[MatrixMessage]:
        messages = []
        if not self.access_token:
            return messages
        try:
            import aiohttp
            params = {"timeout": 30000}
            if self._sync_token:
                params["since"] = self._sync_token
            url = f"{self.homeserver}/_matrix/client/v3/sync"
            async with aiohttp.ClientSession() as s:
                async with s.get(url, headers=self._headers(), params=params) as r:
                    if r.status != 200:
                        return messages
                    data = await r.json()
                    self._sync_token = data.get("next_batch")
                    for room_id, rd in data.get("rooms", {}).get("join", {}).items():
                        for ev in rd.get("timeline", {}).get("events", []):
                            if ev.get("type") != "m.room.message":
                                continue
                            if ev.get("sender") == self.user_id:
                                continue
                            c = ev.get("content", {})
                            messages.append(MatrixMessage(
                                room_id=room_id, sender=ev.get("sender", ""),
                                body=c.get("body", ""), event_id=ev.get("event_id", ""),
                                timestamp=ev.get("origin_server_ts", 0) / 1000,
                                formatted_body=c.get("formatted_body"),
                            ))
        except Exception as e:
            logger.error(f"Matrix sync error: {e}")
        return messages

    def on_message(self, fn: Callable):
        self._handlers.append(fn)
        return fn

    async def start(self):
        logger.info(f"Matrix channel starting: {self.user_id}")
        while True:
            msgs = await self.sync_once()
            for msg in msgs:
                for h in self._handlers:
                    try:
                        await h(msg)
                    except Exception as e:
                        logger.error(f"Matrix handler error: {e}")
            if not msgs:
                await asyncio.sleep(1)

    def is_configured(self) -> bool:
        return bool(self.homeserver and self.access_token and self.user_id)


def init():
    global _matrix_channel
    _matrix_channel = MatrixClient()
    if not _matrix_channel.is_configured():
        logger.debug("Matrix channel not configured — skipping")
        return
    logger.info("Matrix channel initialized")


def get_client() -> Optional[MatrixClient]:
    return _matrix_channel
