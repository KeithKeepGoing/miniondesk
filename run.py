#!/usr/bin/env python3
"""
MinionDesk — run.py
Quick start: python run.py
"""
import argparse
import asyncio
import sys
import os

# Ensure local packages are importable
sys.path.insert(0, os.path.dirname(__file__))

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def main():
    import argparse
    parser = argparse.ArgumentParser(description="MinionDesk Enterprise AI Assistant")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("start", help="Start MinionDesk (default)")
    sub.add_parser("setup", help="Run interactive setup")
    sub.add_parser("validate", help="Run pre-flight validation checks")

    ingest_p = sub.add_parser("ingest", help="Ingest knowledge base files")
    ingest_p.add_argument("path", help="File or directory to ingest")

    admin_p = sub.add_parser("admin", help="Admin CLI commands")
    admin_p.add_argument("admin_args", nargs=argparse.REMAINDER, help="Admin command and args")

    health_p = sub.add_parser("health", help="Check system health")

    sub.add_parser("ingest-ic-kb", help="Ingest IC design knowledge base from knowledge/ic_design/")
    sub.add_parser("confluence-sync", help="Sync Confluence knowledge base")
    sub.add_parser("sharepoint-sync", help="Sync SharePoint knowledge base")
    sub.add_parser("portal", help="Start web portal only (for testing)")

    ldap_p = sub.add_parser("ldap-test", help="Test LDAP connectivity for a user")
    ldap_p.add_argument("username", nargs="?", default="", help="Username to look up")

    args = parser.parse_args()

    if args.command == "setup":
        from setup.setup import run_setup
        run_setup()
    elif args.command == "ingest":
        _ingest(args.path)
    elif args.command == "admin":
        from host.admin import run_admin
        admin_args = args.admin_args if hasattr(args, 'admin_args') else []
        run_admin(admin_args)
    elif args.command == "health":
        _check_health()
    elif args.command == "ingest-ic-kb":
        from host.enterprise.knowledge_base import ingest_document
        from pathlib import Path
        kb_dir = Path("knowledge/ic_design")
        if not kb_dir.exists():
            print("knowledge/ic_design/ directory not found")
        else:
            count = 0
            for f in kb_dir.glob("*.md"):
                text = f.read_text(encoding="utf-8")
                chunks = ingest_document(text, metadata={"source": "ic_kb", "file": f.name})
                print(f"  {f.name} → {chunks} chunks")
                count += chunks
            print(f"Total: {count} chunks ingested from IC knowledge base")
    elif args.command == "confluence-sync":
        from host.enterprise.confluence import sync_confluence
        result = sync_confluence()
        print(f"Confluence sync: {result}")
    elif args.command == "sharepoint-sync":
        from host.enterprise.confluence import sync_sharepoint
        result = sync_sharepoint()
        print(f"SharePoint sync: {result}")
    elif args.command == "portal":
        from host.webportal import start_portal
        import asyncio
        print("Starting web portal...")
        asyncio.run(start_portal(None))
    elif args.command == "ldap-test":
        username = args.username if hasattr(args, 'username') else ""
        if not username:
            print("Usage: python run.py ldap-test <username>")
        else:
            from host.enterprise.ldap import get_user_info, is_configured
            if not is_configured():
                print("LDAP not configured (check LDAP_URL, LDAP_BASE_DN, LDAP_BIND_DN)")
            else:
                info = get_user_info(username)
                if info:
                    print(f"User found: {info}")
                else:
                    print(f"User not found or LDAP error: {username}")
    elif args.command == "validate":
        from host.validate import validate_all
        ok = validate_all(verbose=True)
        sys.exit(0 if ok else 1)
    else:
        # Run validation before starting
        from host.validate import validate_all
        if not validate_all(verbose=True):
            sys.exit(1)
        from host.main import main as host_main
        asyncio.run(host_main())


def _check_health():
    """Quick health check from CLI."""
    import subprocess
    import sys
    try:
        import urllib.request
        resp = urllib.request.urlopen("http://localhost:8080/health", timeout=3)
        import json
        data = json.loads(resp.read())
        print(f"Status: {data['status']}")
        for k, v in data.get('checks', {}).items():
            icon = "✅" if v == "ok" else "❌"
            print(f"  {icon} {k}: {v}")
        print(f"Uptime: {data.get('uptime_seconds', '?')}s")
    except Exception:
        print("❌ Health server not reachable (is MinionDesk running?)")
        sys.exit(1)


def _ingest(path: str):
    from pathlib import Path
    from host import db, config
    db.init(config.DATA_DIR / "miniondesk.db")

    from host.enterprise.knowledge_base import ingest_file, ingest_directory
    p = Path(path)
    if p.is_dir():
        ingest_directory(p)
        print(f"Ingested directory: {p}")
    elif p.is_file():
        count = ingest_file(p)
        print(f"Ingested {count} chunks from {p}")
    else:
        print(f"Error: {path} not found")
        sys.exit(1)


if __name__ == "__main__":
    main()
