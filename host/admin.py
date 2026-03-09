"""
MinionDesk Admin CLI
Run: python run.py admin <command>
"""
from __future__ import annotations
import sys
from pathlib import Path


def run_admin(args: list[str]) -> None:
    """Entry point for admin CLI."""
    if not args:
        _print_help()
        return

    cmd = args[0]
    rest = args[1:]

    commands = {
        "status": _cmd_status,
        "list-employees": _cmd_list_employees,
        "add-employee": _cmd_add_employee,
        "remove-employee": _cmd_remove_employee,
        "allowlist-add": _cmd_allowlist_add,
        "allowlist-remove": _cmd_allowlist_remove,
        "allowlist-list": _cmd_allowlist_list,
        "audit-log": _cmd_audit_log,
        "kb-list": _cmd_kb_list,
        "kb-ingest": _cmd_kb_ingest,
        "kb-clear": _cmd_kb_clear,
        "kb-search": _cmd_kb_search,
        "workflows": _cmd_workflows,
        "minion-set": _cmd_minion_set,
        "confluence-sync": _cmd_confluence_sync,
        "sharepoint-sync": _cmd_sharepoint_sync,
        "help": lambda _: _print_help(),
    }

    if cmd not in commands:
        print(f"❌ Unknown command: {cmd}")
        _print_help()
        sys.exit(1)

    _init_db()
    commands[cmd](rest)


def _init_db():
    from host import db, config
    db.init(config.DATA_DIR / "miniondesk.db")


def _print_help():
    print("""
MinionDesk Admin CLI
════════════════════════════════════════

System:
  status                    Show system status

Employees:
  list-employees            List all employees
  add-employee <jid> <name> <role>
                            Add employee (role: employee|manager|admin)
  remove-employee <jid>     Remove employee

Allowlist:
  allowlist-add <jid>       Add JID to allowlist
  allowlist-remove <jid>    Remove JID from allowlist
  allowlist-list            Show allowlist

Knowledge Base:
  kb-list                   List ingested files
  kb-ingest <path>          Ingest file or directory
  kb-clear                  Clear all KB data
  kb-search <query>         Search knowledge base content

Workflows:
  workflows                 List recent workflow instances

Minions:
  minion-set <chat_jid> <name>
                            Set preferred minion for a chat

Knowledge Base Sync:
  confluence-sync           Fetch all configured Confluence spaces and ingest into KB
  sharepoint-sync           Fetch SharePoint pages and ingest into KB

Audit:
  audit-log [N]             Show last N audit entries (default 20)
""")


def _cmd_status(args):
    from host import db, config
    import subprocess
    print("\n🍌 MinionDesk Status")
    print("=" * 40)
    print(f"Data dir:  {config.DATA_DIR}")
    print(f"IPC dir:   {config.IPC_DIR}")
    print(f"Minions:   {config.MINIONS_DIR}")
    print(f"Docker:    {config.DOCKER_IMAGE}")

    # Check Docker
    try:
        result = subprocess.run(["docker", "images", "-q", config.DOCKER_IMAGE],
                                capture_output=True, text=True)
        if result.stdout.strip():
            print(f"Runner:    ✅ {config.DOCKER_IMAGE} found")
        else:
            print(f"Runner:    ⚠️  {config.DOCKER_IMAGE} NOT built (run: docker build -t {config.DOCKER_IMAGE} container/)")
    except FileNotFoundError:
        print("Runner:    ❌ Docker not installed")

    # DB stats
    conn = db.get_conn()
    for table in ["messages", "employees", "workflow_instances", "meetings", "audit_log"]:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table:<20} {count} rows")
        except Exception:
            print(f"{table:<20} (table not found)")
    print()


