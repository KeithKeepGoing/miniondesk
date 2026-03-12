# MinionDesk Release Notes

---

## v1.2.7 — 2026-03-12

### Reliability and Edge Case Improvements (Fourth Round)

本次版本修正 8 個在 v1.2.6 後發現的新可靠性與安全性問題，涵蓋 DevEngine 並發保護、容器名稱衝突、排程表達式驗證、基因組邊界檢查、群組刪除孤立資料及 SSE 連線洪泛防護。

#### Fix 1: DevEngine 同群組並發 session 防護（#34）

`start_dev_session()` 未限制同群組的並發 session，兩個並發 pipeline 會同時讀寫 artifacts，導致資料損毀。
新增 DB 查詢確認 `pending`/`running` session 不存在再啟動新 session；已有活躍 session 時回傳錯誤並拒絕啟動。

#### Fix 2: `_parse_file_blocks` 路徑穿越繞過（#37）

`_parse_file_blocks()` 以 `replace("..", "")` 淨化路徑，可被 `....//` 模式繞過（替換後剩餘 `../`）。
移除脆弱字串替換邏輯，直接依賴 `_deploy_files()` 中已存在的 `resolve().relative_to()` 正確性檢查。

#### Fix 3: 容器名稱衝突（#36）

`container_name = f"minion-{group_folder}-{int(time.time())}"` 在同一秒內兩次請求時產生相同名稱，Docker 拒絕第二次啟動並累計熔斷計數。
改為使用毫秒精度時間戳加 6 字元 UUID 後綴。

#### Fix 4: 排程器無效表達式靜默儲存（#35）

`add_task()` 對無效 cron/interval 表達式儲存 `next_run=NULL` 的任務，任務永不觸發且無錯誤提示。
新增 `croniter.is_valid()` 驗證；無效時拋出 `ValueError`，`ipc.py` 捕捉後回報使用者。

#### Fix 5: 技能安裝阻塞 asyncio event loop（#41）

`install_skill()`/`uninstall_skill()` 在 async 處理器中同步執行檔案 I/O，阻塞 event loop。
改為 `run_in_executor()` 在執行緒池執行。

#### Fix 6: 基因組浮點數邊界未檢查（#39）

`update_genome()` 接受超出 `[0.0, 1.0]` 範圍的值，導致儀表板 CSS 寬度異常。
新增 `_clamp01()` 輔助函數，在寫入前限制所有浮點基因組欄位。

#### Fix 7: `delete_group` 留下孤立資料（#38）

`delete_group()` 僅刪除 `groups` 表，相關 `messages`、`tasks`、`genome` 等表資料殘留。
改為在單一交易中刪除所有相關表的對應資料列。

#### Fix 8: SSE 連線洪泛導致記憶體耗盡（#40）

SSE 端點未限制並發客戶端數，大量連線可耗盡記憶體與檔案描述符。
新增 `_MAX_SSE_CLIENTS=20` 上限；超過時回傳 HTTP 503。

---

## v1.2.6 — 2026-03-12

### Security and Reliability Improvements (Third Round)

本次版本修正 10 個在 v1.2.5 後發現的新安全與可靠性問題，涵蓋路徑穿越防護、認證強制執行、XSS 修正、記憶體洩漏、排程器穩定性及並發控制。

#### Fix 1: Container runner stdin 阻塞問題（#23）

`container/runner/runner.py` 中 `sys.stdin.read()` 為同步阻塞呼叫，在 `asyncio` 環境中會佔用 event loop thread。
改為 `loop.run_in_executor(None, sys.stdin.read)` 並加入 30 秒 `asyncio.wait_for()` 逾時防護，避免主機部分寫入時容器永久掛起。

#### Fix 2: skills_engine 路徑穿越防護（#24）

`install_skill()` 的 `adds` 檔案列表缺乏路徑驗證，惡意 manifest 可覆蓋主機系統檔案或應用程式原始碼。
加入與 `dev_engine._deploy_files()` 相同的 `target.resolve().relative_to(base_dir.resolve())` 檢查，路徑逃逸時拒絕安裝。

#### Fix 3: Dashboard HTTP Basic Auth 強制執行（#25）

`DASHBOARD_PASSWORD` 設定值存在但從未驗證，所有端點皆可未認證存取。
在 `_Handler.do_GET()` 前加入 `_require_auth()` 檢查，比對 `Authorization: Basic` header；不符時回傳 401 + `WWW-Authenticate`。

