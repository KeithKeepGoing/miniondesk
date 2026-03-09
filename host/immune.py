"""
MinionDesk Immune System
Detects prompt injection and jailbreak attempts, and IC design DLP violations.
Inspired by EvoClaw's immune.py pattern.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ThreatResult:
    blocked: bool
    reason: str = ""
    pattern: str = ""


# Injection/jailbreak patterns (zh + en)
# Format: (regex_str, name, blocked)
_PATTERNS: list[tuple[str, str, bool]] = [
    # Role/identity override
    (r"(?i)(ignore|forget|disregard)\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?|guidelines?)", "role_override_en", True),
    (r"(忽略|無視|忘記|不管).{0,10}(之前|先前|上面|所有).{0,10}(指令|規則|提示|設定)", "role_override_zh", True),
    # System prompt extraction
    (r"(?i)(reveal|show|print|output|repeat|display)\s+(your\s+)?(system\s+prompt|initial\s+prompt|instructions?)", "prompt_extraction", True),
    (r"(告訴我|輸出|顯示|重複).{0,10}(系統提示|system prompt|初始指令|你的指令)", "prompt_extraction_zh", True),
    # New persona injection
    (r"(?i)(you are now|act as|pretend (to be|you are)|roleplay as|from now on you)", "persona_injection", True),
    (r"(你現在是|假裝你是|扮演|從現在起你是)", "persona_injection_zh", True),
    # Jailbreak attempts
    (r"(?i)(DAN|do anything now|developer mode|jailbreak|bypass (safety|filter|restriction))", "jailbreak", True),
    (r"(越獄|繞過安全|解除限制|開發者模式)", "jailbreak_zh", True),
    # Command injection
    (r"(?i)(\$\(|\`|&&|\|\|)\s*(rm|curl|wget|bash|sh|python|exec)", "cmd_injection", True),
    # SQL injection in natural text
    (r"(?i)(union\s+select|drop\s+table|insert\s+into|delete\s+from|exec\s*\()", "sql_injection", True),
    # Repeated token attack
    (r"(.)\1{200,}", "token_flood", True),
    # Override Chinese
    (r"(不用|不需要|不要).{0,5}(管|遵守|理會).{0,10}(規定|規則|限制|指令)", "rule_bypass_zh", True),

    # --- IC Design DLP Rules ---
    # RTL / Netlist — blocked (sensitive IP)
    (r"\b(module|endmodule)\s+\w+", "dlp_rtl_module", True),
    (r"\b(wire|reg|logic)\s+(\[[\d:]+\]\s+)?\w+\s*[,;]", "dlp_rtl_signal", True),
    (r"`(timescale|define|include)\s+", "dlp_verilog_preprocessor", True),
    (r"\.v\b.*\b(always|assign|initial)\b", "dlp_verilog_behavioral", True),
    (r"\b(GDSII|GDS2|\.gds)\b", "dlp_gds_layout", True),
    # Financial / cost — blocked
    (r"\bNRE\s*[:\$]?\s*[\d,]+[KkMm]?\b", "dlp_nre_cost", True),
    (r"\b(unit price|ASP|BOM cost)\s*[:\$]?\s*[\d,.]+", "dlp_pricing_cost", True),
    (r"\b(revenue|forecast|shipment)\s+\w+\s*[\d,]+[KkMm]?\b", "dlp_financial_forecast", True),
    # Design milestones / foundry NDA / SPICE — warning only (blocked=False)
    (r"\bTape.?out\b.*\b(date|schedule|plan|Q[1-4])\b", "dlp_tapeout_schedule", False),
    (r"\b(RTL|netlist|schematic)\s+(freeze|sign.?off|handoff)\b", "dlp_design_milestone", False),
    (r"\bFoundry\s+(NDA|agreement|contract)\b", "dlp_foundry_nda", False),
    (r"\b(SPICE|hspice|spectre)\s+netlist\b", "dlp_spice_netlist", False),
]

_COMPILED = [(re.compile(p), name, blocked) for p, name, blocked in _PATTERNS]


def scan(text: str) -> ThreatResult:
    """Scan a message for injection/jailbreak patterns and IC design DLP violations."""
    if not text:
        return ThreatResult(blocked=False)

    for pattern, name, blocked in _COMPILED:
        if pattern.search(text):
            if blocked:
                return ThreatResult(
                    blocked=True,
                    reason=f"偵測到潛在惡意指令（{name}），訊息已被封鎖。",
                    pattern=name,
                )
            else:
                # Warning-only: return non-blocked result with reason populated
                return ThreatResult(
                    blocked=False,
                    reason=f"DLP警告（{name}）：偵測到敏感設計資訊，請謹慎分享。",
                    pattern=name,
                )
    return ThreatResult(blocked=False)
