"""
Knowledge Base: FTS5 trigram search with LIKE fallback for Chinese.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path

import logging
from .. import db, config

log = logging.getLogger(__name__)


def _file_hash(path: Path) -> str:
    """Return SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_hash_registry(data_dir: Path) -> dict:
    """Load the file hash registry (prevents duplicate ingestion)."""
    registry_path = data_dir / "kb_hashes.json"
    if registry_path.exists():
        try:
            return json.loads(registry_path.read_text())
        except Exception:
            return {}
    return {}


def _save_hash_registry(data_dir: Path, registry: dict) -> None:
    registry_path = data_dir / "kb_hashes.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, indent=2))


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def ingest_document(title: str, url: str, chunks: list[str], source: str = "confluence") -> int:
    """Store document chunks into the knowledge base. Returns number of chunks stored."""
    conn = db.get_conn()
    stored = 0
    for chunk in chunks:
        if not chunk or not chunk.strip():
            continue
        try:
            emb = _get_embedding(chunk)
            conn.execute(
                "INSERT OR REPLACE INTO kb_documents (title, url, chunk, embedding, source) VALUES (?,?,?,?,?)",
                (title, url, chunk.strip(), emb, source)
            )
            stored += 1
        except Exception as e:
            log.error("ingest_document chunk error: %s", type(e).__name__)
            log.debug("ingest_document detail: %s", e)
    conn.commit()
    return stored


def ingest_file(file_path: Path, source: str | None = None) -> int:
    """Ingest a text/markdown file into the knowledge base. Skips if hash unchanged."""
    # Deduplication: check file hash
    try:
        from host import config as _cfg
        _data_dir = getattr(_cfg, 'DATA_DIR', Path('.') / 'data')
        file_hash = _file_hash(file_path)
        registry = _get_hash_registry(_data_dir)
        str_path = str(file_path.resolve())
        if registry.get(str_path) == file_hash:
            print(f"[KB] Skipping {file_path.name} — unchanged (hash: {file_hash[:8]})")
            return 0
        # Will update registry after ingestion succeeds
    except Exception as _e:
        print(f"[KB] Hash check failed: {_e}, proceeding anyway")
        file_hash = None
        registry = None
        str_path = None
        _data_dir = None

    text = file_path.read_text(encoding="utf-8")
    source = source or str(file_path)
    title = file_path.stem

    chunks = _chunk_text(text)
    conn = db.get_conn()
    count = 0
    for chunk in chunks:
        conn.execute(
            "INSERT INTO kb_chunks (title, content, source) VALUES (?, ?, ?)",
            (title, chunk, source),
        )

        # Compute embedding for this chunk (optional, fails gracefully)
        try:
            emb = _get_embedding(chunk)
            emb_json = json.dumps(emb) if emb else None
        except Exception:
            emb_json = None

        conn.execute(
            "INSERT INTO kb_chunks_plain (title, content, source, embedding_json) VALUES (?, ?, ?, ?)",
            (title, chunk, source, emb_json),
        )
        count += 1
    conn.commit()

    # Update hash registry after successful ingestion
    if file_hash is not None and registry is not None and str_path is not None and _data_dir is not None:
        try:
            registry[str_path] = file_hash
            _save_hash_registry(_data_dir, registry)
        except Exception as _e:
            print(f"[KB] Failed to save hash registry: {_e}")

    return count


def ingest_directory(directory: Path) -> None:
    """Ingest all .md and .txt files in a directory."""
    for ext in ["*.md", "*.txt"]:
        for f in directory.glob(ext):
            ingest_file(f)


def search(query: str, limit: int = 5) -> list[dict]:
    """Search KB with FTS5 trigram (>=3 chars) or LIKE fallback."""
    conn = db.get_conn()
    results = []

    if len(query) >= 3:
        try:
            rows = conn.execute(
                "SELECT title, content, source FROM kb_chunks WHERE kb_chunks MATCH ? LIMIT ?",
                (query, limit),
            ).fetchall()
            results = [{"title": r[0], "content": r[1], "source": r[2]} for r in rows]
        except Exception:
            pass

    if not results:
        rows = conn.execute(
            "SELECT title, content, source FROM kb_chunks_plain WHERE content LIKE ? ESCAPE '\\' LIMIT ?",
            (f"%{_escape_like(query)}%", limit),
        ).fetchall()
        results = [{"title": r[0], "content": r[1], "source": r[2]} for r in rows]

    return results


