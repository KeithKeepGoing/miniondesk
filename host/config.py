"""
MinionDesk Host Configuration
"""
from __future__ import annotations
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data")))
IPC_DIR = Path(os.getenv("IPC_DIR", str(PROJECT_ROOT / "ipc")))
MINIONS_DIR = PROJECT_ROOT / "minions"
WORKFLOWS_DIR = PROJECT_ROOT / "workflows"
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"

# Docker
DOCKER_IMAGE = os.getenv("DOCKER_IMAGE", "miniondesk-runner:latest")
DOCKER_MEMORY = os.getenv("DOCKER_MEMORY", "512m")
DOCKER_NETWORK = os.getenv("DOCKER_NETWORK", "none")
CONTAINER_TIMEOUT = int(os.getenv("CONTAINER_TIMEOUT", "120"))

# Channels
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
TEAMS_APP_ID = os.getenv("TEAMS_APP_ID", "")
TEAMS_APP_PASSWORD = os.getenv("TEAMS_APP_PASSWORD", "")
TEAMS_WEBHOOK_PORT = int(os.getenv("TEAMS_WEBHOOK_PORT", "8443"))
WEBPORTAL_ENABLED = os.getenv("WEBPORTAL_ENABLED", "false").lower() == "true"
WEBPORTAL_PORT = int(os.getenv("WEBPORTAL_PORT", "8082"))

# ── Minions ───────────────────────────────────────────────────────────────────
# Single source of truth for available minions.
# Add new minions here; all channels will pick them up automatically.
AVAILABLE_MINIONS: list[str] = ["phil", "kevin", "stuart", "bob"]
DEFAULT_MINION: str = os.getenv("DEFAULT_MINION", "phil")

# Department → minion mapping
DEPT_MINION_MAP: dict[str, str] = {
    "hr": "kevin",
    "it": "stuart",
    "finance": "bob",
    "general": "phil",
}

# Tools available to minions by default
ROUTING_MODEL = os.getenv("ROUTING_MODEL", "claude-3-haiku-20240307")

DEFAULT_TOOLS = [
    "Bash", "Read", "Write", "Edit",
    "send_message", "schedule_task",
    "search_knowledge_base", "start_workflow", "check_workflow_status",
    "route_to_department",
    "create_meeting", "list_meetings", "find_free_slot",
    "read_emails", "draft_email_reply",
]


WEEKLY_REPORT_ENABLED = os.getenv("WEEKLY_REPORT_ENABLED", "false").lower() == "true"
WEEKLY_REPORT_DAY = int(os.getenv("WEEKLY_REPORT_DAY", "4"))
WEEKLY_REPORT_HOUR = int(os.getenv("WEEKLY_REPORT_HOUR", "17"))

# HPC / IC Design Infrastructure
HPC_LSF_HOST = os.getenv("HPC_LSF_HOST", "")
HPC_SLURM_HOST = os.getenv("HPC_SLURM_HOST", "")
FLEXLM_SERVER = os.getenv("FLEXLM_SERVER", "")
NAS_HOST = os.getenv("NAS_HOST", "")
HPC_SSH_KEY_PATH = os.getenv("HPC_SSH_KEY_PATH", "")

# NAS Deep API
NETAPP_URL = os.getenv("NETAPP_URL", "")
NETAPP_USER = os.getenv("NETAPP_USER", "admin")
NETAPP_PASSWORD = os.getenv("NETAPP_PASSWORD", "")
NETAPP_SVM = os.getenv("NETAPP_SVM", "")
GPFS_URL = os.getenv("GPFS_URL", "")
GPFS_USER = os.getenv("GPFS_USER", "admin")
GPFS_PASSWORD = os.getenv("GPFS_PASSWORD", "")
GPFS_FILESYSTEM = os.getenv("GPFS_FILESYSTEM", "")

