"""MinionDesk configuration — loaded from environment variables."""
from __future__ import annotations
import os
from pathlib import Path


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# Directories
BASE_DIR   = Path(_env("BASE_DIR", str(Path(__file__).parent.parent.parent)))
DATA_DIR   = Path(_env("DATA_DIR", str(BASE_DIR / "data")))
GROUPS_DIR = Path(_env("GROUPS_DIR", str(BASE_DIR / "groups")))
KNOWLEDGE_DIR = Path(_env("KNOWLEDGE_DIR", str(BASE_DIR / "knowledge")))
DB_PATH    = DATA_DIR / "miniondesk.db"

# Docker
CONTAINER_IMAGE   = _env("CONTAINER_IMAGE", "miniondesk-agent:latest")
CONTAINER_TIMEOUT = int(_env("CONTAINER_TIMEOUT", "300"))
CONTAINER_MAX_FAILS = int(_env("CONTAINER_MAX_FAILS", "5"))
CONTAINER_FAIL_COOLDOWN = float(_env("CONTAINER_FAIL_COOLDOWN", "60.0"))

# Channels
TELEGRAM_TOKEN = _env("TELEGRAM_TOKEN")
DISCORD_TOKEN  = _env("DISCORD_TOKEN")
TEAMS_WEBHOOK  = _env("TEAMS_WEBHOOK")

# Dashboard
DASHBOARD_HOST     = _env("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT     = int(_env("DASHBOARD_PORT", "8080"))
DASHBOARD_PASSWORD = _env("DASHBOARD_PASSWORD", "changeme")

# LLM (for host-side routing)
GOOGLE_API_KEY    = _env("GOOGLE_API_KEY")
ANTHROPIC_API_KEY = _env("ANTHROPIC_API_KEY")
OPENAI_API_KEY    = _env("OPENAI_API_KEY")

# Minions directory
MINIONS_DIR = BASE_DIR / "minions"

# Assistant identity
ASSISTANT_NAME = _env("ASSISTANT_NAME", "Mini")

# IPC polling interval
IPC_POLL_INTERVAL = float(_env("IPC_POLL_INTERVAL", "0.5"))

# Input sanitization
MAX_PROMPT_LENGTH = int(_env("MAX_PROMPT_LENGTH", "4000"))

# Container concurrency (max simultaneous Docker runs across all groups)
CONTAINER_MAX_CONCURRENT = int(_env("CONTAINER_MAX_CONCURRENT", "4"))
