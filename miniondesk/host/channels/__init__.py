"""Channel protocol and registry."""
from __future__ import annotations
from abc import ABC, abstractmethod

_channels: list["BaseChannel"] = []


class BaseChannel(ABC):
    name: str = "base"

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def send_message(self, jid: str, text: str, sender: str = "") -> None: ...

    async def send_file(self, jid: str, file_path: str, caption: str = "") -> None:
        """Send a file. Override in channels that support it."""
        await self.send_message(jid, f"📎 File: {file_path}\n{caption}")

    def handles(self, jid: str) -> bool:
        """Return True if this channel can handle the given JID."""
        return False


def register_channel(channel: BaseChannel) -> None:
    _channels.append(channel)


def find_channel(jid: str) -> BaseChannel | None:
    for ch in _channels:
        if ch.handles(jid):
            return ch
    return None


def all_channels() -> list[BaseChannel]:
    return list(_channels)