def _cmd_list_employees(args):
    from host import db
    conn = db.get_conn()
    rows = conn.execute("SELECT jid, name, role, created_at FROM employees ORDER BY name").fetchall()
    if not rows:
        print("No employees found.")
        return
    print(f"\n{'JID':<30} {'Name':<20} {'Role':<15} {'Since'}")
    print("-" * 80)
    for jid, name, role, created in rows:
        print(f"{jid:<30} {name:<20} {role:<15} {created[:10]}")
    print()


def _cmd_add_employee(args):
    if len(args) < 3:
        print("Usage: add-employee <jid> <name> <role>")
        print("Roles: employee | manager | admin")
        return
    jid, name, role = args[0], args[1], args[2]
    if role not in ("employee", "manager", "admin"):
        print(f"❌ Invalid role '{role}'. Use: employee, manager, admin")
        return
    from host import db
    conn = db.get_conn()
    from datetime import datetime
    conn.execute(
        "INSERT OR REPLACE INTO employees (jid, name, role, created_at) VALUES (?, ?, ?, ?)",
        (jid, name, role, datetime.utcnow().isoformat()),
    )
    conn.commit()
    db.audit("admin-cli", "add_employee", jid, f"name={name}, role={role}")
    print(f"✅ Added employee: {name} ({jid}) as {role}")


def _cmd_remove_employee(args):
    if not args:
        print("Usage: remove-employee <jid>")
        return
    from host import db
    conn = db.get_conn()
    conn.execute("DELETE FROM employees WHERE jid = ?", (args[0],))
    conn.commit()
    db.audit("admin-cli", "remove_employee", args[0])
    print(f"✅ Removed employee: {args[0]}")


def _cmd_allowlist_add(args):
    if not args:
        print("Usage: allowlist-add <jid>")
        return
    from host.allowlist import add_jid
    from host import db
    add_jid(args[0])
    db.audit("admin-cli", "allowlist_add", args[0])
    print(f"✅ Added to allowlist: {args[0]}")


def _cmd_allowlist_remove(args):
    if not args:
        print("Usage: allowlist-remove <jid>")
        return
    from host.allowlist import remove_jid
    remove_jid(args[0])
    print(f"✅ Removed from allowlist: {args[0]}")


def _cmd_allowlist_list(args):
    from host.allowlist import load_allowlist, _allowlist
    load_allowlist()
    if not _allowlist:
        print("Allowlist is empty (open access — all JIDs allowed).")
        return
    print(f"\nAllowlist ({len(_allowlist)} entries):")
    for jid in sorted(_allowlist):
        print(f"  {jid}")
    print()


def _cmd_audit_log(args):
    limit = int(args[0]) if args else 20
    from host import db
    entries = db.get_audit_log(limit)
    if not entries:
        print("No audit log entries.")
        return
    print(f"\n{'Timestamp':<20} {'Actor':<25} {'Action':<25} {'Target':<20} {'Detail'}")
    print("-" * 110)
    for e in entries:
        print(f"{e['ts'][:19]:<20} {e['actor_jid'][:24]:<25} {e['action'][:24]:<25} {(e['target'] or '')[:19]:<20} {e['detail'] or ''}")
    print()


def _cmd_kb_list(args):
    from host import config
    import json
    registry_path = config.DATA_DIR / "kb_hashes.json"
    if not registry_path.exists():
        print("No files ingested yet.")
        return
    registry = json.loads(registry_path.read_text())
    print(f"\nIngested files ({len(registry)}):")
    for path, hash_val in registry.items():
        print(f"  {Path(path).name:<40} {hash_val[:12]}...")
    print()


def _cmd_kb_search(args):
    """Search the knowledge base and display results."""
    if not args:
        print("Usage: kb-search <query>")
        return

    query = " ".join(args)
    from host.enterprise.knowledge_base import semantic_search

    print(f"\n🔍 Searching KB for: '{query}'\n")
    results = semantic_search(query, limit=5)

    if not results:
        print("No results found.")
        return

    for i, r in enumerate(results, 1):
        score = r.get("score", 0)
        title = r.get("title", "Untitled")
        source = r.get("source", "")
        content = r.get("content", "")[:400]
        print(f"{'─' * 60}")
        print(f"[{i}] {title}  (score: {score:.3f})")
        print(f"    Source: {source}")
        print(f"    {content}")
        if len(r.get('content', '')) > 400:
            print(f"    ... ({len(r.get('content', ''))} chars total)")
    print(f"{'─' * 60}\n")


