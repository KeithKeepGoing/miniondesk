"""
Enterprise Integrations for MinionDesk IC Design Edition.
Covers: Jira, ServiceNow, Git/GitLab - ticket management, weekly reports.
"""
from __future__ import annotations
import os
import json
import urllib.request
import urllib.parse
import urllib.error
import base64
import datetime
from typing import Optional
from . import Tool, ToolContext

# Config injected from environment
JIRA_URL = os.getenv("JIRA_URL", "")                    # https://corp.atlassian.net
JIRA_USER = os.getenv("JIRA_USER", "")                  # user@corp.com
JIRA_TOKEN = os.getenv("JIRA_TOKEN", "")                # Jira API token
JIRA_PROJECT = os.getenv("JIRA_DEFAULT_PROJECT", "IT")  # default project key

SERVICENOW_URL = os.getenv("SERVICENOW_URL", "")        # https://corp.service-now.com
SERVICENOW_USER = os.getenv("SERVICENOW_USER", "")
SERVICENOW_PASSWORD = os.getenv("SERVICENOW_PASSWORD", "")

GITLAB_URL = os.getenv("GITLAB_URL", "https://gitlab.com")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", "")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


def _http_get(url: str, headers: dict) -> Optional[dict]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}


def _http_post(url: str, headers: dict, data: dict) -> Optional[dict]:
    body = json.dumps(data).encode()
    headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"error": f"HTTP {e.code}: {e.reason}", "detail": body[:500]}
    except Exception as e:
        return {"error": str(e)}


# ─── Jira Tools ───────────────────────────────────────────────────────────────

def _jira_headers() -> dict:
    creds = base64.b64encode(f"{JIRA_USER}:{JIRA_TOKEN}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Accept": "application/json"}


def _create_jira_ticket(args: dict, ctx: ToolContext) -> str:
    """Create a Jira issue/ticket."""
    if not (JIRA_URL and JIRA_USER and JIRA_TOKEN):
        return "❌ Jira 未設定。請設定 JIRA_URL, JIRA_USER, JIRA_TOKEN 環境變數。"

    summary = args.get("summary", "")
    description = args.get("description", "")
    issue_type = args.get("issue_type", "Task")
    project = args.get("project", JIRA_PROJECT)
    priority = args.get("priority", "Medium")
    assignee = args.get("assignee", "")
    labels = args.get("labels", [])

    if not summary:
        return "❌ 請提供 summary（標題）"

    payload = {
        "fields": {
            "project": {"key": project},
            "summary": summary,
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}]
            } if description else None,
            "issuetype": {"name": issue_type},
            "priority": {"name": priority},
        }
    }
    if not description:
        del payload["fields"]["description"]

    if assignee:
        payload["fields"]["assignee"] = {"name": assignee}
    if labels:
        payload["fields"]["labels"] = labels if isinstance(labels, list) else [labels]

    url = f"{JIRA_URL}/rest/api/3/issue"
    result = _http_post(url, _jira_headers(), payload)

    if not result or "error" in result:
        return f"❌ Jira 開單失敗：{result.get('error', '未知錯誤')}\n{result.get('detail', '')}"

    issue_key = result.get("key", "")
    issue_url = f"{JIRA_URL}/browse/{issue_key}"
    return f"✅ Jira 單據已建立！\n🎫 {issue_key}：{summary}\n🔗 {issue_url}"


def _get_jira_ticket(args: dict, ctx: ToolContext) -> str:
    """Get Jira ticket details and status."""
    if not (JIRA_URL and JIRA_USER and JIRA_TOKEN):
        return "❌ Jira 未設定"

    ticket_id = args.get("ticket_id", "")
    if not ticket_id:
        return "❌ 請提供 ticket_id（例：IT-1234）"

    url = f"{JIRA_URL}/rest/api/3/issue/{ticket_id}"
    result = _http_get(url, _jira_headers())

    if not result or "error" in result:
        return f"❌ 找不到 {ticket_id}：{result.get('error', '')}"

    fields = result.get("fields", {})
    status = fields.get("status", {}).get("name", "Unknown")
    assignee = fields.get("assignee") or {}
    assignee_name = assignee.get("displayName", "未指派")
    priority = fields.get("priority", {}).get("name", "Medium")
    created = fields.get("created", "")[:10]
    updated = fields.get("updated", "")[:10]
    summary = fields.get("summary", "")

    status_icons = {"To Do": "📋", "In Progress": "🔄", "Done": "✅", "Closed": "✅", "Blocked": "🚫"}
    icon = status_icons.get(status, "❓")

    return (
        f"{icon} *{ticket_id}*：{summary}\n\n"
        f"• 狀態：{status}\n"
        f"• 優先級：{priority}\n"
        f"• 指派給：{assignee_name}\n"
        f"• 建立：{created}\n"
        f"• 更新：{updated}\n"
        f"• 連結：{JIRA_URL}/browse/{ticket_id}"
    )


