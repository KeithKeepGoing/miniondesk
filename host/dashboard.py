"""
MinionDesk Admin Dashboard
Real-time monitoring, stats, and management interface.
"""
from __future__ import annotations
import asyncio
import json
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from .logger import get_logger
log = get_logger("dashboard")

try:
    DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8084"))
except (ValueError, TypeError):
    log.error("DASHBOARD_PORT must be an integer; defaulting to 8084")
    DASHBOARD_PORT = 8084
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")  # Basic auth password
DASHBOARD_USER = os.getenv("DASHBOARD_USER", "admin")


async def start_dashboard(port: int = DASHBOARD_PORT) -> None:
    """Start admin dashboard server."""
    if not DASHBOARD_PASSWORD:
        log.error("DASHBOARD_PASSWORD not set — dashboard disabled. Set env var to enable.")
        return

    try:
        from fastapi import FastAPI, Request, HTTPException, Depends, Query
        from fastapi.responses import HTMLResponse, JSONResponse
        from fastapi.security import HTTPBasic, HTTPBasicCredentials
        import uvicorn
    except ImportError:
        log.warning("fastapi/uvicorn not installed, dashboard disabled")
        return

    app = FastAPI(title="MinionDesk Dashboard")
    security = HTTPBasic()

    def verify_auth(credentials: HTTPBasicCredentials = Depends(security)):
        correct_user = secrets.compare_digest(credentials.username.encode(), DASHBOARD_USER.encode())
        correct_pass = secrets.compare_digest(credentials.password.encode(), DASHBOARD_PASSWORD.encode())
        if not (correct_user and correct_pass):
            raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Basic"})
        return credentials

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(creds=Depends(verify_auth)):
        return HTMLResponse(_dashboard_html())

    @app.get("/api/stats")
    async def get_stats(creds=Depends(verify_auth)):
        return JSONResponse(_get_stats())

    @app.get("/api/audit")
    async def get_audit(limit: int = Query(default=50, ge=1, le=500), creds=Depends(verify_auth)):
        return JSONResponse(_get_audit_log(limit))

    @app.get("/api/workflows")
    async def get_workflows(creds=Depends(verify_auth)):
        return JSONResponse(_get_workflows())

    @app.get("/api/kb/stats")
    async def get_kb_stats(creds=Depends(verify_auth)):
        return JSONResponse(_get_kb_stats())

    config = uvicorn.Config(app, host=DASHBOARD_HOST, port=port, log_level="warning")
    server = uvicorn.Server(config)
    log.info(f"Admin Dashboard starting on http://{DASHBOARD_HOST}:{port}")
    try:
        await server.serve()
    except Exception as e:
        log.error(f"Dashboard server error: {e}")


def _get_stats() -> dict:
    """Gather system statistics."""
    try:
        from host import db
        conn = db.get_conn()

        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")

        # Message counts
        total_messages = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        today_messages = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE created_at LIKE ?", (f"{today}%",)
        ).fetchone()[0]
        week_messages = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE created_at >= ?", (week_ago,)
        ).fetchone()[0]

        # Active users (unique chat_jids with messages in last 7 days)
        active_users = conn.execute(
            "SELECT COUNT(DISTINCT chat_jid) FROM messages WHERE created_at >= ?", (week_ago,)
        ).fetchone()[0]

        # Minion distribution
        minion_dist = conn.execute(
            "SELECT minion_name, COUNT(*) FROM registered_minions GROUP BY minion_name"
        ).fetchall()

        # Workflow stats
        workflow_stats = conn.execute(
            "SELECT status, COUNT(*) FROM workflow_instances GROUP BY status"
        ).fetchall()

        # Employee count
        employee_count = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]

        # KB chunk count
        try:
            kb_count = conn.execute("SELECT COUNT(*) FROM kb_chunks_plain").fetchone()[0]
        except Exception:
            kb_count = 0

        # Recent activity by channel
        channel_dist = conn.execute(
            "SELECT channel, COUNT(*) FROM registered_minions GROUP BY channel"
        ).fetchall()

        # Top departments by message volume (based on minion)
        dept_volume = conn.execute("""
            SELECT r.minion_name, COUNT(m.id) as cnt
            FROM messages m
            JOIN registered_minions r ON m.chat_jid = r.chat_jid
            WHERE m.created_at >= ?
            GROUP BY r.minion_name
            ORDER BY cnt DESC
        """, (week_ago,)).fetchall()

        return {
            "messages": {
                "total": total_messages,
                "today": today_messages,
                "week": week_messages,
            },
            "active_users": active_users,
            "employee_count": employee_count,
            "kb_chunks": kb_count,
            "minion_distribution": dict(minion_dist),
            "workflow_stats": dict(workflow_stats),
            "channel_distribution": dict(channel_dist),
            "dept_volume_week": dict(dept_volume),
            "generated_at": now.isoformat(),
        }
    except Exception as e:
        log.error("Dashboard query error: %s", e)
        return {"error": "Internal error — check server logs"}


