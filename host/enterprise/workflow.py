"""
Workflow Engine: YAML-defined approval flows stored in SQLite.
"""
from __future__ import annotations
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import db, config


def _load_definition(workflow_type: str) -> dict:
    try:
        import yaml
    except ImportError:
        return {}
    path = config.WORKFLOWS_DIR / f"{workflow_type}.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text())


def submit(workflow_type: str, submitter_jid: str, data: dict) -> str:
    """Submit a new workflow instance."""
    wf_id = str(uuid.uuid4())[:8]
    conn = db.get_conn()
    conn.execute(
        """INSERT INTO workflow_instances
           (id, workflow_type, submitter_jid, data_json, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, 'submitted', ?, ?)""",
        (wf_id, workflow_type, submitter_jid, json.dumps(data),
         datetime.utcnow().isoformat(), datetime.utcnow().isoformat()),
    )
    conn.commit()

    # Audit log
    try:
        from .. import db as _db
        _db.audit(submitter_jid, "workflow_submitted", wf_id, f"type={workflow_type}")
    except Exception:
        pass

    # Notify managers
    _notify_managers(workflow_type, wf_id, submitter_jid, data)
    return wf_id


def _is_authorized_approver(jid: str) -> bool:
    """Check if the JID belongs to a manager or admin."""
    conn = db.get_conn()
    row = conn.execute(
        "SELECT role FROM employees WHERE jid = ?", (jid,)
    ).fetchone()
    return row is not None and row[0] in ("manager", "admin")


def approve(workflow_id: str, approver_jid: str) -> bool:
    if not _is_authorized_approver(approver_jid):
        try:
            db.audit(approver_jid, "workflow_approve_denied", workflow_id, "unauthorized")
        except Exception:
            pass
        return False
    conn = db.get_conn()
    row = conn.execute(
        "SELECT workflow_type, submitter_jid FROM workflow_instances WHERE id = ? AND status = 'submitted'",
        (workflow_id,),
    ).fetchone()
    if not row:
        return False
    workflow_type, submitter_jid = row
    conn.execute(
        "UPDATE workflow_instances SET status='approved', approved_by=?, updated_at=? WHERE id=?",
        (approver_jid, datetime.utcnow().isoformat(), workflow_id),
    )
    conn.commit()

    # Audit log
    try:
        from .. import db as _db
        _db.audit(approver_jid, "workflow_approved", workflow_id, f"type={workflow_type}")
    except Exception:
        pass

    db.queue_notification(submitter_jid, f"✅ Your {workflow_type} (ID: {workflow_id}) has been approved.")
    return True


def reject(workflow_id: str, rejector_jid: str, reason: str = "") -> bool:
    if not _is_authorized_approver(rejector_jid):
        try:
            db.audit(rejector_jid, "workflow_reject_denied", workflow_id, "unauthorized")
        except Exception:
            pass
        return False
    conn = db.get_conn()
    row = conn.execute(
        "SELECT workflow_type, submitter_jid FROM workflow_instances WHERE id = ? AND status = 'submitted'",
        (workflow_id,),
    ).fetchone()
    if not row:
        return False
    workflow_type, submitter_jid = row
    conn.execute(
        "UPDATE workflow_instances SET status='rejected', rejected_by=?, updated_at=? WHERE id=?",
        (rejector_jid, datetime.utcnow().isoformat(), workflow_id),
    )
    conn.commit()

    # Audit log
    try:
        from .. import db as _db
        _db.audit(rejector_jid, "workflow_rejected", workflow_id, f"type={workflow_type}")
    except Exception:
        pass

    msg = f"❌ Your {workflow_type} (ID: {workflow_id}) was rejected."
    if reason:
        msg += f" Reason: {reason}"
    db.queue_notification(submitter_jid, msg)
    return True


def get_status(workflow_id: str) -> dict | None:
    conn = db.get_conn()
    row = conn.execute(
        "SELECT id, workflow_type, submitter_jid, status, approved_by, created_at, updated_at "
        "FROM workflow_instances WHERE id = ?",
        (workflow_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row[0], "workflow_type": row[1], "submitter_jid": row[2],
        "status": row[3], "approved_by": row[4], "created_at": row[5], "updated_at": row[6],
    }


def _notify_managers(workflow_type: str, wf_id: str, submitter_jid: str, data: dict) -> None:
    managers = db.get_employees_by_role("manager")
    msg = f"📋 New {workflow_type} submitted (ID: {wf_id}) by {submitter_jid}. Reply /approve {wf_id} or /reject {wf_id}."
    for mgr in managers:
        db.queue_notification(mgr["jid"], msg)


# ── Expiry & Reminders ────────────────────────────────────────────────────────

WORKFLOW_EXPIRY_DAYS: int = 7   # Auto-expire pending workflows after 7 days
WORKFLOW_REMINDER_DAYS: int = 2  # Remind manager if pending > 2 days


def check_expiry_and_reminders() -> int:
    """
    Called by scheduler. Returns number of workflows acted upon.
    - Expires workflows pending > WORKFLOW_EXPIRY_DAYS
    - Sends reminders for workflows pending > WORKFLOW_REMINDER_DAYS
    """
    from .. import db
    conn = db.get_conn()
    now = datetime.utcnow()
    count = 0

    rows = conn.execute(
        "SELECT id, workflow_type, submitter_jid, created_at FROM workflow_instances WHERE status = 'submitted'"
    ).fetchall()

    for wf_id, wf_type, submitter_jid, created_at_str in rows:
        try:
            try:
                created_at = datetime.fromisoformat(created_at_str)
            except (ValueError, TypeError) as e:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    f"Workflow {wf_id} has invalid timestamp '{created_at_str}': {e}"
                )
                continue
            age_days = (now - created_at).days

            if age_days >= WORKFLOW_EXPIRY_DAYS:
                # Auto-expire
                conn.execute(
                    "UPDATE workflow_instances SET status='expired', updated_at=? WHERE id=?",
                    (now.isoformat(), wf_id),
                )
                conn.commit()
                db.queue_notification(
                    submitter_jid,
                    f"⏰ 您的 {wf_type} 申請 (ID: {wf_id}) 因超過 {WORKFLOW_EXPIRY_DAYS} 天未審批，已自動作廢。請重新提交。"
                )
                try:
                    db.audit("system", "workflow_expired", wf_id, f"age={age_days}d")
                except Exception:
                    pass
                count += 1

            elif age_days >= WORKFLOW_REMINDER_DAYS:
                # Only send reminder once per day: check updated_at to avoid spam (fixes #190)
                try:
                    updated = datetime.fromisoformat(
                        conn.execute("SELECT updated_at FROM workflow_instances WHERE id=?", (wf_id,)).fetchone()[0]
                    )
                    hours_since_update = (now - updated).total_seconds() / 3600
                    if hours_since_update < 24:
                        continue  # Already reminded within the last 24 hours
                except Exception:
                    pass
                # Mark as reminded by touching updated_at
                conn.execute(
                    "UPDATE workflow_instances SET updated_at=? WHERE id=?",
                    (now.isoformat(), wf_id),
                )
                conn.commit()
                managers = conn.execute(
                    "SELECT jid FROM employees WHERE role IN ('manager', 'admin')"
                ).fetchall()
                for (mgr_jid,) in managers:
                    db.queue_notification(
                        mgr_jid,
                        f"📋 提醒：{wf_type} 申請 (ID: {wf_id}) 已等待 {age_days} 天，請盡快審批。"
                    )
                count += 1
        except Exception as e:
            print(f"[workflow] expiry check error for {wf_id}: {e}")

    return count