def _cmd_kb_ingest(args):
    if not args:
        print("Usage: kb-ingest <path>")
        return
    from pathlib import Path
    p = Path(args[0])
    from host.enterprise.knowledge_base import ingest_file, ingest_directory
    if p.is_dir():
        ingest_directory(p)
        print(f"✅ Ingested directory: {p}")
    elif p.is_file():
        count = ingest_file(p)
        print(f"✅ Ingested {count} chunks from {p.name}")
    else:
        print(f"❌ Not found: {p}")


def _cmd_kb_clear(args):
    confirm = input("⚠️  This will delete ALL knowledge base data. Type 'yes' to confirm: ")
    if confirm != "yes":
        print("Cancelled.")
        return
    from host import db, config
    conn = db.get_conn()
    conn.execute("DELETE FROM kb_chunks")
    conn.execute("DELETE FROM kb_chunks_plain")
    conn.commit()
    registry_path = config.DATA_DIR / "kb_hashes.json"
    if registry_path.exists():
        registry_path.unlink()
    db.audit("admin-cli", "kb_clear", "", "all KB data cleared")
    print("✅ Knowledge base cleared.")


def _cmd_workflows(args):
    from host import db
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT id, workflow_type, submitter_jid, status, created_at FROM workflow_instances ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    if not rows:
        print("No workflow instances.")
        return
    print(f"\n{'ID':<10} {'Type':<20} {'Submitter':<25} {'Status':<15} {'Created'}")
    print("-" * 90)
    for id_, wtype, subj, status, created in rows:
        print(f"{id_:<10} {wtype:<20} {subj[:24]:<25} {status:<15} {created[:19]}")
    print()


def _cmd_minion_set(args):
    if len(args) < 2:
        print("Usage: minion-set <chat_jid> <minion_name>")
        return
    chat_jid, name = args[0], args[1]
    from host import db
    db.set_user_minion(chat_jid, name)
    print(f"✅ Set minion for {chat_jid} → {name}")


def _cmd_confluence_sync(args):
    """Sync all configured Confluence spaces into the knowledge base."""
    from host.enterprise.confluence import sync_confluence
    print("\n🔄 Syncing Confluence knowledge base...")
    result = sync_confluence()
    if "error" in result:
        print(f"❌ {result['error']}")
        print("   Set CONFLUENCE_URL, CONFLUENCE_USER, CONFLUENCE_TOKEN, CONFLUENCE_SPACES in .env")
        return
    spaces = ", ".join(result.get("spaces_synced", []))
    pages = result.get("pages_fetched", 0)
    chunks = result.get("chunks_ingested", 0)
    print(f"✅ Confluence sync complete")
    print(f"   Spaces:  {spaces}")
    print(f"   Pages:   {pages}")
    print(f"   Chunks:  {chunks}")
    print()


def _cmd_sharepoint_sync(args):
    """Sync SharePoint site pages into the knowledge base."""
    from host.enterprise.confluence import sync_sharepoint
    print("\n🔄 Syncing SharePoint knowledge base...")
    result = sync_sharepoint()
    if "error" in result:
        print(f"❌ {result['error']}")
        print("   Set SHAREPOINT_URL and SHAREPOINT_TOKEN in .env")
        return
    pages = result.get("pages_fetched", 0)
    chunks = result.get("chunks_ingested", 0)
    print(f"✅ SharePoint sync complete")
    print(f"   Pages:   {pages}")
    print(f"   Chunks:  {chunks}")
    print()
