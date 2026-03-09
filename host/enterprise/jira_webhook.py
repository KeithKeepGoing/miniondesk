"""
Jira Webhook Receiver for MinionDesk.
Receives Jira issue events and notifies assigned users via Telegram/Discord/Teams.
"""
from __future__ import annotations
import inspect
import json
import logging
import os
import hmac
import hashlib
from typing import Callable, Optional

try:
    from host import db as _db
except Exception:
    _db = None

log = logging.getLogger(__name__)

JIRA_WEBHOOK_SECRET = os.getenv("JIRA_WEBHOOK_SECRET", "")
try:
    JIRA_WEBHOOK_PORT = int(os.getenv("JIRA_WEBHOOK_PORT", "8083"))
except (ValueError, TypeError):
    log.error("JIRA_WEBHOOK_PORT must be an integer; defaulting to 8083")
    JIRA_WEBHOOK_PORT = 8083
JIRA_WEBHOOK_HOST = os.getenv("JIRA_WEBHOOK_HOST", "127.0.0.1")
JIRA_URL = os.getenv("JIRA_URL", "").rstrip("/")
if JIRA_URL:
    import urllib.parse as _up
    _p = _up.urlparse(JIRA_URL)
    if _p.scheme not in ("http", "https"):
        log.error("JIRA_URL must use http/https scheme; disabling Jira link generation")
        JIRA_URL = ""

_notify_callback: Optional[Callable] = None


def set_notify_callback(cb: Callable) -> None:
    """Set the callback for sending notifications. Called with (jid, message)."""
    global _notify_callback
    _notify_callback = cb


def _safe(s: str, maxlen: int = 200) -> str:
    return str(s or "")[:maxlen].replace("*", "").replace("_", "").replace("`", "").replace("<", "").replace(">", "")


async def _handle_jira_event(event: dict) -> None:
    """Process a Jira webhook event and notify relevant users."""
    webhook_event = event.get("webhookEvent", "")
    issue = event.get("issue", {})
    issue_key = _safe(issue.get("key", ""), 50).replace("\n", "").replace("\r", "")
    fields = issue.get("fields", {})
    summary = _safe(fields.get("summary", ""), 200)

    # Get assignee and reporter
    assignee = fields.get("assignee") or {}
    reporter = fields.get("reporter") or {}
    assignee_name = _safe(assignee.get("name", "") or assignee.get("accountId", ""), 100)
    reporter_name = _safe(reporter.get("name", "") or reporter.get("accountId", ""), 100)

    status = _safe(fields.get("status", {}).get("name", ""), 50)

    event_icons = {
        "jira:issue_created": "🆕",
        "jira:issue_updated": "🔄",
        "jira:issue_deleted": "🗑️",
        "comment_created": "💬",
    }
    icon = event_icons.get(webhook_event, "📋")

    # Build notification message
    changelog = event.get("changelog", {})
    changes = []
    for item in changelog.get("items", []):
        field = _safe(item.get("field", ""), 50)
        from_str = _safe(item.get("fromString", ""), 100)
        to_str = _safe(item.get("toString", ""), 100)
        if field in ("status", "assignee", "priority"):
            changes.append(f"• {field}: {from_str} → {to_str}")

    message = (
        f"{icon} *Jira 更新：{issue_key}*\n"
        f"主旨：{summary}\n"
        f"狀態：{status}\n"
        f"指派給：{assignee_name or '未指派'}\n"
    )
    if changes:
        message += "\n*異動：*\n" + "\n".join(changes)

    if webhook_event == "comment_created":
        comment_body = _safe(event.get("comment", {}).get("body", ""), 300)
        if comment_body:
            message += f"\n💬 {comment_body}"

    import urllib.parse as _up_jira
    if JIRA_URL:
        message += f"\n🔗 {JIRA_URL}/browse/{_up_jira.quote(issue_key, safe='')}"

    # Notify via callback
    if _notify_callback:
        # Notify assignee if we can map their username to a chat_jid
        db = _db
        if db is None:
            try:
                from host import db
            except Exception:
                db = None
        try:
            if db is None:
                raise RuntimeError("db not available")
            conn = db.get_conn()
            # Try to find employee by Jira username
            for username in [assignee_name, reporter_name]:
                if not username:
                    continue
                safe_u = username.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                row = conn.execute(
                    "SELECT jid FROM employees WHERE jid=? OR name LIKE ? ESCAPE '\\\\'",
                    (username, f"%{safe_u}%")
                ).fetchone()
                if row:
                    result = _notify_callback(row[0], message)
                    if inspect.isawaitable(result):
                        await result
                    break
            # Do NOT call conn.close() - it's a global singleton
        except Exception as e:
            log.warning(f"Could not find employee for Jira notification: {e}")


async def start_jira_webhook(port: int = JIRA_WEBHOOK_PORT) -> None:
    """Start Jira webhook receiver server."""
    if not JIRA_WEBHOOK_SECRET:
        log.error("JIRA_WEBHOOK_SECRET not set — Jira webhook disabled")
        return

    try:
        from fastapi import FastAPI, Request, HTTPException
        import uvicorn
    except ImportError:
        log.warning("fastapi not installed, Jira webhook disabled")
        return

    app = FastAPI(title="MinionDesk Jira Webhook")

    @app.post("/jira/webhook")
    async def jira_webhook(request: Request):
        body = await request.body()

        if len(body) > 1_048_576:
            raise HTTPException(status_code=413, detail="Payload too large")

        # Verify webhook secret if configured
        if JIRA_WEBHOOK_SECRET:
            sig_header = request.headers.get("X-Hub-Signature-256", "")
            expected = "sha256=" + hmac.new(
                JIRA_WEBHOOK_SECRET.encode(), body, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(sig_header, expected):
                raise HTTPException(status_code=401, detail="Invalid signature")

        try:
            event = json.loads(body)
            await _handle_jira_event(event)
            return {"ok": True}
        except Exception as e:
            log.error(f"Jira webhook error: {type(e).__name__}")
            from fastapi.responses import JSONResponse
            return JSONResponse({"ok": False, "error": "processing error"}, status_code=500)

    @app.get("/jira/health")
    async def health():
        return {"status": "ok", "service": "jira-webhook"}

    config = uvicorn.Config(app, host=JIRA_WEBHOOK_HOST, port=port, log_level="warning")
    server = uvicorn.Server(config)
    log.info(f"Jira webhook receiver starting on port {port}")
    await server.serve()
