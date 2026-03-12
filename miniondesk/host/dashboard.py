"""MinionDesk Dashboard — pure stdlib HTTP server with real-time SSE log stream."""
from __future__ import annotations
import asyncio
import base64
import html
import json
import logging
import queue
import threading
import time
import time as _time_module
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from . import config, db

logger = logging.getLogger(__name__)

# Maximum concurrent SSE log-stream clients; prevents memory exhaustion from connection floods.
_MAX_SSE_CLIENTS = 20

# ─── Log capture ──────────────────────────────────────────────────────────────

# _log_buffer holds the recent history for new SSE clients to catch up on connect.
# _sse_subscribers is a list of per-client queues — each SSE connection gets its
# own queue so ALL clients receive ALL log entries (fan-out), not just one.
_log_buffer: deque = deque(maxlen=500)
_log_lock = threading.Lock()
_sse_subscribers: list[queue.Queue] = []
_start_time = _time_module.time()

LEVEL_COLORS = {
    "DEBUG":    "#888",
    "INFO":     "#4fc3f7",
    "WARNING":  "#ffb74d",
    "ERROR":    "#ef5350",
    "CRITICAL": "#e040fb",
}


class _QueueHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "ts": time.strftime("%H:%M:%S", time.localtime(record.created)),
                "level": record.levelname,
                "name": record.name.replace("miniondesk.host.", ""),
                "msg": self.format(record),
            }
            with _log_lock:
                _log_buffer.append(entry)
                # Fan-out: deliver to every active SSE subscriber's dedicated queue
                to_remove = []
                for sub_q in list(_sse_subscribers):  # iterate copy
                    try:
                        sub_q.put_nowait(entry)
                    except queue.Full:
                        to_remove.append(sub_q)  # dead reader — queue full
                    except Exception:
                        to_remove.append(sub_q)
                for sub_q in to_remove:
                    try:
                        _sse_subscribers.remove(sub_q)
                    except ValueError:
                        pass
        except Exception:
            pass


def install_log_handler() -> None:
    handler = _QueueHandler()
    handler.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(handler)


# ─── HTML template ────────────────────────────────────────────────────────────

