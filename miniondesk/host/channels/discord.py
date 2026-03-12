"""Discord channel (stub — extend as needed)."""
from __future__ import annotations
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)
MessageHandler = Callable[[str, str, str], Awaitable[None]]


class DiscordChannel:
    name = "discord"

    def __init__(self, token: str, on_message: MessageHandler):
        self._token = token
        self._on_message = on_message
        self._client = None

    def handles(self, jid: str) -> bool:
        return jid.startswith("dc:")

    async def start(self) -> None:
        logger.info("Discord channel: not yet implemented")

    async def stop(self) -> None:
        pass

    async def send_message(self, jid: str, text: str, sender: str = "") -> None:
        logger.warning("Discord send_message not implemented: %s", jid)

    async def send_file(self, jid: str, file_path: str, caption: str = "") -> None:
        logger.warning("Discord send_file not implemented: %s", jid)