#### Fix 4: 循環任務死信佇列 / 暫停機制（#26）

循環任務每次執行失敗後仍持續以完整頻率重新排程，導致失效任務無限消耗容器資源並觸發熔斷器。
新增每任務連續失敗計數器；達 `_MAX_CONSECUTIVE_FAILURES`（預設 5）次後將任務設為 `suspended`。

#### Fix 5: immune.py 記憶體洩漏修正（#27）

`_sender_timestamps` defaultdict 對每個曾發訊的發送者永遠保留鍵，長期執行下字典鍵無限累積。
滑動視窗內無時間戳記時刪除對應鍵，防止記憶體無限成長。

#### Fix 6: 動態工具名稱衝突偵測（#28）

安裝兩個包含同名 container_tool 的技能時，第二次安裝會靜默覆蓋第一個技能的工具檔案。
安裝前檢查 `dynamic_tools/` 中是否已有同名檔案且屬於不同技能，若有則拒絕安裝並提示衝突技能名稱。

#### Fix 7: workflow.py format string injection（#29）

`trigger_workflow()` 使用 `step.message.format(**data)` 其中 data 部分來自使用者輸入，可能洩漏物件屬性。
改為 `string.Template(template).safe_substitute(data)`，僅替換明確的 `$key` 佔位符。

#### Fix 8: Dashboard XSS 修正（#30）

群組名稱、JID、folder、minion、trigger 欄位透過 `innerHTML` 直接插入 DOM，未經 HTML 轉義。
對所有透過 innerHTML 渲染的群組欄位套用既有的 `htmlEsc()` 函數。

#### Fix 9: Container semaphore 持有整個生命週期（#31）

Semaphore 在 `create_subprocess_exec` 返回後立即釋放，使 `CONTAINER_MAX_CONCURRENT` 僅限制啟動速率而非實際執行數量。
將 `proc.communicate()` 移入 `async with semaphore:` 區塊，確保限制真正生效。

#### Fix 10: DB atexit 多執行緒連線清理（#32）

`atexit` 只在主執行緒執行，Dashboard 背景執行緒的 thread-local DB 連線在關閉時不會被清理。
新增 `suspend_task()` 函數；修正 `delete_group()` 使用單次 `_conn()` 呼叫確保一致性。

---

## v1.2.5 — 2026-03-12

### 架構改進第二輪（Architecture Improvements Round 2）

本次版本修正 10 個在 v1.2.4 後發現的新架構問題，涵蓋記憶體安全、並發模型、安全加固與可觀測性。

#### Fix 1: ipc.py dev_task 中遺漏的 ensure_future 替換（#12）

v1.2.4 修正了 `dev_engine.py` 中的 `ensure_future`，但 `ipc.py` 第 121 行的 `dev_task` handler 被遺漏。
改為 `asyncio.create_task()` 並加入 `.add_done_callback()` 記錄例外。

#### Fix 2: scheduler.py task dispatch ensure_future 替換（#13）

`run_scheduler()` 中的 `asyncio.ensure_future(dispatch_fn(...))` 改為 `asyncio.create_task()` 並加入 done callback。
Task dispatch 失敗不再被靜默丟棄。

#### Fix 3: GroupQueue 有界佇列背壓保護（#14）

`asyncio.Queue()` 改為 `asyncio.Queue(maxsize=config.QUEUE_MAX_PER_GROUP)`（預設 50）。
佇列達 75% 容量時記錄 WARNING；佇列滿時丟棄新訊息並記錄 WARNING，防止記憶體無限成長。
新增 `QUEUE_MAX_PER_GROUP` 環境變數可調整。

#### Fix 4: Minion 名稱路徑穿越防護（#15）

`host/runner.py` 中 `minion_name` 在用於構建檔案路徑前，以 `[A-Za-z0-9_-]{1,64}` 正則驗證。
含 `../` 或特殊字元的 DB 存儲值會被拒絕並回傳結構化錯誤。

#### Fix 5: SSE 日誌流 fan-out 修正（#16）

原實作使用共享 `_log_queue`，多個瀏覽器分頁連線時每條日誌只有一個客戶端收到。
改為 per-client 專屬 `queue.Queue`，`_QueueHandler` 廣播至所有訂閱者。
連線斷開（BrokenPipeError）時在 `finally` 區塊中移除客戶端佇列，防止洩漏。

