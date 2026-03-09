"""
Confluence & SharePoint Knowledge Base Crawler for MinionDesk.
Fetches pages from Confluence/SharePoint and ingests into the RAG knowledge base.
"""
from __future__ import annotations
import os
import json
import urllib.request
import urllib.parse
import urllib.error
import base64
import logging
import re
from typing import Optional

log = logging.getLogger(__name__)

_MAX_PAGE_CHARS = int(os.getenv("CONFLUENCE_MAX_PAGE_CHARS", "50000"))

# Confluence config
CONFLUENCE_URL = os.getenv("CONFLUENCE_URL", "").rstrip("/")         # https://corp.atlassian.net/wiki
CONFLUENCE_USER = os.getenv("CONFLUENCE_USER", "")
CONFLUENCE_TOKEN = os.getenv("CONFLUENCE_TOKEN", "")
CONFLUENCE_SPACES = os.getenv("CONFLUENCE_SPACES", "IT,HR,INFRA")  # comma-separated space keys

# SharePoint config
SHAREPOINT_URL = os.getenv("SHAREPOINT_URL", "").rstrip("/")         # https://corp.sharepoint.com/sites/IT
SHAREPOINT_TOKEN = os.getenv("SHAREPOINT_TOKEN", "")     # Azure AD access token


def _validate_confluence_url(url: str) -> None:
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        raise ValueError("CONFLUENCE_URL is not parseable")
    if p.scheme not in ("http", "https"):
        raise ValueError(f"CONFLUENCE_URL must use http/https, got: {p.scheme!r}")
    if not p.hostname:
        raise ValueError("CONFLUENCE_URL has no hostname")


def _confluence_headers() -> dict:
    creds = base64.b64encode(f"{CONFLUENCE_USER}:{CONFLUENCE_TOKEN}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Accept": "application/json"}


def _http_get(url: str, headers: dict) -> Optional[dict]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read(4 * 1024 * 1024).decode())
    except Exception as e:
        log.error(f"HTTP GET failed {url}: {e}")
        return None


def _strip_html(html: str) -> str:
    """Strip HTML tags and decode entities."""
    html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def fetch_confluence_pages(space_key: str, limit: int = 50) -> list[dict]:
    """
    Fetch pages from a Confluence space.
    Returns list of {"title": str, "content": str, "url": str}
    """
    try:
        _validate_confluence_url(CONFLUENCE_URL)
    except ValueError as e:
        log.error(f"Confluence misconfigured: {e}")
        return []

    if not space_key or not re.match(r'^[A-Za-z0-9_~\-]+$', space_key):
        log.warning(f"Invalid or empty space_key: {space_key!r}")
        return []

    if not (CONFLUENCE_URL and CONFLUENCE_USER and CONFLUENCE_TOKEN):
        log.warning("Confluence not configured")
        return []

    pages = []
    start = 0

    while True:
        params = urllib.parse.urlencode({
            "spaceKey": space_key, "type": "page", "status": "current",
            "expand": "body.storage,version", "limit": 25, "start": start
        })
        url = f"{CONFLUENCE_URL}/rest/api/content?{params}"

        result = _http_get(url, _confluence_headers())
        if not result:
            log.warning(f"Confluence fetch stopped at start={start}")
            break

        results = result.get("results", [])
        if not isinstance(results, list):
            log.warning(f"Unexpected results type from Confluence API: {type(results).__name__}")
            break
        if not results:
            break

        for page in results:
            title = page.get("title", "")
            body = page.get("body", {}).get("storage", {}).get("value", "")
            page_id = page.get("id", "")
            page_url = f"{CONFLUENCE_URL}/pages/{urllib.parse.quote(str(page.get('id', '')), safe='')}"

            if body:
                content = _strip_html(body)
                if len(content) > 50:  # Skip near-empty pages
                    pages.append({
                        "title": title,
                        "content": content[:_MAX_PAGE_CHARS],
                        "url": page_url,
                        "space": space_key,
                        "source": "confluence",
                    })
            if len(pages) >= limit:
                break

        next_link = result.get("_links", {}).get("next", "")
        if not next_link or len(pages) >= limit:
            break
        start += len(results)

    log.info(f"Fetched {len(pages)} pages from Confluence space {space_key}")
    return pages


