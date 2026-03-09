"""
Enterprise tools: KB search, workflow, calendar, department routing.
These tools call the host via IPC file-based protocol.
"""
from __future__ import annotations
import json
import os
import sqlite3
import uuid
from datetime import datetime
from . import Tool, ToolContext


def _get_db(ctx: ToolContext) -> sqlite3.Connection:
    db_path = os.path.join(ctx.data_dir, "miniondesk.db")
    return sqlite3.connect(db_path)


def _search_knowledge_base(args: dict, ctx: ToolContext) -> str:
    query = args.get("query", "")
    limit = args.get("limit", 5)

    try:
        conn = _get_db(ctx)
        try:
            cursor = conn.cursor()

            results = []
            # FTS5 trigram for >=3 char queries
            if len(query) >= 3:
                try:
                    cursor.execute(
                        "SELECT title, content, source FROM kb_chunks WHERE kb_chunks MATCH ? LIMIT ?",
                        (query, limit),
                    )
                    results = cursor.fetchall()
                except Exception:
                    pass

            # LIKE fallback for short queries or FTS miss
            if not results:
                cursor.execute(
                    "SELECT title, content, source FROM kb_chunks_plain WHERE content LIKE ? LIMIT ?",
                    (f"%{query}%", limit),
                )
                results = cursor.fetchall()

            if not results:
                return f"No results found for: {query}"

            parts = []
            for title, content, source in results:
                parts.append(f"**{title}** (來源: {source})\n{content[:300]}")
            return "\n\n---\n\n".join(parts)
        finally:
            conn.close()

    except Exception as e:
        return f"Knowledge base error: {e}"


def _start_workflow(args: dict, ctx: ToolContext) -> str:
    workflow_type = args.get("workflow_type", "")
    data = args.get("data", {})

    # Sanity: cap data payload size
    import json as _json
    if len(_json.dumps(data)) > 10_000:
        return "❌ 申請資料過大，請簡化後重試。"

    # RBAC: verify sender has at least 'employee' role
    if ctx.sender_jid:
        try:
            conn = _get_db(ctx)
            row = conn.execute(
                "SELECT role FROM employees WHERE jid = ?",
                (ctx.sender_jid,),
            ).fetchone()
            conn.close()
            if row is None:
                return (
                    "⛔ 您尚未在系統中登記為員工，無法提交申請。"
                    "請聯繫管理員將您加入系統：python run.py admin add-employee"
                )
            # All registered employees can submit workflows
            # (managers/admins can approve via the approval workflow)
        except Exception as e:
            import logging as _logging
            _logging.getLogger(__name__).error(f"RBAC check failed due to exception: {e}")
            return "❌ 無法驗證您的權限（資料庫暫時無法連線），請稍後再試。"

    try:
        conn = _get_db(ctx)
        try:
            wf_id = str(uuid.uuid4())[:8]
            conn.execute(
                """INSERT INTO workflow_instances
                   (id, workflow_type, submitter_jid, data_json, status, created_at)
                   VALUES (?, ?, ?, ?, 'submitted', ?)""",
                (wf_id, workflow_type, ctx.sender_jid, json.dumps(data), datetime.utcnow().isoformat()),
            )
            conn.commit()
            return f"✅ 申請已送出：{workflow_type} (ID: {wf_id})。請等候主管審批，審批結果將通知您。"
        finally:
            conn.close()
    except Exception as e:
        return f"Workflow error: {e}"


def _check_workflow_status(args: dict, ctx: ToolContext) -> str:
    workflow_id = args.get("workflow_id", "")
    try:
        conn = _get_db(ctx)
        try:
            row = conn.execute(
                "SELECT workflow_type, status, created_at, approved_by FROM workflow_instances WHERE id = ?",
                (workflow_id,),
            ).fetchone()
            if not row:
                return f"Workflow {workflow_id} not found."
            wtype, status, created_at, approved_by = row
            result = f"Workflow {workflow_id}: {wtype}\nStatus: {status}\nSubmitted: {created_at}"
            if approved_by:
                result += f"\nApproved by: {approved_by}"
            return result
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {e}"


def _route_to_department(args: dict, ctx: ToolContext) -> str:
    """Write a routing IPC message for the host to handle."""
    dept = args.get("department", "")
    message = args.get("message", "")

    route_msg = {
        "id": str(uuid.uuid4()),
        "type": "route_to_dept",
        "from_chat_jid": ctx.chat_jid,
        "department": dept,
        "message": message,
        "timestamp": datetime.utcnow().isoformat(),
    }
    ipc_path = os.path.join(ctx.ipc_dir, "routes")
    os.makedirs(ipc_path, exist_ok=True)
    with open(os.path.join(ipc_path, f"{route_msg['id']}.json"), "w") as f:
        json.dump(route_msg, f)
    return f"Routed to {dept} department."


