## [2.3.0] — 2026-03-13

### Added
- Dashboard 新增小小兵瀏覽器、功能總覽和使用統計三個頁籤
- **小小兵瀏覽器**：`GET /api/minions`，掃描 minions/*.md，提取名稱、說明、能力
- **功能總覽**：`GET /api/features`，掃描 enterprise/*.py + channels/*.py，列出模組與函數
- **使用統計**：`GET /api/usage`，群組訊息排行 + 任務執行統計（成功率、平均耗時）
- Dashboard UI 新增 🤖 Minions / ⚙️ Features / 📈 使用統計 三個頁籤

## [2.2.0] — 2026-03-13

### Added
- Dashboard 全面補強 — 從 8 個 API endpoint 擴展到 14 個
- **任務管理**：`GET /api/tasks`、`POST /api/tasks/{id}/cancel`
- **任務執行歷史**：`GET /api/task-runs`；新增 `task_run_logs` DB 表
- **對話歷史瀏覽器**：`GET /api/messages`，按群組瀏覽完整對話
- **記憶查看器**：`GET /api/memory`，熱記憶（MEMORY.md）+ 暖記憶日誌
- **知識庫瀏覽器**：`GET /api/knowledge`，FTS5 搜尋 + 文件列表
- Dashboard UI 新增 7 個頁籤（概覽/任務/對話/記憶/知識庫/工作流程/審計）
- `scheduler.py` 每次任務執行後自動記錄結果到 `task_run_logs`
- `db.py` 新增 `log_task_run()`、`get_task_run_logs()`、`get_kb_docs()` 函數
- KPI 卡片新增「排程任務」計數

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
