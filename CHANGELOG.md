# Changelog

All notable changes to MinionDesk will be documented in this file.

---

## [1.2.8] - 2026-03-12

### Reliability, Correctness, and Security Improvements (Fifth Round)

- `dashboard.py`: Fixed SSE 503 response sent after HTTP 200 headers were already committed — guard now runs before `send_response(200)` so browsers receive a real 503 and back off (#43)
- `container/runner/tools/messaging.py` + `enterprise.py`: IPC files now written atomically via `.tmp` + `os.rename()` to prevent host reading partially-written files (TOCTOU race) that caused silent message loss under load (#44)
- `providers/auto.py`: Removed silent fallback to `localhost:11434` when no LLM is configured — now raises `RuntimeError` with a clear actionable message instead of producing cryptic connection-refused errors in production (#45)
- `db.py`: `add_message()` and `record_evolution_run()` now assign `conn = _conn()` once and reuse it for both `execute()` and `commit()`, eliminating the two-call pattern where a future reconnect could skip the commit (#46)
- `evolution.py`: `changed` check now includes `fitness_score` delta so the dashboard always reflects actual recent performance even when style/formality/depth dimensions are stable (#47)
- `runner.py` (host): On `CancelledError`, `proc.kill()` is called on the subprocess handle before `docker stop`, and the circuit-breaker failure counter is incremented — prevents zombie containers and undercounted failures (#48)
- `skills_engine.py`: `install_skill()` now rolls back all copied files on any mid-install failure, preventing partial-install state that bypassed collision detection on retry (#49)
- `scheduler.py`: `once` tasks are no longer deleted before dispatch completes — deletion now happens in the done callback on success, preventing silent loss of one-time tasks on container failure (#50)
- `config.py`: Default `CONTAINER_IMAGE` updated to `miniondesk-agent:1.2.8`; startup now logs the active image tag so operators can verify host/container alignment (#51)
- `ipc.py`: Added handlers for `kb_search`, `workflow_trigger`, and `calendar_check` IPC types that were silently discarded (enterprise tools were effectively broken) (#52)
- `miniondesk/__init__.py`: Version bumped to 1.2.8

---

## [1.2.7] - 2026-03-12

### Reliability and Edge Case Improvements (Fourth Round)

- `dev_engine.py`: Added concurrency guard in `start_dev_session()` — checks for an existing `pending`/`running` session before creating a new one, preventing parallel pipelines from corrupting artifacts for the same group (#34)
- `dev_engine.py`: Removed fragile string-replace path sanitization in `_parse_file_blocks()`; rely solely on the already-correct `resolve().relative_to()` check in `_deploy_files()` to prevent the `....//` bypass pattern (#37)
- `runner.py` (host): Container names now include milliseconds + 6-char UUID suffix (`minion-{folder}-{ms}-{uuid}`) to prevent Docker name collisions when two requests arrive within the same second (#36)
- `scheduler.py`: `add_task()` now raises `ValueError` for invalid cron/interval expressions (using `croniter.is_valid()`) instead of silently saving a task with `next_run=NULL` that never fires; interval values validated to be positive (#35)
- `ipc.py`: `schedule_task` IPC handler now catches `ValueError` from `add_task` and reports the error to the user; skill install/uninstall handlers now run in `asyncio.run_in_executor` to avoid blocking the event loop (#41)
- `db.py`: `update_genome()` now clamps `formality`, `technical_depth`, and `fitness_score` to `[0.0, 1.0]` via `_clamp01()` helper, preventing out-of-range values from breaking dashboard display (#39)
- `db.py`: `delete_group()` now atomically deletes all related rows across `messages`, `tasks`, `genome`, `evolution_runs`, `evolution_log`, `immune_threats`, and `dev_sessions` tables in a single transaction (#38)
- `dashboard.py`: SSE `/api/logs/stream` now enforces a `_MAX_SSE_CLIENTS=20` cap; excess connections receive HTTP 503 instead of silently consuming memory and file descriptors (#40)
- `config.py`: Default `CONTAINER_IMAGE` updated to `miniondesk-agent:1.2.7`
- `miniondesk/__init__.py`: Version bumped to 1.2.7

---

## [1.2.6] - 2026-03-12

### Security and Reliability Improvements (Third Round)

- `skills_engine.py`: `install_skill()` 的 `adds` 檔案路徑加入 `relative_to()` 路徑穿越防護，與 `dev_engine._deploy_files()` 一致；`container_tools` 加入檔名安全檢查及同名衝突偵測，拒絕安裝會覆蓋已安裝技能工具的技能（#24, #28）
- `dashboard.py`: 實作 HTTP Basic Auth，`DASHBOARD_PASSWORD` 設定值現已正確強制執行；所有端點在憑證不符時回傳 401；修正群組名稱、JID、folder、minion、trigger 等欄位在 `innerHTML` 中未轉義的 XSS 漏洞（#25, #30）
- `immune.py`: 修正 `_sender_timestamps` 字典鍵永不刪除導致的記憶體洩漏；滑動視窗過期後空列表對應的鍵現在會被清除（#27）
- `workflow.py`: `trigger_workflow()` 的 `step.message.format(**data)` 改為 `string.Template.safe_substitute()`，防止使用者控制資料觸發 format string injection（#29）
- `runner.py`（host）: semaphore 現在持有整個容器生命週期（spawn + communicate），而非僅在 spawn 時，使 `CONTAINER_MAX_CONCURRENT` 真正限制同時執行的容器數量（#31）
- `scheduler.py` + `db.py`: 新增每任務連續失敗計數器；循環任務連續失敗 `_MAX_CONSECUTIVE_FAILURES`（預設 5）次後自動設為 `suspended` 狀態，防止失效任務無限重試消耗資源（#26）
- `runner.py`（container）: `sys.stdin.read()` 改為在執行器中以非阻塞方式執行並加入 30 秒逾時，防止阻塞 asyncio event loop 及主機部分寫入時永久掛起（#23）
- `db.py`: 新增 `suspend_task()` 函數；`delete_group()` 改為單次 `_conn()` 呼叫避免潛在不一致（#32）
- `miniondesk/__init__.py`: 版本號更新為 1.2.6

---

## [1.2.5] - 2026-03-12

### Architecture Improvements (Second Round)

- `ipc.py`：`dev_task` handler 中的 `asyncio.ensure_future` 改為 `asyncio.create_task` 並加入 done callback，確保例外不被靜默丟失（#12）
- `scheduler.py`：task dispatch 中剩餘的 `asyncio.ensure_future` 改為 `asyncio.create_task` 並加入 done callback（#13）
- `queue.py`：`GroupQueue` 由無界改為有界佇列（`maxsize=QUEUE_MAX_PER_GROUP`，預設 50），佇列滿時丟棄訊息並記錄 WARNING，防止記憶體無限成長（#14）
- `runner.py`：minion 名稱以正則表達式驗證（`[A-Za-z0-9_-]{1,64}`），拒絕含路徑穿越字元的 DB 存儲值（#15）
- `dashboard.py`：SSE `/api/logs/stream` 由共享 `_log_queue`（每條日誌只有一個客戶端收到）改為 per-client 專屬佇列 + fan-out 廣播模式，所有連線客戶端均收到完整日誌流；連線斷開時自動清除客戶端佇列（#16）
- `ipc.py`：`processed` set 改為有界 deque + set 組合（maxlen=10,000），防止長期執行下的記憶體洩漏（#17）
- `runner.py`：`proc.communicate()` 完成後檢查 stdout 大小，超過 `CONTAINER_MAX_OUTPUT_BYTES`（預設 10MB）時記錄錯誤並回傳失敗，防止失控容器 OOM（#18）
- `config.py`：新增 `validate()` 函數，啟動時快速失敗驗證（numeric bounds、LLM key 存在、channel token 設定），並以 `_int_env`/`_float_env` 替換 `int()`/`float()` 硬轉型，壞值時 fallback 並記錄 WARNING；在 `main.py` 啟動時呼叫（#19）
- `config.py`：`CONTAINER_IMAGE` 預設值從 `miniondesk-agent:latest` 改為 `miniondesk-agent:1.2.5`，避免隱式 image 版本漂移（#21）
- `miniondesk/__init__.py`：版本號更新為 1.2.5

---

## [1.2.4] - 2026-03-12

### Architecture Improvements
- 新增 `CONTAINER_MAX_CONCURRENT` 設定值，以 `asyncio.Semaphore` 取代全域 `asyncio.Lock`，允許最多 N 個容器同時執行（預設 4），修正所有群組被單一鎖序列化的問題（#1）
- Container JSON 輸出增加 schema 驗證，確認必要欄位（`status`、`result`）存在，遺失欄位時記錄錯誤並回傳結構化錯誤訊息（#2）
- Container 執行加入 `request_id` 日誌關聯，所有相關 log 行均標記同一 request ID，方便追蹤單一請求的完整流程（#3）
- Dashboard 啟動時若 `DASHBOARD_PASSWORD` 為預設值 `changeme`，發出 WARNING 安全警告；新增 `/api/health` 端點，包含 DB 連線狀態確認（#4, #6）
- IPC watcher 將 `db.get_all_groups()` 移至迴圈外，每次輪詢只查詢一次並建立 folder→group 字典，修正 O(n²) 查詢問題（#5）
- 輸入提示詞進行基本截斷清理（`MAX_PROMPT_LENGTH`，預設 4000 字元），並記錄截斷警告（#7）
- DevEngine 以 `asyncio.create_task()` 取代已棄用的 `asyncio.ensure_future()`，並加入 done callback 確保 pipeline 例外不被靜默吞掉（#8）
- `skills_engine.list_available_skills()` 將 `_load_registry()` 移至迴圈外，從 O(n) 次磁碟讀取降至 1 次（#9）
- `miniondesk/__init__.py` 版本號更新為 1.2.4；`main.py` 改從 `__version__` 讀取版本，不再使用硬編碼字串（#10）

---

## [1.2.3] - 2026-03-12

### Fixed
- 修正 circuit breaker 競態條件（threading.Lock 保護全域 dict）
- 修正 DB connection 未關閉造成的 file lock 殘留（atexit 正確關閉）
- 修正 history loading 例外被靜默吞掉（改為 logger.warning）
- 修正 Dashboard log buffer OOM 風險（改用 deque maxlen=500）
- 修正 /api/status 回傳絕對時間戳而非 uptime 秒數
- 修正 JSON parse 失敗時訊息靜默消失（改為回傳錯誤提示）
- 修正 Skills API 無分頁（限制最多回傳 50 筆）
- 修正 genome 並發更新競態條件（改為原子操作）

---

## [1.2.2] - 2026-03-11

### Added
- 對話記憶功能：Agent 現在能記住最近 20 則對話歷史
- host/runner.py 在建立 payload 前呼叫 db.get_history()
- container/runner/runner.py 將歷史注入 LLM 對話串

### Fixed
- 修正每次對話都從零開始的問題（get_history 存在但從未被呼叫）

---

## [1.2.1] — 2026-03-11

### 🔌 Dynamic Container Tool Hot-swap (Skills 2.0)

Solves the core Docker limitation: DevEngine-generated skills that add new Python tools to containers no longer require an image rebuild.

#### Architecture: `dynamic_tools/` volume mount
- `miniondesk/host/runner.py`: mounts `{BASE_DIR}/dynamic_tools/` → `/app/dynamic_tools:ro` in every container
- `container/runner/runner.py`: `_load_dynamic_tools()` — scans `/app/dynamic_tools/*.py` at startup and dynamically imports each file via `importlib.util`; each file registers itself with the tool registry
- No image rebuild needed — drop a `.py` file in `dynamic_tools/`, next container run picks it up automatically

#### Skills Engine: `container_tools:` manifest field
- `skills_engine.py` now supports `container_tools:` in `manifest.yaml`
- `install_skill()`: copies `container_tools` files into `{BASE_DIR}/dynamic_tools/` (flattened by filename)
- `uninstall_skill()`: removes corresponding files from `dynamic_tools/`
- `list_available_skills()` returns `container_tools` field for dashboard display

#### New built-in skill: `web-search`
- Demonstrates the `container_tools:` pattern end-to-end
- Adds `web_search` tool (DuckDuckGo Instant Answer API, no API key)
- Adds `SKILL.md` behavioral guide to system prompt
- `manifest.yaml` with both `adds:` and `container_tools:` fields

### 📁 Files Added / Changed
- `miniondesk/host/runner.py` (dynamic_tools volume mount)
- `container/runner/runner.py` (`_load_dynamic_tools()`)
- `miniondesk/host/skills_engine.py` (container_tools install/uninstall)
- `dynamic_tools/.gitkeep` (new — git-tracked placeholder)
- `skills/web-search/` (new — example container_tool skill)

---

## [1.2.0] — 2026-03-11

### ✨ Features — DevEngine + Superpowers Skills

#### 🔧 DevEngine — 7-stage LLM-powered Development Pipeline (`host/dev_engine.py`)
- `ANALYZE → DESIGN → IMPLEMENT → TEST → REVIEW → DOCUMENT → DEPLOY` pipeline
- Each stage (except DEPLOY) runs a Docker container with a specialized system prompt
- **DEPLOY** stage: parses `--- FILE: path ---` blocks from IMPLEMENT output and writes files to disk (path traversal protection included)
- **Interactive mode**: pauses after each stage for user review; resume with `/dev resume <session_id>`
- **Auto mode**: runs all 7 stages unattended in sequence
- Session lifecycle: `pending → running → paused → completed | failed | cancelled`
- Sessions persisted in `dev_sessions` SQLite table (survives restarts)
- `start_dev_session()`, `resume_dev_session()`, `cancel_dev_session()` public API
- IPC message type `dev_task` — trigger from any minion via JSON file
- Progress notifications sent to group via `notify_fn`

#### ⚡ Superpowers Skills Engine (`host/skills_engine.py`)
- YAML manifest-based installable plugin packages (`skills/{name}/manifest.yaml`)
- **5 built-in skill packages** in `skills/`:
  - `brainstorming` — design-first thinking gate
  - `systematic-debugging` — 4-phase root cause protocol (Observe → Hypothesize → Isolate → Fix)
  - `planning` — atomic step decomposition before action
  - `verification` — mandatory verification before claiming task done
  - `subagent-delegation` — parallel subagent spawning pattern
- `install_skill(name)` / `uninstall_skill(name)` — copy/remove skill files
- `get_installed_skill_docs()` — returns combined SKILL.md content for system prompt injection
- `list_available_skills()` / `list_installed_skills()` — discovery API
- Installed skill docs automatically injected into every container system prompt via `runner.py`
- IPC message types: `apply_skill`, `uninstall_skill`, `list_skills`

#### 📊 Dashboard Updates (DevEngine + Skills pages)
- New **🔧 DevEngine** page: live session table with status badges, stage progress, prompt preview
- New **⚡ Skills** page: skill cards showing name, version, description, install status
- New API endpoints: `/api/dev_sessions`, `/api/skills`
- DevEngine sessions polled every 10s; Skills polled every 30s
- Filter sessions by: ALL / RUNNING / DONE / FAILED / PAUSED

#### 🔧 container/runner/runner.py — skillDocs injection
- `skillDocs` from payload now injected as `## Installed Superpowers Skills` section in system prompt
- All installed skills' instructions are available to every container agent automatically

### 📁 Files Added / Changed
- `miniondesk/host/dev_engine.py` (new)
- `miniondesk/host/skills_engine.py` (new)
- `skills/brainstorming/` (new)
- `skills/systematic-debugging/` (new)
- `skills/planning/` (new)
- `skills/verification/` (new)
- `skills/subagent-delegation/` (new)
- `container/runner/runner.py` (skillDocs injection)
- `miniondesk/host/runner.py` (skillDocs payload)
- `miniondesk/host/ipc.py` (dev_task / apply_skill / uninstall_skill / list_skills handlers)
- `miniondesk/host/dashboard.py` (DevEngine + Skills pages)

---

## [1.1.0] — 2026-03-11

### ✨ Features — ported from evoclaw

#### 🧬 Adaptive Genome Evolution (`host/evolution.py`)
- `calculate_fitness()` — maps (success, response_ms) → 0.0-1.0 fitness score
- `evolve_genome()` — 3-dimension evolution: response_style, formality, technical_depth; updates DB only on actual change
- `genome_hints()` — generates plain-English behavioral hints injected into container system prompt
- `evolution_loop()` — async loop evolving all group genomes every 300s
- New DB tables: `evolution_runs`, `evolution_log`
- Evolution tracked after every container run in `main.py`

#### 🛡️ Immune / Anti-spam System (`host/immune.py`)
- In-memory sliding window (60s) per-sender rate limiting
- `is_allowed()` — checks DB block status + in-memory rate (max 15 msgs/min)
- Auto-block after 30 msgs/min, persisted to `immune_threats` table
- `record_message()` — DB tracking for audit trail
- Integrated into `handle_inbound()` before trigger check

#### 📊 Dashboard Web UI (`host/dashboard.py`)
- Pure Python stdlib HTTP server (no Flask/npm/React required)
- 4-page SPA: Status / Groups / Genome / Logs
- Real-time SSE log stream at `/api/logs/stream`
- Genome evolution visualized with progress bars
- Minion status table with fitness badges
- JSON APIs: `/api/status`, `/api/groups`, `/api/logs`
- Runs in daemon thread, integrated into `asyncio.gather()`

#### 📄 Per-group CLAUDE.md Injection (evoclaw-style)
- `groups/global/CLAUDE.md` — baseline instructions for all minions
- `groups/{folder}/CLAUDE.md` — per-group overrides
- Both injected into container system prompt at runtime
- `container/runner/runner.py` — reads `globalClaudeMd` + `groupClaudeMd` from payload

#### 🔄 Dual-output Prevention
- Container runner tracks `send_message` tool calls via wrapper
- If agent already sent reply via IPC `send_message`, final `result` is suppressed
- Prevents duplicate messages to users

#### 🌟 Mini — 主助理名稱
- 預設助理從 `phil` 改為 **`mini`**，觸發詞 `@Mini`
- 新增 `ASSISTANT_NAME=Mini` 環境變數（config.py + .env.example）
- 新增 `minions/mini.md` persona 檔案
- 所有程式預設值（db.py / main.py / dept_init.py / dept_router.py）更新為 `mini`
- global CLAUDE.md 更新 Mini 身份描述
- `assistantName` 欄位透過 payload 注入 container

### 🔧 Improvements
- `main.py`: 7 async loops (was 4): IPC + Scheduler + Evolution + Health Monitor + Orphan Cleanup + Dashboard + Stop Event
- `main.py`: Version bumped to 1.1.0
- `host/runner.py`: CLAUDE.md injection + `genome_hints()` + `assistantName` 傳遞
- `db.py`: 3 new tables (evolution_runs, evolution_log, immune_threats) + default minion=mini
- New `groups/global/CLAUDE.md` + `groups/example-group/CLAUDE.md`

### 📁 Files Added / Changed
- `miniondesk/host/evolution.py` (new)
- `miniondesk/host/immune.py` (new)
- `miniondesk/host/dashboard.py` (new)
- `minions/mini.md` (new)
- `groups/global/CLAUDE.md` (new)
- `groups/example-group/CLAUDE.md` (new)
- `RELEASE.md` (new)

---

## [1.0.0] — 2026-03-11

### 🎉 Initial Release

MinionDesk — 從零打造的企業 AI 助理框架。不 fork 任何現有框架，參考 nanoclaw（極簡隔離）+ openclaw（模型無關 gateway）+ evoclaw（Python + 企業安全）的精華。

### ✨ Features

#### 核心框架
- **模型無關 Provider 抽象層**：Gemini / Claude / OpenAI / Ollama / vLLM 一套介面，換模型只改一行設定
- **工具系統**：`Tool` + `ToolRegistry` 設計，JSON Schema 格式，各 provider 自動轉換
- **小小兵 Runner**：Docker container 隔離，agentic loop 最多 30 輪，stdin/stdout JSON 通訊
- **模型自動偵測**：按優先順序偵測 API key，無縫切換

#### 小小兵人設
- **Phil**：主助理 Boss，一般問答與協調
- **Kevin**：HR — 請假、招募、薪資、福利
- **Stuart**：IT — 技術支援、設備、帳號管理
- **Bob**：財務 — 報銷、採購、預算審核

#### Host 系統
- **SQLite WAL 模式**：高效並發讀寫，`PRAGMA busy_timeout=5000`
- **IPC 檔案監控**：`watch_ipc()` 輪詢各 group `.ipc/` 目錄
- **per-group GroupQueue**：每個群組訊息串行執行，避免競態條件
- **Docker 熔斷器**：連續 5 次失敗 → 60 秒冷卻
- **任務排程**：支援 cron、interval、once 三種格式

#### 頻道支援
- **Telegram**：完整 bot 整合，訊息自動切分（4096 字元限制），send_document 傳檔
- **Discord**：stub（框架已備，待擴充）
- **Teams**：stub（框架已備，待擴充）

#### 企業模組
- **Knowledge Base**：SQLite FTS5 全文搜尋 + LIKE fallback，支援批次目錄匯入
- **Workflow Engine**：YAML 定義工作流程，支援 notify / approval 步驟
- **Calendar**：Google/Outlook 日曆整合 stub
- **RBAC**：角色權限控制（admin / manager / employee / readonly）
- **Department Router**：關鍵字評分自動路由到對應部門小小兵
- **Department Init**：批次初始化部門群組

#### 內建工作流程
- `leave_request.yaml`：請假申請（主管審批 → HR 確認）
- `expense_report.yaml`：費用報銷（按金額分級審批）
- `it_ticket.yaml`：IT 工單（分類 + 優先級）

#### 安全
- **Container network=none**：容器無法連外網
- **Memory 512MB / CPU 1.0** 限制
- **非 root 用戶**：container 以 `minion:1000` 執行
- **DASHBOARD_HOST=127.0.0.1** 預設本機存取
- **UTF-8 強制編碼**：所有檔案讀寫指定 `encoding="utf-8"`

#### 開發體驗
- **CLI**：`python run.py start|setup|check`
- **Setup Wizard**：互動式設定嚮導
- **System Check**：自動驗證 Python / Docker / 映像 / LLM / Telegram
- **Container 詳細日誌**：毫秒時間戳 + emoji 標籤，方便除錯

### 📦 Providers

| Provider | 環境變數 | 優先順序 |
|----------|---------|---------|
| Google Gemini | `GOOGLE_API_KEY` | 1（首選） |
| Anthropic Claude | `ANTHROPIC_API_KEY` | 2 |
| OpenAI | `OPENAI_API_KEY` | 3 |
| OpenAI-compatible | `OPENAI_BASE_URL` | 4 |
| Ollama | `OLLAMA_URL` | 5 |

### 📁 Project Stats

- Python 檔案：43 個
- 總程式碼行數：~2,400 行
- 外部依賴：12 個（host）+ 5 個（container）
