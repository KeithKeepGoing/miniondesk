"""Enterprise knowledge base — FTS5 + LIKE search."""
from __future__ import annotations
import logging
import os
from pathlib import Path

from .. import config, db

logger = logging.getLogger(__name__)


def index_document(title: str, content: str, source: str = "", dept: str = "") -> int:
    """Add a document to the knowledge base."""
    rowid = db.kb_add(title, content, source, dept)
    logger.info("Indexed document #%d: %s", rowid, title)
    return rowid


def search(query: str, limit: int = 5, dept: str = "") -> list[dict]:
    """Search the knowledge base."""
    results = db.kb_search(query, limit, dept)
    return [
        {"id": r["id"], "title": r["title"], "snippet": r["content"][:300], "dept": r.get("dept", "")}
        for r in results
    ]


def ingest_directory(directory: str | Path, dept: str = "", extensions: list[str] | None = None) -> int:
    """Ingest all files from a directory into the knowledge base."""
    directory = Path(directory)
    extensions = extensions or [".md", ".txt", ".rst"]
    count = 0
    for f in directory.rglob("*"):
        if f.suffix.lower() in extensions and f.is_file():
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                index_document(f.stem, content, source=str(f), dept=dept)
                count += 1
            except Exception as exc:
                logger.warning("Failed to ingest %s: %s", f, exc)
    logger.info("Ingested %d documents from %s", count, directory)
    return count
