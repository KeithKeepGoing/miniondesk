"""Telegram channel."""
from __future__ import annotations
import asyncio
import logging
import pathlib
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)

# Callback type: (jid, text, trigger) -> None
MessageHandler = Callable[[str, str, str], Awaitable[None]]


class TelegramChannel:
    name = "telegram"

    def __init__(self, token: str, on_message: MessageHandler):
        self._token = token
        self._on_message = on_message
        self._app = None

    def handles(self, jid: str) -> bool:
        return jid.startswith("tg:")

    async def start(self) -> None:
        try:
            from telegram.ext import Application, MessageHandler, filters
            self._app = Application.builder().token(self._token).build()
            self._app.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle)
            )
            await self._app.initialize()
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)
            logger.info("Telegram channel started")
        except Exception as exc:
            logger.error("Telegram start failed: %s", exc)
            raise

    async def stop(self) -> None:
        if self._app:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception:
                pass

    async def _handle(self, update, context) -> None:
        if not update.message or not update.message.text:
            return
        chat_id = update.effective_chat.id
        jid = f"tg:{chat_id}"
        text = update.message.text
        from_user = update.message.from_user
        trigger = f"@{from_user.username}" if from_user and from_user.username else text
        try:
            await self._on_message(jid, text, trigger)
        except Exception as exc:
            logger.error("Error handling Telegram message: %s", exc)

    async def send_message(self, jid: str, text: str, sender: str = "") -> None:
        if not self._app:
            return
        chat_id = int(jid.replace("tg:", ""))
        # Split long messages
        max_len = 4096
        for i in range(0, len(text), max_len):
            chunk = text[i:i + max_len]
            try:
                await self._app.bot.send_message(chat_id=chat_id, text=chunk)
            except Exception as exc:
                logger.error("Telegram send_message failed: %s", exc)

    async def send_file(self, jid: str, file_path: str, caption: str = "") -> None:
        if not self._app:
            return
        chat_id = int(jid.replace("tg:", ""))
        p = pathlib.Path(file_path)
        if not p.exists():
            await self.send_message(jid, f"⚠️ File not found: {p.name}")
            return
        try:
            with open(p, "rb") as f:
                await self._app.bot.send_document(
                    chat_id=chat_id,
                    document=f,
                    filename=p.name,
                    caption=caption or f"📎 {p.name}",
                )
        except Exception as exc:
            logger.error("Telegram send_file failed: %s", exc)
            await self.send_message(jid, f"⚠️ Failed to send file '{p.name}': {exc}")
