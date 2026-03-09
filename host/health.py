"""
MinionDesk Health Check HTTP Server
Provides /health and /metrics endpoints for monitoring.
"""
from __future__ import annotations
import asyncio
import json
import time
from datetime import datetime

_start_time = time.time()


async def handle_health(request) -> "web.Response":
    """Health check endpoint."""
    from aiohttp import web
    from . import db, config

    checks = {}

    # DB check
    try:
        conn = db.get_conn()
        conn.execute("SELECT 1").fetchone()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Docker image check
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "images", "-q", config.DOCKER_IMAGE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        checks["docker_image"] = "ok" if stdout.strip() else "missing"
    except Exception as e:
        checks["docker_image"] = f"error: {e}"

    uptime = int(time.time() - _start_time)
    status = "ok" if all(v == "ok" for v in checks.values()) else "degraded"

    payload = {
        "status": status,
        "uptime_seconds": uptime,
        "timestamp": datetime.utcnow().isoformat(),
        "checks": checks,
        "version": "2.0.0",
    }

    http_status = 200 if status == "ok" else 503
    return web.Response(
        text=json.dumps(payload, indent=2),
        content_type="application/json",
        status=http_status,
    )


async def handle_metrics(request) -> "web.Response":
    """Prometheus-style metrics endpoint."""
    from aiohttp import web
    from . import db

    conn = db.get_conn()
    metrics = {}

    for table in ["messages", "employees", "workflow_instances", "meetings", "audit_log"]:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            metrics[f"miniondesk_{table}_total"] = count
        except Exception:
            pass

    uptime = int(time.time() - _start_time)
    metrics["miniondesk_uptime_seconds"] = uptime

    lines = [f"# MinionDesk Metrics\n"]
    for key, val in metrics.items():
        lines.append(f"{key} {val}")

    return web.Response(text="\n".join(lines) + "\n", content_type="text/plain")


async def start_health_server(port: int = 8080) -> None:
    """Start the health check HTTP server."""
    try:
        from aiohttp import web
        app = web.Application()
        app.router.add_get("/health", handle_health)
        app.router.add_get("/metrics", handle_metrics)
        app.router.add_get("/", handle_health)  # Alias

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        print(f"[health] HTTP server on :{port} (GET /health, GET /metrics)")
    except ImportError:
        print("[health] aiohttp not installed, health server disabled")
    except Exception as e:
        print(f"[health] Failed to start: {e}")