def _get_audit_log(limit: int = 50) -> list:
    try:
        from host import db
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT actor_jid, action, target, detail, ts FROM audit_log ORDER BY ts DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [{"actor": r[0], "action": r[1], "target": r[2], "detail": r[3], "ts": r[4]} for r in rows]
    except Exception as e:
        log.error("Dashboard query error: %s", e)
        return [{"error": "Internal error — check server logs"}]


def _get_workflows() -> list:
    try:
        from host import db
        conn = db.get_conn()
        rows = conn.execute("""
            SELECT id, workflow_type, status, submitter_jid, approved_by, created_at
            FROM workflow_instances ORDER BY created_at DESC LIMIT 50
        """).fetchall()
        return [{"id": r[0], "type": r[1], "status": r[2], "submitter": r[3],
                 "approved_by": r[4], "created_at": r[5]} for r in rows]
    except Exception as e:
        log.error("Dashboard query error: %s", e)
        return [{"error": "Internal error — check server logs"}]


def _get_kb_stats() -> dict:
    try:
        from host import db
        conn = db.get_conn()
        total = conn.execute("SELECT COUNT(*) FROM kb_chunks_plain").fetchone()[0]
        # Top sources
        try:
            sources = conn.execute(
                "SELECT source, COUNT(*) FROM kb_chunks_plain GROUP BY source ORDER BY COUNT(*) DESC LIMIT 10"
            ).fetchall()
        except Exception:
            sources = []
        return {"total_chunks": total, "sources": dict(sources)}
    except Exception as e:
        log.error("Dashboard query error: %s", e)
        return {"error": "Internal error — check server logs"}


