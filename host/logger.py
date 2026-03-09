"""
MinionDesk Logging Configuration
Replaces scattered print() calls with structured logging.
"""
from __future__ import annotations
import logging
import logging.handlers
import os
from pathlib import Path


def setup_logging(
    level: str | None = None,
    log_file: Path | None = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10 MB
    backup_count: int = 5,
) -> None:
    """
    Configure root logger with console + optional rotating file handler.
    Call once at startup before any other imports.
    """
    log_level = getattr(logging, (level or os.getenv("LOG_LEVEL", "INFO")).upper(), logging.INFO)

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(log_level)

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    # Rotating file handler (optional)
    if log_file is None:
        data_dir = os.getenv("DATA_DIR", "./data")
        log_file = Path(data_dir) / "miniondesk.log"

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except Exception as e:
        logging.warning(f"Could not set up file logging: {e}")


def get_logger(name: str) -> logging.Logger:
    """Get a named logger. Use module __name__ as name."""
    return logging.getLogger(name)