_HTML = """<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🐤 MinionDesk Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f0f1a; color: #e0e0e0; font-family: 'Courier New', monospace; font-size: 13px; }
  #layout { display: flex; height: 100vh; }
  #sidebar { width: 180px; background: #1a1a2e; padding: 16px 0; display: flex; flex-direction: column; }
  #logo { padding: 8px 16px 24px; font-size: 18px; color: #b39ddb; font-weight: bold; }
  .nav-item { padding: 10px 16px; cursor: pointer; color: #aaa; transition: all 0.2s; border-left: 3px solid transparent; }
  .nav-item:hover { color: #e0e0e0; background: #16213e; }
  .nav-item.active { color: #b39ddb; border-left-color: #b39ddb; background: #16213e; }
  #main { flex: 1; overflow-y: auto; padding: 20px; }
  .page { display: none; }
  .page.active { display: block; }
  h2 { color: #b39ddb; margin-bottom: 16px; font-size: 16px; }
  .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 20px; }
  .stat-card { background: #1a1a2e; border: 1px solid #2d2d44; border-radius: 8px; padding: 16px; }
  .stat-label { color: #888; font-size: 11px; text-transform: uppercase; margin-bottom: 4px; }
  .stat-value { font-size: 24px; color: #b39ddb; }
  .stat-sub { color: #666; font-size: 11px; margin-top: 4px; }
  #log-box { background: #0a0a12; border: 1px solid #2d2d44; border-radius: 6px; height: 500px; overflow-y: scroll; padding: 8px; font-size: 12px; }
  .log-line { padding: 2px 0; border-bottom: 1px solid #1a1a2e; }
  .log-ts { color: #555; }
  .log-name { color: #7c4dff; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; padding: 8px; background: #1a1a2e; color: #888; font-size: 11px; text-transform: uppercase; }
  td { padding: 8px; border-bottom: 1px solid #1a1a2e; vertical-align: top; }
  tr:hover td { background: #16213e; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; }
  .badge-ok { background: #1b5e20; color: #69f0ae; }
  .badge-warn { background: #e65100; color: #ffcc80; }
  .filter-bar { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
  .filter-btn { padding: 4px 12px; border: 1px solid #2d2d44; background: #1a1a2e; color: #888; border-radius: 4px; cursor: pointer; font-family: monospace; font-size: 12px; }
  .filter-btn.active { background: #b39ddb; color: #0f0f1a; border-color: #b39ddb; }
  #log-search { flex: 1; background: #1a1a2e; border: 1px solid #2d2d44; color: #e0e0e0; padding: 4px 8px; border-radius: 4px; font-family: monospace; font-size: 12px; }
  .btn { padding: 6px 14px; border: 1px solid #b39ddb; background: transparent; color: #b39ddb; border-radius: 4px; cursor: pointer; font-family: monospace; }
  .btn:hover { background: #b39ddb; color: #0f0f1a; }
  .genome-bar { height: 8px; background: #2d2d44; border-radius: 4px; overflow: hidden; margin-top: 4px; }
  .genome-fill { height: 100%; background: #b39ddb; transition: width 0.5s; }
</style>
</head>
<body>
<div id="layout">
  <nav id="sidebar">
    <div id="logo">🐤 MinionDesk</div>
    <div class="nav-item active" onclick="showPage('status')">📊 Status</div>
    <div class="nav-item" onclick="showPage('groups')">👥 Groups</div>
    <div class="nav-item" onclick="showPage('genome')">🧬 Genome</div>
    <div class="nav-item" onclick="showPage('devengine')">🔧 DevEngine</div>
    <div class="nav-item" onclick="showPage('skills')">⚡ Skills</div>
    <div class="nav-item" onclick="showPage('logs')">📋 Logs</div>
  </nav>
  <div id="main">
    <!-- Status Page -->
    <div id="page-status" class="page active">
      <h2>📊 System Status</h2>
      <div class="stat-grid" id="stat-grid">
        <div class="stat-card"><div class="stat-label">Groups</div><div class="stat-value" id="st-groups">-</div></div>
        <div class="stat-card"><div class="stat-label">Messages Today</div><div class="stat-value" id="st-msgs">-</div></div>
        <div class="stat-card"><div class="stat-label">Tasks Active</div><div class="stat-value" id="st-tasks">-</div></div>
        <div class="stat-card"><div class="stat-label">KB Documents</div><div class="stat-value" id="st-kb">-</div></div>
      </div>
      <h2 style="margin-top:20px">🐤 Minion Status</h2>
      <table id="minion-table">
        <thead><tr><th>Group</th><th>Minion</th><th>Trigger</th><th>Genome Gen</th><th>Fitness</th></tr></thead>
        <tbody id="minion-tbody"></tbody>
      </table>
    </div>
    <!-- Groups Page -->
    <div id="page-groups" class="page">
      <h2>👥 Registered Groups</h2>
      <table>
        <thead><tr><th>Name</th><th>JID</th><th>Folder</th><th>Minion</th><th>Trigger</th></tr></thead>
        <tbody id="groups-tbody"></tbody>
      </table>
    </div>
    <!-- Genome Page -->
    <div id="page-genome" class="page">
      <h2>🧬 Genome Evolution</h2>
      <div id="genome-cards"></div>
    </div>
    <!-- DevEngine Page -->
    <div id="page-devengine" class="page">
      <h2>🔧 DevEngine Sessions</h2>
      <div class="filter-bar">
        <button class="filter-btn active" onclick="setDevFilter('ALL')">ALL</button>
        <button class="filter-btn" onclick="setDevFilter('running')" style="color:#4fc3f7">RUNNING</button>
        <button class="filter-btn" onclick="setDevFilter('completed')" style="color:#69f0ae">DONE</button>
        <button class="filter-btn" onclick="setDevFilter('failed')" style="color:#ef5350">FAILED</button>
        <button class="filter-btn" onclick="setDevFilter('paused')" style="color:#ffb74d">PAUSED</button>
      </div>
      <table id="dev-table">
        <thead><tr><th>Session</th><th>Status</th><th>Stage</th><th>Prompt</th><th>Updated</th></tr></thead>
        <tbody id="dev-tbody"></tbody>
      </table>
    </div>
    <!-- Skills Page -->
    <div id="page-skills" class="page">
      <h2>⚡ Superpowers Skills</h2>
      <div id="skills-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;margin-top:8px"></div>
    </div>
    <!-- Logs Page -->
    <div id="page-logs" class="page">
      <h2>📋 Live Logs</h2>
      <div class="filter-bar">
        <button class="filter-btn active" onclick="setFilter('ALL')">ALL</button>
        <button class="filter-btn" onclick="setFilter('INFO')" style="color:#4fc3f7">INFO</button>
        <button class="filter-btn" onclick="setFilter('WARNING')" style="color:#ffb74d">WARN</button>
        <button class="filter-btn" onclick="setFilter('ERROR')" style="color:#ef5350">ERROR</button>
        <input id="log-search" type="text" placeholder="Filter logs..." oninput="renderLogs()">
        <button class="btn" onclick="clearLogs()">Clear</button>
        <label style="color:#888;align-self:center"><input type="checkbox" id="auto-scroll" checked> Auto-scroll</label>
      </div>
      <div id="log-box"></div>
    </div>
  </div>
</div>
<script>
const LEVEL_COLORS = {DEBUG:'#888',INFO:'#4fc3f7',WARNING:'#ffb74d',ERROR:'#ef5350',CRITICAL:'#e040fb'};
let allLogs = [], logFilter = 'ALL';

function showPage(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-'+name).classList.add('active');
  event.target.classList.add('active');
  if (name === 'logs') renderLogs();
}

function setFilter(f) {
  logFilter = f;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.toggle('active', b.textContent.includes(f) || (f==='ALL' && b.textContent==='ALL')));
  renderLogs();
}

function clearLogs() { allLogs = []; renderLogs(); }

function renderLogs() {
  const search = document.getElementById('log-search').value.toLowerCase();
  const box = document.getElementById('log-box');
  const filtered = allLogs.filter(l =>
    (logFilter === 'ALL' || l.level === logFilter) &&
    (!search || l.msg.toLowerCase().includes(search))
  );
  box.innerHTML = filtered.map(l =>
    `<div class="log-line"><span class="log-ts">${l.ts}</span> <span style="color:${LEVEL_COLORS[l.level]||'#aaa'}">${l.level.padEnd(7)}</span> <span class="log-name">${l.name}</span> ${htmlEsc(l.msg)}</div>`
  ).join('');
  if (document.getElementById('auto-scroll').checked) box.scrollTop = box.scrollHeight;
}

function htmlEsc(s) { return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

// SSE for logs
const evtSrc = new EventSource('/api/logs/stream');
evtSrc.onmessage = e => {
  const data = JSON.parse(e.data);
  allLogs.push(data);
  if (allLogs.length > 1000) allLogs.shift();
  if (document.getElementById('page-logs').classList.contains('active')) renderLogs();
};

// Poll status every 5s
async function pollStatus() {
  try {
    const [status, groups] = await Promise.all([
      fetch('/api/status').then(r=>r.json()),
      fetch('/api/groups').then(r=>r.json()),
    ]);
    document.getElementById('st-groups').textContent = status.groups;
    document.getElementById('st-msgs').textContent = status.messages_today;
    document.getElementById('st-tasks').textContent = status.tasks_active;
    document.getElementById('st-kb').textContent = status.kb_docs;

    // Minion table
    const tbody = document.getElementById('minion-tbody');
    tbody.innerHTML = groups.map(g => `
      <tr>
        <td>${htmlEsc(g.name||'')}</td>
        <td>🐤 ${htmlEsc(g.minion||'')}</td>
        <td><code>${htmlEsc(g.trigger||'')}</code></td>
        <td>${g.genome?.generation ?? 0}</td>
        <td><span class="badge badge-ok">${((g.genome?.fitness_score||0.5)*100).toFixed(0)}%</span></td>
      </tr>`).join('');

    // Groups table
    document.getElementById('groups-tbody').innerHTML = groups.map(g => `
      <tr>
        <td>${htmlEsc(g.name||'')}</td>
        <td><code style="font-size:11px">${htmlEsc(g.jid||'')}</code></td>
        <td>${htmlEsc(g.folder||'')}</td>
        <td>🐤 ${htmlEsc(g.minion||'')}</td>
        <td><code>${htmlEsc(g.trigger||'')}</code></td>
      </tr>`).join('');

    // Genome cards
    document.getElementById('genome-cards').innerHTML = groups.map(g => {
      const gn = g.genome || {};
      return `<div class="stat-card" style="margin-bottom:12px">
        <b>🐤 ${htmlEsc(g.name||'')} (${htmlEsc(g.minion||'')})</b><br>
        <div style="margin-top:8px;color:#888">Style: <span style="color:#b39ddb">${htmlEsc(gn.response_style||'balanced')}</span> &nbsp; Gen: ${gn.generation||0}</div>
        <div style="margin-top:6px;color:#888">Formality (${((gn.formality||0.5)*100).toFixed(0)}%)
          <div class="genome-bar"><div class="genome-fill" style="width:${(gn.formality||0.5)*100}%"></div></div></div>
        <div style="margin-top:6px;color:#888">Tech Depth (${((gn.technical_depth||0.5)*100).toFixed(0)}%)
          <div class="genome-bar"><div class="genome-fill" style="width:${(gn.technical_depth||0.5)*100}%"></div></div></div>
        <div style="margin-top:6px;color:#888">Fitness (${((gn.fitness_score||0.5)*100).toFixed(0)}%)
          <div class="genome-bar"><div class="genome-fill" style="background:#69f0ae;width:${(gn.fitness_score||0.5)*100}%"></div></div></div>
      </div>`;
    }).join('');
  } catch(e) { console.error('poll error', e); }
}
pollStatus();
setInterval(pollStatus, 5000);

// ─── DevEngine ───────────────────────────────────────────────────────────────
let allDevSessions = [], devFilter = 'ALL';

const DEV_STATUS_COLORS = {
  pending:'#888', running:'#4fc3f7', paused:'#ffb74d',
  completed:'#69f0ae', failed:'#ef5350', cancelled:'#aaa',
};
const DEV_STAGE_LABELS = ['ANALYZE','DESIGN','IMPLEMENT','TEST','REVIEW','DOCUMENT','DEPLOY'];

function setDevFilter(f) {
  devFilter = f;
  document.querySelectorAll('#page-devengine .filter-btn').forEach(b =>
    b.classList.toggle('active', b.textContent === f || (f==='ALL' && b.textContent==='ALL'))
  );
  renderDevSessions();
}

function renderDevSessions() {
  const filtered = allDevSessions.filter(s => devFilter === 'ALL' || s.status === devFilter);
  document.getElementById('dev-tbody').innerHTML = filtered.map(s => {
    const stageIdx = DEV_STAGE_LABELS.indexOf(s.current_stage);
    const stageBar = s.current_stage
      ? `<span style="color:#b39ddb">${s.current_stage}</span> <span style="color:#555">[${stageIdx+1}/7]</span>`
      : '<span style="color:#555">—</span>';
    const age = s.updated_at ? timeSince(s.updated_at) : '?';
    const prompt = (s.prompt||'').slice(0,60) + ((s.prompt||'').length>60?'…':'');
    return `<tr>
      <td><code style="font-size:11px">${s.session_id}</code></td>
      <td><span class="badge" style="background:#1a1a2e;color:${DEV_STATUS_COLORS[s.status]||'#aaa'}">${s.status}</span></td>
      <td>${stageBar}</td>
      <td style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${htmlEsc(s.prompt||'')}">${htmlEsc(prompt)}</td>
      <td style="color:#555;white-space:nowrap">${age}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="5" style="color:#555;text-align:center">No sessions</td></tr>';
}

function timeSince(ts) {
  const secs = Math.floor(Date.now()/1000 - ts);
  if (secs < 60) return secs + 's ago';
  if (secs < 3600) return Math.floor(secs/60) + 'm ago';
  return Math.floor(secs/3600) + 'h ago';
}

async function pollDevEngine() {
  try {
    allDevSessions = await fetch('/api/dev_sessions').then(r=>r.json());
    if (document.getElementById('page-devengine').classList.contains('active')) renderDevSessions();
    // Update status stat
    const running = allDevSessions.filter(s=>s.status==='running').length;
    const el = document.getElementById('st-devsessions');
    if (el) el.textContent = allDevSessions.length + (running ? ` (${running} active)` : '');
  } catch(e) {}
}

// ─── Skills ──────────────────────────────────────────────────────────────────
async function pollSkills() {
  try {
    const skills = await fetch('/api/skills').then(r=>r.json());
    if (document.getElementById('page-skills').classList.contains('active')) renderSkills(skills);
  } catch(e) {}
}

function renderSkills(skills) {
  document.getElementById('skills-grid').innerHTML = skills.map(s => `
    <div class="stat-card">
      <div style="display:flex;justify-content:space-between;align-items:start">
        <b style="color:#b39ddb">⚡ ${htmlEsc(s.name)}</b>
        <span class="badge ${s.installed?'badge-ok':'badge-warn'}">${s.installed?'Installed':'Available'}</span>
      </div>
      <div style="color:#888;font-size:11px;margin-top:4px">v${htmlEsc(s.version||'?')} · ${htmlEsc(s.author||'')}</div>
      <div style="margin-top:8px;color:#ccc;font-size:12px">${htmlEsc(s.description||'')}</div>
      ${s.adds && s.adds.length ? `<div style="margin-top:8px;color:#555;font-size:11px">${s.adds.length} file(s) added</div>` : ''}
    </div>
  `).join('') || '<div style="color:#555">No skills found in skills/ directory</div>';
}

// Poll DevEngine + Skills every 10s
pollDevEngine();
pollSkills();
setInterval(pollDevEngine, 10000);
setInterval(pollSkills, 30000);
</script>
</body>
</html>
"""