def _create_meeting(args: dict, ctx: ToolContext) -> str:
    title = args.get("title", "")
    start_time = args.get("start_time", "")
    end_time = args.get("end_time", "")
    attendees = args.get("attendees", [])
    location = args.get("location", "")

    try:
        conn = _get_db(ctx)
        try:
            meeting_id = str(uuid.uuid4())[:8]
            conn.execute(
                """INSERT INTO meetings (id, title, start_time, end_time, attendees_json, location, organizer_jid, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    meeting_id, title, start_time, end_time,
                    json.dumps(attendees), location, ctx.sender_jid,
                    datetime.utcnow().isoformat(),
                ),
            )
            conn.commit()
            return f"Meeting created: {title} at {start_time} (ID: {meeting_id})"
        finally:
            conn.close()
    except Exception as e:
        return f"Error creating meeting: {e}"


def _list_meetings(args: dict, ctx: ToolContext) -> str:
    date = args.get("date", "")
    try:
        conn = _get_db(ctx)
        try:
            if date:
                rows = conn.execute(
                    "SELECT title, start_time, end_time, location FROM meetings WHERE start_time LIKE ? ORDER BY start_time",
                    (f"{date}%",),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT title, start_time, end_time, location FROM meetings ORDER BY start_time LIMIT 20"
                ).fetchall()
            if not rows:
                return "No meetings found."
            parts = [f"• {title}: {start} ~ {end} @ {loc or 'TBD'}" for title, start, end, loc in rows]
            return "\n".join(parts)
        finally:
            conn.close()
    except Exception as e:
        return f"Error: {e}"


def _find_free_slot(args: dict, ctx: ToolContext) -> str:
    date = args.get("date", "")
    duration_minutes = args.get("duration_minutes", 60)
    work_start = 9
    work_end = 18
    try:
        conn = _get_db(ctx)
        try:
            rows = conn.execute(
                "SELECT start_time, end_time FROM meetings WHERE start_time LIKE ? ORDER BY start_time",
                (f"{date}%",),
            ).fetchall()
        finally:
            conn.close()

        # Parse occupied intervals as (start_minute, end_minute)
        occupied = []
        for start_t, end_t in rows:
            try:
                # Handle both "HH:MM" and "YYYY-MM-DDTHH:MM:SS" formats
                s = start_t[11:16] if "T" in start_t else start_t[:5]
                e = end_t[11:16] if "T" in end_t else end_t[:5]
                sh, sm = map(int, s.split(":"))
                eh, em = map(int, e.split(":"))
                occupied.append((sh * 60 + sm, eh * 60 + em))
            except Exception:
                continue

        # Merge overlapping intervals
        occupied.sort()
        merged = []
        for start, end in occupied:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append([start, end])

        # Find first gap >= duration_minutes within work hours
        work_start_min = work_start * 60
        work_end_min = work_end * 60
        cursor = work_start_min
        for occ_start, occ_end in merged:
            if cursor + duration_minutes <= occ_start:
                h, m = divmod(cursor, 60)
                eh, em = divmod(cursor + duration_minutes, 60)
                return (
                    f"Available slot on {date}: {h:02d}:{m:02d} - {eh:02d}:{em:02d} "
                    f"({duration_minutes} minutes)"
                )
            cursor = max(cursor, occ_end)

        # Check after last meeting
        if cursor + duration_minutes <= work_end_min:
            h, m = divmod(cursor, 60)
            eh, em = divmod(cursor + duration_minutes, 60)
            return (
                f"Available slot on {date}: {h:02d}:{m:02d} - {eh:02d}:{em:02d} "
                f"({duration_minutes} minutes)"
            )

        return f"No free slot found on {date} within working hours (09:00-18:00) for {duration_minutes} minutes."
    except Exception as e:
        return f"Error: {e}"


def get_enterprise_tools() -> list[Tool]:
    return [
        Tool(
            name="search_knowledge_base",
            description="Search the company knowledge base for policies, FAQs, and documents.",
            schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results (default 5)"},
                },
                "required": ["query"],
            },
            execute=_search_knowledge_base,
        ),
        Tool(
            name="start_workflow",
            description="Start an enterprise workflow (leave request, expense report, IT ticket).",
            schema={
                "type": "object",
                "properties": {
                    "workflow_type": {
                        "type": "string",
                        "enum": ["leave_request", "expense_report", "it_ticket"],
                        "description": "Type of workflow",
                    },
                    "data": {"type": "object", "description": "Workflow form data"},
                },
                "required": ["workflow_type", "data"],
            },
            execute=_start_workflow,
        ),
        Tool(
            name="check_workflow_status",
            description="Check the status of a workflow by ID.",
            schema={
                "type": "object",
                "properties": {
                    "workflow_id": {"type": "string", "description": "Workflow ID"},
                },
                "required": ["workflow_id"],
            },
            execute=_check_workflow_status,
        ),
        Tool(
            name="route_to_department",
            description="Route a request to a specific department (hr/it/finance/general).",
            schema={
                "type": "object",
                "properties": {
                    "department": {
                        "type": "string",
                        "enum": ["hr", "it", "finance", "general"],
                    },
                    "message": {"type": "string", "description": "Message to route"},
                },
                "required": ["department", "message"],
            },
            execute=_route_to_department,
        ),
        Tool(
            name="create_meeting",
            description="Create a meeting/calendar event.",
            schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start_time": {"type": "string", "description": "ISO 8601 datetime"},
                    "end_time": {"type": "string", "description": "ISO 8601 datetime"},
                    "attendees": {"type": "array", "items": {"type": "string"}},
                    "location": {"type": "string"},
                },
                "required": ["title", "start_time", "end_time"],
            },
            execute=_create_meeting,
        ),
        Tool(
            name="list_meetings",
            description="List meetings, optionally filtered by date (YYYY-MM-DD).",
            schema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date filter YYYY-MM-DD"},
                },
            },
            execute=_list_meetings,
        ),
        Tool(
            name="find_free_slot",
            description="Find a free time slot for a meeting on a given date.",
            schema={
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date YYYY-MM-DD"},
                    "duration_minutes": {"type": "integer", "description": "Duration in minutes"},
                },
                "required": ["date"],
            },
            execute=_find_free_slot,
        ),
    ]
