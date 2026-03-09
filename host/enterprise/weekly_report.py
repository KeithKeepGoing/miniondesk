"""
Automated Weekly Report Generator for MinionDesk.
Runs every Friday afternoon, generates and sends weekly reports to employees.
"""
from __future__ import annotations
import asyncio
import inspect
import os
import logging
import re as _re
import urllib.request
import urllib.parse
import base64
import json
from datetime import datetime, date, timedelta, timezone
from typing import Callable, Optional

log = logging.getLogger(__name__)

import zoneinfo


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        log.warning("Invalid value for %s, using default %d", name, default)
        return default


_day_raw = _env_int("WEEKLY_REPORT_DAY", 4)
_hour_raw = _env_int("WEEKLY_REPORT_HOUR", 17)

WEEKLY_REPORT_ENABLED = os.getenv("WEEKLY_REPORT_ENABLED", "false").lower() == "true"

if not (0 <= _day_raw <= 6):
    log.error("WEEKLY_REPORT_DAY must be 0-6 (got %d); disabling weekly report", _day_raw)
    WEEKLY_REPORT_ENABLED = False
    WEEKLY_REPORT_DAY = 4
else:
    WEEKLY_REPORT_DAY = _day_raw

if not (0 <= _hour_raw <= 23):
    log.error("WEEKLY_REPORT_HOUR must be 0-23 (got %d); disabling weekly report", _hour_raw)
    WEEKLY_REPORT_ENABLED = False
    WEEKLY_REPORT_HOUR = 17
else:
    WEEKLY_REPORT_HOUR = _hour_raw

WEEKLY_REPORT_JIRA_PROJECT = os.getenv("WEEKLY_REPORT_JIRA_PROJECT", "")
WEEKLY_REPORT_GITLAB_PROJECT = os.getenv("WEEKLY_REPORT_GITLAB_PROJECT", "")
WEEKLY_REPORT_TZ = os.getenv("WEEKLY_REPORT_TZ", "UTC")

import zoneinfo as _zoneinfo
try:
    _zoneinfo.ZoneInfo(WEEKLY_REPORT_TZ)
except Exception:
    log.error("Invalid WEEKLY_REPORT_TZ %r, falling back to UTC", WEEKLY_REPORT_TZ)
    WEEKLY_REPORT_TZ = "UTC"

_send_callback: Optional[Callable] = None


def set_send_callback(cb: Callable) -> None:
    global _send_callback
    _send_callback = cb


