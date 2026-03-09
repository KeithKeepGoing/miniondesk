"""
Discord channel for MinionDesk using discord.py.
"""
from __future__ import annotations
import logging
from typing import Callable

from . import register_channel

logger = logging.getLogger(__name__)


async def _auto_route_minion(chat_jid: str, text: str) -> str:
    """
    Pick the best minion for this message.
    Priority: user preference > keyword score >= 2 > LLM fallback > default.
    """
    from host import db, config
    from host.enterprise import dept_router

    # 1. Respect explicit user preference
    preferred = db.get_user_minion(chat_jid)
    if preferred:
        return preferred

    # 2. Keyword routing (fast, no API cost)
    dept, score = dept_router.route_with_score(text)
    if score >= 2:
        return config.DEPT_MINION_MAP.get(dept, config.DEFAULT_MINION)

    # 3. LLM fallback for ambiguous messages (async, costs tokens)
    try:
        dept = await dept_router.route_with_llm(text, fallback="general")
        return config.DEPT_MINION_MAP.get(dept, config.DEFAULT_MINION)
    except Exception:
        pass

    return config.DEFAULT_MINION


class DiscordChannel:
    def __init__(self, token: str):
        self._token = token
        self._client = None

    async def send_message(self, chat_jid: str, text: str) -> None:
        if not self._client:
            return
        # chat_jid format: "dc:{channel_id}"
        channel_id = int(chat_jid.removeprefix("dc:"))
        try:
            channel = self._client.get_channel(channel_id)
            if channel:
                # Split long messages at newline boundaries
                if len(text) <= 2000:
                    await channel.send(text)
                else:
                    parts = []
                    current = []
                    current_len = 0
                    for line in text.splitlines(keepends=True):
                        if current_len + len(line) > 1900 and current:
                            parts.append("".join(current))
                            current = []
                            current_len = 0
                        current.append(line)
                        current_len += len(line)
                    if current:
                        parts.append("".join(current))
                    for part in parts:
                        await channel.send(part)
        except Exception as e:
            logger.error(f"Discord send error: {e}")

    async def start(self, on_message: Callable) -> None:
        try:
            import discord
        except ImportError:
            logger.warning("discord.py not installed, Discord disabled")
            return

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)

        _host_callback = on_message  # capture before inner function shadows it

        @self._client.event
        async def on_message(message: discord.Message):
            if message.author.bot:
                return
            chat_jid = f"dc:{message.channel.id}"
            sender_jid = str(message.author.id)
            message_content = message.content

            # Help command
            if message_content.startswith("!help") or message_content.startswith("!start"):
                help_text = (
                    "🍌 **MinionDesk 企業助理**\n\n"
                    "**可用指令：**\n"
                    "• `!help` — 顯示此說明\n"
                    "• `!minions` — 列出所有助理\n"
                    "• `!minion <名字>` — 切換助理\n"
                    "• `!status` — 查看我的申請進度\n\n"
                    "**助理介紹：**\n"
                    "• **Phil** — 首席助理\n"
                    "• **Kevin** — HR（請假/薪資）\n"
                    "• **Stuart** — IT（電腦/帳號）\n"
                    "• **Bob** — 財務（報帳/預算）\n\n"
                    "直接傳訊息就能開始！"
                )
                await message.channel.send(help_text)
                return

            # Status command
            if message_content.startswith("!status"):
                try:
                    from host import db as _db
                    conn = _db.get_conn()
                    rows = conn.execute(
                        "SELECT id, workflow_type, status, created_at FROM workflow_instances WHERE submitter_jid = ? ORDER BY created_at DESC LIMIT 10",
                        (sender_jid,),
                    ).fetchall()
                    if not rows:
                        await message.channel.send("您目前沒有任何申請記錄。")
                    else:
                        icons = {"submitted": "⏳", "approved": "✅", "rejected": "❌", "expired": "⏰"}
                        lines = ["📋 **您的申請記錄：**\n"]
                        for wf_id, wf_type, status, created_at in rows:
                            icon = icons.get(status, "❓")
                            date = created_at[:10] if created_at else "?"
                            lines.append(f"{icon} `[{wf_id}]` {wf_type} — {status} ({date})")
                        await message.channel.send("\n".join(lines))
                except Exception as e:
                    await message.channel.send(f"查詢失敗：{e}")
                return

            # Handle !minion command
            if message_content.startswith("!minion") or message_content.startswith("!minions"):
                parts = message_content.split()
                from .. import config
                available = config.AVAILABLE_MINIONS
                if len(parts) < 2:
                    try:
                        from .. import db as _db
                        current = _db.get_user_minion(chat_jid)
                    except Exception:
                        current = "phil"
                    await message.channel.send(
                        f"🍌 目前的小小兵：**{current}**\n"
                        f"可用：{', '.join(available)}\n"
                        f"切換：!minion kevin"
                    )
                    return
                name = parts[1].lower()
                if name not in available:
                    await message.channel.send(f"❌ 找不到小小兵 '{name}'。可用：{', '.join(available)}")
                    return
                try:
                    from .. import db as _db
                    _db.set_user_minion(chat_jid, name)
                    _db.audit(sender_jid, "minion_switch", chat_jid, f"to={name}")
                except Exception:
                    pass
                await message.channel.send(f"✅ 已切換到 **{name}**！")
                return

            # Rate limiting
            try:
                from .. import ratelimit
                allowed, reason = await ratelimit.check(sender_jid)
                if not allowed:
                    await message.channel.send(reason)
                    return
            except Exception:
                pass

            # Immune scan
            try:
                from .. import immune
                threat = immune.scan(message_content)
                if threat.blocked:
                    await message.channel.send(f"🛡️ {threat.reason}")
                    try:
                        from .. import db as _db
                        _db.audit(sender_jid, "threat_blocked", chat_jid, threat.pattern)
                    except Exception:
                        pass
                    return
            except Exception:
                pass

            # Auto-route to the best minion for this message
            try:
                routed_minion = await _auto_route_minion(chat_jid, message_content)
                from host import db as _db
                _db.register_minion(chat_jid, routed_minion, "discord")
            except Exception:
                pass

            async with message.channel.typing():
                result = await _host_callback(
                    chat_jid=chat_jid,
                    sender_jid=sender_jid,
                    text=message_content,
                    channel="discord",
                )

        # Run in background task, storing reference for error handling and cancellation
        import asyncio
        self._client_task = asyncio.create_task(self._client.start(self._token))

        def _on_task_done(task):
            if not task.cancelled():
                exc = task.exception()
                if exc:
                    logger.error(f"Discord client crashed: {exc}")

        self._client_task.add_done_callback(_on_task_done)
        logger.info("Discord channel starting...")


    async def stop(self):
        if hasattr(self, '_client_task') and self._client_task:
            self._client_task.cancel()
            await self._client.close()


def init(token: str) -> None:
    if not token:
        return
    channel = DiscordChannel(token)
    register_channel("discord", channel)
