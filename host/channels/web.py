"""
Web channel for MinionDesk Portal.
Delivers replies back to WebSocket connections via the portal server.
"""
from __future__ import annotations
import asyncio
import inspect
import logging
from typing import Callable, Dict
from . import register_channel

log = logging.getLogger(__name__)

_reply_callbacks: Dict[str, Callable] = {}


def register_reply_callback(chat_jid: str, callback: Callable) -> None:
    _reply_callbacks[chat_jid] = callback


def unregister_reply_callback(chat_jid: str) -> None:
    _reply_callbacks.pop(chat_jid, None)


class WebChannel:
    async def send_message(self, chat_jid: str, text: str) -> None:
        cb = _reply_callbacks.get(chat_jid)
        if cb:
            try:
                result = cb(text)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                log.warning("Web reply callback failed for %s: %s", chat_jid, exc)
        else:
            log.debug("No web reply callback for %s", chat_jid)

    async def start(self, on_message: Callable) -> None:
        # Web channel is started via webportal.py
        log.info("Web channel registered")


def init() -> None:
    channel = WebChannel()
    register_channel("web", channel)
