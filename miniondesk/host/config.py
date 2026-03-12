"""MinionDesk configuration — loaded from environment variables."""
from __future__ import annotations
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _int_env(key: str, default: int) -> int:
    """Read an integer env var; fall back to default and warn on bad value."""
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Config: %s=%r is not a valid integer, using default %d", key, raw, default)
        return default


def _float_env(key: str, default: float) -> float:
    """Read a float env var; fall back to default and warn on bad value."""
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Config: %s=%r is not a valid float, using default %f", key, raw, default)
        return default


# Directories
BASE_DIR   = Path(_env("BASE_DIR", str(Path(__file__).parent.parent.parent)))
DATA_DIR   = Path(_env("DATA_DIR", str(BASE_DIR / "data")))
GROUPS_DIR = Path(_env("GROUPS_DIR", str(BASE_DIR / "groups")))
KNOWLEDGE_DIR = Path(_env("KNOWLEDGE_DIR", str(BASE_DIR / "knowledge")))
DB_PATH    = DATA_DIR / "miniondesk.db"

# Docker
CONTAINER_IMAGE   = _env("CONTAINER_IMAGE", "miniondesk-agent:1.2.11")
CONTAINER_TIMEOUT = _int_env("CONTAINER_TIMEOUT", 300)
CONTAINER_MAX_FAILS = _int_env("CONTAINER_MAX_FAILS", 5)
CONTAINER_FAIL_COOLDOWN = _float_env("CONTAINER_FAIL_COOLDOWN", 60.0)

# Channels
TELEGRAM_TOKEN = _env("TELEGRAM_TOKEN")
DISCORD_TOKEN  = _env("DISCORD_TOKEN")
TEAMS_WEBHOOK  = _env("TEAMS_WEBHOOK")

# Dashboard
DASHBOARD_HOST     = _env("DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT     = _int_env("DASHBOARD_PORT", 8080)
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
IPC_POLL_INTERVAL = _float_env("IPC_POLL_INTERVAL", 0.5)

# Input sanitization
MAX_PROMPT_LENGTH = _int_env("MAX_PROMPT_LENGTH", 4000)

# Container concurrency (max simultaneous Docker runs across all groups)
CONTAINER_MAX_CONCURRENT = _int_env("CONTAINER_MAX_CONCURRENT", 4)

# Per-group message queue backpressure limit
# Messages submitted when the queue is at this depth are dropped with a WARNING
QUEUE_MAX_PER_GROUP = _int_env("QUEUE_MAX_PER_GROUP", 50)

# Container stdout size limit in bytes (prevents OOM from runaway containers)
# Default: 10MB. Set to 0 to disable (not recommended).
CONTAINER_MAX_OUTPUT_BYTES = _int_env("CONTAINER_MAX_OUTPUT_BYTES", 10 * 1024 * 1024)


def validate() -> None:
    """Fail-fast startup validation of critical config values.

    Call this from main.py before starting any services. Logs warnings for
    non-fatal misconfigurations and raises ValueError for fatal ones.
    """
    errors: list[str] = []

    # At least one channel token must be configured
    if not TELEGRAM_TOKEN and not DISCORD_TOKEN and not TEAMS_WEBHOOK:
        logger.warning(
            "Config: No channel token set (TELEGRAM_TOKEN / DISCORD_TOKEN / TEAMS_WEBHOOK). "
            "MinionDesk will start but cannot receive messages."
        )

    # At least one LLM API key must be configured (container needs one)
    llm_keys = [
        ("GOOGLE_API_KEY", GOOGLE_API_KEY),
        ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
        ("OPENAI_API_KEY", OPENAI_API_KEY),
    ]
    ollama_url = _env("OLLAMA_URL")
    openai_base = _env("OPENAI_BASE_URL")
    if not any(v for _, v in llm_keys) and not ollama_url and not openai_base:
        logger.warning(
            "Config: No LLM API key set. Set one of: %s, OLLAMA_URL, or OPENAI_BASE_URL.",
            ", ".join(k for k, _ in llm_keys),
        )

    # Numeric bounds checks
    if CONTAINER_TIMEOUT <= 0:
        errors.append(f"CONTAINER_TIMEOUT must be > 0, got {CONTAINER_TIMEOUT}")
    if CONTAINER_MAX_CONCURRENT <= 0:
        errors.append(f"CONTAINER_MAX_CONCURRENT must be > 0, got {CONTAINER_MAX_CONCURRENT}")
    if QUEUE_MAX_PER_GROUP <= 0:
        errors.append(f"QUEUE_MAX_PER_GROUP must be > 0, got {QUEUE_MAX_PER_GROUP}")
    if MAX_PROMPT_LENGTH <= 0:
        errors.append(f"MAX_PROMPT_LENGTH must be > 0, got {MAX_PROMPT_LENGTH}")

    # Directory existence / writability checks
    if not MINIONS_DIR.exists():
        logger.warning(
            "Config: MINIONS_DIR=%s does not exist. "
            "Minion personas will fall back to the default 'helpful assistant' prompt.",
            MINIONS_DIR,
        )

    # Check that DATA_DIR parent is writable so the DB file can be created.
    # A read-only BASE_DIR (e.g., Docker image layer without a volume) produces a
    # PermissionError with no user-friendly guidance — surface it here instead.
    data_parent = DATA_DIR.parent
    import os as _os
    if data_parent.exists() and not _os.access(str(data_parent), _os.W_OK):
        errors.append(
            f"DATA_DIR parent '{data_parent}' is not writable. "
            "Mount a writable volume or set DATA_DIR to a writable path."
        )

    if errors:
        for e in errors:
            logger.error("Config validation error: %s", e)
        raise ValueError(f"MinionDesk config validation failed: {'; '.join(errors)}")
