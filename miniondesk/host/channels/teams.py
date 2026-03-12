"""Microsoft Teams channel (stub — extend as needed)."""
from __future__ import annotations
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)
MessageHandler = Callable[[str, str, str], Awaitable[None]]


class TeamsChannel:
    name = "teams"

    def __init__(self, webhook_url: str, on_message: MessageHandler):
        self._webhook = webhook_url
        self._on_message = on_message

    def handles(self, jid: str) -> bool:
        return jid.startswith("teams:")

    async def start(self) -> None:
        logger.info("Teams channel: not yet implemented")

    async def stop(self) -> None:
        pass

    async def send_message(self, jid: str, text: str, sender: str = "") -> None:
        logger.warning("Teams send_message not implemented: %s", jid)

    async def send_file(self, jid: str, file_path: str, caption: str = "") -> None:
        logger.warning("Teams send_file not implemented: %s", jid)