def _dashboard_html() -> str:
    return '''<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MinionDesk Admin Dashboard</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0d1117; color: #c9d1d9; min-height: 100vh; }
header { background: #161b22; border-bottom: 1px solid #30363d; padding: 16px 24px; display: flex; align-items: center; gap: 12px; }
header h1 { font-size: 1.2rem; color: #f0f6fc; }
header .badge { background: #238636; color: #fff; padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; }
.container { max-width: 1400px; margin: 0 auto; padding: 24px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
.card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; }
.card h3 { font-size: 0.8rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }
.card .value { font-size: 2rem; font-weight: 700; color: #f0f6fc; }
.card .sub { font-size: 0.8rem; color: #8b949e; margin-top: 4px; }
.card.green .value { color: #3fb950; }
.card.blue .value { color: #58a6ff; }
.card.yellow .value { color: #d29922; }
.card.purple .value { color: #bc8cff; }
.section { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 16px; }
.section h2 { font-size: 1rem; color: #f0f6fc; margin-bottom: 16px; border-bottom: 1px solid #30363d; padding-bottom: 12px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 768px) { .two-col { grid-template-columns: 1fr; } }
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th { text-align: left; padding: 8px; color: #8b949e; font-weight: 500; border-bottom: 1px solid #30363d; }
td { padding: 8px; border-bottom: 1px solid #21262d; }
tr:last-child td { border-bottom: none; }
.badge-status { padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; font-weight: 500; }
.badge-submitted { background: #1f4a8f; color: #58a6ff; }
.badge-approved { background: #1a4731; color: #3fb950; }
.badge-rejected { background: #5c1a1a; color: #f85149; }
.badge-expired { background: #3d2d00; color: #d29922; }
.bar-chart { margin-top: 8px; }
.bar-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 0.8rem; }
.bar-label { width: 80px; color: #8b949e; text-align: right; flex-shrink: 0; }
.bar-bg { flex: 1; background: #21262d; border-radius: 3px; height: 16px; position: relative; }
.bar-fill { height: 100%; border-radius: 3px; background: #58a6ff; transition: width 0.5s; }
.bar-val { width: 40px; text-align: right; color: #8b949e; flex-shrink: 0; }
.refresh-btn { background: #238636; color: #fff; border: none; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; float: right; }
.refresh-btn:hover { background: #2ea043; }
.loading { color: #8b949e; font-style: italic; }
.error { color: #f85149; }
</style>
</head>
<body>
<header>
  <span style="font-size:1.5rem">🍌</span>
  <h1>MinionDesk Admin Dashboard</h1>
  <span class="badge">IC Design Edition</span>
  <button class="refresh-btn" onclick="loadAll()" style="margin-left:auto">🔄 更新</button>
</header>
<div class="container">
  <!-- KPI Cards -->
  <div class="grid" id="kpi-grid">
    <div class="card"><h3>載入中...</h3><div class="value loading">--</div></div>
  </div>

  <div class="two-col">
    <!-- Minion Distribution -->
    <div class="section">
      <h2>🍌 助理分佈</h2>
      <div id="minion-chart" class="bar-chart loading">載入中...</div>
    </div>
    <!-- Channel Distribution -->
    <div class="section">
      <h2>📱 渠道分佈</h2>
      <div id="channel-chart" class="bar-chart loading">載入中...</div>
    </div>
  </div>

  <!-- Workflow Status -->
  <div class="section">
    <h2>📋 工作流程審批記錄</h2>
    <div id="workflow-table" class="loading">載入中...</div>
  </div>

  <!-- Audit Log -->
  <div class="section">
    <h2>🔍 操作審計記錄</h2>
    <div id="audit-table" class="loading">載入中...</div>
  </div>
</div>

<script>
async function api(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}

function esc(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function barChart(data, maxVal) {
  if (!data || Object.keys(data).length === 0) return '<span style="color:#8b949e">暫無資料</span>';
  const max = maxVal || Object.values(data).reduce((a,b) => Math.max(a,b), 0) || 1;
  return Object.entries(data).map(([k, v]) => `
    <div class="bar-row">
      <span class="bar-label">${esc(k)}</span>
      <div class="bar-bg"><div class="bar-fill" style="width:${Math.round(v/max*100)}%"></div></div>
      <span class="bar-val">${esc(String(v))}</span>
    </div>`).join("");
}

function statusBadge(s) {
  const cls = {submitted:"badge-submitted",approved:"badge-approved",rejected:"badge-rejected",expired:"badge-expired"}[s] || "badge-submitted";
  const labels = {submitted:"⏳ 待審",approved:"✅ 已核准",rejected:"❌ 已拒絕",expired:"⏰ 已到期"};
  return `<span class="badge-status ${cls}">${esc(labels[s] || s)}</span>`;
}

async function loadStats() {
  try {
    const d = await api("/api/stats");
    if (d.error) throw new Error(d.error);

    document.getElementById("kpi-grid").innerHTML = `
      <div class="card blue"><h3>總訊息數</h3><div class="value">${esc(String(d.messages.total))}</div><div class="sub">今日 +${esc(String(d.messages.today))}</div></div>
      <div class="card green"><h3>本週訊息</h3><div class="value">${esc(String(d.messages.week))}</div><div class="sub">最近 7 天</div></div>
      <div class="card yellow"><h3>活躍用戶</h3><div class="value">${esc(String(d.active_users))}</div><div class="sub">本週不重複</div></div>
      <div class="card purple"><h3>員工數</h3><div class="value">${esc(String(d.employee_count))}</div><div class="sub">已登記</div></div>
      <div class="card"><h3>知識庫</h3><div class="value">${esc(String(d.kb_chunks))}</div><div class="sub">知識片段數</div></div>
      <div class="card green"><h3>工作流程</h3><div class="value">${esc(String(Object.values(d.workflow_stats).reduce((a,b)=>a+b,0)))}</div><div class="sub">總申請數</div></div>
    `;

    const maxMinion = Object.values(d.minion_distribution || {}).reduce((a,b) => Math.max(a,b), 0) || 1;
    document.getElementById("minion-chart").innerHTML = barChart(d.minion_distribution, maxMinion);
    document.getElementById("channel-chart").innerHTML = barChart(d.channel_distribution);
  } catch(e) {
    document.getElementById("kpi-grid").innerHTML = `<div class="card"><div class="error">載入失敗：${esc(e.message)}</div></div>`;
  }
}

async function loadWorkflows() {
  try {
    const rows = await api("/api/workflows");
    if (!rows.length) { document.getElementById("workflow-table").innerHTML = "暫無工作流程記錄"; return; }
    document.getElementById("workflow-table").innerHTML = `
      <table>
        <thead><tr><th>ID</th><th>類型</th><th>狀態</th><th>申請人</th><th>審批人</th><th>時間</th></tr></thead>
        <tbody>${rows.slice(0,20).map(r=>`
          <tr>
            <td><code>${esc(r.id)}</code></td>
            <td>${esc(r.type)}</td>
            <td>${statusBadge(r.status)}</td>
            <td>${esc(r.submitter)||"-"}</td>
            <td>${esc(r.approved_by)||"-"}</td>
            <td>${esc((r.created_at||"").slice(0,16))}</td>
          </tr>`).join("")}
        </tbody>
      </table>`;
  } catch(e) { document.getElementById("workflow-table").innerHTML = `<span class="error">${esc(e.message)}</span>`; }
}

async function loadAudit() {
  try {
    const rows = await api("/api/audit?limit=30");
    if (!rows.length || rows[0]?.error) { document.getElementById("audit-table").innerHTML = rows[0]?.error || "暫無記錄"; return; }
    document.getElementById("audit-table").innerHTML = `
      <table>
        <thead><tr><th>操作者</th><th>動作</th><th>對象</th><th>細節</th><th>時間</th></tr></thead>
        <tbody>${rows.map(r=>`
          <tr>
            <td>${esc(r.actor)||"-"}</td>
            <td><code>${esc(r.action)||"-"}</code></td>
            <td>${esc(r.target)||"-"}</td>
            <td style="color:#8b949e">${esc(r.detail)||""}</td>
            <td>${esc((r.ts||"").slice(0,16))}</td>
          </tr>`).join("")}
        </tbody>
      </table>`;
  } catch(e) { document.getElementById("audit-table").innerHTML = `<span class="error">${esc(e.message)}</span>`; }
}

async function loadAll() {
  await Promise.all([loadStats(), loadWorkflows(), loadAudit()]);
}

loadAll();
setInterval(loadAll, 30000); // Auto-refresh every 30s
</script>
</body>
</html>'''
