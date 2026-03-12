"""
MinionDesk DevEngine — 7-stage LLM-powered self-development pipeline.

Stages: ANALYZE → DESIGN → IMPLEMENT → TEST → REVIEW → DOCUMENT → DEPLOY

Each stage (except DEPLOY) runs a Docker container with a specialized prompt.
DEPLOY parses file blocks and writes them to the filesystem.

Session lifecycle:
  pending → running → paused (interactive mode) → completed | failed

Resume: sessions can be resumed from any paused state.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from . import config, db
from .runner import run_minion

# Per-group lock to prevent concurrent DevEngine sessions for the same group
_dev_engine_locks: dict[str, asyncio.Lock] = {}
_dev_engine_locks_mutex = asyncio.Lock()

logger = logging.getLogger(__name__)

# ─── Stage definitions ────────────────────────────────────────────────────────

STAGES = [
    "ANALYZE",
    "DESIGN",
    "IMPLEMENT",
    "TEST",
    "REVIEW",
    "DOCUMENT",
    "DEPLOY",
]

STAGE_PROMPTS: dict[str, str] = {
    "ANALYZE": """You are a requirements analyst for a software project.
Analyze the following requirement and produce a structured breakdown:

## Current State
(What exists now, what's missing)

## Proposed Changes
(What needs to be built, API/interface changes)

## Acceptance Criteria
(Testable conditions for success)

## Risk Assessment
(Potential issues, dependencies, edge cases)

Be specific and technical. Output in Markdown.""",

    "DESIGN": """You are a software architect.
Based on the requirements analysis, produce a detailed technical design:

## Architecture Overview
(High-level system design)

## Module Structure
(Files to create/modify, directory layout)

## Key Classes and Functions
(Interfaces, signatures, responsibilities)

## Data Flow
(How data moves through the system)

## Integration Points
(How new code connects to existing code)

## Database Schema
(Any new tables or schema changes)

Output in Markdown with code snippets where helpful.""",

    "IMPLEMENT": """You are a senior Python developer.
Based on the design, write complete, production-ready code.

Rules:
- Write COMPLETE files, not snippets
- Include all imports
- Add docstrings for public functions
- Handle errors gracefully
- Follow existing code style

Output each file using this exact format:
--- FILE: path/to/file.py ---
(complete file contents)
--- END FILE ---

You may output multiple files. After all files, write:
## Summary
(Brief description of what was implemented)""",

    "TEST": """You are a QA engineer.
Write comprehensive pytest test files for the implementation.

Rules:
- Test all public functions and classes
- Include happy path, edge cases, and error conditions
- Use pytest fixtures where appropriate
- Mock external dependencies (Docker, network, DB)
- Aim for >80% coverage

Output test files using:
--- FILE: tests/test_<name>.py ---
(complete test file)
--- END FILE ---""",

    "REVIEW": """You are a senior code reviewer.
Review the implementation for security, quality, and correctness.

Check for:
1. Security vulnerabilities (injection, path traversal, auth bypass)
2. Code quality (DRY, SOLID, readability)
3. Performance issues (N+1 queries, blocking operations)
4. Error handling gaps
5. Missing type hints or documentation

Output:
## Overall Assessment: PASS | FAIL | PASS_WITH_NOTES

## Critical Issues (must fix)
(List any blocking problems)

## Warnings (should fix)
(List non-blocking improvements)

## Suggestions (nice to have)
(Optional improvements)

## Verdict
(One paragraph summary)""",

    "DOCUMENT": """You are a technical writer.
Produce documentation for the new feature:

## README Section
(User-facing documentation, usage examples)

## CHANGELOG Entry
(Version bump entry, feature description)

## API Reference
(If applicable — function signatures, parameters, return values)

## Usage Examples
(Code snippets showing how to use the feature)

Output in Markdown.""",

    "DEPLOY": """You are a deployment engineer.
Produce a deployment plan for the implementation.

## Files to Write
(List all files that need to be created/modified)

## Pre-deployment Steps
(Database migrations, config changes, etc.)

## Deployment Steps
(Ordered list of actions)

## Verification
(How to confirm successful deployment)

## Rollback Plan
(Steps to revert if something goes wrong)

Output in Markdown.""",
}


# ─── DB helpers ───────────────────────────────────────────────────────────────

def _init_dev_sessions_table() -> None:
    """Create dev_sessions table if not exists."""
    conn = db._conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS dev_sessions (
        session_id    TEXT PRIMARY KEY,
        group_jid     TEXT NOT NULL,
        prompt        TEXT NOT NULL,
        mode          TEXT NOT NULL DEFAULT 'auto',
        status        TEXT NOT NULL DEFAULT 'pending',
        current_stage TEXT,
        artifacts     TEXT NOT NULL DEFAULT '{}',
        error         TEXT,
        created_at    REAL NOT NULL,
        updated_at    REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_dev_jid ON dev_sessions(group_jid, created_at);
    """)
    conn.commit()


