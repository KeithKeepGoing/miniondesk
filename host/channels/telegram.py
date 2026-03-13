"""
Telegram channel for MinionDesk using python-telegram-bot.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Callable

from . import register_channel
from host import db

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


async def _send_typing_loop(bot, chat_id: int, stop_event: asyncio.Event) -> None:
    """Keep sending typing action every 4s until stop_event is set."""
    while not stop_event.is_set():
        try:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass
        try:
            await asyncio.wait_for(asyncio.shield(stop_event.wait()), timeout=4.0)
        except asyncio.TimeoutError:
            pass


def _split_message(text: str, max_len: int = 4000) -> list[str]:
    """Split a long message into chunks at newline boundaries."""
    if len(text) <= max_len:
        return [text]

    parts = []
    current = []
    current_len = 0

    for line in text.splitlines(keepends=True):
        if current_len + len(line) > max_len and current:
            parts.append("".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line)

    if current:
        parts.append("".join(current))

    return parts or [text[:max_len]]


class TelegramChannel:
    def __init__(self, token: str):
        self._token = token
        self._app = None

    async def send_message(self, chat_jid: str, text: str) -> None:
        if not self._app:
            return
        # chat_jid format: "tg:{chat_id}"
        chat_id = chat_jid.removeprefix("tg:")
        try:
            parts = _split_message(text)
            for part in parts:
                await self._app.bot.send_message(chat_id=chat_id, text=part)
        except Exception as e:
            logger.error(f"Telegram send error: {e}")

    async def start(self, on_message: Callable) -> None:
        try:
            from telegram.ext import Application, MessageHandler, CommandHandler, filters
            from telegram import Update
            from telegram.ext import ContextTypes
        except ImportError:
            logger.warning("python-telegram-bot not installed, Telegram disabled")
            return

        self._app = Application.builder().token(self._token).build()

        async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not update.message or not update.message.text:
                return
            chat_id = str(update.message.chat_id)
            chat_jid = f"tg:{chat_id}"
            user_id = str(update.message.from_user.id) if update.message.from_user else ""
            sender_jid = user_id
            text = update.message.text

            # Rate limiting
            try:
                from .. import ratelimit
                allowed, reason = await ratelimit.check(user_id)
                if not allowed:
                    await update.message.reply_text(reason)
                    return
            except Exception:
                pass

            # Immune scan
            try:
                from .. import immune
                threat = immune.scan(text)
                if threat.blocked:
                    await update.message.reply_text(f"🛡️ {threat.reason}")
                    try:
                        from .. import db as _db
                        _db.audit(user_id, "threat_blocked", chat_jid, threat.pattern)
                    except Exception:
                        pass
                    return
            except Exception:
                pass

            # Auto-route to the best minion for this message
            try:
                routed_minion = await _auto_route_minion(chat_jid, text)
                from .. import db as _db
                _db.register_minion(chat_jid, routed_minion, "telegram")
            except Exception:
                pass

            # Start typing indicator
            stop_typing = asyncio.Event()
            typing_task = asyncio.create_task(
                _send_typing_loop(context.bot, update.effective_chat.id, stop_typing)
            )

            try:
                await on_message(chat_jid=chat_jid, sender_jid=sender_jid, text=text, channel="telegram")
            finally:
                stop_typing.set()
                typing_task.cancel()
                try:
                    await typing_task
                except asyncio.CancelledError:
                    pass

        async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            help_text = (
                "🍌 *MinionDesk 企業助理*\n\n"
                "*可用指令：*\n"
                "• /help — 顯示此說明\n"
                "• /minions — 列出所有助理\n"
                "• /minion <名字> — 切換助理（例：/minion kevin）\n"
                "• /status — 查看我的申請進度\n\n"
                "*助理介紹：*\n"
                "• *Phil* — 首席助理，協調所有部門\n"
                "• *Kevin* — HR，請假/薪資/福利\n"
                "• *Stuart* — IT，電腦/帳號/網路\n"
                "• *Bob* — 財務，報帳/預算/採購\n\n"
                "直接傳訊息就能開始！例如：「我想申請三天年假」"
            )
            await update.message.reply_text(help_text, parse_mode="Markdown")

        async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            sender_jid = str(update.effective_user.id)
            try:
                conn = db.get_conn()
                rows = conn.execute(
                    """SELECT id, workflow_type, status, created_at
                       FROM workflow_instances
                       WHERE submitter_jid = ?
                       ORDER BY created_at DESC LIMIT 10""",
                    (sender_jid,),
                ).fetchall()

                if not rows:
                    await update.message.reply_text("您目前沒有任何申請記錄。")
                    return

                status_icons = {
                    "submitted": "⏳",
                    "approved": "✅",
                    "rejected": "❌",
                    "expired": "⏰",
                }
                lines = ["📋 *您的申請記錄：*\n"]
                for wf_id, wf_type, status, created_at in rows:
                    icon = status_icons.get(status, "❓")
                    date = created_at[:10] if created_at else "?"
                    lines.append(f"{icon} [{wf_id}] {wf_type} — {status} ({date})")

                await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
            except Exception as e:
                await update.message.reply_text(f"查詢失敗：{e}")

        async def cmd_minion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            """Handle /minion command to switch minions."""
            chat_jid = f"tg:{update.effective_chat.id}"
            args = context.args or []

            from .. import config
            available = config.AVAILABLE_MINIONS

            if not args:
                try:
                    from .. import db as _db
                    current = _db.get_user_minion(chat_jid)
                except Exception:
                    current = "phil"
                await update.message.reply_text(
                    f"🍌 目前的小小兵：*{current}*\n"
                    f"可用：{', '.join(available)}\n"
                    f"切換：/minion kevin",
                    parse_mode="Markdown",
                )
                return

            name = args[0].lower()
            if name not in available:
                await update.message.reply_text(f"❌ 找不到小小兵 '{name}'。可用：{', '.join(available)}")
                return

            try:
                from .. import db as _db
                _db.set_user_minion(chat_jid, name)
                _db.audit(str(update.effective_user.id), "minion_switch", chat_jid, f"to={name}")
            except Exception:
                pass
            await update.message.reply_text(f"✅ 已切換到 *{name}*！", parse_mode="Markdown")

        MAX_FILE_BYTES = 1 * 1024 * 1024  # 1 MB limit

        async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            """Handle file uploads — extract text and process via on_message callback."""
            chat_jid = f"tg:{update.effective_chat.id}"
            user_id = str(update.effective_user.id) if update.effective_user else ""

            doc = update.message.document
            if not doc:
                return

            # Reject oversized files before downloading
            if doc.file_size and doc.file_size > MAX_FILE_BYTES:
                await update.message.reply_text(
                    f"⚠️ 檔案太大（{doc.file_size // 1024}KB），上限為 1MB。"
                )
                return

            # Only handle text files
            supported_types = ["text/plain", "text/markdown", "application/json", "text/csv"]
            if (doc.mime_type not in supported_types and
                    not (doc.file_name or "").endswith((".txt", ".md", ".csv", ".json"))):
                await update.message.reply_text("📎 目前只支援文字檔案（.txt, .md, .csv, .json）")
                return

            try:
                processing_msg = await update.message.reply_text("📎 正在處理檔案...")
                file = await context.bot.get_file(doc.file_id)
                file_bytes = await file.download_as_bytearray()
                file_text = file_bytes.decode("utf-8", errors="replace")[:5000]

                prompt = f"用戶上傳了一個檔案 '{doc.file_name}'，內容如下：\n\n{file_text}"

                if update.message.caption:
                    prompt += f"\n\n用戶的問題：{update.message.caption}"

                if processing_msg:
                    try:
                        await processing_msg.delete()
                    except Exception:
                        pass

                # Start typing indicator for document processing
                stop_typing = asyncio.Event()
                typing_task = asyncio.create_task(
                    _send_typing_loop(context.bot, update.effective_chat.id, stop_typing)
                )

                try:
                    # Use on_message callback so message is saved, history is loaded, etc.
                    await on_message(
                        chat_jid=chat_jid,
                        sender_jid=user_id,
                        text=prompt,
                        channel="telegram",
                    )
                finally:
                    stop_typing.set()
                    typing_task.cancel()
                    try:
                        await typing_task
                    except asyncio.CancelledError:
                        pass
            except Exception as e:
                await update.message.reply_text(f"❌ 檔案處理失敗：{e}")

        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
        self._app.add_handler(CommandHandler("minion", cmd_minion))
        self._app.add_handler(CommandHandler("minions", cmd_minion))
        self._app.add_handler(CommandHandler("help", cmd_help))
        self._app.add_handler(CommandHandler("start", cmd_help))  # /start also shows help
        self._app.add_handler(CommandHandler("status", cmd_status))
        self._app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        logger.info("Telegram channel started")

    async def disconnect(self) -> None:
        if not self._app:
            return
        try:
            await self._app.updater.stop()
        except Exception:
            pass
        try:
            await self._app.stop()
        except asyncio.CancelledError:
            pass  # update_fetcher already cancelled — expected during shutdown
        except Exception:
            pass
        try:
            await self._app.shutdown()
        except Exception:
            pass
        self._app = None


def init(token: str) -> None:
    if not token:
        return
    channel = TelegramChannel(token)
    register_channel("telegram", channel)
