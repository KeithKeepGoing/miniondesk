# Changelog

## [2.4.15] - 2026-03-16
### Added
- MEMORY.md 啟動注入：session 啟動時讀取 {data_dir}/MEMORY.md，注入為「長期記憶」section — 讓知識歸檔真正有效 (#167)
- 里程碑強制器：runner loop 追蹤 _turns_since_notify，超過 4 輪無 send_message 自動注入提醒 (#167)
- Level B 啟發式偵測：prompt 長度 > 200 或含關鍵字時代碼層面標記 Level B，輔助模型委派決策 (#167)

All notable changes to MinionDesk will be documented in this file.

## [2.4.14] - 2026-03-16
### Added
- `run_agent` tool: new container-side tool that spawns a sub-agent via IPC and returns its output (up to 300s)
- `host/main.py`: `on_ipc_task` handles `spawn_agent` type — runs `runner.run_container()` and writes result to IPC results dir
- `host/config.py`: `run_agent` added to DEFAULT_TOOLS
- Agent soul: `## 任務協調與智慧委派` rules appended to all persona system prompts
- Pre-flight analysis: Level A/B classification, smart delegation, MEMORY.md archiving, transparency rules (#165)

## [2.4.13] — 2026-03-16

### Fixed
- `container/runner/providers/__init__.py`: `BaseProvider.complete()` 加入 `force_tool: bool = False` 參數 (Fix #163)
- `container/runner/providers/openai_compat.py`: `force_tool=True` 時使用 `tool_choice="required"` — API 層面強制；不支援時自動降級 (Fix #163)
- `container/runner/runner.py`: 追蹤 `_no_tool_turns` 計數器，>0 時傳入 `force_tool=True` (Fix #163)
- `container/runner/runner.py`: 連續 3 次無 tool call → break loop，防止無限循環 (Fix #163)
- `container/runner/runner.py`: fake-status 偵測保留作為日誌，主要強制機制改為 `force_tool` (Fix #161+#163)

## [2.4.12] — 2026-03-16

### Fixed
- `container/runner/runner.py`: CRITICAL 系統提示加入第二條禁令 — 明確禁止 `*(正在執行...)*` 等假狀態行 (Fix #161)
- `container/runner/runner.py`: 新增 Fallback 2 — 偵測 `*(...)* ` 假狀態模式，自動 re-prompt 模型「請停止假裝，立刻呼叫 Bash tool」(Fix #161)

## [2.4.11] — 2026-03-14

### Fixed
- `host/runner.py`: 新增 `except asyncio.CancelledError` handler — shutdown 時 `task.cancel()` 觸發後直接呼叫 `proc.kill()` 殺死 Docker subprocess，不讓 container 繼續跑 (Fix #159)
- `host/main.py`: 第二次 Ctrl+C (SIGINT) → `docker ps` 找出所有 `miniondesk-` container + `docker kill` + 立即 `os._exit(1)` — 不再無限卡住 (Fix #159)
- `host/main.py`: `asyncio.gather(*tasks, ...)` 加 **5 秒 timeout** — task cleanup 本身卡住時不再永久阻塞 (Fix #159)
- `host/main.py`: signal handler 改用 `list[int]` 計數器取代 `nonlocal int` — 修復雙層 closure 無法正確 mutate 的 scoping bug (Fix #159)

## [2.4.10] — 2026-03-14

### Fixed
- `pyproject.toml`: 加入 `python-dotenv>=1.0.0` 為必要依賴 — 未安裝時 `.env` 不載入，導致 `GITHUB_TOKEN` 等所有 secrets 為空
- `run.py`: `load_dotenv()` ImportError 由靜默跳過改為 stderr 警告，明確提示用戶安裝 `python-dotenv`

## [2.4.9] — 2026-03-13

### Fixed
- `container/runner/runner.py`: 加入 bash code block 自動執行 fallback — 模型輸出 ` ```bash ` 代碼塊時自動偵測並執行，結果回饋 history 繼續迴圈
- `container/runner/runner.py`: 每個 persona 系統提示後加入 CRITICAL 工具警告 — 明確禁止輸出 code blocks，要求 ALWAYS call Bash tool directly

## [2.4.8] — 2026-03-13

### Added
- `.env.example`: 更新 `GITHUB_TOKEN` 說明，標示為必要設定，附 GitHub settings token 連結

## [2.4.7] — 2026-03-13

### Fixed
- `container/Dockerfile`: 安裝 GitHub CLI (`gh`)，修復 container 內 `gh: command not found` 根本原因
- `container/runner/runner.py`: `_ALLOWED_SECRET_KEYS` 加入 `GITHUB_TOKEN` / `GH_TOKEN`，修復 token 被過濾丟棄的問題
- `container/runner/runner.py`: `gh auth login` 成功後執行 `gh auth setup-git` + `git config user.email/user.name`

## [2.4.6] — 2026-03-13

### Fixed
- `host/config.py`: `get_secrets()` 加入 `GITHUB_TOKEN` / `GH_TOKEN`，修復 container 啟動時 gh CLI 永遠顯示 `⚠️ GH AUTH no GITHUB_TOKEN in secrets` 的根本原因

## [2.4.5] — 2026-03-13

### Fixed
- runner.py: secrets 設入 env 後自動執行 `gh auth login --with-token`，解決 gh CLI / git push 無憑證問題
- runner.py: 認證成功記錄 `🔑 GH AUTH gh CLI authenticated ✓`，失敗或 gh 未安裝亦有對應 `⚠️ GH AUTH` _slog 記錄

## [2.4.4] — 2026-03-13

### Added
- runner.py: 新增 🔧 TOOL / 🔧 RESULT `_slog` 記錄，在每次工具呼叫前後輸出到 stderr
- runner.py: tool args 和 result 截斷上限設為 1500 字元，可看到完整 bash command 和執行結果

## [2.4.3] — 2026-03-13

### Fixed
- runner.py: main() 加入 `logging.basicConfig(stream=sys.stderr)`，修復所有 log 完全靜音問題
- runner.py: 新增 `_slog()` structured log 函數（仿 EvoClaw 風格，帶 emoji tag）
- runner.py: run() 加入 USER / SYSTEM / HISTORY / LLM 呼叫 / REPLY 完整 log，Container Logs dashboard 現在可見輸出

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