def _search_jira_tickets(args: dict, ctx: ToolContext) -> str:
    """Search Jira tickets with JQL."""
    if not (JIRA_URL and JIRA_USER and JIRA_TOKEN):
        return "❌ Jira 未設定"

    jql = args.get("jql", "")
    assignee = args.get("assignee", "")
    status = args.get("status", "")
    project = args.get("project", JIRA_PROJECT)

    if not jql:
        parts = []
        if project:
            parts.append(f"project = {project}")
        if assignee:
            parts.append(f"assignee = '{assignee}'")
        if status:
            parts.append(f"status = '{status}'")
        parts.append("ORDER BY updated DESC")
        jql = " AND ".join(parts)

    encoded_jql = urllib.parse.quote(jql)
    url = f"{JIRA_URL}/rest/api/3/search?jql={encoded_jql}&maxResults=10&fields=summary,status,assignee,priority"
    result = _http_get(url, _jira_headers())

    if not result or "error" in result:
        return f"❌ Jira 搜尋失敗：{result.get('error', '')}"

    issues = result.get("issues", [])
    total = result.get("total", 0)

    if not issues:
        return f"🔍 找不到符合的 Jira 單據（JQL: {jql}）"

    lines = [f"🔍 Jira 搜尋結果（共 {total} 筆，顯示前 10）：\n"]
    for issue in issues:
        key = issue.get("key", "")
        fields = issue.get("fields", {})
        summary = fields.get("summary", "")[:60]
        status_name = fields.get("status", {}).get("name", "")
        status_icons = {"To Do": "📋", "In Progress": "🔄", "Done": "✅", "Closed": "✅"}
        icon = status_icons.get(status_name, "❓")
        lines.append(f"{icon} *{key}* — {summary} [{status_name}]")

    return "\n".join(lines)


# ─── ServiceNow Tools ─────────────────────────────────────────────────────────