# Enterprise Integrations
JIRA_URL = os.getenv("JIRA_URL", "")
JIRA_USER = os.getenv("JIRA_USER", "")
JIRA_TOKEN = os.getenv("JIRA_TOKEN", "")
JIRA_DEFAULT_PROJECT = os.getenv("JIRA_DEFAULT_PROJECT", "IT")
SERVICENOW_URL = os.getenv("SERVICENOW_URL", "")
SERVICENOW_USER = os.getenv("SERVICENOW_USER", "")
SERVICENOW_PASSWORD = os.getenv("SERVICENOW_PASSWORD", "")
GITLAB_URL = os.getenv("GITLAB_URL", "https://gitlab.com")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", "")


# Email
EMAIL_IMAP_HOST = os.getenv("EMAIL_IMAP_HOST", "")
EMAIL_IMAP_PORT = int(os.getenv("EMAIL_IMAP_PORT", "993"))
EMAIL_USER = os.getenv("EMAIL_USER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))
# IBM Notes / HCL Domino Mail
DOMINO_REST_URL = os.getenv("DOMINO_REST_URL", "")
DOMINO_REST_USER = os.getenv("DOMINO_REST_USER", "")
DOMINO_REST_PASSWORD = os.getenv("DOMINO_REST_PASSWORD", "")
DOMINO_DATABASE = os.getenv("DOMINO_DATABASE", "")
NOTES_IMAP_HOST = os.getenv("NOTES_IMAP_HOST", "")
NOTES_IMAP_PORT = int(os.getenv("NOTES_IMAP_PORT", "993"))
NOTES_USER = os.getenv("NOTES_USER", "")
NOTES_PASSWORD = os.getenv("NOTES_PASSWORD", "")
NOTES_SERVER = os.getenv("NOTES_SERVER", "")
NOTES_MAILDB = os.getenv("NOTES_MAILDB", "")
# Jira Webhook
JIRA_WEBHOOK_ENABLED = os.getenv("JIRA_WEBHOOK_ENABLED", "false").lower() == "true"
JIRA_WEBHOOK_PORT = int(os.getenv("JIRA_WEBHOOK_PORT", "8083"))
JIRA_WEBHOOK_SECRET = os.getenv("JIRA_WEBHOOK_SECRET", "")
# Admin Dashboard
DASHBOARD_ENABLED = os.getenv("DASHBOARD_ENABLED", "false").lower() == "true"
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8084"))
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")


def validate() -> list[str]:
    """Return a list of configuration warnings/errors."""
    issues = []

    # Check at least one LLM provider
    has_provider = any([
        os.getenv("ANTHROPIC_API_KEY"),
        os.getenv("GOOGLE_API_KEY"),
        os.getenv("OPENAI_API_KEY"),
        os.getenv("OLLAMA_URL"),
        os.getenv("OPENAI_BASE_URL"),
    ])
    if not has_provider:
        issues.append("ERROR: No LLM provider configured (ANTHROPIC_API_KEY / GOOGLE_API_KEY / OPENAI_API_KEY / OLLAMA_URL)")

    # Check at least one channel
    has_channel = any([
        os.getenv("TELEGRAM_TOKEN"),
        os.getenv("DISCORD_TOKEN"),
        os.getenv("TEAMS_APP_ID"),
    ])
    if not has_channel:
        issues.append("WARNING: No messaging channel configured (TELEGRAM_TOKEN / DISCORD_TOKEN / TEAMS_APP_ID)")

    # Check data dir
    if not DATA_DIR.exists():
        try:
            DATA_DIR.mkdir(parents=True)
        except Exception as e:
            issues.append(f"ERROR: Cannot create data directory {DATA_DIR}: {e}")

    # Check minions dir
    for minion in AVAILABLE_MINIONS:
        persona = MINIONS_DIR / f"{minion}.md"
        if not persona.exists():
            issues.append(f"WARNING: Missing persona file: {persona}")

    return issues


def get_secrets() -> dict:
    """Collect all API keys for injection into container stdin (not env vars)."""
    secrets = {}
    for key in [
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "OLLAMA_URL",
        "OPENAI_BASE_URL",
        "OLLAMA_MODEL",
        "LLM_PROVIDER",
        "CLAUDE_MODEL",
        "GEMINI_MODEL",
        "OPENAI_MODEL",
        "GITHUB_TOKEN",
        "GH_TOKEN",
    ]:
        val = os.getenv(key, "")
        if val:
            secrets[key] = val
    return secrets