#### Fix 6: IPC watcher processed set 有界化（#17）

`watch_ipc()` 中的 `processed: set[str]` 無限成長。
改為 `deque(maxlen=10_000)` + `set` 組合，維持 O(1) 查找的同時限制記憶體佔用。
超過容量時自動淘汰最舊條目。

#### Fix 7: Container stdout 大小限制（#18）

`proc.communicate()` 完成後檢查 `len(stdout) > CONTAINER_MAX_OUTPUT_BYTES`（預設 10MB）。
超出限制時記錄錯誤、增加熔斷計數並回傳失敗，防止失控容器耗盡主機記憶體。
新增 `CONTAINER_MAX_OUTPUT_BYTES` 環境變數可調整（設 0 停用）。

#### Fix 8: Config 啟動驗證與安全轉型（#19）

新增 `config.validate()` 函數：
- 警告：無 channel token、無 LLM API key
- 錯誤（ValueError）：CONTAINER_TIMEOUT、CONTAINER_MAX_CONCURRENT、QUEUE_MAX_PER_GROUP、MAX_PROMPT_LENGTH 為 0 或負數
新增 `_int_env()` / `_float_env()` helper，壞值時 fallback 並記錄 WARNING（取代直接 `int()` 轉型）。
`main.run_host()` 啟動時呼叫 `config.validate()`，在啟動任何服務前快速失敗。

#### Fix 9: Container image 版本鎖定（#21）

`CONTAINER_IMAGE` 預設值從 `miniondesk-agent:latest` 改為 `miniondesk-agent:1.2.5`。
防止 `docker pull` 後靜默切換到不相容的新 image。
升級時需明確指定新版本號。

### 升級指引

```bash
# 如使用預設 image tag，需重建（tag 從 :latest 改為 :1.2.5）
docker build -t miniondesk-agent:1.2.5 ./container

# 不需重建資料庫（schema 無變更）
python run.py start
```

---

## v1.2.4 — 2026-03-12

### 架構改進（Architecture Improvements）

本次版本針對 10 個架構問題進行修正，涵蓋並發模型、輸出驗證、日誌追蹤、安全警告與效能優化。

#### Fix 1: 全域鎖改為可配置 Semaphore（runner.py）

原本 `_active_lock`（`asyncio.Lock`）在整個容器執行期間持鎖，導致所有群組被序列化。
改為 `asyncio.Semaphore(CONTAINER_MAX_CONCURRENT)`，預設允許 4 個容器並行，且僅在 spawn 階段持鎖。

#### Fix 2: Container 輸出 Schema 驗證（runner.py）

JSON 解析成功後增加 schema 驗證，確認 `status`、`result` 欄位存在。
遺失欄位時記錄結構化錯誤並回傳 `{"status": "error", "result": "..."}` 而非靜默通過。

#### Fix 3: Request ID 日誌關聯（main.py, runner.py）

每次 `_run_and_reply()` 產生 `request_id = uuid4().hex[:8]`，注入所有相關 log 行。
可用 `grep "\[abc12345\]"` 追蹤單一請求的完整生命週期。

#### Fix 4: Dashboard 安全警告 + /api/health 端點（dashboard.py）

啟動時若 `DASHBOARD_PASSWORD == 'changeme'` 發出 WARNING 日誌。
新增 `/api/health` 端點，回傳 DB 連線狀態、uptime、整體 health status。

#### Fix 5: IPC Watcher N+1 查詢修正（ipc.py）

`db.get_all_groups()` 從每個目錄迴圈內移至迴圈外，每次輪詢僅查詢一次。
以 `folder_to_group` dict 做 O(1) 查找，消除 O(groups²) 查詢模式。

#### Fix 6: 輸入截斷清理（main.py）

`handle_inbound()` 在派發前截斷超過 `MAX_PROMPT_LENGTH`（預設 4000）的提示詞。
截斷時記錄 WARNING，確保操作人員知情。

#### Fix 7: DevEngine 使用 asyncio.create_task（dev_engine.py）

`asyncio.ensure_future()`（Python 3.10+ 已棄用）全部改為 `asyncio.create_task()`。
加入 `.add_done_callback()` 確保 pipeline 例外不被靜默丟失。

#### Fix 8: skills_engine 降低磁碟讀取次數（skills_engine.py）

