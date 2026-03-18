"""
WSBridge — WebSocket IPC bridge for MinionDesk Phase 1.

Replaces file-based polling with real-time WebSocket communication
between host gateway and container agent runtime.

Port: 8769 (miniondesk; evoclaw uses 8768)

Protocol:
  - JSON messages over WebSocket
  - Each message has: {"type": str, "agent_id": str, "payload": dict, "ts": float}
  - Types: "task", "result", "heartbeat", "memory_sync", "identity"

Usage:
    bridge = WSBridge(port=8769)
    await bridge.start()   # Start server
    await bridge.stop()    # Graceful shutdown
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Awaitable

log = logging.getLogger(__name__)

DEFAULT_PORT = 8769
DEFAULT_HOST = "0.0.0.0"

MessageHandler = Callable[[dict[str, Any], Any], Awaitable[None]]


class WSBridge:
    """WebSocket IPC bridge server.

    Manages bidirectional communication between host and container agents.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self._server = None
        self._clients: dict[str, Any] = {}  # agent_id -> websocket
        self._handlers: dict[str, list[MessageHandler]] = {}
        self._running = False

    def on(self, msg_type: str, handler: MessageHandler) -> None:
        """Register a handler for a message type."""
        self._handlers.setdefault(msg_type, []).append(handler)

    async def start(self) -> None:
        """Start the WebSocket server."""
        try:
            import websockets
        except ImportError:
            log.error("WSBridge requires 'websockets' package. Install with: pip install websockets>=12.0")
            raise

        self._running = True
        self._server = await websockets.serve(
            self._handle_connection,
            self.host,
            self.port,
            ping_interval=30,
            ping_timeout=10,
        )
        log.info("WSBridge listening on ws://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for agent_id, ws in list(self._clients.items()):
            try:
                await ws.close()
            except Exception:
                pass
        self._clients.clear()
        log.info("WSBridge stopped")

    async def send(self, agent_id: str, msg_type: str, payload: dict[str, Any]) -> bool:
        """Send a message to a specific connected agent."""
        ws = self._clients.get(agent_id)
        if not ws:
            log.warning("WSBridge: agent %s not connected", agent_id[:12])
            return False
        msg = json.dumps({
            "type": msg_type,
            "agent_id": agent_id,
            "payload": payload,
            "ts": time.time(),
        })
        try:
            await ws.send(msg)
            return True
        except Exception as exc:
            log.error("WSBridge send failed for %s: %s", agent_id[:12], exc)
            self._clients.pop(agent_id, None)
            return False

    async def broadcast(self, msg_type: str, payload: dict[str, Any]) -> int:
        """Broadcast a message to all connected agents. Returns count sent."""
        sent = 0
        for agent_id in list(self._clients):
            if await self.send(agent_id, msg_type, payload):
                sent += 1
        return sent

    @property
    def connected_agents(self) -> list[str]:
        return list(self._clients.keys())

    async def _handle_connection(self, websocket, path=None) -> None:
        """Handle a new WebSocket connection."""
        agent_id = None
        try:
            async for raw in websocket:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    log.warning("WSBridge: invalid JSON from client")
                    continue

                msg_type = msg.get("type", "")
                agent_id = msg.get("agent_id", "")

                # Register client on first message
                if agent_id and agent_id not in self._clients:
                    self._clients[agent_id] = websocket
                    log.info("WSBridge: agent connected: %s", agent_id[:12])

                # Dispatch to handlers
                for handler in self._handlers.get(msg_type, []):
                    try:
                        await handler(msg, websocket)
                    except Exception as exc:
                        log.error("WSBridge handler error (%s): %s", msg_type, exc)

                # Auto-respond to heartbeats
                if msg_type == "heartbeat" and agent_id:
                    await websocket.send(json.dumps({
                        "type": "heartbeat_ack",
                        "agent_id": "host",
                        "payload": {"status": "ok"},
                        "ts": time.time(),
                    }))

        except Exception as exc:
            log.debug("WSBridge: connection closed: %s", exc)
        finally:
            if agent_id:
                self._clients.pop(agent_id, None)
                log.info("WSBridge: agent disconnected: %s", agent_id[:12])
