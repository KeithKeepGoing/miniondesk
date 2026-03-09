"""
MinionDesk Web Portal
Browser-based chat interface supporting large file/log/code paste.
Runs alongside the main host on a configurable port.
"""
from __future__ import annotations
import asyncio
import hmac
import json
import os
import re
import secrets
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

from .logger import get_logger

log = get_logger("webportal")

PORTAL_PORT = int(os.getenv("WEBPORTAL_PORT", "8082"))
PORTAL_HOST = os.getenv("WEBPORTAL_HOST", "127.0.0.1")
PORTAL_INTERNAL_SECRET = os.getenv("WEBPORTAL_INTERNAL_SECRET", "")
if not PORTAL_INTERNAL_SECRET:
    log.error("WEBPORTAL_INTERNAL_SECRET is not set — /api/send_reply endpoint is unauthenticated. Refusing to start.")
    raise RuntimeError("WEBPORTAL_INTERNAL_SECRET must be set")
try:
    MAX_WS_MESSAGE_BYTES = int(os.getenv("WEBPORTAL_MAX_MESSAGE_BYTES", str(4 * 1024 * 1024)))
except (ValueError, TypeError):
    log.error("WEBPORTAL_MAX_MESSAGE_BYTES must be an integer; defaulting to 4194304")
    MAX_WS_MESSAGE_BYTES = 4 * 1024 * 1024

_on_message_cb: Optional[Callable] = None
_message_store: dict[str, list] = {}  # session_id -> messages
_ws_connections: dict[str, Any] = {}


async def start_portal(on_message: Callable, port: int = PORTAL_PORT) -> None:
    """Start the web portal server."""
    global _on_message_cb
    _on_message_cb = on_message

    try:
        from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, HTTPException
        from fastapi.responses import HTMLResponse, JSONResponse
        import uvicorn
    except ImportError:
        log.warning("fastapi/uvicorn not installed. Web portal disabled. Run: pip install fastapi uvicorn")
        return

    app = FastAPI(title="MinionDesk Portal", docs_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        html_path = Path(__file__).parent / "templates" / "portal.html"
        if html_path.exists():
            return HTMLResponse(html_path.read_text())
        return HTMLResponse(_inline_html())

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "miniondesk-portal"}

    @app.get("/api/session")
    async def new_session():
        import uuid
        return {"session_id": str(uuid.uuid4())}

    @app.websocket("/ws/{session_id}")
    async def websocket_endpoint(websocket: WebSocket, session_id: str):
        import re as _re
        _UUID_RE = _re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
        if not _UUID_RE.match(session_id):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        _ws_connections[session_id] = websocket
        if session_id not in _message_store:
            _message_store[session_id] = []

        chat_jid = f"web:{session_id}"

        # Register minion once on connection (not per message)
        try:
            from . import db, config
            minion_default = "phil"
            db.register_minion(chat_jid, minion_default, "web")
        except Exception:
            pass

        # Register web reply callback so WebChannel can deliver replies
        _registered_web_callback = False
        try:
            from host.channels.web import register_reply_callback, unregister_reply_callback
            async def _ws_send(text: str):
                try:
                    await websocket.send_text(json.dumps({"type": "reply", "text": text}))
                except Exception:
                    pass
            register_reply_callback(chat_jid, _ws_send)
            _registered_web_callback = True
        except ImportError:
            _registered_web_callback = False

        try:
            while True:
                data = await websocket.receive_text()
                if len(data.encode("utf-8")) > MAX_WS_MESSAGE_BYTES:
                    await websocket.send_text(json.dumps({"type": "error", "text": "訊息過大，請分批傳送"}))
                    await websocket.close(code=1009)
                    return

                try:
                    msg = json.loads(data)
                except json.JSONDecodeError:
                    await websocket.send_text(json.dumps({"type": "error", "text": "訊息格式錯誤"}))
                    continue

                text = msg.get("text", "")
                minion = msg.get("minion", "phil")
                # Validate against known minions from DB
                try:
                    from . import db as _db
                    valid_minions = {row[0] for row in _db.get_conn().execute("SELECT DISTINCT minion_name FROM registered_minions").fetchall()}
                except Exception:
                    valid_minions = set()
                if not valid_minions:
                    valid_minions = {"phil", "kevin", "stuart", "bob"}
                if minion not in valid_minions:
                    minion = next(iter(valid_minions), "phil")

                if not text.strip():
                    continue

                # Send thinking indicator
                await websocket.send_text(json.dumps({"type": "thinking", "minion": minion}))

                # Save user message
                _message_store[session_id].append({"role": "user", "content": text})
                if len(_message_store[session_id]) > 100:
                    _message_store[session_id] = _message_store[session_id][-100:]

                # Send to main on_message handler
                try:
                    if _on_message_cb:
                        await _on_message_cb(
                            chat_jid=chat_jid,
                            sender_jid=f"web_user_{session_id[:8]}",
                            text=text,
                            channel="web",
                        )
                except Exception as e:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "text": "處理失敗，請稍後再試。"
                    }))

        except WebSocketDisconnect:
            pass
        except Exception as e:
            log.error(f"WebSocket error: {e}")
        finally:
            _ws_connections.pop(session_id, None)
            _message_store.pop(session_id, None)
            if _registered_web_callback:
                try:
                    from host.channels.web import unregister_reply_callback
                    unregister_reply_callback(chat_jid)
                except ImportError:
                    pass

    @app.post("/api/send_reply")
    async def send_reply(request: Request):
        """Called by the channel to deliver replies to WebSocket clients."""
        secret = request.headers.get("X-Internal-Secret", "")
        if not secrets.compare_digest(secret.encode(), PORTAL_INTERNAL_SECRET.encode()):
            raise HTTPException(status_code=403, detail="Forbidden")
        body = await request.json()
        _UUID_RE_SR = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
        session_id = body.get("session_id", "")
        if not _UUID_RE_SR.match(session_id):
            return JSONResponse({"ok": False, "error": "invalid session_id"}, status_code=400)
        text = body.get("text", "")
        ws = _ws_connections.get(session_id)
        if not ws:
            from fastapi.responses import JSONResponse
            return JSONResponse({"ok": False, "error": "session not found"}, status_code=404)
        try:
            await ws.send_text(json.dumps({"type": "reply", "text": text}))
        except Exception:
            pass
        return {"ok": True}

    config = uvicorn.Config(app, host=PORTAL_HOST, port=port, log_level="warning")
    server = uvicorn.Server(config)
    log.info(f"Web Portal starting on http://{PORTAL_HOST}:{port}")
    await server.serve()