def fetch_sharepoint_pages(site_url: str = "", limit: int = 50) -> list[dict]:
    """
    Fetch pages from SharePoint using Microsoft Graph API.
    """
    if not SHAREPOINT_TOKEN:
        log.warning("SharePoint token not configured")
        return []

    base = site_url or SHAREPOINT_URL
    if not base:
        return []
    try:
        _validate_confluence_url(base)
    except ValueError as e:
        log.error("SharePoint URL invalid: %s", e)
        return []

    headers = {
        "Authorization": f"Bearer {SHAREPOINT_TOKEN}",
        "Accept": "application/json",
    }

    pages = []

    # Use SharePoint REST API to get site pages
    api_url = f"{base}/_api/web/lists/getbytitle('Site Pages')/items?$select=Title,FileRef,Modified&$top=50"
    result = _http_get(api_url, headers)

    if not result:
        return []

    items = result.get("value", [])
    for item in items[:limit]:
        title = item.get("Title", "")
        safe_ref = item.get("FileRef", "")
        if title and safe_ref:
            # Validate file_ref is a relative path under the SharePoint site, not a traversal
            if not safe_ref.startswith("/") or ".." in safe_ref:
                log.warning("SharePoint: suspicious FileRef %r — skipping", safe_ref)
                continue
            # Additional: ensure it doesn't escape to another host or protocol
            if safe_ref.startswith("//") or ":" in safe_ref.split("/")[1]:
                log.warning("SharePoint: FileRef looks like absolute URL %r — skipping", safe_ref)
                continue
            encoded_ref = urllib.parse.quote(safe_ref, safe='/')
            content_url = f"{base}/_api/web/getfilebyserverrelativeurl('{encoded_ref}')/$value"
            try:
                req = urllib.request.Request(content_url, headers=headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw = resp.read(1024 * 1024).decode(errors="replace")
                    content = _strip_html(raw)
                    if len(content) > 50:
                        pages.append({
                            "title": title,
                            "content": content[:_MAX_PAGE_CHARS],
                            "url": f"{base}{urllib.parse.quote(safe_ref, safe='/')}",
                            "source": "sharepoint",
                        })
            except Exception as e:
                log.warning(f"Failed to fetch SharePoint page {safe_ref}: {e}")

    log.info(f"Fetched {len(pages)} pages from SharePoint")
    return pages


def ingest_to_kb(pages: list[dict], ctx=None) -> int:
    """
    Ingest fetched pages into MinionDesk knowledge base.
    Returns number of chunks ingested.
    """
    try:
        from host.enterprise.knowledge_base import ingest_document
    except ImportError:
        log.error("knowledge_base module not available")
        return 0

    total = 0
    for page in pages:
        title = page.get("title", "Untitled")
        content = page.get("content", "")
        source = page.get("source", "web")
        url = page.get("url", "")

        if not content:
            continue

        # Add source header for context
        safe_title = re.sub(r'[\x00-\x1f\x7f]', '', title)
        safe_url_str = re.sub(r'[\x00-\x1f\x7f]', '', url)
        full_text = f"# {safe_title}\n來源：{source} - {safe_url_str}\n\n{content}"

        try:
            # Split content into chunks (simple paragraph splitting)
            text_chunks = [c.strip() for c in full_text.split("\n\n") if c.strip()]
            if not text_chunks:
                text_chunks = [full_text]
            stored = ingest_document(safe_title, safe_url_str, text_chunks, source=source)
            total += stored
            log.info(f"Ingested '{title}' → {stored} chunks")
        except Exception as e:
            log.error(f"Failed to ingest '{title}': {e}")

    return total


def sync_confluence(ctx=None) -> dict:
    """
    Full sync: fetch all configured Confluence spaces and ingest into KB.
    # Note: this is a blocking function — call via asyncio.to_thread() from async contexts.
    """
    spaces = [s.strip() for s in CONFLUENCE_SPACES.split(",") if s.strip()]
    if not spaces:
        return {"error": "No CONFLUENCE_SPACES configured"}

    total_pages = 0
    total_chunks = 0

    for space in spaces:
        pages = fetch_confluence_pages(space)
        total_pages += len(pages)
        chunks = ingest_to_kb(pages, ctx=ctx)
        total_chunks += chunks

    result = {
        "spaces_synced": spaces,
        "pages_fetched": total_pages,
        "chunks_ingested": total_chunks,
    }
    log.info(f"Confluence sync complete: {result}")
    return result


def sync_sharepoint(ctx=None) -> dict:
    """Full sync: fetch SharePoint pages and ingest into KB.
    # Note: this is a blocking function — call via asyncio.to_thread() from async contexts.
    """
    pages = fetch_sharepoint_pages()
    if not pages:
        return {"error": "No SharePoint pages fetched (check SHAREPOINT_URL and SHAREPOINT_TOKEN)"}

    chunks = ingest_to_kb(pages, ctx=ctx)
    result = {"pages_fetched": len(pages), "chunks_ingested": chunks}
    log.info(f"SharePoint sync complete: {result}")
    return result