def _chunk_text(text: str, max_size: int = 800, overlap_lines: int = 1) -> list[str]:
    """
    Split text into chunks respecting paragraph and sentence boundaries.
    Priority: split on double-newline (paragraphs) → single newline → sentence end → max_size.
    """
    if len(text) <= max_size:
        return [text.strip()] if text.strip() else []

    chunks: list[str] = []

    # First split by double newlines (paragraphs)
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    current_chunk: list[str] = []
    current_size = 0

    for para in paragraphs:
        para_size = len(para)

        # If single paragraph is too large, split by sentences
        if para_size > max_size:
            # Split by common sentence endings (handles Chinese 。！？ and English . ! ?)
            import re
            sentences = re.split(r'(?<=[。！？.!?])\s*', para)
            sentences = [s.strip() for s in sentences if s.strip()]

            for sent in sentences:
                if current_size + len(sent) + 1 > max_size and current_chunk:
                    chunks.append("\n".join(current_chunk))
                    # Keep last N lines as overlap
                    current_chunk = current_chunk[-overlap_lines:] if overlap_lines else []
                    current_size = sum(len(l) for l in current_chunk)
                current_chunk.append(sent)
                current_size += len(sent) + 1
        else:
            # Try to fit whole paragraph
            if current_size + para_size + 2 > max_size and current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = current_chunk[-overlap_lines:] if overlap_lines else []
                current_size = sum(len(l) for l in current_chunk)
            current_chunk.append(para)
            current_size += para_size + 2

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return [c for c in chunks if c.strip()]


# ── Semantic Search (optional) ─────────────────────────────────────────────

def _get_embedding(text: str) -> list[float] | None:
    """
    Get embedding for text. Tries multiple providers.
    Returns None if no embedding provider is available.
    """
    import os

    # Try OpenAI-compatible embeddings
    openai_key = os.getenv("OPENAI_API_KEY")
    openai_base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    if openai_key:
        try:
            import urllib.request
            import json as _json
            data = _json.dumps({
                "model": os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
                "input": text[:8000],
            }).encode()
            req = urllib.request.Request(
                f"{openai_base}/embeddings",
                data=data,
                headers={
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read(512 * 1024)  # cap at 512KB
                result = _json.loads(body)
                return result["data"][0]["embedding"]
        except Exception:
            pass

    # Try Ollama embeddings
    ollama_url = os.getenv("OLLAMA_URL")
    if ollama_url:
        try:
            import urllib.request
            import json as _json
            model = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
            data = _json.dumps({"model": model, "prompt": text[:8000]}).encode()
            req = urllib.request.Request(
                f"{ollama_url}/api/embeddings",
                data=data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read(512 * 1024)  # cap at 512KB
                result = _json.loads(body)
                return result.get("embedding")
        except Exception:
            pass

    return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def semantic_search(query: str, ctx=None, limit: int = 5) -> list[dict]:
    """
    Search the knowledge base using semantic similarity.
    Falls back to FTS5 text search if embeddings are unavailable.
    Results are returned as list of dicts with title, content, source, score.
    If ctx is provided, uses the shared connection from context; otherwise opens its own.
    """
    # Try semantic search
    query_embedding = _get_embedding(query)
    if query_embedding:
        try:
            conn = db.get_conn()
            # Get chunks that have stored embeddings
            rows = conn.execute(
                "SELECT title, content, source, embedding_json FROM kb_chunks_plain LIMIT 500"
            ).fetchall()

            scored = []
            for title, content, source, emb_json in rows:
                if not emb_json:
                    continue
                try:
                    import json as _json
                    chunk_emb = _json.loads(emb_json)
                    score = _cosine_similarity(query_embedding, chunk_emb)
                    scored.append((score, title, content, source))
                except Exception:
                    continue

            if scored:
                scored.sort(reverse=True)
                return [
                    {"title": t, "content": c, "source": s, "score": round(sc, 3)}
                    for sc, t, c, s in scored[:limit]
                ]
        except Exception:
            pass

    # Fallback: FTS5 text search
    conn = db.get_conn()
    results = []
    if len(query) >= 3:
        try:
            rows = conn.execute(
                "SELECT title, content, source FROM kb_chunks WHERE kb_chunks MATCH ? LIMIT ?",
                (query, limit),
            ).fetchall()
            results = [{"title": t, "content": c, "source": s, "score": 1.0} for t, c, s in rows]
        except Exception:
            pass
    if not results:
        rows = conn.execute(
            "SELECT title, content, source FROM kb_chunks_plain WHERE content LIKE ? ESCAPE '\\' LIMIT ?",
            (f"%{_escape_like(query)}%", limit),
        ).fetchall()
        results = [{"title": t, "content": c, "source": s, "score": 0.5} for t, c, s in rows]
    return results


def _get_db():
    """Get a read-only DB connection for knowledge base queries."""
    import sqlite3
    import os
    db_path = Path(os.getenv("DATA_DIR", "./data")) / "miniondesk.db"
    return sqlite3.connect(str(db_path))
