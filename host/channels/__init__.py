"""
Channel Protocol for MinionDesk.
Each channel implements send_message and start().
"""
from __future__ import annotations
from typing import Callable, Protocol

# Registry: channel_name -> channel instance
_channels: dict[str, "Channel"] = {}


class Channel(Protocol):
    async def send_message(self, chat_jid: str, text: str) -> None: ...
    async def start(self, on_message: Callable) -> None: ...


def register_channel(name: str, channel: "Channel") -> None:
    _channels[name] = channel


def get_channel(name: str) -> "Channel | None":
    return _channels.get(name)


def all_channels() -> dict[str, "Channel"]:
    return _channels
