"""Email tools for MinionDesk minions."""
from __future__ import annotations
import os
import re
import re as _re_ef
import sys
import logging
import email.header as _email_header
from . import Tool

_SAFE_FOLDER_RE_ET = _re_ef.compile(r'^[\w\-\./ ]+$')

log = logging.getLogger(__name__)

DOMINO_SSL_VERIFY = os.getenv("DOMINO_SSL_VERIFY", "true").lower() != "false"
DOMINO_SSL_CA_BUNDLE = os.getenv("DOMINO_SSL_CA_BUNDLE", "")

def _get_email():
    workspace = os.getenv("MINIONDESK_WORKSPACE", "/workspace")
    if workspace not in sys.path:
        sys.path.insert(0, workspace)
    try:
        from host.enterprise import email as email_mod
        return email_mod
    except ImportError:
        return None


def read_emails(args: dict, ctx) -> str:
    """Read and summarize recent emails."""
    user = os.getenv("EMAIL_USER", "")
    password = os.getenv("EMAIL_PASSWORD", "")
    if not user or not password:
        return "❌ EMAIL_USER 或 EMAIL_PASSWORD 未設定"

    try:
        count = max(1, min(int(args.get("count", 5)), 20))
    except (ValueError, TypeError):
        count = 5
    unread_only = args.get("unread_only", False)

    imap_host = os.getenv("EMAIL_IMAP_HOST", "")
    if not imap_host:
        return "❌ 電子郵件未設定。請設定 EMAIL_IMAP_HOST, EMAIL_USER, EMAIL_PASSWORD。"

    # Do inline to avoid import issues in container
    import imaplib
    import email as email_lib
    import re, html

    mail = None
    try:
        mail = imaplib.IMAP4_SSL(imap_host, int(os.getenv("EMAIL_IMAP_PORT", "993")), timeout=15)
        mail.login(user, password)
        _folder = os.getenv("EMAIL_FOLDER", "INBOX")
        if not _SAFE_FOLDER_RE_ET.match(_folder):
            log.warning("Unsafe EMAIL_FOLDER value, using INBOX")
            _folder = "INBOX"
        if '..' in _folder:
            log.warning("Path traversal in EMAIL_FOLDER value, using INBOX")
            _folder = "INBOX"
        mail.select(_folder)

        criteria = "UNSEEN" if unread_only else "ALL"
        _, data = mail.search(None, criteria)
        msg_ids = data[0].split()
        recent = list(reversed(msg_ids[-count:]))

        results = []
        for mid in recent:
            _, mdata = mail.fetch(mid, "(RFC822)")
            if not mdata or not isinstance(mdata[0], (tuple, list)) or len(mdata[0]) < 2:
                continue
            msg = email_lib.message_from_bytes(mdata[0][1])

            def decode_h(v):
                parts = _email_header.decode_header(v or "")
                return "".join(p.decode(c or "utf-8", errors="replace") if isinstance(p, bytes) else p for p, c in parts)

            subject = decode_h(msg.get("Subject", "(無主旨)"))
            sender = decode_h(msg.get("From", ""))
            date = msg.get("Date", "")[:16]

            # Extract body
            body = ""
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    raw = part.get_payload(decode=True) or b""
                    body = raw.decode(part.get_content_charset() or "utf-8", errors="replace")[:500]
                    break

            # Urgency
            urgency = "🔴 緊急" if any(k in (subject + " " + body).lower() for k in ["urgent","緊急","asap","critical","down"]) else "🟢 一般"

            results.append(f"📧 *{subject}*\n寄件人：{sender}\n時間：{date}\n緊急程度：{urgency}\n摘要：{body[:200].strip()}\n")

        if not results:
            label = "未讀" if unread_only else "最新"
            return f"📭 目前沒有{label}郵件。"

        header = f"📬 最近 {len(results)} 封郵件：\n\n"
        return header + "\n---\n".join(results)

    except Exception as e:
        log.error("Email read error: %s", type(e).__name__, exc_info=True)
        return "❌ 郵件讀取失敗，請聯絡系統管理員。"
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass


def read_notes_mail(args: dict, ctx) -> str:
    """Read IBM Lotus Notes / HCL Domino mail."""
    try:
        count = max(1, min(int(args.get("count", 5)), 20))
    except (ValueError, TypeError):
        count = 5
    unread_only = args.get("unread_only", False)

    if (os.getenv("DOMINO_REST_URL") and
            os.getenv("DOMINO_REST_USER") and
            os.getenv("DOMINO_REST_PASSWORD")):
        method = "rest"
    elif (os.getenv("NOTES_IMAP_HOST") and
            os.getenv("NOTES_USER") and
            os.getenv("NOTES_PASSWORD")):
        method = "imap"
    else:
        method = "none"

    if method == "none":
        return (
            "❌ Notes Mail 未設定。請配置以下其中一種方式：\n\n"
            "*方式 1 — HCL Domino REST API（推薦）：*\n"
            "• DOMINO_REST_URL=https://domino.corp.local:8880\n"
            "• DOMINO_REST_USER=firstname.lastname\n"
            "• DOMINO_REST_PASSWORD=your_password\n"
            "• DOMINO_DATABASE=mail/username.nsf\n\n"
            "*方式 2 — Domino IMAP（需伺服器開啟 IMAP）：*\n"
            "• NOTES_IMAP_HOST=domino.corp.local\n"
            "• NOTES_USER=your_notes_username\n"
            "• NOTES_PASSWORD=your_password\n\n"
            "*方式 3 — noteslib（Windows 限定，需安裝 Notes Client）：*\n"
            "• NOTES_SERVER=DominoServer/Corp\n"
            "• NOTES_MAILDB=mail\\\\username.nsf\n"
            "• pip install noteslib"
        )

    # Inline implementation to avoid import issues in container
    emails = []

    if method == "rest":
        # REST API fetch
        domino_url = os.getenv("DOMINO_REST_URL", "")
        domino_user = os.getenv("DOMINO_REST_USER", "")
        domino_pass = os.getenv("DOMINO_REST_PASSWORD", "")
        domino_db = os.getenv("DOMINO_DATABASE", "")

        if not domino_url.startswith("https://"):
            log.error("DOMINO_REST_URL must use https://; refusing to send credentials over plain HTTP")
            return "❌ Domino 設定錯誤：DOMINO_REST_URL 必須使用 https://"

        try:
            import json, ssl, urllib.request, urllib.parse

            # Auth
            ctx = ssl.create_default_context()
            if not DOMINO_SSL_VERIFY:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            elif DOMINO_SSL_CA_BUNDLE:
                ctx.load_verify_locations(DOMINO_SSL_CA_BUNDLE)

            payload = json.dumps({"username": domino_user, "password": domino_pass}).encode()
            req = urllib.request.Request(f"{domino_url}/api/v1/auth", data=payload,
                                        headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
                try:
                    body = resp.read(512 * 1024)
                    token = json.loads(body).get("bearer", "") if body else ""
                except json.JSONDecodeError:
                    log.error("Domino auth: invalid JSON response")
                    return "❌ Domino 認證失敗：伺服器回應格式異常"

            if not token:
                return "❌ Domino 認證失敗，請確認帳號密碼"

            db_enc = urllib.parse.quote(domino_db, safe="")
            docs = None
            for inbox_path in ["$inbox", "inbox"]:
                req2 = urllib.request.Request(
                    f"{domino_url}/api/v1/lists/{db_enc}/{inbox_path}?count={count}",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
                )
                try:
                    with urllib.request.urlopen(req2, timeout=15, context=ctx) as resp:
                        docs = json.loads(resp.read(4 * 1024 * 1024))
                    break
                except Exception:
                    docs = None
            if docs is None:
                return "❌ 無法取得 Domino 收件匣，請確認 DOMINO_DATABASE 設定"

            if isinstance(docs, dict):
                docs = docs.get("documents", [])

            for doc in docs[:count]:
                fields = doc["fields"] if "fields" in doc else doc
                subject = str(fields.get("Subject", fields.get("AbbreviatedSubject", "(無主旨)")))
                sender = str(fields.get("From", fields.get("SentBy", "")))
                date = str(fields.get("PostedDate", fields.get("DeliveredDate", "")))[:16]
                body = str(fields.get("Body", fields.get("Comment", "")))[:200]
                emails.append({"subject": subject, "sender": sender, "date": date, "preview": body})

        except Exception as e:
            log.error("Email read error: %s", type(e).__name__, exc_info=True)
            return "❌ 郵件讀取失敗，請聯絡系統管理員。"

    elif method == "imap":
        # IMAP fetch (reuse standard IMAP logic with Notes server)
        import imaplib, email as email_lib
        mail = None
        try:
            try:
                notes_port = int(os.getenv("NOTES_IMAP_PORT", "993"))
            except (ValueError, TypeError):
                notes_port = 993
            mail = imaplib.IMAP4_SSL(os.getenv("NOTES_IMAP_HOST"), notes_port, timeout=15)
            mail.login(os.getenv("NOTES_USER", ""), os.getenv("NOTES_PASSWORD", ""))
            mail.select("INBOX")
            _, data = mail.search(None, "UNSEEN" if unread_only else "ALL")
            for mid in list(reversed(data[0].split()[-count:])):
                _, mdata = mail.fetch(mid, "(RFC822)")
                if not mdata or not isinstance(mdata[0], (tuple, list)) or len(mdata[0]) < 2:
                    continue
                msg = email_lib.message_from_bytes(mdata[0][1])
                def dh(v):
                    parts = _email_header.decode_header(v or "")
                    return "".join(p.decode(c or "utf-8", errors="replace") if isinstance(p, bytes) else p for p, c in parts)
                body = ""
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = (part.get_payload(decode=True) or b"").decode(part.get_content_charset() or "utf-8", errors="replace")[:200]
                        break
                emails.append({"subject": dh(msg.get("Subject", "(無主旨)")), "sender": dh(msg.get("From", "")), "date": msg.get("Date", "")[:16], "preview": body})
        except Exception as e:
            log.error("Email read error: %s", type(e).__name__, exc_info=True)
            return "❌ 郵件讀取失敗，請聯絡系統管理員。"
        finally:
            if mail is not None:
                try:
                    mail.logout()
                except Exception:
                    pass

    if not emails:
        return "📭 目前沒有 Notes 郵件。"

    lines = [f"📧 *Notes Mail*（{method}）— {len(emails)} 封：\n"]
    for m in emails:
        urgency = "🔴 緊急" if any(k in (m['subject'] + " " + m['preview']).lower() for k in ["urgent","緊急","asap","critical"]) else "🟢 一般"
        lines.append(f"📨 *{m['subject']}*\n   寄件人：{m['sender']}\n   時間：{m['date']}  {urgency}\n   摘要：{m['preview'][:150]}\n")
    return "\n---\n".join([lines[0]] + lines[1:])


def draft_email_reply(args: dict, ctx) -> str:
    """Draft a professional IT reply email."""
    original_subject = args.get("original_subject", "")
    original_sender = args.get("original_sender", "")
    original_content = args.get("original_content", "")
    reply_type = args.get("reply_type", "general")  # general, ticket_created, permission_granted, need_info
    ticket_id = re.sub(r'[^\w\-]', '', args.get("ticket_id", ""))
    custom_message = args.get("custom_message", "")[:2000]

    original_subject = original_subject.strip()
    original_subject = re.sub(r'^(re\s*:|fwd?\s*:)\s*', '', original_subject, flags=re.IGNORECASE).strip()
    subject = f"Re: {original_subject}" if original_subject else ""

    templates = {
        "ticket_created": f"感謝您的來信。\n\n您的問題已記錄為工單 {ticket_id}，我們將在 1-2 個工作日內處理並回覆您。\n\n如有緊急需求，請直接致電 IT 服務台：分機 XXXX。",
        "permission_granted": f"您申請的權限已完成開通，請重新嘗試登入。\n\n如仍有問題，請回覆此郵件或致電 IT 服務台。",
        "need_info": f"感謝您的來信。\n\n為了協助您解決問題，我們需要以下資訊：\n• 錯誤訊息截圖\n• 作業系統版本\n• 問題發生的確切時間\n\n請提供上述資訊後，我們將盡快處理。",
        "general": custom_message or "感謝您的來信。我們已收到您的問題，將盡快處理。",
    }

    body = templates.get(reply_type, templates["general"])

    draft = (
        f"📝 *回信草稿*\n\n"
        f"*主旨：* {subject}\n"
        f"*收件人：* {original_sender}\n\n"
        f"---\n\n"
        f"{body}\n\n"
        f"此致\nIT 支援團隊\n\n"
        f"---\n"
        f"*原信件摘要：{original_content[:200]}*"
    )
    return draft


def get_email_tools() -> list[Tool]:
    """Return email tools as Tool objects for the registry."""
    return [
        Tool(
            name="read_emails",
            description="讀取並摘要最新電子郵件。自動識別緊急程度、核心訴求。支援 Exchange/Gmail/Outlook。",
            schema={
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "讀取幾封郵件（預設 5，最多 20）"},
                    "unread_only": {"type": "boolean", "description": "只顯示未讀郵件"},
                },
            },
            execute=read_emails,
        ),
        Tool(
            name="draft_email_reply",
            description="根據來信意圖自動生成專業的 IT 回覆草稿。支援多種回覆類型：開單確認、權限開通通知、補件要求等。",
            schema={
                "type": "object",
                "properties": {
                    "original_subject": {"type": "string", "description": "原始郵件主旨"},
                    "original_sender": {"type": "string", "description": "原始寄件人"},
                    "original_content": {"type": "string", "description": "原始郵件內容摘要"},
                    "reply_type": {"type": "string", "description": "回覆類型：general(一般), ticket_created(開單確認), permission_granted(權限開通), need_info(需要補件)"},
                    "ticket_id": {"type": "string", "description": "工單編號（reply_type=ticket_created 時使用）"},
                    "custom_message": {"type": "string", "description": "自訂回覆內容（reply_type=general 時使用）"},
                },
            },
            execute=draft_email_reply,
        ),
        Tool(
            name="read_notes_mail",
            description="讀取 IBM Lotus Notes / HCL Domino 郵件 (支援 REST API / IMAP / noteslib COM)",
            schema={
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "讀取郵件數量 (預設 5)", "default": 5},
                    "unread_only": {"type": "boolean", "description": "只讀未讀郵件", "default": False},
                },
            },
            execute=read_notes_mail,
        ),
    ]


