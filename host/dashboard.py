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

    # ── Task Management ────────────────────────────────────────────────────────

    @app.get("/api/tasks")
    async def get_tasks(chat_jid: str = Query(default=""), creds=Depends(verify_auth)):
        from host import db
        try:
            if chat_jid:
                tasks = db.get_scheduled_tasks_for_chat(chat_jid)
            else:
                tasks = db.get_scheduled_tasks()
            return JSONResponse({"tasks": tasks})
        except Exception as e:
            log.error("get_tasks error: %s", e)
            return JSONResponse({"tasks": [], "error": str(e)})

    @app.get("/api/task-runs")
    async def get_task_runs(
        task_id: str = Query(default=""),
        chat_jid: str = Query(default=""),
        limit: int = Query(default=50, ge=1, le=500),
        creds=Depends(verify_auth)
    ):
        from host import db
        try:
            logs = db.get_task_run_logs(task_id or None, chat_jid or None, limit=limit)
            return JSONResponse({"runs": logs})
        except Exception as e:
            log.error("get_task_runs error: %s", e)
            return JSONResponse({"runs": [], "error": str(e)})

    @app.post("/api/tasks/{task_id}/cancel")
    async def cancel_task(task_id: str, creds=Depends(verify_auth)):
        from host import db
        try:
            found = db.cancel_scheduled_task(task_id)
            return JSONResponse({"ok": found, "task_id": task_id})
        except Exception as e:
            log.error("cancel_task error: %s", e)
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    # ── Message / Conversation Browser ────────────────────────────────────────

    @app.get("/api/messages")
    async def get_messages(
        jid: str = Query(default=""),
        limit: int = Query(default=50, ge=1, le=500),
        creds=Depends(verify_auth)
    ):
        from host import db
        try:
            msgs = db.get_conversation_history(jid, limit=limit) if jid else []
            chats = db.get_all_minions()
            return JSONResponse({"messages": msgs, "chats": chats})
        except Exception as e:
            log.error("get_messages error: %s", e)
            return JSONResponse({"messages": [], "chats": [], "error": str(e)})

    # ── Memory System ──────────────────────────────────────────────────────────

    @app.get("/api/memory")
    async def get_memory(jid: str = Query(default=""), creds=Depends(verify_auth)):
        from host import db
        try:
            if jid:
                hot = db.get_hot_memory(jid)
                warm = db.get_warm_logs_recent(jid, days=7)
            else:
                hot = ""
                warm = []
            chats = db.get_all_minions()
            return JSONResponse({"jid": jid, "hot_memory": hot, "warm_logs": warm[-20:], "chats": chats})
        except Exception as e:
            log.error("get_memory error: %s", e)
            return JSONResponse({"jid": jid, "hot_memory": "", "warm_logs": [], "chats": [], "error": str(e)})

    # ── Knowledge Base Browser ─────────────────────────────────────────────────

    @app.get("/api/knowledge")
    async def get_knowledge(
        search: str = Query(default=""),
        limit: int = Query(default=20, ge=1, le=100),
        creds=Depends(verify_auth)
    ):
        from host import db
        try:
            docs = db.get_kb_docs(search or None, limit=limit)
            return JSONResponse({"docs": docs})
        except Exception as e:
            log.error("get_knowledge error: %s", e)
            return JSONResponse({"docs": [], "error": str(e)})

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

        # Task count (active)
        try:
            task_count = conn.execute(
                "SELECT COUNT(*) FROM scheduled_tasks WHERE status IS NULL OR status = 'active'"
            ).fetchone()[0]
        except Exception:
            task_count = 0

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
            "active_tasks": task_count,
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
.card.orange .value { color: #f78166; }
.section { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; margin-bottom: 16px; }
.section h2 { font-size: 1rem; color: #f0f6fc; margin-bottom: 16px; border-bottom: 1px solid #30363d; padding-bottom: 12px; }
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 768px) { .two-col { grid-template-columns: 1fr; } }
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
th { text-align: left; padding: 8px; color: #8b949e; font-weight: 500; border-bottom: 1px solid #30363d; }
td { padding: 8px; border-bottom: 1px solid #21262d; vertical-align: top; }
tr:last-child td { border-bottom: none; }
.badge-status { padding: 2px 8px; border-radius: 12px; font-size: 0.75rem; font-weight: 500; }
.badge-submitted { background: #1f4a8f; color: #58a6ff; }
.badge-approved { background: #1a4731; color: #3fb950; }
.badge-rejected { background: #5c1a1a; color: #f85149; }
.badge-expired { background: #3d2d00; color: #d29922; }
.badge-active { background: #1a4731; color: #3fb950; }
.badge-cancelled { background: #3d2d00; color: #d29922; }
.badge-error { background: #5c1a1a; color: #f85149; }
.badge-success { background: #1a4731; color: #3fb950; }
.bar-chart { margin-top: 8px; }
.bar-row { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 0.8rem; }
.bar-label { width: 80px; color: #8b949e; text-align: right; flex-shrink: 0; }
.bar-bg { flex: 1; background: #21262d; border-radius: 3px; height: 16px; position: relative; }
.bar-fill { height: 100%; border-radius: 3px; background: #58a6ff; transition: width 0.5s; }
.bar-val { width: 40px; text-align: right; color: #8b949e; flex-shrink: 0; }
.refresh-btn { background: #238636; color: #fff; border: none; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 0.85rem; }
.refresh-btn:hover { background: #2ea043; }
.loading { color: #8b949e; font-style: italic; }
.error { color: #f85149; }
.cancel-btn { background: #5c1a1a; color: #f85149; border: 1px solid #f85149; padding: 2px 8px; border-radius: 4px; cursor: pointer; font-size: 0.75rem; }
.cancel-btn:hover { background: #7a2222; }
/* Tab Navigation */
.tabs { display: flex; gap: 4px; border-bottom: 2px solid #30363d; margin-bottom: 24px; flex-wrap: wrap; }
.tab-btn { background: none; border: none; padding: 10px 18px; color: #8b949e; cursor: pointer; font-size: 0.9rem; border-bottom: 2px solid transparent; margin-bottom: -2px; transition: color 0.2s; }
.tab-btn:hover { color: #c9d1d9; }
.tab-btn.active { color: #58a6ff; border-bottom-color: #58a6ff; }
.tab-panel { display: none; }
.tab-panel.active { display: block; }
/* Message browser */
.msg-list { max-height: 500px; overflow-y: auto; font-size: 0.85rem; }
.msg-item { padding: 8px 12px; border-bottom: 1px solid #21262d; }
.msg-item:last-child { border-bottom: none; }
.msg-role-user { border-left: 3px solid #58a6ff; }
.msg-role-assistant { border-left: 3px solid #3fb950; }
.msg-meta { font-size: 0.75rem; color: #8b949e; margin-bottom: 4px; }
.msg-content { color: #c9d1d9; word-break: break-word; white-space: pre-wrap; }
/* Memory viewer */
.hot-memory { background: #0d1117; border: 1px solid #30363d; border-radius: 6px; padding: 16px; font-family: monospace; font-size: 0.8rem; white-space: pre-wrap; max-height: 400px; overflow-y: auto; color: #c9d1d9; }
.warm-log-item { padding: 8px; border-bottom: 1px solid #21262d; font-size: 0.8rem; }
.warm-log-date { color: #58a6ff; font-size: 0.75rem; margin-bottom: 4px; }
.warm-log-content { color: #c9d1d9; white-space: pre-wrap; }
/* KB doc */
.kb-item { padding: 12px; border-bottom: 1px solid #21262d; }
.kb-title { font-weight: 500; color: #f0f6fc; margin-bottom: 4px; }
.kb-source { font-size: 0.75rem; color: #8b949e; margin-bottom: 6px; }
.kb-content { font-size: 0.8rem; color: #8b949e; white-space: pre-wrap; }
/* Select & Input */
select, input[type=text], input[type=number] { background: #0d1117; border: 1px solid #30363d; color: #c9d1d9; padding: 6px 10px; border-radius: 6px; font-size: 0.85rem; }
select:focus, input:focus { outline: none; border-color: #58a6ff; }
.search-row { display: flex; gap: 8px; margin-bottom: 16px; align-items: center; }
.search-row label { color: #8b949e; font-size: 0.85rem; flex-shrink: 0; }
</style>
</head>
<body>
<header>
  <span style="font-size:1.5rem">🍌</span>
  <h1>MinionDesk Admin Dashboard</h1>
  <span class="badge">v2.2.0</span>
  <button class="refresh-btn" onclick="loadCurrentTab()" style="margin-left:auto">🔄 更新</button>
</header>
<div class="container">

  <!-- Tab Navigation -->
  <div class="tabs">
    <button class="tab-btn active" onclick="switchTab('overview')">📊 概覽</button>
    <button class="tab-btn" onclick="switchTab('tasks')">📋 任務</button>
    <button class="tab-btn" onclick="switchTab('messages')">💬 對話</button>
    <button class="tab-btn" onclick="switchTab('memory')">🧠 記憶</button>
    <button class="tab-btn" onclick="switchTab('knowledge')">📚 知識庫</button>
    <button class="tab-btn" onclick="switchTab('workflows')">📝 工作流程</button>
    <button class="tab-btn" onclick="switchTab('audit')">🔍 審計</button>
  </div>

  <!-- OVERVIEW TAB -->
  <div id="tab-overview" class="tab-panel active">
    <div class="grid" id="kpi-grid">
      <div class="card"><h3>載入中...</h3><div class="value loading">--</div></div>
    </div>
    <div class="two-col">
      <div class="section">
        <h2>🍌 助理分佈</h2>
        <div id="minion-chart" class="bar-chart loading">載入中...</div>
      </div>
      <div class="section">
        <h2>📱 渠道分佈</h2>
        <div id="channel-chart" class="bar-chart loading">載入中...</div>
      </div>
    </div>
  </div>

  <!-- TASKS TAB -->
  <div id="tab-tasks" class="tab-panel">
    <div class="section">
      <h2>📋 排程任務</h2>
      <div class="search-row">
        <label>群組篩選：</label>
        <select id="task-jid-filter" onchange="loadTasks()">
          <option value="">全部群組</option>
        </select>
        <button class="refresh-btn" onclick="loadTasks()">🔄 更新</button>
      </div>
      <div id="task-table" class="loading">載入中...</div>
    </div>
    <div class="section">
      <h2>⏱ 任務執行歷史</h2>
      <div class="search-row">
        <label>任務 ID：</label>
        <input type="text" id="run-task-id-filter" placeholder="篩選任務 ID..." oninput="loadTaskRuns()" style="width:200px">
        <label>群組：</label>
        <select id="run-jid-filter" onchange="loadTaskRuns()">
          <option value="">全部</option>
        </select>
        <button class="refresh-btn" onclick="loadTaskRuns()">🔄 更新</button>
      </div>
      <div id="task-run-table" class="loading">載入中...</div>
    </div>
  </div>

  <!-- MESSAGES TAB -->
  <div id="tab-messages" class="tab-panel">
    <div class="section">
      <h2>💬 對話歷史</h2>
      <div class="search-row">
        <label>群組：</label>
        <select id="msg-jid-select" onchange="loadMessages()">
          <option value="">選擇群組...</option>
        </select>
        <label>筆數：</label>
        <input type="number" id="msg-limit" value="50" min="10" max="500" style="width:70px" onchange="loadMessages()">
        <button class="refresh-btn" onclick="loadMessages()">🔄 更新</button>
      </div>
      <div id="msg-list" class="msg-list"><span class="loading">請選擇群組</span></div>
    </div>
  </div>

  <!-- MEMORY TAB -->
  <div id="tab-memory" class="tab-panel">
    <div class="section">
      <h2>🧠 記憶查看器</h2>
      <div class="search-row">
        <label>群組：</label>
        <select id="mem-jid-select" onchange="loadMemory()">
          <option value="">選擇群組...</option>
        </select>
        <button class="refresh-btn" onclick="loadMemory()">🔄 更新</button>
      </div>
      <div class="two-col" style="margin-top:16px">
        <div>
          <h3 style="color:#f0f6fc;margin-bottom:10px;font-size:0.9rem">🔥 熱記憶（MEMORY.md）</h3>
          <div id="hot-memory" class="hot-memory loading">請選擇群組</div>
        </div>
        <div>
          <h3 style="color:#f0f6fc;margin-bottom:10px;font-size:0.9rem">🌡 暖記憶（最近 7 天）</h3>
          <div id="warm-logs" style="max-height:400px;overflow-y:auto"><span class="loading">請選擇群組</span></div>
        </div>
      </div>
    </div>
  </div>

  <!-- KNOWLEDGE TAB -->
  <div id="tab-knowledge" class="tab-panel">
    <div class="section">
      <h2>📚 知識庫瀏覽器</h2>
      <div class="search-row">
        <label>搜尋：</label>
        <input type="text" id="kb-search" placeholder="關鍵字搜尋..." style="width:250px" oninput="debounceKB()">
        <label>數量：</label>
        <input type="number" id="kb-limit" value="20" min="5" max="100" style="width:70px" onchange="loadKB()">
        <button class="refresh-btn" onclick="loadKB()">🔍 搜尋</button>
      </div>
      <div id="kb-docs" class="loading">載入中...</div>
    </div>
  </div>

  <!-- WORKFLOWS TAB -->
  <div id="tab-workflows" class="tab-panel">
    <div class="section">
      <h2>📋 工作流程審批記錄</h2>
      <button class="refresh-btn" onclick="loadWorkflows()" style="margin-bottom:16px">🔄 更新</button>
      <div id="workflow-table" class="loading">載入中...</div>
    </div>
  </div>

  <!-- AUDIT TAB -->
  <div id="tab-audit" class="tab-panel">
    <div class="section">
      <h2>🔍 操作審計記錄</h2>
      <button class="refresh-btn" onclick="loadAudit()" style="margin-bottom:16px">🔄 更新</button>
      <div id="audit-table" class="loading">載入中...</div>
    </div>
  </div>

</div>

<script>
// ── Utilities ──────────────────────────────────────────────────────────────
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
  const cls = {submitted:"badge-submitted",approved:"badge-approved",rejected:"badge-rejected",expired:"badge-expired",
               active:"badge-active",cancelled:"badge-cancelled",error:"badge-error",success:"badge-success"}[s] || "badge-submitted";
  const labels = {submitted:"⏳ 待審",approved:"✅ 已核准",rejected:"❌ 已拒絕",expired:"⏰ 已到期",
                  active:"✅ 活躍",cancelled:"🚫 已取消",error:"❌ 錯誤",success:"✅ 成功"};
  return `<span class="badge-status ${cls}">${esc(labels[s] || s)}</span>`;
}

// ── Tab Switching ──────────────────────────────────────────────────────────
let currentTab = 'overview';

function switchTab(name) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');
  currentTab = name;
  loadTabData(name);
}

function loadCurrentTab() { loadTabData(currentTab); }

function loadTabData(name) {
  switch(name) {
    case 'overview': loadStats(); break;
    case 'tasks': loadTasks(); loadTaskRuns(); break;
    case 'messages': loadMessageChats(); break;
    case 'memory': loadMemoryChats(); break;
    case 'knowledge': loadKB(); break;
    case 'workflows': loadWorkflows(); break;
    case 'audit': loadAudit(); break;
  }
}

// ── Overview ───────────────────────────────────────────────────────────────
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
      <div class="card green"><h3>工作流程</h3><div class="value">${esc(String(Object.values(d.workflow_stats||{}).reduce((a,b)=>a+b,0)))}</div><div class="sub">總申請數</div></div>
      <div class="card orange"><h3>排程任務</h3><div class="value">${esc(String(d.active_tasks||0))}</div><div class="sub">活躍中</div></div>
    `;

    const maxMinion = Object.values(d.minion_distribution || {}).reduce((a,b) => Math.max(a,b), 0) || 1;
    document.getElementById("minion-chart").innerHTML = barChart(d.minion_distribution, maxMinion);
    document.getElementById("channel-chart").innerHTML = barChart(d.channel_distribution);
  } catch(e) {
    document.getElementById("kpi-grid").innerHTML = `<div class="card"><div class="error">載入失敗：${esc(e.message)}</div></div>`;
  }
}

// ── Tasks ──────────────────────────────────────────────────────────────────
let allMinions = [];

async function populateMinionSelects() {
  try {
    const d = await api("/api/messages");
    allMinions = d.chats || [];
    ['task-jid-filter','run-jid-filter','msg-jid-select','mem-jid-select'].forEach(id => {
      const sel = document.getElementById(id);
      if (!sel) return;
      const current = sel.value;
      while (sel.options.length > 1) sel.remove(1);
      allMinions.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m.chat_jid;
        opt.text = `${m.minion_name} (${m.chat_jid.slice(0,20)}...)`;
        sel.add(opt);
      });
      if (current) sel.value = current;
    });
  } catch(e) { /* ignore */ }
}

async function loadTasks() {
  const jid = document.getElementById('task-jid-filter').value;
  const el = document.getElementById('task-table');
  el.innerHTML = '<span class="loading">載入中...</span>';
  try {
    const url = jid ? `/api/tasks?chat_jid=${encodeURIComponent(jid)}` : '/api/tasks';
    const d = await api(url);
    const tasks = d.tasks || [];
    if (!tasks.length) { el.innerHTML = '<span style="color:#8b949e">暫無任務資料</span>'; return; }
    el.innerHTML = `<table>
      <thead><tr><th>ID</th><th>群組</th><th>助理</th><th>類型</th><th>計劃值</th><th>狀態</th><th>上次執行</th><th>建立時間</th><th>操作</th></tr></thead>
      <tbody>${tasks.map(t => `
        <tr>
          <td><code style="font-size:0.75rem">${esc((t.id||'').slice(0,16))}…</code></td>
          <td style="font-size:0.75rem">${esc((t.chat_jid||'').slice(0,20))}…</td>
          <td>${esc(t.minion_name||'-')}</td>
          <td><code>${esc(t.schedule_type||'-')}</code></td>
          <td style="font-size:0.75rem;color:#8b949e"><code>${esc(t.schedule_value||'-')}</code></td>
          <td>${statusBadge(t.status||'active')}</td>
          <td style="font-size:0.75rem">${esc((t.last_run||'').slice(0,16)||'從未')}</td>
          <td style="font-size:0.75rem">${esc((t.created_at||'').slice(0,16))}</td>
          <td>${(t.status||'active')==='active' ? `<button class="cancel-btn" onclick="cancelTask('${esc(t.id)}')">取消</button>` : ''}</td>
        </tr>`).join('')}
      </tbody>
    </table>`;
  } catch(e) { el.innerHTML = `<span class="error">${esc(e.message)}</span>`; }
}

async function cancelTask(taskId) {
  if (!confirm('確認取消任務 ' + taskId + '?')) return;
  try {
    const res = await fetch(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, {method:'POST'});
    const d = await res.json();
    if (d.ok) { loadTasks(); } else { alert('取消失敗: ' + (d.error||'未知錯誤')); }
  } catch(e) { alert('取消失敗: ' + e.message); }
}

async function loadTaskRuns() {
  const taskId = document.getElementById('run-task-id-filter').value.trim();
  const jid = document.getElementById('run-jid-filter').value;
  const el = document.getElementById('task-run-table');
  el.innerHTML = '<span class="loading">載入中...</span>';
  try {
    let url = '/api/task-runs?limit=50';
    if (taskId) url += '&task_id=' + encodeURIComponent(taskId);
    if (jid) url += '&chat_jid=' + encodeURIComponent(jid);
    const d = await api(url);
    const runs = d.runs || [];
    if (!runs.length) { el.innerHTML = '<span style="color:#8b949e">暫無執行歷史</span>'; return; }
    el.innerHTML = `<table>
      <thead><tr><th>時間</th><th>任務 ID</th><th>群組</th><th>狀態</th><th>耗時(ms)</th><th>結果 / 錯誤</th></tr></thead>
      <tbody>${runs.map(r => `
        <tr>
          <td style="font-size:0.75rem">${esc((r.run_at||'').slice(0,16))}</td>
          <td><code style="font-size:0.75rem">${esc((r.task_id||'').slice(0,16))}…</code></td>
          <td style="font-size:0.75rem">${esc((r.chat_jid||'').slice(0,20))}…</td>
          <td>${statusBadge(r.status||'success')}</td>
          <td>${esc(String(r.duration_ms||'-'))}</td>
          <td style="font-size:0.75rem;color:#8b949e">${esc((r.error||r.result||'').slice(0,100))}</td>
        </tr>`).join('')}
      </tbody>
    </table>`;
  } catch(e) { el.innerHTML = `<span class="error">${esc(e.message)}</span>`; }
}

// ── Messages ───────────────────────────────────────────────────────────────
async function loadMessageChats() {
  await populateMinionSelects();
}

async function loadMessages() {
  const jid = document.getElementById('msg-jid-select').value;
  const limit = document.getElementById('msg-limit').value || 50;
  const el = document.getElementById('msg-list');
  if (!jid) { el.innerHTML = '<span class="loading">請選擇群組</span>'; return; }
  el.innerHTML = '<span class="loading">載入中...</span>';
  try {
    const d = await api(`/api/messages?jid=${encodeURIComponent(jid)}&limit=${limit}`);
    const msgs = d.messages || [];
    if (!msgs.length) { el.innerHTML = '<span style="color:#8b949e">暫無對話記錄</span>'; return; }
    el.innerHTML = msgs.map(m => `
      <div class="msg-item msg-role-${esc(m.role||'user')}">
        <div class="msg-meta">${esc(m.role||'user')} · ${esc(m.sender_jid||'')} · ${esc((m.ts||'').slice(0,16))}</div>
        <div class="msg-content">${esc((m.content||'').slice(0,500))}${(m.content||'').length>500?'…':''}</div>
      </div>`).join('');
  } catch(e) { el.innerHTML = `<span class="error">${esc(e.message)}</span>`; }
}

// ── Memory ─────────────────────────────────────────────────────────────────
async function loadMemoryChats() {
  await populateMinionSelects();
}

async function loadMemory() {
  const jid = document.getElementById('mem-jid-select').value;
  const hotEl = document.getElementById('hot-memory');
  const warmEl = document.getElementById('warm-logs');
  if (!jid) {
    hotEl.innerHTML = '請選擇群組';
    warmEl.innerHTML = '<span class="loading">請選擇群組</span>';
    return;
  }
  hotEl.textContent = '載入中...';
  warmEl.innerHTML = '<span class="loading">載入中...</span>';
  try {
    const d = await api(`/api/memory?jid=${encodeURIComponent(jid)}`);
    hotEl.textContent = d.hot_memory || '（空）';
    const logs = d.warm_logs || [];
    if (!logs.length) { warmEl.innerHTML = '<span style="color:#8b949e">暫無暖記憶</span>'; return; }
    warmEl.innerHTML = logs.slice().reverse().map(l => `
      <div class="warm-log-item">
        <div class="warm-log-date">${esc(l.log_date||'')} · ${new Date((l.created_at||0)*1000).toLocaleString('zh-TW')}</div>
        <div class="warm-log-content">${esc((l.content||'').slice(0,300))}${(l.content||'').length>300?'…':''}</div>
      </div>`).join('');
  } catch(e) {
    hotEl.textContent = '載入失敗：' + e.message;
    warmEl.innerHTML = `<span class="error">${esc(e.message)}</span>`;
  }
}

// ── Knowledge Base ─────────────────────────────────────────────────────────
let kbTimer = null;
function debounceKB() { clearTimeout(kbTimer); kbTimer = setTimeout(loadKB, 400); }

async function loadKB() {
  const search = document.getElementById('kb-search').value.trim();
  const limit = document.getElementById('kb-limit').value || 20;
  const el = document.getElementById('kb-docs');
  el.innerHTML = '<span class="loading">載入中...</span>';
  try {
    let url = `/api/knowledge?limit=${limit}`;
    if (search) url += '&search=' + encodeURIComponent(search);
    const d = await api(url);
    const docs = d.docs || [];
    if (!docs.length) { el.innerHTML = '<span style="color:#8b949e">暫無知識庫資料</span>'; return; }
    el.innerHTML = docs.map(doc => `
      <div class="kb-item">
        <div class="kb-title">${esc(doc.title||'（無標題）')}</div>
        <div class="kb-source">📎 ${esc(doc.source||'未知來源')}</div>
        <div class="kb-content">${esc((doc.content||'').slice(0,300))}${(doc.content||'').length>300?'…':''}</div>
      </div>`).join('');
  } catch(e) { el.innerHTML = `<span class="error">${esc(e.message)}</span>`; }
}

// ── Workflows ──────────────────────────────────────────────────────────────
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

// ── Audit ──────────────────────────────────────────────────────────────────
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

// ── Init ────────────────────────────────────────────────────────────────────
loadStats();
setInterval(() => loadTabData(currentTab), 30000); // Auto-refresh every 30s
</script>
</body>
</html>'''
