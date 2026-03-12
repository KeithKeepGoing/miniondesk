"""
web_search — DuckDuckGo Instant Answer tool for MinionDesk containers.
Installed by the web-search Skill. Auto-loaded from /app/dynamic_tools/.
No API key required.
"""
import json
import urllib.request
import urllib.parse

# ── Register with tool registry (executed at import time) ─────────────────────
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # reach runner/
try:
    from tools import Tool, register_tool
except ImportError:
    # Fallback if path not set up yet — tool will be registered when tools module loads
    Tool = None
    register_tool = None


def _web_search(args: dict, ctx: dict) -> str:
    query = str(args.get("query", "")).strip()
    if not query:
        return json.dumps({"error": "query is required"})
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_redirect=1&no_html=1"
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = []
        # Abstract (instant answer)
        if data.get("AbstractText"):
            results.append({
                "type": "abstract",
                "text": data["AbstractText"],
                "source": data.get("AbstractSource", ""),
                "url": data.get("AbstractURL", ""),
            })
        # Related topics (top 5)
        for topic in data.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "type": "topic",
                    "text": topic["Text"],
                    "url": topic.get("FirstURL", ""),
                })
        if not results:
            return json.dumps({"results": [], "note": "No instant answer found. Try a more specific query."})
        return json.dumps({"results": results}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": str(exc)})


if Tool and register_tool:
    register_tool(Tool(
        name="web_search",
        description="Search the web using DuckDuckGo. Returns instant answers and related topics. Use for current events, facts, and live data.",
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query. Be specific and concise.",
                }
            },
            "required": ["query"],
        },
        execute=_web_search,
    ))
