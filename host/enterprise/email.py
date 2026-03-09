"""
Email Integration for MinionDesk.
Supports IMAP (Exchange Online, Gmail, Outlook) for reading and summarizing emails.
Uses smtplib for sending draft replies.
"""
from __future__ import annotations
import os
import re
import ssl
import imaplib
import smtplib
import email as email_lib
import email.header
import email.utils
import html
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from datetime import datetime, timedelta

log = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        log.warning("Invalid value for %s, using default %d", name, default)
        return default


# Config
IMAP_HOST = os.getenv("EMAIL_IMAP_HOST", "")           # outlook.office365.com or imap.gmail.com
IMAP_PORT = _env_int("EMAIL_IMAP_PORT", 993)
IMAP_USER = os.getenv("EMAIL_USER", "")
IMAP_PASSWORD = os.getenv("EMAIL_PASSWORD", "")         # app password for Gmail
SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "")
SMTP_PORT = _env_int("EMAIL_SMTP_PORT", 587)
EMAIL_FOLDER = os.getenv("EMAIL_FOLDER", "INBOX")
EMAIL_MAX_FETCH = _env_int("EMAIL_MAX_FETCH", 10)
SMTP_SSL_VERIFY = os.getenv("EMAIL_SMTP_SSL_VERIFY", "true").lower() != "false"
SMTP_SSL_CA_BUNDLE = os.getenv("EMAIL_SMTP_SSL_CA_BUNDLE", "")


_SAFE_FOLDER_RE = re.compile(r'^[\w\-\./ ]+$')


def _validate_folder(folder: str) -> str:
    if not _SAFE_FOLDER_RE.match(folder):
        raise ValueError(f"Unsafe IMAP folder name: {folder!r}")
    if '..' in folder:
        raise ValueError(f"Path traversal in IMAP folder name: {folder!r}")
    return folder


def _safe_header(value: str, field: str) -> str:
    if '\n' in value or '\r' in value:
        raise ValueError(f"Header injection attempt in {field}")
    return value


def _smtp_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not SMTP_SSL_VERIFY:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        log.warning("SMTP SSL verification disabled")
    elif SMTP_SSL_CA_BUNDLE:
        ctx.load_verify_locations(SMTP_SSL_CA_BUNDLE)
    return ctx


def is_configured() -> bool:
    return bool(IMAP_HOST and IMAP_USER and IMAP_PASSWORD)


def _decode_header(value: str) -> str:
    """Decode RFC2047 encoded email headers."""
    parts = email.header.decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _extract_text(msg) -> str:
    """Extract plain text from email message."""
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                try:
                    text += payload.decode(charset, errors="replace")
                except (LookupError, TypeError):
                    text += payload.decode("utf-8", errors="replace")
            elif ct == "text/html" and not text:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                raw = payload.decode(charset, errors="replace")
                # Strip HTML tags
                raw = re.sub(r'<[^>]+>', ' ', raw)
                raw = html.unescape(raw)
                text += re.sub(r'\s+', ' ', raw).strip()
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
    return text.strip()


def fetch_recent_emails(folder: str = EMAIL_FOLDER, count: int = EMAIL_MAX_FETCH, unread_only: bool = False) -> list[dict]:
    """
    Fetch recent emails from IMAP mailbox.
    Returns list of email dicts with subject, sender, date, body, message_id.
    """
    if not is_configured():
        return []

    count = min(count, 100)

    mail = None
    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=15)
        mail.login(IMAP_USER, IMAP_PASSWORD)
        mail.select(_validate_folder(folder))

        search_criteria = "UNSEEN" if unread_only else "ALL"
        _, data = mail.search(None, search_criteria)

        msg_ids = data[0].split()
        # Get latest N messages
        recent_ids = msg_ids[-count:] if len(msg_ids) > count else msg_ids
        recent_ids = list(reversed(recent_ids))  # newest first

        emails = []
        for msg_id in recent_ids:
            _, msg_data = mail.fetch(msg_id, "(RFC822)")
            if not msg_data or not isinstance(msg_data[0], (tuple, list)) or len(msg_data[0]) < 2:
                continue
            raw = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw)

            subject = _decode_header(msg.get("Subject", "(無主旨)"))
            sender = _decode_header(msg.get("From", ""))
            date_str = msg.get("Date", "")
            message_id = msg.get("Message-ID", "")
            body = _extract_text(msg)

            emails.append({
                "id": msg_id.decode(),
                "message_id": message_id,
                "subject": subject,
                "sender": sender,
                "date": date_str,
                "body": body[:3000],  # limit body size
                "body_preview": body[:200],
            })

        return emails

    except imaplib.IMAP4.error as e:
        log.error("IMAP connection/auth error")
        log.debug(f"IMAP detail: {e}")
        return []
    except Exception as e:
        log.error("Email fetch error: %s", type(e).__name__)
        log.debug("Email fetch detail: %s", e)
        return []
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass


def summarize_email(email_dict: dict) -> dict:
    """
    Extract key info from email:
    - Core request/issue
    - Steps already tried (if any)
    - Urgency level
    - Suggested action
    """
    body = email_dict.get("body", "")
    subject = email_dict.get("subject", "")

    # Urgency keywords
    urgency = "一般"
    urgent_keywords = ["緊急", "urgent", "ASAP", "critical", "down", "停擺", "系統異常", "production", "immediately"]
    if any(kw.lower() in (subject + body).lower() for kw in urgent_keywords):
        urgency = "🔴 緊急"
    elif any(kw in subject for kw in ["請假", "報帳", "申請"]):
        urgency = "🟡 一般行政"

    # Extract tried steps
    tried_patterns = [r"已[試嘗][過過](.{5,50})[，。\n]", r"tried (.{5,50})[,.\n]", r"嘗試了(.{5,50})[，。\n]"]
    tried = []
    for pat in tried_patterns:
        matches = re.findall(pat, body)
        tried.extend(matches[:3])

    return {
        "subject": subject,
        "sender": email_dict.get("sender", ""),
        "date": email_dict.get("date", ""),
        "urgency": urgency,
        "core_request": body[:300] if body else subject,
        "tried_steps": tried,
        "body_preview": email_dict.get("body_preview", ""),
    }


def _strip_newlines(s: str) -> str:
    return s.replace('\r', ' ').replace('\n', ' ')


def draft_reply(original: dict, reply_content: str, sender_name: str = "IT Support") -> str:
    """
    Generate a professional reply email draft.
    Returns formatted draft as string.
    """
    reply_content = _strip_newlines(reply_content)
    sender_name = _strip_newlines(sender_name)
    original_sender = original.get("sender", "")
    original_sender = _strip_newlines(original_sender)
    subject = original.get("subject", "")
    subject = subject.strip()
    subject = re.sub(r'^(re\s*:|fwd?\s*:)\s*', '', subject, flags=re.IGNORECASE).strip()
    subject = f"Re: {subject}"
    date = original.get("date", "")

    draft = f"""主旨：{subject}
收件人：{original_sender}

---

您好，

{reply_content}

如有任何問題，請隨時聯絡我們。

此致
{sender_name}
IT 支援團隊

---
原信件：
寄件時間：{date}
內容：{original.get('body_preview', '')}
"""
    return draft


def send_email(to: str, subject: str, body: str, in_reply_to: str = "") -> bool:
    """Send email via SMTP."""
    to = _safe_header(to, "To")
    subject = _safe_header(subject, "Subject")
    if in_reply_to:
        in_reply_to = _safe_header(in_reply_to, "In-Reply-To")

    if not (SMTP_HOST and IMAP_USER and IMAP_PASSWORD):
        log.warning("SMTP not configured, cannot send email")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = IMAP_USER
        msg["To"] = to
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to

        msg.attach(MIMEText(body, "plain", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            try:
                server.starttls(context=_smtp_ssl_context())
            except smtplib.SMTPException as e:
                raise smtplib.SMTPException(f"STARTTLS negotiation failed: {e}")
            server.login(IMAP_USER, IMAP_PASSWORD)
            server.send_message(msg)

        safe_subject = subject.replace('\n', ' ').replace('\r', ' ')
        safe_to = to.replace('\n', ' ').replace('\r', ' ')
        log.info("Email sent to %s: %s", safe_to, safe_subject)
        return True
    except Exception as e:
        log.error("SMTP send failed")
        log.debug(f"SMTP detail: {e}")
        return False
