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

from . import register_channel

logger = logging.getLogger(__name__)

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

    def is_configured(self) -> bool:
        return bool(self.homeserver and self.access_token and self.user_id)


class MatrixChannel:
    """Channel wrapper for MatrixClient — implements the Channel protocol."""

    def __init__(self, client: MatrixClient):
        self._client = client

    async def send_message(self, chat_jid: str, text: str) -> None:
        # chat_jid format: "matrix:{room_id}" or bare room_id
        room_id = chat_jid.removeprefix("matrix:")
        await self._client.send(text, room_id=room_id or None)

    async def start(self, on_message: Callable) -> None:
        logger.info(f"Matrix channel starting: {self._client.user_id}")
        while True:
            msgs = await self._client.sync_once()
            for msg in msgs:
                # Forward each incoming Matrix message through the main on_message pipeline
                chat_jid = f"matrix:{msg.room_id}"
                sender_jid = msg.sender
                try:
                    await on_message(
                        chat_jid=chat_jid,
                        sender_jid=sender_jid,
                        text=msg.body,
                        channel="matrix",
                    )
                except Exception as e:
                    logger.error(f"Matrix handler error: {e}")
            if not msgs:
                await asyncio.sleep(1)


def init() -> None:
    global _matrix_channel
    client = MatrixClient()
    if not client.is_configured():
        logger.debug("Matrix channel not configured — skipping")
        return
    channel = MatrixChannel(client)
    _matrix_channel = channel
    register_channel("matrix", channel)
    logger.info("Matrix channel initialized")


def get_client() -> Optional[MatrixClient]:
    if _matrix_channel is not None:
        return _matrix_channel._client
    return None
