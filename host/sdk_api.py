"""
SdkApi — External WebSocket API — Phase 2
Port 8770 (miniondesk, to avoid conflict with evoclaw's 8767).

Handles: memory_query, memory_write, agent_list, system_status, task_submit, ping
Auth: optional bearer token via SDK_API_TOKEN env var.
"""
import asyncio
import json
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

SDK_API_PORT = int(os.getenv("SDK_API_PORT", "8770"))
SDK_API_TOKEN = os.getenv("SDK_API_TOKEN", "")


class SdkApi:
    """External-facing WebSocket API for MinionDesk SDK/CLI access."""

    def __init__(
        self,
        port: int = SDK_API_PORT,
        memory_bus=None,
        agent_registry=None,
        bot_registry=None,
    ):
        self.port = port
        self.memory_bus = memory_bus
        self.agent_registry = agent_registry
        self.bot_registry = bot_registry
        self._server = None

    async def start(self):
        try:
            import websockets
            self._server = await websockets.serve(
                self._handle, "0.0.0.0", self.port
            )
            logger.info(f"SdkApi listening on ws://0.0.0.0:{self.port}")
        except ImportError:
            logger.warning("websockets not installed — SdkApi unavailable")
        except Exception as e:
            logger.error(f"SdkApi start failed: {e}")

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, ws, path=""):
        """Handle an incoming SDK WebSocket connection."""
        # Auth check
        if SDK_API_TOKEN:
            try:
                auth_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                auth = json.loads(auth_raw)
                if auth.get("token") != SDK_API_TOKEN:
                    await ws.send(json.dumps({"error": "unauthorized"}))
                    return
            except Exception:
                await ws.send(json.dumps({"error": "auth_required"}))
                return

        async for raw in ws:
            try:
                msg = json.loads(raw)
                resp = await self._dispatch(msg)
                await ws.send(json.dumps(resp))
            except json.JSONDecodeError:
                await ws.send(json.dumps({"error": "invalid_json"}))
            except Exception as e:
                await ws.send(json.dumps({"error": str(e)}))

    async def _dispatch(self, msg: dict) -> dict:
        action = msg.get("action", "")
        payload = msg.get("payload", {})

        if action == "ping":
            return {"action": "pong", "ts": time.time()}

        elif action == "system_status":
            return {
                "action": "system_status",
                "status": "ok",
                "ts": time.time(),
                "memory_bus": self.memory_bus is not None,
                "agent_registry": self.agent_registry is not None,
                "bot_registry": self.bot_registry is not None,
            }

        elif action == "memory_query":
            if not self.memory_bus:
                return {"error": "memory_bus not available"}
            key = payload.get("key", "")
            scope = payload.get("scope", "shared")
            result = self.memory_bus.recall(key, scope=scope)
            return {"action": "memory_query", "key": key, "result": result}

        elif action == "memory_write":
            if not self.memory_bus:
                return {"error": "memory_bus not available"}
            key = payload.get("key", "")
            value = payload.get("value")
            scope = payload.get("scope", "shared")
            self.memory_bus.remember(key, value, scope=scope)
            return {"action": "memory_write", "status": "ok", "key": key}

        elif action == "agent_list":
            if not self.agent_registry:
                return {"action": "agent_list", "agents": []}
            agents = self.agent_registry.list_all() if hasattr(self.agent_registry, 'list_all') else []
            return {"action": "agent_list", "agents": [
                a.to_dict() if hasattr(a, 'to_dict') else str(a) for a in agents
            ]}

        elif action == "bot_list":
            if not self.bot_registry:
                return {"action": "bot_list", "bots": []}
            bots = self.bot_registry.list_all()
            return {"action": "bot_list", "bots": [b.to_dict() for b in bots]}

        elif action == "task_submit":
            task = payload.get("task", "")
            context = payload.get("context", {})
            return {
                "action": "task_submit",
                "status": "queued",
                "task": task,
                "ts": time.time(),
            }

        else:
            return {"error": f"unknown_action: {action}"}
