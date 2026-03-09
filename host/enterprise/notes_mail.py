"""
IBM Lotus Notes / HCL Domino Mail Integration for MinionDesk.

Supports three access methods (in priority order):
1. HCL Domino REST API (modern, cross-platform)
2. Domino IMAP bridge (if IMAP enabled on Domino)
3. noteslib COM interface (Windows only, requires Notes client installed)

Configure via environment variables — system auto-detects which method to use.
"""
from __future__ import annotations
import os
import ssl
import json
import logging
import urllib.request
import urllib.parse
import base64
import re
import html
from typing import Optional

log = logging.getLogger(__name__)

# ─── Config ────────────────────────────────────────────────────────────────────

# Method 1: HCL Domino REST API (recommended)
DOMINO_REST_URL = os.getenv("DOMINO_REST_URL", "")       # https://domino.corp.local:8880
DOMINO_REST_USER = os.getenv("DOMINO_REST_USER", "")     # notes username
DOMINO_REST_PASSWORD = os.getenv("DOMINO_REST_PASSWORD", "")
DOMINO_DATABASE = os.getenv("DOMINO_DATABASE", "mail/username.nsf")  # path to mail db

DOMINO_SSL_VERIFY = os.getenv("DOMINO_SSL_VERIFY", "true").lower() != "false"
DOMINO_SSL_CA_BUNDLE = os.getenv("DOMINO_SSL_CA_BUNDLE", "")

# Method 2: IMAP on Domino (same config as email.py but different host)
NOTES_IMAP_HOST = os.getenv("NOTES_IMAP_HOST", "")      # domino.corp.local
try:
    NOTES_IMAP_PORT = int(os.getenv("NOTES_IMAP_PORT", "993"))
except (ValueError, TypeError):
    log.warning("Invalid NOTES_IMAP_PORT, using 993")
    NOTES_IMAP_PORT = 993
NOTES_USER = os.getenv("NOTES_USER", "")                # Notes user (short name or email)
NOTES_PASSWORD = os.getenv("NOTES_PASSWORD", "")

# Method 3: noteslib (Windows, requires HCL Notes client)
NOTES_SERVER = os.getenv("NOTES_SERVER", "")            # Domino server name
NOTES_MAILDB = os.getenv("NOTES_MAILDB", "")            # e.g. mail\\username.nsf


def _build_ssl_context() -> ssl.SSLContext:
    """Create SSL context based on environment configuration."""
    ctx = ssl.create_default_context()
    if not DOMINO_SSL_VERIFY:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        log.warning("Domino SSL verification disabled — only use in trusted environments")
    elif DOMINO_SSL_CA_BUNDLE:
        ctx.load_verify_locations(DOMINO_SSL_CA_BUNDLE)
    return ctx


_ssl_context_cache: object = None
import threading
_ssl_context_lock = threading.Lock()

def _get_ssl_context() -> ssl.SSLContext:
    global _ssl_context_cache
    if _ssl_context_cache is None:
        with _ssl_context_lock:
            if _ssl_context_cache is None:
                _ssl_context_cache = _build_ssl_context()
    return _ssl_context_cache


def get_access_method() -> str:
    """Detect which access method is available."""
    if DOMINO_REST_URL and DOMINO_REST_USER and DOMINO_REST_PASSWORD:
        return "rest"
    if NOTES_IMAP_HOST and NOTES_USER and NOTES_PASSWORD:
        return "imap"
    try:
        import noteslib  # noqa: F401
        if NOTES_SERVER and NOTES_MAILDB:
            return "noteslib"
    except ImportError:
        pass
    return "none"


# ─── Method 1: HCL Domino REST API ────────────────────────────────────────────

