## [2.1.1] — 2026-03-13

### Fixed
- `host/main.py`: 關機順序修正 — 先斷開頻道再取消 asyncio tasks，消除 Telegram CRITICAL CancelledError 誤報 (#131)
- `host/channels/telegram.py`: `disconnect()` 各步驟獨立 try/except asyncio.CancelledError

## [2.1.0] — 2026-03-13

### Added
- Three-tier memory system (OpenClaw/MemSearch-inspired)
  - Hot Memory: per-chat MEMORY.md (8KB), injected into every container run via `hotMemory` field
  - Warm Memory: auto-appended daily log after each conversation, 30-day retention
  - Cold Memory: SQLite FTS5 + trigram tokenizer, hybrid search (BM25 70% + recency 30%)
  - Weekly Compound: prune old entries, distill patterns to hot memory
- `runner.py`: conversation history limit 10 → 50, hot memory injection, `memory_patch` parsing
- `host/memory/` module: hot, warm, search, compound submodules