def _inline_html() -> str:
    """Fallback inline HTML if template file not found."""
    return '''<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MinionDesk Portal</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f0f2f5; height: 100vh; display: flex; flex-direction: column; }
  header { background: #1a1a2e; color: #fff; padding: 12px 20px; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 1.2rem; }
  header select { background: #16213e; color: #fff; border: 1px solid #0f3460; border-radius: 6px; padding: 4px 8px; cursor: pointer; }
  #chat { flex: 1; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 12px; }
  .msg { max-width: 80%; padding: 10px 14px; border-radius: 12px; line-height: 1.5; white-space: pre-wrap; font-size: 0.9rem; }
  .msg.user { background: #0f3460; color: #fff; align-self: flex-end; border-radius: 12px 12px 2px 12px; }
  .msg.bot { background: #fff; color: #1a1a2e; align-self: flex-start; border-radius: 12px 12px 12px 2px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  .msg.thinking { background: #e8eaf6; color: #666; font-style: italic; }
  #input-area { padding: 12px 16px; background: #fff; border-top: 1px solid #e0e0e0; display: flex; gap: 8px; }
  #msg-input { flex: 1; border: 1px solid #ddd; border-radius: 8px; padding: 10px 14px; font-size: 0.9rem; resize: none; height: 80px; font-family: inherit; }
  #msg-input:focus { outline: none; border-color: #0f3460; }
  #send-btn { background: #0f3460; color: #fff; border: none; border-radius: 8px; padding: 0 20px; cursor: pointer; font-size: 0.9rem; font-weight: 600; }
  #send-btn:hover { background: #1a1a2e; }
  #send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  code, pre { background: #f5f5f5; border-radius: 4px; padding: 2px 6px; font-family: monospace; font-size: 0.85em; }
  pre { padding: 10px; overflow-x: auto; }
  .status { font-size: 0.75rem; color: #999; text-align: center; padding: 4px; }
</style>
</head>
<body>
<header>
  <span style="font-size:1.5rem">🍌</span>
  <h1>MinionDesk Enterprise Portal</h1>
  <label style="margin-left:auto;color:#aaa;font-size:0.85rem">助理：</label>
  <select id="minion-select">
    <option value="phil">Phil（首席）</option>
    <option value="kevin">Kevin（HR）</option>
    <option value="stuart">Stuart（IT）</option>
    <option value="bob">Bob（財務）</option>
  </select>
</header>
<div id="chat">
  <div class="msg bot">👋 您好！我是 MinionDesk 企業助理。您可以在此貼上 Log 檔、程式碼，或直接提問。</div>
</div>
<div id="input-area">
  <textarea id="msg-input" placeholder="輸入訊息，或貼上 Log / 程式碼...&#10;Ctrl+Enter 送出"></textarea>
  <button id="send-btn" onclick="sendMsg()">送出</button>
</div>
<script>
const chat = document.getElementById("chat");
const input = document.getElementById("msg-input");
const btn = document.getElementById("send-btn");
let ws;

async function connect() {
  const sessionResp = await fetch('/api/session');
  const { session_id } = await sessionResp.json();
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws/${session_id}`);
  ws.onmessage = (e) => {
    const data = JSON.parse(e.data);
    removeThinking();
    if (data.type === "thinking") {
      addMsg("🤔 思考中...", "thinking");
      btn.disabled = true;
    } else if (data.type === "reply") {
      addMsg(data.text, "bot");
      btn.disabled = false;
    } else if (data.type === "error") {
      addMsg("❌ " + data.text, "bot");
      btn.disabled = false;
    }
  };
  ws.onclose = () => setTimeout(connect, 2000);
}

function addMsg(text, cls) {
  const div = document.createElement("div");
  div.className = "msg " + cls;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function removeThinking() {
  const thinking = chat.querySelector(".thinking");
  if (thinking) thinking.remove();
}

function sendMsg() {
  const text = input.value.trim();
  if (!text || !ws || ws.readyState !== 1) return;
  addMsg(text, "user");
  const minion = document.getElementById("minion-select").value;
  ws.send(JSON.stringify({ text, minion }));
  input.value = "";
}

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) sendMsg();
});

connect();
</script>
</body>
</html>'''
