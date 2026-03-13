## [2.4.2] — 2026-03-13

### Fixed
- dashboard.py: showContainerLog 雙 key 查找修復 undefined 問題（numeric + string key fallback）
- db.py: stderr 儲存限制從 8KB 提升至 32KB

## [2.4.1] — 2026-03-13

### Added
- Dashboard 🐳 Container Logs 頁籤新增「📋 展開」按鈕，點擊後彈出 Modal 顯示完整 stderr
- Stderr 預覽從最後 3 行增加到最後 5 行
- Modal 以 Monospace 字體顯示完整 container log，可捲動，方便除錯
- 使用 JS Map (`_clFullLogs`) 暫存每筆記錄的完整 stderr，避免重複請求

## [2.4.0] — 2026-03-13

### Added
- 新增 `container_logs` 表，記錄每次小小兵 Container 執行的 stderr/stdout 預覽、耗時與狀態
- `db.py` 新增 `log_container_start()`、`log_container_finish()`、`get_container_logs()` 函數
- `runner.py` 在所有執行路徑（success / error / timeout / FileNotFoundError）記錄 Container Log
- Dashboard 新增 🐳 Container Logs 頁籤，支援按群組 / 狀態篩選
- 新增 `GET /api/container-logs` API endpoint（支援 jid / status / limit 參數）

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