`list_available_skills()` 將 `_load_registry()` 移至迴圈外。
20 個 skills 的情況下，磁碟讀取從 20 次降至 1 次。

#### Fix 9: Health Monitor 錯誤等級提升（main.py）

`_health_monitor_loop()` 的例外從 `logger.debug` 改為 `logger.warning`，確保在預設 INFO 日誌等級下可見。

#### Fix 10: 版本號統一（__init__.py, main.py）

`miniondesk/__init__.py` 更新為 `__version__ = "1.2.4"`。
`main.py` 改為 `logger.info("MinionDesk v%s starting...", __version__)`，不再硬編碼版本字串。

### 升級指引

```bash
# 不需重建 Docker image（僅 host 端修正）
# 不需重建資料庫（schema 無變更）
python run.py start
```

---

## v1.2.3 — 2026-03-12

### 穩定性修正（Stability Fixes）

本次版本專注於修正 v1.2.2 發現的 8 個穩定性問題，無新功能。

#### Fix 1: Circuit Breaker 競態條件（runner.py）

`_group_fail_counts` 與 `_group_fail_time` 兩個全域 dict 在多執行緒環境下存在 TOCTOU 競態條件。
新增 `threading.Lock`（`_group_lock`）並在所有讀寫操作前加上 `with _group_lock:`。

#### Fix 2: DB Connection 未關閉（db.py）

程序正常關閉時，thread-local SQLite connection 從未被關閉，可能造成 WAL file lock 殘留。
改用 `atexit.register(_close_connections)` 確保關閉。

#### Fix 3: History Loading 例外靜默吞掉（runner.py）

`conv_history` 載入區塊中的 `except Exception: pass` 完全隱藏錯誤，難以除錯。
改為 `logger.warning("Failed to load conversation history: %s", exc)` 記錄警告。

#### Fix 4: Dashboard Log Buffer OOM 風險（dashboard.py）

`_log_buffer: list[dict]` 使用 `pop(0)` 手動維護上限，`pop(0)` 為 O(n) 操作，大量日誌時效能差且有競態風險。
改用 `deque(maxlen=500)` 自動管理上限，O(1) 操作。

#### Fix 5: /api/status 回傳絕對時間戳（dashboard.py）

`"uptime": int(time.time())` 回傳的是 Unix epoch 時間戳，而非運行秒數。
新增 `_start_time = time.time()` 模組載入時記錄，改為 `int(time.time() - _start_time)`。

#### Fix 6: JSON Parse 失敗時訊息靜默消失（runner.py）

`json.JSONDecodeError` 被捕捉後只記錄 log，沒有回傳任何結果，呼叫端收不到任何錯誤提示。
改為同時記錄詳細 log 並回傳 `{"error": ..., "reply": "⚠️ 處理發生錯誤，請重試。"}`。

#### Fix 7: Skills API 無分頁（dashboard.py）

`_get_skills()` 直接回傳所有 skills，skills/ 目錄過大時可能回傳大量資料。
新增 `limit: int = 50` 參數，預設最多回傳 50 筆。

#### Fix 8: Genome 並發更新競態條件（db.py）

`update_genome()` 先 Python 端 `get_genome()` 讀取再寫入，多個 goroutine 同時更新時會互相覆蓋。
改為單一原子 SQL 語句，使用 `COALESCE` 在 SQL 層合併預設值，消除 read-then-write race。

### 升級指引

```bash
# 不需重建 Docker image（僅 host 端修正）
# 不需重建資料庫（schema 無變更）
python run.py start
```

---

## v1.2.2 — 2026-03-11

### 🧠 對話記憶持久化（Conversation Memory）

修正了 MinionDesk 最核心的缺陷：每次對話都從零開始。`db.get_history()` 早已存在，但從未被呼叫。

#### 問題

每次 Agent 啟動時，container runner 只收到當前使用者訊息，完全不知道之前說了什麼。

#### 解決方案

**host/runner.py** — payload 建立前先載入對話歷史：

```python
conv_history = []
try:
    raw_history = db.get_history(group_jid, limit=20)
    for h in raw_history:
        role = h.get("role", "user")
        content = str(h.get("content", "")).strip()
        if content:
            conv_history.append({"role": role, "content": content})
except Exception:
    pass
```

**container/runner/runner.py** — 將歷史注入 LLM 對話串（在當前使用者訊息之前）：