# ─── API helpers ──────────────────────────────────────────────────────────────

def _get_status() -> dict:
    groups = db.get_all_groups()
    today_start = int(time.time()) - 86400
    conn = db._conn()
    msgs_today = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE created_at > ?", (today_start,)
    ).fetchone()[0]
    tasks_active = conn.execute(
        "SELECT COUNT(*) FROM tasks WHERE status='active'"
    ).fetchone()[0]
    kb_docs = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
    return {
        "groups": len(groups),
        "messages_today": msgs_today,
        "tasks_active": tasks_active,
        "kb_docs": kb_docs,
        "uptime": int(time.time() - _start_time),
    }


def _get_groups() -> list[dict]:
    groups = db.get_all_groups()
    # Single batch query replaces N individual get_genome() calls (Issue #97).
    genomes = db.get_all_genomes()
    return [{**g, "genome": genomes.get(g["jid"], {
        "group_jid":       g["jid"],
        "response_style":  "balanced",
        "formality":       0.5,
        "technical_depth": 0.5,
        "fitness_score":   0.5,
    })} for g in groups]


def _get_dev_sessions() -> list[dict]:
    """Return recent DevEngine sessions across all groups."""
    try:
        conn = db._conn()
        rows = conn.execute(
            "SELECT session_id, group_jid, status, current_stage, prompt, created_at, updated_at "
            "FROM dev_sessions ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _get_skills(limit: int = 50) -> list[dict]:
    """Return available skills from the skills/ directory."""
    try:
        from .skills_engine import list_available_skills
        skills = list_available_skills()
        return skills[:limit]
    except Exception:
        return []


def _get_health() -> dict:
    """Health check: verify DB connectivity and return system health status."""
    health: dict = {"status": "ok", "checks": {}}

    # DB connectivity check
    try:
        conn = db._conn()
        result = conn.execute("SELECT 1").fetchone()
        health["checks"]["db"] = "ok" if result else "fail"
    except Exception as exc:
        health["checks"]["db"] = f"error: {exc}"
        health["status"] = "degraded"

    health["uptime"] = int(time.time() - _start_time)
    return health


# ─── HTTP handler ─────────────────────────────────────────────────────────────

def _check_auth(handler: "BaseHTTPRequestHandler") -> bool:
    """Return True if the request is authenticated (or auth is disabled)."""
    password = config.DASHBOARD_PASSWORD
    # Auth disabled when password is empty string
    if not password:
        return True
    auth_header = handler.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8", errors="replace")
        # Accept either ":<password>" or "admin:<password>"
        _, _, provided = decoded.partition(":")
        return provided == password
    except Exception:
        return False


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Suppress access logs

    def _require_auth(self) -> bool:
        """Send 401 if not authenticated. Returns True if auth passed."""
        if _check_auth(self):
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="MinionDesk Dashboard"')
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", "13")
        self.end_headers()
        self.wfile.write(b"Unauthorized\n")
        return False

    def do_GET(self):
        if not self._require_auth():
            return
        path = self.path.split("?")[0]

        if path == "/":
            self._html(_HTML)
        elif path == "/api/status":
            self._json(_get_status())
        elif path == "/api/groups":
            self._json(_get_groups())
        elif path == "/api/logs":
            with _log_lock:
                self._json(list(_log_buffer[-100:]))
        elif path == "/api/logs/stream":
            self._sse_stream()
        elif path == "/api/dev_sessions":
            self._json(_get_dev_sessions())
        elif path == "/api/skills":
            self._json(_get_skills())
        elif path == "/api/health":
            self._json(_get_health())
        else:
            self.send_error(404)

    def _html(self, content: str):
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj):
        data = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _sse_stream(self):
        # Enforce max concurrent SSE clients BEFORE writing any response headers.
        # Checking after send_response(200) would result in 503 body on a 200
        # connection — browsers would silently retry instead of backing off.
        with _log_lock:
            if len(_sse_subscribers) >= _MAX_SSE_CLIENTS:
                self.send_response(503)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", "29")
                self.end_headers()
                self.wfile.write(b"Too many SSE clients (limit 20)")
                return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        # Each SSE client gets its own dedicated queue (fan-out model).
        # This ensures all connected clients receive all log entries,
        # not just one client per entry (the old shared-queue bug).
        client_q: queue.Queue = queue.Queue(maxsize=200)
        with _log_lock:
            # Send recent history so the new client sees existing logs
            for entry in list(_log_buffer)[-50:]:
                try:
                    client_q.put_nowait(entry)
                except queue.Full:
                    break
            _sse_subscribers.append(client_q)

        try:
            while True:
                try:
                    entry = client_q.get(timeout=15)
                    data = json.dumps(entry, ensure_ascii=False)
                    self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    # Keep-alive ping
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            # Always remove the client queue on disconnect (prevents leak)
            with _log_lock:
                try:
                    _sse_subscribers.remove(client_q)
                except ValueError:
                    pass


# ─── Dashboard server ─────────────────────────────────────────────────────────

def _run_server(host: str, port: int) -> None:
    server = HTTPServer((host, port), _Handler)
    logger.info("Dashboard running at http://%s:%d", host, port)
    server.serve_forever()


async def run_dashboard() -> None:
    """Start dashboard in a background thread (non-blocking for asyncio)."""
    install_log_handler()
    host = config.DASHBOARD_HOST
    port = config.DASHBOARD_PORT

    # Warn if default dashboard password is unchanged
    if config.DASHBOARD_PASSWORD == "changeme":
        logger.warning(
            "SECURITY: DASHBOARD_PASSWORD is set to the default 'changeme'. "
            "The dashboard has no authentication — set DASHBOARD_PASSWORD and firewall port %d.",
            port,
        )
    t = threading.Thread(
        target=_run_server,
        args=(host, port),
        daemon=True,
        name="dashboard",
    )
    t.start()
    logger.info("Dashboard thread started: http://%s:%d", host, port)
    # Keep coroutine alive (thread is daemon)
    while t.is_alive():
        await asyncio.sleep(5)
