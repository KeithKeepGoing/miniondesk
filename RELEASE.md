# v2.4.1 — Container Logs Dashboard 全文 Stderr 展開查看器

**Released**: 2026-03-13

🐳 Container Logs 頁籤新增「📋 展開」按鈕，一鍵查看完整 Docker 容器 stderr 輸出。

## 新功能

### 📋 全文 Stderr Modal 查看器
每筆 Container Log 記錄新增「📋 展開」按鈕：
- 點擊後彈出 Modal，顯示完整 stderr（不截斷）
- Monospace 字體，可捲動，方便複製除錯資訊
- 使用 JS Map 暫存完整 log，避免重複 API 請求
- Stderr 預覽從最後 3 行增加到最後 5 行

---

# v2.4.0 — Container 執行 Log 持久化 + Dashboard 查看器

**Released**: 2026-03-13

小小兵 Container 的 stderr/stdout 現在完整記錄到 SQLite DB，並可在 Dashboard 的新頁籤中查看與篩選。

## 新功能

### 🐳 Container Logs DB 持久化
每次 `run_container()` 執行時，自動記錄到 `container_logs` 表：
- `run_id`：每次執行的唯一 ID（UUID 前 8 碼）
- `started_at` / `finished_at`：開始 / 結束 UNIX 時間戳
- `status`：`running` → `success` / `error` / `timeout`
- `stderr`：完整 stderr 輸出（最多 8192 字元）
- `stdout_preview`：stdout 前 200 字元（JSON 解析前）
- `response_ms`：Container 執行耗時（毫秒）

### 🐳 Dashboard Container Logs 頁籤
新增 `/api/container-logs` endpoint 與 Dashboard 頁籤，支援：
- 按群組（jid）篩選
- 按狀態（success / error / timeout / running）篩選
- 顯示最近 100 筆，含時間、群組、Minion、狀態、耗時、Stderr 摘要

## 新增 API Endpoints
- `GET /api/container-logs` — Container 執行記錄（支援 jid / status / limit 參數）

## DB 變更
- 新增 `container_logs` 表
- 新增索引：`idx_md_container_logs_jid`

---

# v2.3.0 — Dashboard 小小兵瀏覽器 + 功能總覽 + 使用統計

**Released**: 2026-03-13

Dashboard 新增三個分頁，讓管理員一眼掌握小小兵陣容、企業模組與系統使用狀況。

## 新功能

### 🤖 小小兵瀏覽器
掃描 `minions/*.md`，以卡片形式展示每個小小兵的名稱、說明和能力標籤。

### ⚙️ 功能總覽
掃描 `host/enterprise/*.py` 與 `host/channels/*.py`，列出企業模組與頻道模組的說明及函數清單。

### 📈 使用統計
- KPI 卡片：總訊息數、任務執行次數、成功率、平均耗時
- 群組訊息排行（Top 10 長條圖）
- 任務執行摘要表

## 新增 API Endpoints
- `GET /api/minions` — 小小兵清單
- `GET /api/features` — 企業 + 頻道模組清單
- `GET /api/usage` — 訊息 / 任務統計

---

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