EMAIL_TOOLS = {
    "read_emails": {
        "fn": read_emails,
        "schema": {
            "name": "read_emails",
            "description": "讀取並摘要最新電子郵件。自動識別緊急程度、核心訴求。支援 Exchange/Gmail/Outlook。",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "讀取幾封郵件（預設 5，最多 20）"},
                    "unread_only": {"type": "boolean", "description": "只顯示未讀郵件"},
                },
            },
        },
    },
    "draft_email_reply": {
        "fn": draft_email_reply,
        "schema": {
            "name": "draft_email_reply",
            "description": "根據來信意圖自動生成專業的 IT 回覆草稿。支援多種回覆類型：開單確認、權限開通通知、補件要求等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "original_subject": {"type": "string", "description": "原始郵件主旨"},
                    "original_sender": {"type": "string", "description": "原始寄件人"},
                    "original_content": {"type": "string", "description": "原始郵件內容摘要"},
                    "reply_type": {"type": "string", "description": "回覆類型：general(一般), ticket_created(開單確認), permission_granted(權限開通), need_info(需要補件)"},
                    "ticket_id": {"type": "string", "description": "工單編號（reply_type=ticket_created 時使用）"},
                    "custom_message": {"type": "string", "description": "自訂回覆內容（reply_type=general 時使用）"},
                },
            },
        },
    },
}
