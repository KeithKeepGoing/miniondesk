"""
Calendar: Meeting management using SQLite.
"""
from __future__ import annotations
import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from .. import db


def _get_db():
    """Get a direct DB connection for calendar queries."""
    db_path = Path(os.getenv("DATA_DIR", "./data")) / "miniondesk.db"
    return sqlite3.connect(str(db_path))


def create_meeting(
    title: str,
    start_time: str,
    end_time: str,
    organizer_jid: str,
    attendees: list[str] | None = None,
    location: str = "",
) -> str:
    meeting_id = str(uuid.uuid4())[:8]
    conn = db.get_conn()
    conn.execute(
        """INSERT INTO meetings (id, title, start_time, end_time, attendees_json, location, organizer_jid, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            meeting_id, title, start_time, end_time,
            json.dumps(attendees or []), location, organizer_jid,
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    return meeting_id


def list_meetings(date: str | None = None) -> list[dict]:
    conn = db.get_conn()
    if date:
        rows = conn.execute(
            "SELECT id, title, start_time, end_time, location FROM meetings WHERE start_time LIKE ? ORDER BY start_time",
            (f"{date}%",),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, title, start_time, end_time, location FROM meetings ORDER BY start_time LIMIT 50"
        ).fetchall()
    return [{"id": r[0], "title": r[1], "start_time": r[2], "end_time": r[3], "location": r[4]} for r in rows]


def find_free_slots(date: str, duration_minutes: int = 60) -> list[str]:
    meetings = list_meetings(date)
    work_start = 9 * 60  # 9:00
    work_end = 18 * 60   # 18:00
    occupied = set()
    for m in meetings:
        try:
            st = m["start_time"][11:16]  # HH:MM
            et = m["end_time"][11:16]
            sh, sm = int(st[:2]), int(st[3:])
            eh, em = int(et[:2]), int(et[3:])
            for minute in range(sh * 60 + sm, eh * 60 + em):
                occupied.add(minute)
        except Exception:
            pass

    free_slots = []
    start = work_start
    while start + duration_minutes <= work_end:
        slot = set(range(start, start + duration_minutes))
        if not slot & occupied:
            h, m = divmod(start, 60)
            free_slots.append(f"{date}T{h:02d}:{m:02d}:00")
        start += 30  # 30-min increments
    return free_slots[:5]


def find_free_slot(date_str: str, duration_mins: int = 60,
                   work_start: int = 9, work_end: int = 18,
                   ctx=None) -> dict:
    """Find first available slot on given date."""
    conn = db.get_conn(ctx) if ctx else _get_db()
    try:
        rows = conn.execute(
            "SELECT start_time, end_time FROM meetings WHERE start_time LIKE ? ORDER BY start_time",
            (f"{date_str}%",)
        ).fetchall()
    finally:
        if ctx is None:
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

    # Find first gap >= duration_mins within work hours
    work_start_min = work_start * 60
    work_end_min = work_end * 60
    cursor = work_start_min
    for occ_start, occ_end in merged:
        if cursor + duration_mins <= occ_start:
            # Free slot found before this occupied block
            h, m = divmod(cursor, 60)
            eh, em = divmod(cursor + duration_mins, 60)
            return {
                "available": True,
                "date": date_str,
                "start": f"{h:02d}:{m:02d}",
                "end": f"{eh:02d}:{em:02d}",
            }
        cursor = max(cursor, occ_end)

    # Check after last meeting
    if cursor + duration_mins <= work_end_min:
        h, m = divmod(cursor, 60)
        eh, em = divmod(cursor + duration_mins, 60)
        return {
            "available": True,
            "date": date_str,
            "start": f"{h:02d}:{m:02d}",
            "end": f"{eh:02d}:{em:02d}",
        }

    return {"available": False, "date": date_str, "message": "當天工作時間內沒有空閒時段"}