```python
history = []
for h in stdin_data.get("conversationHistory", []):
    history.append(Message(role=h["role"], content=h["content"]))
history.append(Message(role="user", content=stdin_data["prompt"]))
```

#### 效果

- Agent 現在能記住最近 20 則對話
- 跨 container 呼叫保持上下文連貫
- 歷史記錄從 SQLite `messages` 表讀取（role + content 欄位）
- 完全向後相容，舊群組無歷史記錄時自動降級為空歷史

#### 升級指引

```bash
# 不需重建 Docker image（runner.py 在容器外執行的部分有更新）
# container/runner/runner.py 已更新，需重建 image
docker build -t miniondesk-agent:latest ./container

# 重啟即可（DB schema 無變更）
python run.py start
```

---

## v1.2.1 — 2026-03-11

### 🔌 動態容器工具熱插拔（Skills 2.0）

解決了 Docker 的核心限制：DevEngine 生成的 Skill 新增 Python 工具時，**不需重建 image**。

#### 問題

evoclaw 在 OS process 中執行 agent，生成的工具可以直接 import。
MinionDesk 使用 Docker container（network=none 隔離），靜態 image 無法取得執行時新增的工具檔案。

#### 解決方案：`dynamic_tools/` Volume Mount

```
Host: {BASE_DIR}/dynamic_tools/  ─── 掛載 ──→  /app/dynamic_tools:ro (container)
```

1. *Host runner* 在每次 `docker run` 時自動掛載 `dynamic_tools/` 目錄
2. *Container runner* 啟動時 `_load_dynamic_tools()` 掃描 `/app/dynamic_tools/*.py`，用 `importlib.util` 動態 import
3. 每個工具檔案在 import 時呼叫 `register_tool()`，立即可用
4. *Skills Engine* 安裝含 `container_tools:` 的 Skill 時，把工具 copy 到 `dynamic_tools/`

#### Skills 2.0 — Manifest 新欄位

```yaml
skill: my-skill
version: "1.0.0"
description: "示範 container_tools: 的 Skill"
adds:
  - docs/superpowers/my-skill/SKILL.md   # 文件注入系統提示
container_tools:
  - dynamic_tools/my_tool.py             # 熱載入工具（不需重建 image）
```

#### 新內建 Skill：`web-search`

展示 `container_tools:` 完整流程：
- 安裝 `web_search` 工具（DuckDuckGo Instant Answer API，不需 API key）
- SKILL.md 注入使用指引至系統提示

```json
{"type": "apply_skill", "skill": "web-search"}
```

安裝後，所有小小兵在下一次 container 啟動時自動擁有 `web_search` 工具。

#### 升級指引

```bash
# 不需重建 Docker image（runner.py 在容器外執行）
# 直接重啟即可
python run.py start
```

---

## v1.2.0 — 2026-03-11

### 🔧 DevEngine — AI 驅動的 7 階段開發流水線

MinionDesk 現在可以自己寫程式！DevEngine 是 7 階段 LLM 驅動的軟體開發流水線，從需求分析到部署一氣呵成。

#### 階段流程

| # | 階段 | 說明 |
|---|------|------|
| 1 | ANALYZE | 需求分析、驗收條件、風險評估 |
| 2 | DESIGN | 架構設計、模組結構、資料流 |
| 3 | IMPLEMENT | 完整 Python 程式碼實作 |
| 4 | TEST | pytest 測試案例 |
| 5 | REVIEW | 安全性與品質審查（PASS / FAIL） |
| 6 | DOCUMENT | README 段落、CHANGELOG 條目 |
| 7 | DEPLOY | 將程式碼寫入磁碟（路徑安全防護） |

#### 使用方式（IPC）

```json
{"type": "dev_task", "prompt": "新增 Slack 頻道整合", "mode": "auto"}
```

兩種模式：
- **auto**：7 個階段自動連跑
- **interactive**：每階段完成後暫停，等待 `/dev resume <session_id>` 繼續

---

### ⚡ Superpowers Skills Engine

可安裝的行為插件系統。每個 Skill 是 YAML manifest + Markdown 文件包，安裝後自動注入所有 container 的系統提示。

#### 內建 5 個 Skills

