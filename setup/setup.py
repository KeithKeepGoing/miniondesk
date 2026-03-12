"""MinionDesk interactive setup wizard and system checker."""
from __future__ import annotations
import asyncio
import os
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()

BANNER = """
╔══════════════════════════════════════════╗
║     🐤  MinionDesk Setup Wizard  🐤      ║
║   Enterprise AI assistant framework      ║
╚══════════════════════════════════════════╝
"""


async def run_check() -> None:
    """Check system requirements and current configuration."""
    console.print(BANNER)
    console.print(Panel("[bold]System Check[/bold]", box=box.ROUNDED))

    checks = [
        ("Python version", _check_python),
        ("Docker available", _check_docker),
        ("Docker image", _check_docker_image),
        ("LLM provider", _check_llm_provider),
        ("Telegram token", _check_telegram),
        ("Database", _check_db),
    ]

    table = Table(box=box.SIMPLE_HEAD)
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Details", style="dim")

    all_ok = True
    for name, fn in checks:
        ok, detail = fn()
        status = "✅ OK" if ok else "❌ FAIL"
        if not ok:
            all_ok = False
        table.add_row(name, status, detail)

    console.print(table)

    if all_ok:
        console.print("\n[bold green]✅ All checks passed! Ready to start.[/bold green]")
        console.print("Run: [bold]python run.py start[/bold]")
    else:
        console.print("\n[bold yellow]⚠️ Some checks failed. Fix issues above and re-run.[/bold yellow]")


def _check_python() -> tuple[bool, str]:
    v = sys.version_info
    ok = v >= (3, 11)
    return ok, f"Python {v.major}.{v.minor}.{v.micro}"


def _check_docker() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return True, f"Docker {result.stdout.strip()}"
        return False, "Docker not running"
    except FileNotFoundError:
        return False, "Docker not installed"
    except Exception as exc:
        return False, str(exc)


def _check_docker_image() -> tuple[bool, str]:
    image = os.getenv("CONTAINER_IMAGE", "miniondesk-agent:latest")
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return True, f"Image: {image}"
        return False, f"Image not found: {image} — run: docker build -t {image} ./container"
    except Exception as exc:
        return False, str(exc)


def _check_llm_provider() -> tuple[bool, str]:
    providers = [
        ("GOOGLE_API_KEY", "Gemini"),
        ("ANTHROPIC_API_KEY", "Claude"),
        ("OPENAI_API_KEY", "OpenAI"),
        ("OLLAMA_URL", "Ollama"),
        ("OPENAI_BASE_URL", "OpenAI-compat"),
    ]
    for key, name in providers:
        if os.getenv(key):
            return True, f"{name} ({key} set)"
    return False, "No LLM provider configured — set at least one API key in .env"


def _check_telegram() -> tuple[bool, str]:
    token = os.getenv("TELEGRAM_TOKEN")
    if token:
        return True, "TELEGRAM_TOKEN set"
    return False, "TELEGRAM_TOKEN not set (optional but needed for Telegram)"


def _check_db() -> tuple[bool, str]:
    from dotenv import load_dotenv
    load_dotenv()
    data_dir = Path(os.getenv("DATA_DIR", "./data"))
    db_path = data_dir / "miniondesk.db"
    if db_path.exists():
        size = db_path.stat().st_size
        return True, f"Database exists ({size:,} bytes)"
    return True, "Database will be created on first start"


async def run_setup() -> None:
    """Interactive setup wizard."""
    console.print(BANNER)
    console.print(Panel("[bold]Interactive Setup[/bold]", box=box.ROUNDED))

    env_path = Path(".env")
    if env_path.exists():
        console.print(f"[yellow]⚠️  .env already exists. Editing existing file.[/yellow]")
        existing = env_path.read_text(encoding="utf-8")
    else:
        template = Path(".env.example")
        existing = template.read_text(encoding="utf-8") if template.exists() else ""

    console.print("\n[bold]Step 1: LLM Provider[/bold]")
    console.print("Choose your preferred LLM (at least one required):")
    console.print("  1. Google Gemini (free tier available, recommended)")
    console.print("  2. Anthropic Claude")
    console.print("  3. OpenAI")
    console.print("  4. Ollama (local, no internet)")
    console.print("  5. Skip (configure manually in .env)")

    choice = _prompt("Choice [1-5]", "1")

    env_additions = {}
    if choice == "1":
        key = _prompt("GOOGLE_API_KEY")
        if key:
            env_additions["GOOGLE_API_KEY"] = key
    elif choice == "2":
        key = _prompt("ANTHROPIC_API_KEY")
        if key:
            env_additions["ANTHROPIC_API_KEY"] = key
    elif choice == "3":
        key = _prompt("OPENAI_API_KEY")
        if key:
            env_additions["OPENAI_API_KEY"] = key
    elif choice == "4":
        url = _prompt("OLLAMA_URL", "http://localhost:11434")
        env_additions["OLLAMA_URL"] = url

    console.print("\n[bold]Step 2: Telegram Bot[/bold]")
    tg_token = _prompt("TELEGRAM_TOKEN (press Enter to skip)")
    if tg_token:
        env_additions["TELEGRAM_TOKEN"] = tg_token

    console.print("\n[bold]Step 3: Dashboard Password[/bold]")
    pwd = _prompt("DASHBOARD_PASSWORD", "changeme")
    if pwd != "changeme":
        env_additions["DASHBOARD_PASSWORD"] = pwd

    # Write .env
    if env_additions:
        lines = existing.splitlines()
        for key, val in env_additions.items():
            replaced = False
            for i, line in enumerate(lines):
                if line.startswith(f"{key}=") or line.startswith(f"# {key}="):
                    lines[i] = f"{key}={val}"
                    replaced = True
                    break
            if not replaced:
                lines.append(f"{key}={val}")
        env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        console.print(f"\n[green]✅ Configuration saved to {env_path}[/green]")

    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Build Docker image: [bold]docker build -t miniondesk-agent:latest ./container[/bold]")
    console.print("  2. Run checks:         [bold]python run.py check[/bold]")
    console.print("  3. Start MinionDesk:   [bold]python run.py start[/bold]")


def _prompt(label: str, default: str = "") -> str:
    prompt = f"  {label}"
    if default:
        prompt += f" [{default}]"
    prompt += ": "
    try:
        val = input(prompt).strip()
        return val or default
    except (KeyboardInterrupt, EOFError):
        return default
