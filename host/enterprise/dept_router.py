"""
Department Router: keyword scoring + fallback to LLM for routing decisions.
"""
from __future__ import annotations
import re

DEPT_KEYWORDS: dict[str, list[str]] = {
    "hr": [
        "假", "leave", "休假", "年假", "病假", "薪資", "salary", "payroll",
        "HR", "人資", "員工", "onboard", "offboard", "resignation", "離職",
        "招募", "recruit", "福利", "benefit", "考勤", "attendance",
    ],
    "it": [
        "電腦", "computer", "laptop", "wifi", "網路", "network", "VPN",
        "系統", "system", "軟體", "software", "硬體", "hardware",
        "帳號", "account", "密碼", "password", "IT", "資訊", "bug",
        "設備", "device", "安裝", "install", "權限", "permission",
    ],
    "finance": [
        "費用", "expense", "報帳", "reimbursement", "發票", "invoice",
        "預算", "budget", "採購", "procurement", "付款", "payment",
        "財務", "finance", "accounting", "帳務", "稅", "tax",
    ],
}


def route(text: str) -> str:
    """Return department name: hr | it | finance | general."""
    text_lower = text.lower()
    scores: dict[str, int] = {"hr": 0, "it": 0, "finance": 0}

    for dept, keywords in DEPT_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in text_lower:
                scores[dept] += 1

    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else "general"


def route_with_score(text: str) -> tuple[str, int]:
    """
    Return (department, confidence_score) based on keyword matching.
    Higher score = more confident match.
    """
    text_lower = text.lower()
    scores: dict[str, int] = {"hr": 0, "it": 0, "finance": 0, "general": 0}

    for dept, kws in DEPT_KEYWORDS.items():
        for kw in kws:
            if kw.lower() in text_lower:
                scores[dept] = scores.get(dept, 0) + 1

    best_dept = max(scores, key=lambda d: scores[d])
    best_score = scores[best_dept]
    # Return "general" when no keywords matched (score=0 = no signal)
    return ("general", 0) if best_score == 0 else (best_dept, best_score)


async def route_with_llm(text: str, fallback: str = "general") -> str:
    """
    Route a message to a department using LLM for ambiguous cases.
    First tries keyword matching; if confidence is low, asks the LLM.

    Uses run_in_executor to avoid blocking the asyncio event loop.
    """
    import asyncio
    import os
    from .. import config

    # Try keyword routing first (always fast, no I/O)
    dept, score = route_with_score(text)
    if score >= 2:
        return dept

    # LLM fallback — run sync clients in thread pool
    prompt = (
        "You are a department router for an enterprise AI assistant.\n"
        "Route this message to exactly one department: hr, it, finance, general\n\n"
        "hr = leave, salary, benefits, hiring, HR\n"
        "it = computer, software, hardware, network, VPN, password, device, IT\n"
        "finance = expense, budget, invoice, purchase, reimbursement, payment\n"
        "general = everything else\n\n"
        f"Message: {text[:500]}\n\n"
        "Reply with ONLY one word: hr, it, finance, or general"
    )

    valid_depts = {"hr", "it", "finance", "general"}
    loop = asyncio.get_event_loop()

    # Try Claude (async-wrapped)
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            def _claude():
                import anthropic
                client = anthropic.Anthropic()
                resp = client.messages.create(
                    model=config.ROUTING_MODEL,
                    max_tokens=10,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.content[0].text.strip().lower()

            result = await loop.run_in_executor(None, _claude)
            if result in valid_depts:
                return result
        except Exception as e:
            pass  # Fall through to next provider

    # Try Gemini (async-wrapped)
    if os.getenv("GOOGLE_API_KEY"):
        try:
            def _gemini():
                import google.generativeai as genai
                genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
                model = genai.GenerativeModel("gemini-2.0-flash-exp")
                resp = model.generate_content(prompt)
                return resp.text.strip().lower()

            result = await loop.run_in_executor(None, _gemini)
            if result in valid_depts:
                return result
        except Exception:
            pass

    # Try OpenAI (async-wrapped)
    if os.getenv("OPENAI_API_KEY"):
        try:
            def _openai():
                from openai import OpenAI
                client = OpenAI()
                resp = client.chat.completions.create(
                    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    max_tokens=10,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content.strip().lower()

            result = await loop.run_in_executor(None, _openai)
            if result in valid_depts:
                return result
        except Exception:
            pass

    return fallback
