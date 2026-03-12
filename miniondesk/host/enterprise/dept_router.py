"""Department-based message routing."""
from __future__ import annotations
import logging
import re

logger = logging.getLogger(__name__)

# Keyword → minion mapping (English + 繁體中文)
DEPT_KEYWORDS: dict[str, list[str]] = {
    "kevin": [
        # English
        "leave", "vacation", "hr", "hiring", "salary", "payroll", "employee", "onboard",
        # 繁體中文
        "請假", "年假", "病假", "特休", "人資", "招募", "薪資", "薪水", "員工", "入職", "離職",
        "出勤", "考勤", "福利", "保險", "勞健保",
    ],
    "stuart": [
        # English
        "laptop", "vpn", "password", "network", "software", "install", "it", "computer", "ticket",
        # 繁體中文
        "電腦", "筆電", "網路", "密碼", "系統", "軟體", "安裝", "帳號", "工單", "設備",
        "印表機", "手機", "WIFI", "wifi", "斷線", "當機", "重開機", "藍芽",
    ],
    "bob": [
        # English
        "expense", "invoice", "budget", "reimburse", "payment", "finance", "purchase",
        # 繁體中文
        "報銷", "發票", "費用", "預算", "採購", "付款", "財務", "核銷", "收據", "報帳",
        "支出", "帳單", "請款", "匯款",
    ],
    "mini": [],  # default
}


def route_to_minion(text: str) -> str:
    """Determine which minion should handle the message based on keywords."""
    text_lower = text.lower()
    scores: dict[str, int] = {minion: 0 for minion in DEPT_KEYWORDS}
    for minion, keywords in DEPT_KEYWORDS.items():
        for kw in keywords:
            # Use simple substring match for CJK (no word boundaries needed)
            if kw in text_lower:
                scores[minion] += 1
            elif re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
                scores[minion] += 1
    best = max(scores, key=lambda m: scores[m])
    if scores[best] == 0:
        return "mini"
    logger.info("Dept router: '%s...' → %s (score=%d)", text[:50], best, scores[best])
    return best