| Skill | 說明 |
|-------|------|
| `brainstorming` | 行動前先設計，避免衝動實作 |
| `systematic-debugging` | 4 階段根因分析（觀察→假設→隔離→修復） |
| `planning` | 原子步驟分解，逐步執行 |
| `verification` | 宣稱完成前必須驗證 |
| `subagent-delegation` | 平行子代理模式，加速複雜任務 |

#### 安裝方式（IPC）

```json
{"type": "apply_skill", "skill": "systematic-debugging"}
```

#### Dashboard

- 🔧 **DevEngine** 頁面：即時工作階段列表、狀態徽章、進度追蹤
- ⚡ **Skills** 頁面：技能卡片、版本、安裝狀態

### 升級指引

```bash
# 重新建立 Docker 映像（container/runner/runner.py 有更新）
docker build -t miniondesk-agent:latest ./container

# 重啟即可（新 DB 表 dev_sessions 自動建立）
python run.py start
```

---

## v1.1.0 — 2026-03-11

### 🌟 主要更新：Mini 主助理 + evoclaw 特性移植

#### Mini — 新的主助理名稱
- 預設助理名稱改為 **Mini**（觸發詞 `@Mini`）
- 新增 `ASSISTANT_NAME=Mini` 環境變數（可自訂）
- 新增 `minions/mini.md` persona 檔案
- 所有預設值從 `phil/@Phil` 更新為 `mini/@Mini`
- 全域 CLAUDE.md 更新 Mini 身份描述

#### 自適應基因組演化
- 3維演化：response_style / formality / technical_depth
- 每 5 分鐘自動根據成功率與回應時間調整行為
- 演化歷史記錄在 evolution_log 表

#### 免疫系統
- 滑動視窗限速（60秒內最多 15 條訊息）
- 超過 30 條/分鐘自動封鎖
- 封鎖狀態持久化至 SQLite

#### Dashboard Web UI
- 純 Python stdlib，無需安裝 Flask/npm
- 即時 SSE 日誌串流
- 基因組演化視覺化（進度條）
- 預設 `http://127.0.0.1:8080`

#### CLAUDE.md 行為注入
- 全域 `groups/global/CLAUDE.md`
- 每群組 `groups/{folder}/CLAUDE.md` 覆寫
- 執行期注入容器系統提示

### 升級指引
```bash
# 重新建立 Docker 映像
docker build -t miniondesk-agent:latest ./container

# 如果有舊資料庫，刪除後重啟（schema 有新增欄位）
rm data/miniondesk.db
python run.py start
```

---

## v1.0.0 — 2026-03-11

### 🎉 初次發布

MinionDesk 企業 AI 助理框架首次發布。

**核心特性：**
- 模型無關 Provider 抽象層（Gemini / Claude / OpenAI / Ollama）
- Docker container 隔離（network=none，512MB，非 root）
- 小小兵人設系統（Kevin=HR / Stuart=IT / Bob=財務 / Mini=主助理）
- SQLite WAL 模式資料庫
- Telegram / Discord / Teams 頻道支援
- 企業知識庫（FTS5 全文搜尋）
- YAML 工作流程引擎
- RBAC 角色權限控制
- 部門自動路由（關鍵字評分，中英雙語）
- per-group GroupQueue 序列化
- Docker 熔斷器（連續 5 次失敗 → 60 秒冷卻）
- cron / interval / once 任務排程

**小小兵：** Mini（主）/ Kevin（HR）/ Stuart（IT）/ Bob（財務）

---

## 版本對應

| 版本 | 日期 | 重點 |
|------|------|------|
| v1.2.5 | 2026-03-12 | 架構改進第二輪（背壓保護 / 路徑穿越防護 / SSE fan-out / stdout 限制 / config 驗證） |
| v1.2.4 | 2026-03-12 | 架構改進（semaphore / request_id / schema 驗證 / health API / 輸入截斷） |
| v1.2.3 | 2026-03-12 | 穩定性修正（thread safety / db cleanup / error handling） |
| v1.2.2 | 2026-03-11 | 對話記憶持久化（get_history 正式啟用） |
| v1.2.1 | 2026-03-11 | dynamic_tools 熱插拔 + container_tools manifest |
| v1.2.0 | 2026-03-11 | DevEngine 7 階段流水線 + Superpowers Skills |
| v1.1.0 | 2026-03-11 | Mini 主助理 + 演化 + 免疫 + Dashboard |
| v1.0.0 | 2026-03-11 | 初次發布 |
