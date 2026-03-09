"""
Microsoft Teams channel for MinionDesk via Bot Framework webhook.
"""
from __future__ import annotations
import hashlib
import hmac
import base64
import json
import logging
import os
import time
import urllib.parse as _urlparse
from collections import defaultdict
from typing import Callable

from aiohttp import web

from . import register_channel

logger = logging.getLogger(__name__)

_RATE_LIMIT_WINDOW = 60  # seconds
_RATE_LIMIT_MAX = 20     # max messages per window
_RATE_COUNTS_MAX_KEYS = 10000
_rate_counts: dict = defaultdict(list)

_ALLOWED_SERVICE_URL_HOSTS = {
    "smba.trafficmanager.net",
    "teams.microsoft.com",
    "api.botframework.com",
}

_token_cache: dict = {"token": None, "expires_at": 0.0}


def _validate_service_url(url: str) -> bool:
    """Allow only known Microsoft Bot Framework service URLs."""
    try:
        p = _urlparse.urlparse(url)
        if p.scheme != "https":
            return False
        host = p.hostname or ""
        # Allow subdomains of known hosts
        return any(host == h or host.endswith("." + h) for h in _ALLOWED_SERVICE_URL_HOSTS)
    except Exception:
        return False


def _check_rate_limit(sender_id: str) -> bool:
    """Returns True if allowed, False if rate limited."""
    now = time.time()
    # Prune this sender's old timestamps
    _rate_counts[sender_id] = [t for t in _rate_counts[sender_id] if now - t < _RATE_LIMIT_WINDOW]
    if len(_rate_counts[sender_id]) >= _RATE_LIMIT_MAX:
        return False
    # Global cap: evict oldest-accessed entry if dict too large
    if len(_rate_counts) > _RATE_COUNTS_MAX_KEYS:
        oldest_key = next(iter(_rate_counts))
        del _rate_counts[oldest_key]
    _rate_counts[sender_id].append(now)
    return True


class TeamsChannel:
    def __init__(self, app_id: str, app_password: str, port: int = 8443):
        self._app_id = app_id
        self._app_password = app_password
        self._port = port
        self._on_message: Callable | None = None
        self._conversations: dict[str, str] = {}  # chat_jid -> service_url

    async def send_message(self, chat_jid: str, text: str) -> None:
        import aiohttp
        conv_id = chat_jid.removeprefix("teams:")
        service_url = self._conversations.get(conv_id, "https://smba.trafficmanager.net/apis/")
        token = await self._get_token()
        url = f"{service_url}v3/conversations/{conv_id}/activities"
        payload = {"type": "message", "text": text}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers={"Authorization": f"Bearer {token}"},
            ) as resp:
                if resp.status >= 400:
                    logger.error(f"Teams send error: {resp.status}")

    async def _get_token(self) -> str:
        import aiohttp
        if _token_cache["token"] and time.time() < _token_cache["expires_at"] - 60:
            return _token_cache["token"]
        url = "https://login.microsoftonline.com/botframework.com/oauth2/v2.0/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self._app_id,
            "client_secret": self._app_password,
            "scope": "https://api.botframework.com/.default",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as resp:
                result = await resp.json()
                token = result.get("access_token", "")
                expires_in = result.get("expires_in", 3600)
                _token_cache["token"] = token
                _token_cache["expires_at"] = time.time() + expires_in
                return token

    @staticmethod
    def _verify_teams_token(auth_header: str, body_bytes: bytes, app_password: str) -> bool:
        """Verify Teams outgoing webhook HMAC signature."""
        if not auth_header or not auth_header.startswith("HMAC "):
            return False
        try:
            received_sig = base64.b64decode(auth_header[5:])
            key = base64.b64decode(app_password)
            expected_sig = hmac.new(key, body_bytes, hashlib.sha256).digest()
            return hmac.compare_digest(received_sig, expected_sig)
        except Exception:
            return False

    async def _webhook_handler(self, request: web.Request) -> web.Response:
        # Read raw body bytes for HMAC verification
        body_bytes = await request.read()

        # Verify Teams outgoing webhook HMAC signature
        app_password = self._app_password
        if not app_password:
            return web.Response(status=403, text="Forbidden: TEAMS_APP_PASSWORD not configured")

        auth_header = request.headers.get("Authorization", "")
        if not self._verify_teams_token(auth_header, body_bytes, app_password):
            return web.Response(status=401, text="Unauthorized")

        # Validate activity type
        try:
            data = json.loads(body_bytes)
        except Exception:
            return web.Response(status=400, text="Invalid JSON")

        if data.get("type") not in ("message", "conversationUpdate"):
            return web.Response(status=200, text="OK")  # Ignore non-message activities

        body = data

        if body.get("type") != "message":
            return web.Response(status=200, text="OK")

        conv_id = body.get("conversation", {}).get("id", "")
        svc_url = body.get("serviceUrl", "")
        if not _validate_service_url(svc_url):
            logger.warning("Teams: rejected suspicious serviceUrl: %r", svc_url)
            return web.Response(status=400)
        if conv_id and svc_url:
            self._conversations[conv_id] = svc_url

        chat_jid = f"teams:{conv_id}"
        sender_jid = body.get("from", {}).get("id", "")
        text = body.get("text", "").strip()

        if sender_jid and not _check_rate_limit(sender_jid):
            logger.warning(f"Rate limit exceeded for sender {sender_jid!r}")
            return web.Response(status=429, text="Too Many Requests")

        if text and self._on_message:
            import asyncio
            asyncio.create_task(
                self._on_message(
                    chat_jid=chat_jid,
                    sender_jid=sender_jid,
                    text=text,
                    channel="teams",
                )
            )

        return web.Response(status=200, text="OK")

    async def start(self, on_message: Callable) -> None:
        self._on_message = on_message
        app = web.Application()
        app.router.add_post("/api/messages", self._webhook_handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", self._port)
        await site.start()
        logger.info(f"Teams webhook listening on port {self._port}")


def init(app_id: str, app_password: str, port: int = 8443) -> None:
    if not app_id or not app_password:
        return
    channel = TeamsChannel(app_id, app_password, port)
    register_channel("teams", channel)