def _domino_auth_token() -> Optional[str]:
    """Get Domino REST API JWT token."""
    if not DOMINO_REST_URL.startswith("https://"):
        log.error("DOMINO_REST_URL must use https://; refusing to send credentials over plain HTTP")
        return None
    url = f"{DOMINO_REST_URL}/api/v1/auth"
    payload = json.dumps({"username": DOMINO_REST_USER, "password": DOMINO_REST_PASSWORD}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        ctx = _get_ssl_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            try:
                body = resp.read()
                data = json.loads(body) if body else {}
                return data.get("bearer") or None
            except json.JSONDecodeError as e:
                log.error("Domino auth: invalid JSON response: %s", e)
                return None
    except Exception as e:
        log.error(f"Domino auth failed: {type(e).__name__}")
        log.debug(f"Domino auth detail: {e}")
        return None


def _domino_get(path: str, token: str) -> Optional[dict]:
    """Make authenticated GET request to Domino REST API."""
    if not DOMINO_REST_URL.startswith("https://"):
        log.error("DOMINO_REST_URL must use https://; refusing to send credentials over plain HTTP")
        return None
    url = f"{DOMINO_REST_URL}{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        ctx = _get_ssl_context()
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            try:
                body = resp.read()
                data = json.loads(body) if body else {}
                return data
            except json.JSONDecodeError as e:
                log.error("Domino GET %s: invalid JSON response: %s", path, e)
                return None
    except Exception as e:
        log.error("Domino GET %s: %s", path, type(e).__name__)
        log.debug("Domino GET detail: %s", e)
        return None


def fetch_notes_via_rest(count: int = 10, unread_only: bool = False) -> list[dict]:
    """Fetch emails from HCL Domino via REST API."""
    token = _domino_auth_token()
    if not token:
        return []

    # Encode database path
    db_encoded = urllib.parse.quote(DOMINO_DATABASE, safe="")

    # List documents in inbox
    count = max(1, min(count, 100))
    params = f"?count={count}&start=0"
    if unread_only:
        params += "&unread=true"

    # Try Domino REST API v1 endpoint
    result = _domino_get(f"/api/v1/lists/{db_encoded}/inbox{params}", token)

    if not result:
        # Try alternative endpoint format
        result = _domino_get(f"/api/v1/lists/{db_encoded}/$inbox{params}", token)

    if not result:
        return []

    docs = result if isinstance(result, list) else result.get("documents", [])
    emails = []

    for doc in docs[:count]:
        # Fetch full document
        unid = doc.get("@unid", doc.get("unid", ""))
        if unid:
            full_doc = _domino_get(f"/api/v1/document/{db_encoded}/{unid}", token)
            if full_doc:
                doc = full_doc

        # Extract standard Notes fields
        subject = _notes_field(doc, ["Subject", "$Subject", "AbbreviatedSubject"])
        sender = _notes_field(doc, ["From", "SentBy", "Principal"])
        date = _notes_field(doc, ["PostedDate", "DeliveredDate", "Date"])
        body = _notes_field(doc, ["Body", "$Body", "Comment"])

        emails.append({
            "id": unid or doc.get("@unid", ""),
            "subject": subject,
            "sender": sender,
            "date": str(date)[:20] if date else "",
            "body": str(body)[:3000] if body else "",
            "body_preview": str(body)[:200] if body else "",
            "source": "domino_rest",
        })

    return emails


def _notes_field(doc: dict, field_names: list) -> str:
    """Try multiple field names to extract Notes document field value."""
    fields = doc.get("fields", doc)  # Handle both wrapped and unwrapped format
    for name in field_names:
        val = fields.get(name)
        if val:
            if isinstance(val, list):
                return str(val[0]) if val else ""
            return str(val)
    return ""


# ─── Method 2: IMAP on Domino ─────────────────────────────────────────────────

def fetch_notes_via_imap(count: int = 10, unread_only: bool = False) -> list[dict]:
    """Fetch Notes mail via Domino IMAP bridge."""
    count = max(1, min(count, 100))
    if not (NOTES_IMAP_HOST and NOTES_USER and NOTES_PASSWORD):
        return []

    mail = None
    try:
        import imaplib
        import email as email_lib
        import email.header

        mail = imaplib.IMAP4_SSL(NOTES_IMAP_HOST, NOTES_IMAP_PORT, timeout=15)
        # Notes IMAP login: can be "Firstname Lastname/OrgUnit/Org" or short name
        mail.login(NOTES_USER, NOTES_PASSWORD)
        mail.select("INBOX")

        criteria = "UNSEEN" if unread_only else "ALL"
        _, data = mail.search(None, criteria)
        msg_ids = data[0].split()
        recent = list(reversed(msg_ids[-count:]))

        emails = []
        for mid in recent:
            _, mdata = mail.fetch(mid, "(RFC822)")
            if not mdata or not isinstance(mdata[0], (tuple, list)) or len(mdata[0]) < 2:
                continue
            msg = email_lib.message_from_bytes(mdata[0][1])

            def decode_h(v):
                if not v:
                    return ""
                parts = email.header.decode_header(v)
                return "".join(
                    p.decode(c or "utf-8", errors="replace") if isinstance(p, bytes) else p
                    for p, c in parts
                )

            # Extract body
            body = ""
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    raw = part.get_payload(decode=True) or b""
                    body = raw.decode(part.get_content_charset() or "utf-8", errors="replace")[:3000]
                    break

            emails.append({
                "id": mid.decode(),
                "subject": decode_h(msg.get("Subject", "(無主旨)")),
                "sender": decode_h(msg.get("From", "")),
                "date": msg.get("Date", "")[:20],
                "body": body,
                "body_preview": body[:200],
                "source": "domino_imap",
            })

        return emails

    except Exception as e:
        log.error("Notes IMAP error: %s", type(e).__name__)
        log.debug("Notes IMAP detail: %s", e)
        return []
    finally:
        if mail is not None:
            try:
                mail.logout()
            except Exception:
                pass


# ─── Method 3: noteslib (Windows COM) ─────────────────────────────────────────

def fetch_notes_via_noteslib(count: int = 10, unread_only: bool = False) -> list[dict]:
    """
    Fetch Notes mail via noteslib COM interface (Windows only).
    Requires: pip install noteslib, HCL Notes client installed.
    """
    try:
        import noteslib
    except ImportError:
        log.warning("noteslib not installed. Run: pip install noteslib (Windows + Notes client required)")
        return []

    if not (NOTES_SERVER and NOTES_MAILDB):
        log.warning("NOTES_SERVER and NOTES_MAILDB must be set for noteslib access")
        return []

    try:
        db = noteslib.Database(NOTES_SERVER, NOTES_MAILDB)

        # Get inbox view
        view = db.GetView("($Inbox)")
        if not view:
            view = db.GetView("Inbox")
        if not view:
            return []

        emails = []
        doc = view.GetFirstDocument()
        count_fetched = 0

        while doc and count_fetched < count:
            if unread_only and not getattr(doc, 'IsNewNote', False):
                doc = view.GetNextDocument(doc)
                continue

            subject = _get_notes_item(doc, ["Subject", "AbbreviatedSubject"])
            sender = _get_notes_item(doc, ["From", "SentBy"])
            date = _get_notes_item(doc, ["PostedDate", "DeliveredDate"])
            body = _get_notes_item(doc, ["Body"])

            emails.append({
                "id": doc.UniversalID,
                "subject": subject,
                "sender": sender,
                "date": str(date)[:20] if date else "",
                "body": str(body)[:3000],
                "body_preview": str(body)[:200],
                "source": "noteslib",
            })

            doc = view.GetNextDocument(doc)
            count_fetched += 1

        return emails

    except Exception as e:
        log.error("noteslib error: %s", type(e).__name__)
        log.debug("noteslib detail: %s", e)
        return []


def _get_notes_item(doc, item_names: list) -> str:
    """Try multiple Notes item names."""
    for name in item_names:
        try:
            item = doc.GetFirstItem(name)
            if item:
                val = item.Values
                if isinstance(val, (list, tuple)):
                    return str(val[0]) if val else ""
                return str(val)
        except Exception:
            continue
    return ""


# ─── Unified Interface ─────────────────────────────────────────────────────────

def fetch_notes_emails(count: int = 10, unread_only: bool = False) -> list[dict]:
    """
    Fetch Notes emails using best available method.
    Priority: REST API > IMAP > noteslib
    """
    method = get_access_method()
    log.info(f"Notes mail access method: {method}")

    if method == "rest":
        return fetch_notes_via_rest(count, unread_only)
    elif method == "imap":
        return fetch_notes_via_imap(count, unread_only)
    elif method == "noteslib":
        return fetch_notes_via_noteslib(count, unread_only)
    else:
        return []


def is_notes_configured() -> bool:
    return get_access_method() != "none"


def format_notes_emails(emails: list[dict]) -> str:
    """Format Notes emails for display in chat."""
    if not emails:
        return "📭 目前沒有 Notes 郵件（或 Notes Mail 未設定）。"

    lines = [f"📧 Notes Mail（{emails[0].get('source', 'notes')}）— 最近 {len(emails)} 封：\n"]

    for mail in emails:
        subject = mail.get("subject", "(無主旨)")
        sender = mail.get("sender", "")
        date = mail.get("date", "")[:16]
        preview = mail.get("body_preview", "")

        # Urgency detection
        text = subject + preview
        urgency = "🔴 緊急" if any(
            k in text.lower() for k in ["urgent", "緊急", "asap", "critical", "down", "停擺"]
        ) else "🟢 一般"

        lines.append(
            f"📨 *{subject}*\n"
            f"   寄件人：{sender}\n"
            f"   時間：{date}  {urgency}\n"
            f"   摘要：{preview[:150].strip()}\n"
        )

    return "\n---\n".join([lines[0]] + lines[1:])