async def generate_report_for_employee(jid: str, name: str) -> str:
    """Generate weekly report for a single employee."""
    tz = zoneinfo.ZoneInfo(WEEKLY_REPORT_TZ)
    today = datetime.now(tz=tz).date()
    week_start = today - timedelta(days=today.weekday())
    week_end = today

    lines = [
        f"📊 *{name} 本週工作摘要*",
        f"週期：{week_start} ~ {week_end}",
        "",
    ]

    # Try Jira
    if WEEKLY_REPORT_JIRA_PROJECT:
        if not _re.match(r'^[\w\-]+$', WEEKLY_REPORT_JIRA_PROJECT):
            log.error(f"Invalid WEEKLY_REPORT_JIRA_PROJECT: {WEEKLY_REPORT_JIRA_PROJECT!r}, skipping Jira")
            jira_items = []
        else:
            if not _re.match(r'^[\w.@\-]+$', jid):
                log.warning(f"Skipping Jira query for suspicious jid format")
            else:
                try:
                    jira_url = os.getenv("JIRA_URL", "")
                    jira_user = os.getenv("JIRA_USER", "")
                    jira_token = os.getenv("JIRA_TOKEN", "")
                    if jira_url and jira_user and jira_token and jira_url.startswith("https://"):
                        creds = base64.b64encode(f"{jira_user}:{jira_token}".encode()).decode()
                        jql = f"project={WEEKLY_REPORT_JIRA_PROJECT} AND assignee='{jid}' AND updated>=-7d"
                        encoded = urllib.parse.quote(jql)
                        url = f"{jira_url}/rest/api/3/search?jql={encoded}&maxResults=10&fields=summary,status"
                        req = urllib.request.Request(url, headers={
                            "Authorization": f"Basic {creds}", "Accept": "application/json"
                        })
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            data = json.loads(resp.read())
                        issues = data.get("issues", [])
                        if issues:
                            lines.append("*🎫 Jira 工單：*")
                            for issue in issues:
                                key = issue["key"]
                                summary = issue["fields"]["summary"][:60]
                                status = issue["fields"]["status"]["name"]
                                lines.append(f"• {key} [{status}] {summary}")
                            lines.append("")
                except Exception as e:
                    log.warning(f"Weekly report Jira fetch error: {type(e).__name__}")
                    log.debug(f"Jira detail: {e}")

    # Try GitLab
    if WEEKLY_REPORT_GITLAB_PROJECT:
        try:
            gitlab_url = os.getenv("GITLAB_URL", "https://gitlab.com")
            if not gitlab_url.startswith("https://"):
                log.error("GITLAB_URL must use https://; skipping GitLab fetch to protect token")
                gitlab_token = ""
            else:
                gitlab_token = os.getenv("GITLAB_TOKEN", "")
            if gitlab_token:
                since = (datetime.now(tz=timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
                encoded_proj = urllib.parse.quote(WEEKLY_REPORT_GITLAB_PROJECT, safe="")
                url = f"{gitlab_url}/api/v4/projects/{encoded_proj}/commits?since={since}&per_page=20"
                req = urllib.request.Request(url, headers={"PRIVATE-TOKEN": gitlab_token})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    commits = json.loads(resp.read())
                jid_lower = jid.lower()
                user_commits = [
                    c for c in commits
                    if jid_lower == c.get("author_email", "").lower()
                    or jid_lower == c.get("author_name", "").lower()
                ]
                if user_commits:
                    lines.append("*📝 Git Commits：*")
                    for c in user_commits[:10]:
                        msg = c.get("message", "").split("\n")[0][:70]
                        sha = c.get("short_id", "")
                        lines.append(f"• `{sha}` {msg}")
                    lines.append("")
        except Exception as e:
            log.warning(f"Weekly report GitLab fetch error: {type(e).__name__}")
            log.debug(f"GitLab detail: {e}")

    lines.extend([
        "*📋 本週重點工作：*",
        "（以上資料自動整理，如有遺漏請補充）",
        "",
        "*🎯 下週計畫：*",
        "請回覆此訊息填寫下週計畫，系統將自動彙整。",
    ])

    return "\n".join(lines)


async def run_weekly_reports() -> None:
    """Send weekly reports to all employees."""
    if not _send_callback:
        log.warning("Weekly report: no send callback set")
        return

    try:
        from host import db
        conn = db.get_conn()
        try:
            employees = conn.execute(
                "SELECT jid, name FROM employees WHERE role != 'admin'"
            ).fetchall()
        finally:
            pass  # Do NOT close — DB connection is a global singleton

        log.info(f"Generating weekly reports for {len(employees)} employees")

        for jid, name in employees:
            if not _re.fullmatch(r'^[\w.@\-]+$', jid):
                log.warning("Skipping employee with invalid jid: %r", jid)
                continue
            try:
                report = await generate_report_for_employee(jid, name)
                result = _send_callback(jid, report)
                if inspect.isawaitable(result):
                    await result
                await asyncio.sleep(1)  # Rate limit
            except Exception as e:
                log.error("Weekly report error for employee: %s", type(e).__name__)
                log.debug("Weekly report error detail for %s: %s", jid, e)

    except Exception as e:
        log.error("Weekly report run error: %s", type(e).__name__)
        log.debug("Weekly report run detail: %s", e)


async def weekly_report_loop() -> None:
    """Background loop that triggers weekly reports on schedule."""
    if not WEEKLY_REPORT_ENABLED:
        log.info("Weekly report disabled due to invalid configuration")
        return

    log.info(f"Weekly report scheduler active: every weekday={WEEKLY_REPORT_DAY} at {WEEKLY_REPORT_HOUR}:00")

    last_report_date: Optional[date] = None
    while True:
        tz = zoneinfo.ZoneInfo(WEEKLY_REPORT_TZ)
        now = datetime.now(tz=tz)
        today = now.date()
        if (now.weekday() == WEEKLY_REPORT_DAY and
                now.hour == WEEKLY_REPORT_HOUR and
                now.minute < 5 and
                last_report_date != today):
            last_report_date = today
            log.info("Weekly report time! Generating reports...")
            await run_weekly_reports()
        await asyncio.sleep(30)
