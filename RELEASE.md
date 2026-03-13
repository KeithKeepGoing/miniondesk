# v2.2.0 — Dashboard 全面補強

**Released**: 2026-03-13

全面補強 Admin Dashboard，從 8 個 API endpoint 擴展到 14 個，並新增 7 個頁籤 UI。

## 新功能

### 📋 任務管理
任務列表、狀態（active/cancelled/error）、一鍵取消。新增 `task_run_logs` 表記錄每次執行結果（狀態、耗時、錯誤訊息）。

### 💬 對話歷史瀏覽器
按群組瀏覽完整對話記錄，支援筆數限制。

### 🧠 記憶查看器
檢視每個群組的熱記憶（MEMORY.md 內容）與最近 7 天暖記憶日誌。

### 📚 知識庫瀏覽器
FTS5 全文搜尋 + 文件清單瀏覽，支援關鍵字即時搜尋。

## 新增 API Endpoints
- `GET /api/tasks` — 所有排程任務（可按群組篩選）
- `GET /api/task-runs` — 任務執行歷史（可按任務 ID / 群組篩選）
- `POST /api/tasks/{id}/cancel` — 取消任務
- `GET /api/messages` — 對話歷史（需指定 jid）
- `GET /api/memory` — 記憶查看（熱 + 暖）
- `GET /api/knowledge` — 知識庫搜尋

## DB 變更
- 新增 `task_run_logs` 表（`id`, `task_id`, `chat_jid`, `run_at`, `status`, `result`, `error`, `duration_ms`）
- 新增索引：`idx_task_run_logs_task_id`, `idx_task_run_logs_chat`

---

# v2.1.1 — Telegram 關機 CRITICAL 日誌修復

**Released**: 2026-03-13

修正關機時的誤導性 `CRITICAL CancelledError` 日誌。根本原因是關機順序：先取消 asyncio tasks 再 disconnect 頻道，導致 telegram library 把正常的 CancelledError 記錄為 CRITICAL。

修復：先 disconnect 頻道 → 再取消 tasks。

---

# v2.1.0 — 三層記憶系統

*Released*: 2026-03-13

## 新功能

三層記憶系統（參考 OpenClaw / MemSearch by Zilliz）讓小小兵真正記住你。

### 熱記憶（Hot Memory）
每次對話載入 per-chat MEMORY.md（8KB 上限）。小小兵可透過 `memory_patch` 欄位更新。

### 暖記憶（Warm Memory）
每次對話後自動追加日誌。保留 30 天，超過自動剪除。

### 冷記憶（Cold Memory）
SQLite FTS5 trigram 搜尋 + 時效性評分混合檢索。

### Weekly Compound
每週自動剪除低價值舊記憶，提煉知識至熱記憶。

## 其他改善
- 對話歷史窗口 10 → 50 則訊息