def _snow_headers() -> dict:
    creds = base64.b64encode(f"{SERVICENOW_USER}:{SERVICENOW_PASSWORD}".encode()).decode()
    return {
        "Authorization": f"Basic {creds}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _create_snow_ticket(args: dict, ctx: ToolContext) -> str:
    """Create a ServiceNow incident or request."""
    if not (SERVICENOW_URL and SERVICENOW_USER and SERVICENOW_PASSWORD):
        return "❌ ServiceNow 未設定。請設定 SERVICENOW_URL, SERVICENOW_USER, SERVICENOW_PASSWORD。"

    short_desc = args.get("short_description", "")
    description = args.get("description", "")
    category = args.get("category", "IT")
    urgency = args.get("urgency", "3")  # 1=High, 2=Med, 3=Low
    ticket_type = args.get("type", "incident")  # incident or sc_request

    if not short_desc:
        return "❌ 請提供 short_description（問題摘要）"

    table = "incident" if ticket_type == "incident" else "sc_request"
    payload = {
        "short_description": short_desc,
        "description": description,
        "category": category,
        "urgency": urgency,
        "caller_id": SERVICENOW_USER,
    }

    url = f"{SERVICENOW_URL}/api/now/table/{table}"
    result = _http_post(url, _snow_headers(), payload)

    if not result or "error" in result:
        return f"❌ ServiceNow 開單失敗：{result.get('error', '未知錯誤')}"

    record = result.get("result", {})
    number = record.get("number", "")
    sys_id = record.get("sys_id", "")
    ticket_url = f"{SERVICENOW_URL}/nav_to.do?uri=/{table}.do?sys_id={sys_id}"

    return f"✅ ServiceNow 單據已建立！\n🎫 {number}：{short_desc}\n🔗 {ticket_url}"


def _get_snow_ticket(args: dict, ctx: ToolContext) -> str:
    """Get ServiceNow ticket status."""
    if not (SERVICENOW_URL and SERVICENOW_USER and SERVICENOW_PASSWORD):
        return "❌ ServiceNow 未設定"

    ticket_num = args.get("ticket_number", "")
    if not ticket_num:
        return "❌ 請提供 ticket_number（例：INC0001234）"

    table = "incident" if ticket_num.startswith("INC") else "sc_request"
    encoded = urllib.parse.quote(f"number={ticket_num}")
    url = f"{SERVICENOW_URL}/api/now/table/{table}?sysparm_query={encoded}&sysparm_limit=1"
    result = _http_get(url, _snow_headers())

    if not result or "error" in result:
        return f"❌ 查詢失敗：{result.get('error', '')}"

    records = result.get("result", [])
    if not records:
        return f"❌ 找不到單據 {ticket_num}"

    r = records[0]
    state_map = {"1": "🆕 新建", "2": "🔄 進行中", "3": "✅ 已解決", "6": "✅ 已結案", "7": "🚫 已取消"}
    state = state_map.get(r.get("state", ""), r.get("state", "未知"))

    return (
        f"📋 *{ticket_num}*：{r.get('short_description', '')}\n\n"
        f"• 狀態：{state}\n"
        f"• 類別：{r.get('category', '')}\n"
        f"• 優先級：{r.get('priority', '')}\n"
        f"• 指派給：{r.get('assigned_to', {}).get('display_value', '未指派') if isinstance(r.get('assigned_to'), dict) else r.get('assigned_to', '未指派')}\n"
        f"• 建立：{r.get('sys_created_on', '')[:10]}"
    )


# ─── Git/GitLab Tools ─────────────────────────────────────────────────────────

def _get_gitlab_commits(args: dict, ctx: ToolContext) -> str:
    """Fetch recent GitLab commits for a user/project."""
    if not GITLAB_TOKEN:
        return "❌ GitLab 未設定。請設定 GITLAB_TOKEN。"

    project_id = args.get("project_id", "")
    username = args.get("username", "")
    days = int(args.get("days", 7))

    if not project_id:
        return "❌ 請提供 project_id（GitLab 專案 ID 或 namespace/project）"

    since = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    encoded_project = urllib.parse.quote(str(project_id), safe="")
    url = f"{GITLAB_URL}/api/v4/projects/{encoded_project}/commits?since={since}&per_page=50"
    if username:
        url += f"&author={urllib.parse.quote(username)}"

    headers = {"PRIVATE-TOKEN": GITLAB_TOKEN, "Accept": "application/json"}
    result = _http_get(url, headers)

    if isinstance(result, dict) and "error" in result:
        return f"❌ GitLab 查詢失敗：{result['error']}"

    if not result:
        return f"✅ 最近 {days} 天沒有 commits。"

    commits = result if isinstance(result, list) else []
    lines = [f"📝 最近 {days} 天的 commits（{project_id}）：\n"]
    for c in commits[:20]:
        date = c.get("committed_date", "")[:10]
        author = c.get("author_name", "")
        message = c.get("message", "").split("\n")[0][:80]
        sha = c.get("short_id", "")
        lines.append(f"• `{sha}` [{date}] {author}: {message}")

    if len(commits) > 20:
        lines.append(f"... 共 {len(commits)} 筆")

    return "\n".join(lines)


def _generate_weekly_report(args: dict, ctx: ToolContext) -> str:
    """Generate a weekly work report by combining GitLab commits and Jira tickets."""
    username = args.get("username", "")
    project_id = args.get("gitlab_project_id", "")
    jira_assignee = args.get("jira_assignee", username)
    week_end = args.get("week_end", datetime.date.today().strftime("%Y-%m-%d"))

    report_lines = [
        f"# 每週工作日誌",
        f"**員工：** {username or '(未指定)'}",
        f"**週別：** {week_end} 當週",
        f"**生成時間：** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
    ]

    # Get commits
    if project_id and GITLAB_TOKEN:
        commits_text = _get_gitlab_commits({"project_id": project_id, "username": username, "days": 7}, ctx)
        report_lines.append("## 程式提交記錄 (Commits)")
        report_lines.append(commits_text)
        report_lines.append("")

    # Get Jira tickets
    if JIRA_URL and jira_assignee:
        tickets_text = _search_jira_tickets({
            "jql": f"assignee = '{jira_assignee}' AND updated >= -7d ORDER BY updated DESC"
        }, ctx)
        report_lines.append("## 工單處理記錄 (Jira)")
        report_lines.append(tickets_text)
        report_lines.append("")

    report_lines.extend([
        "## 本週工作摘要",
        "*(請根據上方記錄填寫或由 AI 自動整理)*",
        "",
        "## 下週計畫",
        "*(待填寫)*",
        "",
        "## 需要協助",
        "*(如有阻礙或需跨部門協作，請在此說明)*",
    ])

    return "\n".join(report_lines)


def _analyze_log(args: dict, ctx: ToolContext) -> str:
    """
    Analyze error logs intelligently.
    Extracts error lines, identifies patterns, and suggests fixes.
    """
    log_content = args.get("log", "")
    log_type = args.get("type", "auto")  # auto, kernel, eda, database, application

    if not log_content:
        return "❌ 請提供 log 內容（log 參數）"

    lines = log_content.split("\n")

    # Extract error lines
    error_keywords = ["error", "fatal", "panic", "exception", "failed", "critical",
                      "ERROR", "FATAL", "PANIC", "Exception", "FAILED", "CRITICAL",
                      "Segmentation fault", "OOM", "out of memory", "killed"]

    error_lines = []
    for i, line in enumerate(lines):
        if any(kw in line for kw in error_keywords):
            # Include context lines
            start = max(0, i - 1)
            end = min(len(lines), i + 2)
            error_lines.extend(lines[start:end])
            error_lines.append("---")

    if not error_lines:
        return "✅ 未在日誌中發現明顯錯誤關鍵字。日誌看起來正常。"

    # Common error pattern recognition
    suggestions = []
    log_text = "\n".join(error_lines)

    patterns = [
        ("OOM killer", "Out of Memory", "記憶體不足被系統強制終止。建議：增加記憶體、降低並行 Job 數量、設定 ulimit。"),
        ("Segmentation fault", "Segfault", "程式記憶體存取錯誤。建議：用 gdb 或 valgrind 找出問題點。"),
        ("certificate", "SSL/TLS 憑證", "憑證相關錯誤。建議：確認憑證是否過期，執行 openssl x509 -in cert.pem -noout -dates 檢查。"),
        ("disk quota exceeded", "磁碟配額", "儲存空間配額已滿。建議：清理暫存檔或申請 Quota 擴充。"),
        ("Connection refused", "連線被拒", "服務未啟動或防火牆阻擋。建議：確認服務狀態 (systemctl status) 與防火牆規則。"),
        ("Permission denied", "權限不足", "檔案或目錄權限問題。建議：確認 Unix 權限設定 (ls -la)。"),
        ("license", "EDA 授權", "授權不足或伺服器無回應。建議：使用 lmstat 確認授權數量，或聯絡 IT。"),
    ]

    for keyword, label, suggestion in patterns:
        if keyword.lower() in log_text.lower():
            suggestions.append(f"• *{label}*：{suggestion}")

    result = [
        f"🔍 日誌分析結果（共 {len(lines)} 行，找到 {len([l for l in error_lines if l != '---'])} 行異常）：\n",
        "**錯誤行摘取：**",
        f"```\n{chr(10).join(error_lines[:30])}\n```",
    ]

    if suggestions:
        result.append("\n**可能原因與建議：**")
        result.extend(suggestions)

    return "\n".join(result)


# ─── Tool Registry ────────────────────────────────────────────────────────────

def get_integration_tools() -> list[Tool]:
    return [
        Tool(
            name="create_jira_ticket",
            description="在 Jira 建立新工單（Issue）。適用於 IT 報修、功能請求、Bug 回報等。",
            schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "工單標題（必填）"},
                    "description": {"type": "string", "description": "詳細說明"},
                    "issue_type": {"type": "string", "description": "類型：Task, Bug, Story, Incident（預設 Task）"},
                    "project": {"type": "string", "description": "Jira 專案 Key（預設使用 JIRA_DEFAULT_PROJECT）"},
                    "priority": {"type": "string", "description": "優先級：Highest, High, Medium, Low（預設 Medium）"},
                    "assignee": {"type": "string", "description": "指派給（Jira 用戶名）"},
                    "labels": {"type": "array", "items": {"type": "string"}, "description": "標籤清單"},
                },
                "required": ["summary"],
            },
            execute=_create_jira_ticket,
        ),
        Tool(
            name="get_jira_ticket",
            description="查詢 Jira 工單狀態與詳情",
            schema={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string", "description": "Jira 工單 ID，例如 IT-1234"},
                },
                "required": ["ticket_id"],
            },
            execute=_get_jira_ticket,
        ),
        Tool(
            name="search_jira_tickets",
            description="搜尋 Jira 工單（支援 JQL 查詢）",
            schema={
                "type": "object",
                "properties": {
                    "jql": {"type": "string", "description": "JQL 查詢語句（可選，留空則用其他篩選條件）"},
                    "assignee": {"type": "string", "description": "指派給誰"},
                    "status": {"type": "string", "description": "狀態篩選"},
                    "project": {"type": "string", "description": "專案 Key"},
                },
            },
            execute=_search_jira_tickets,
        ),
        Tool(
            name="create_snow_ticket",
            description="在 ServiceNow 建立 Incident 或 Request",
            schema={
                "type": "object",
                "properties": {
                    "short_description": {"type": "string", "description": "問題摘要（必填）"},
                    "description": {"type": "string", "description": "詳細描述"},
                    "category": {"type": "string", "description": "類別（例：IT, Network, Application）"},
                    "urgency": {"type": "string", "description": "緊急程度：1=High, 2=Medium, 3=Low"},
                    "type": {"type": "string", "description": "類型：incident 或 sc_request"},
                },
                "required": ["short_description"],
            },
            execute=_create_snow_ticket,
        ),
        Tool(
            name="get_snow_ticket",
            description="查詢 ServiceNow 單據狀態",
            schema={
                "type": "object",
                "properties": {
                    "ticket_number": {"type": "string", "description": "單據編號，例如 INC0001234"},
                },
                "required": ["ticket_number"],
            },
            execute=_get_snow_ticket,
        ),
        Tool(
            name="get_gitlab_commits",
            description="查詢 GitLab 專案近期的 commit 記錄",
            schema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "GitLab 專案 ID 或 namespace/project"},
                    "username": {"type": "string", "description": "篩選特定作者（可選）"},
                    "days": {"type": "integer", "description": "查詢最近幾天（預設 7）"},
                },
                "required": ["project_id"],
            },
            execute=_get_gitlab_commits,
        ),
        Tool(
            name="generate_weekly_report",
            description="自動生成每週工作日誌，整合 GitLab commits 和 Jira 工單記錄",
            schema={
                "type": "object",
                "properties": {
                    "username": {"type": "string", "description": "員工帳號"},
                    "gitlab_project_id": {"type": "string", "description": "GitLab 專案 ID"},
                    "jira_assignee": {"type": "string", "description": "Jira 指派帳號（留空同 username）"},
                    "week_end": {"type": "string", "description": "週結束日期 YYYY-MM-DD（預設今天）"},
                },
            },
            execute=_generate_weekly_report,
        ),
        Tool(
            name="analyze_log",
            description="智能分析錯誤日誌。支援 Linux kernel、EDA 工具、資料庫、應用程式日誌。自動提取錯誤行並給出修復建議。",
            schema={
                "type": "object",
                "properties": {
                    "log": {"type": "string", "description": "日誌內容（直接貼上）"},
                    "type": {"type": "string", "description": "日誌類型：auto, kernel, eda, database, application（預設 auto）"},
                },
                "required": ["log"],
            },
            execute=_analyze_log,
        ),
    ]