def _get_session(session_id: str) -> dict | None:
    conn = db._conn()
    row = conn.execute(
        "SELECT * FROM dev_sessions WHERE session_id=?", (session_id,)
    ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["artifacts"] = json.loads(d["artifacts"])
    return d


def _save_session(session: dict) -> None:
    conn = db._conn()
    artifacts_json = json.dumps(session.get("artifacts", {}), ensure_ascii=False)
    conn.execute(
        """INSERT INTO dev_sessions
               (session_id, group_jid, prompt, mode, status, current_stage, artifacts, error, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(session_id) DO UPDATE SET
               status=excluded.status, current_stage=excluded.current_stage,
               artifacts=excluded.artifacts, error=excluded.error, updated_at=excluded.updated_at""",
        (
            session["session_id"], session["group_jid"], session["prompt"],
            session.get("mode", "auto"), session["status"],
            session.get("current_stage"), artifacts_json,
            session.get("error"), session.get("created_at", time.time()),
            time.time(),
        ),
    )
    conn.commit()


def get_session(session_id: str) -> dict | None:
    return _get_session(session_id)


def list_sessions(group_jid: str, limit: int = 20) -> list[dict]:
    rows = db._conn().execute(
        "SELECT session_id, status, current_stage, prompt, created_at, updated_at FROM dev_sessions WHERE group_jid=? ORDER BY created_at DESC LIMIT ?",
        (group_jid, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ─── File deployment helper ───────────────────────────────────────────────────

def _parse_file_blocks(text: str) -> list[tuple[str, str]]:
    """
    Parse --- FILE: path --- ... --- END FILE --- blocks.
    Returns list of (path, content) tuples.
    Prevents path traversal attacks.
    """
    pattern = re.compile(
        r"---\s*FILE:\s*(.+?)\s*---\n(.*?)---\s*END FILE\s*---",
        re.DOTALL,
    )
    files = []
    for match in pattern.finditer(text):
        raw_path = match.group(1).strip()
        content = match.group(2)
        # Strip leading slashes; rely on _deploy_files' resolve().relative_to() check
        # for actual containment enforcement (string-replace is not sufficient).
        safe_path = raw_path.lstrip("/")
        if safe_path:
            files.append((safe_path, content))
    return files


def _deploy_files(
    files: list[tuple[str, str]],
    base_dir: Path,
) -> list[str]:
    """Write files to base_dir. Returns list of written paths."""
    written = []
    for rel_path, content in files:
        target = base_dir / rel_path
        # Safety: must be within base_dir
        try:
            target.resolve().relative_to(base_dir.resolve())
        except ValueError:
            logger.warning("DevEngine: rejected path traversal attempt: %s", rel_path)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written.append(str(target))
        logger.info("DevEngine deployed: %s", target)
    return written


# ─── Stage execution ──────────────────────────────────────────────────────────

async def _run_stage(
    stage: str,
    session: dict,
    notify_fn,
) -> str:
    """Run a single pipeline stage via Docker container. Returns stage output."""
    group_jid   = session["group_jid"]
    group       = db.get_group(group_jid)
    if not group:
        raise RuntimeError(f"Group not found: {group_jid}")

    artifacts   = session.get("artifacts", {})
    stage_prompt = STAGE_PROMPTS[stage]

    # Build context from previous artifacts
    context_parts = [f"## Original Requirement\n{session['prompt']}"]
    prev_stages = STAGES[: STAGES.index(stage)]
    for prev in prev_stages:
        if prev in artifacts:
            context_parts.append(f"## {prev} Output\n{artifacts[prev]}")

    full_prompt = "\n\n".join(context_parts) + f"\n\n---\n\n{stage_prompt}"

    logger.info("DevEngine running stage %s for session %s", stage, session["session_id"])

    result = await run_minion(
        group_jid=group_jid,
        group_folder=group["folder"],
        minion_name="mini",
        prompt=full_prompt,
        chat_jid=group_jid,
        enabled_tools=None,
    )

    if result.get("status") == "error":
        raise RuntimeError(f"Stage {stage} failed: {result.get('result', 'unknown error')}")

    output = result.get("result", "")
    return output


# ─── Pipeline runner ──────────────────────────────────────────────────────────

async def run_pipeline(
    session_id: str,
    notify_fn,
    start_from: str | None = None,
) -> None:
    """
    Run (or resume) a DevEngine pipeline session.
    notify_fn: async callable(jid, text) for progress updates.
    start_from: resume from this stage (default: first pending stage).
    """
    session = _get_session(session_id)
    if not session:
        logger.error("DevEngine: session not found: %s", session_id)
        return

    group_jid = session["group_jid"]
    mode      = session.get("mode", "auto")
    artifacts = session.get("artifacts", {})

    # Determine starting point
    if start_from:
        pending_stages = STAGES[STAGES.index(start_from):]
    else:
        completed = set(artifacts.keys())
        pending_stages = [s for s in STAGES if s not in completed]

    if not pending_stages:
        session["status"] = "completed"
        _save_session(session)
        await notify_fn(group_jid, "✅ DevEngine: All stages already completed.")
        return

    session["status"] = "running"
    _save_session(session)

    for stage in pending_stages:
        session["current_stage"] = stage
        session["status"] = "running"
        _save_session(session)

        await notify_fn(
            group_jid,
            f"🔧 DevEngine [{STAGES.index(stage)+1}/{len(STAGES)}] Running *{stage}*...",
        )

        try:
            if stage == "DEPLOY":
                # Special: parse file blocks from IMPLEMENT output and write files
                implement_output = artifacts.get("IMPLEMENT", "")
                files = _parse_file_blocks(implement_output)
                base_dir = Path(config.BASE_DIR)
                written = _deploy_files(files, base_dir)

                # Also run DEPLOY stage for deployment plan
                deploy_plan = await _run_stage(stage, session, notify_fn)
                artifacts[stage] = deploy_plan

                summary = f"✅ DevEngine DEPLOY: wrote {len(written)} file(s)\n"
                summary += "\n".join(f"  • `{w}`" for w in written[:10])
                await notify_fn(group_jid, summary)
            else:
                output = await _run_stage(stage, session, notify_fn)
                artifacts[stage] = output

                # Send stage summary (first 300 chars)
                preview = output[:300].strip()
                if len(output) > 300:
                    preview += "..."
                await notify_fn(
                    group_jid,
                    f"✅ DevEngine *{stage}* complete:\n{preview}",
                )

            session["artifacts"] = artifacts
            _save_session(session)

        except Exception as exc:
            logger.error("DevEngine stage %s failed: %s", stage, exc)
            session["status"] = "failed"
            session["error"] = str(exc)
            _save_session(session)
            await notify_fn(group_jid, f"❌ DevEngine *{stage}* failed: {exc}")
            return

        # Interactive mode: pause after each stage for user review
        if mode == "interactive":
            session["status"] = "paused"
            _save_session(session)
            await notify_fn(
                group_jid,
                f"⏸️ DevEngine paused after *{stage}*.\n"
                f"Reply with `/dev resume {session_id}` to continue, or `/dev cancel {session_id}` to stop.",
            )
            return

    session["status"] = "completed"
    session["current_stage"] = None
    _save_session(session)
    await notify_fn(
        group_jid,
        f"🎉 DevEngine pipeline complete! All {len(STAGES)} stages done for: _{session['prompt'][:80]}_",
    )


# ─── Public API ───────────────────────────────────────────────────────────────

async def _get_group_dev_lock(group_jid: str) -> asyncio.Lock:
    """Return (or create) the per-group asyncio.Lock for DevEngine."""
    async with _dev_engine_locks_mutex:
        if group_jid not in _dev_engine_locks:
            _dev_engine_locks[group_jid] = asyncio.Lock()
        return _dev_engine_locks[group_jid]


async def start_dev_session(
    group_jid: str,
    prompt: str,
    mode: str = "auto",
    notify_fn = None,
) -> str:
    """Start a new DevEngine session. Returns session_id.

    Guards against concurrent sessions for the same group: if a session is
    already running or pending, the call is rejected with an error message.
    """
    _init_dev_sessions_table()

    # Concurrency guard: reject if a session is already active for this group
    try:
        conn = db._conn()
        running = conn.execute(
            "SELECT session_id FROM dev_sessions WHERE group_jid=? AND status IN ('pending','running') LIMIT 1",
            (group_jid,),
        ).fetchone()
        if running:
            msg = (
                f"⚠️ DevEngine: a session (`{running['session_id']}`) is already running for this group. "
                "Wait for it to complete or cancel it first."
            )
            if notify_fn:
                await notify_fn(group_jid, msg)
            return running["session_id"]
    except Exception as exc:
        logger.warning("DevEngine concurrency check failed: %s", exc)

    session_id = str(uuid.uuid4())[:8]
    session = {
        "session_id": session_id,
        "group_jid": group_jid,
        "prompt": prompt,
        "mode": mode,
        "status": "pending",
        "current_stage": None,
        "artifacts": {},
        "error": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    _save_session(session)
    logger.info("DevEngine session created: %s (mode=%s)", session_id, mode)

    if notify_fn:
        await notify_fn(
            group_jid,
            f"🚀 DevEngine started (session: `{session_id}`, mode: {mode})\n"
            f"Requirement: _{prompt[:100]}_",
        )

    # Run pipeline in background (create_task preferred over ensure_future; add error callback)
    def _on_pipeline_done(task: asyncio.Task) -> None:
        exc = task.exception() if not task.cancelled() else None
        if exc:
            logger.error("DevEngine pipeline task failed for session %s: %s", session_id, exc)

    task = asyncio.create_task(run_pipeline(session_id, notify_fn or _noop_notify))
    task.add_done_callback(_on_pipeline_done)
    return session_id


async def resume_dev_session(
    session_id: str,
    notify_fn = None,
) -> bool:
    """Resume a paused DevEngine session."""
    session = _get_session(session_id)
    if not session:
        return False
    if session["status"] not in ("paused", "failed"):
        return False

    def _on_resume_done(task: asyncio.Task) -> None:
        exc = task.exception() if not task.cancelled() else None
        if exc:
            logger.error("DevEngine resume task failed for session %s: %s", session_id, exc)

    task = asyncio.create_task(run_pipeline(session_id, notify_fn or _noop_notify))
    task.add_done_callback(_on_resume_done)
    return True


async def cancel_dev_session(session_id: str) -> bool:
    """Cancel a DevEngine session."""
    session = _get_session(session_id)
    if not session:
        return False
    session["status"] = "cancelled"
    _save_session(session)
    return True


async def _noop_notify(jid: str, text: str) -> None:
    logger.info("DevEngine [%s]: %s", jid, text[:100])
