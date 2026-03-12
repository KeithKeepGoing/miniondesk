# MinionDesk Release Notes

---

## v1.2.18 — 2026-03-12

### Shutdown Reliability, Concurrency, and Security Fixes (Issues #116–#121)

This release addresses 6 issues across shutdown correctness, scheduler race conditions, config validation, dashboard lifecycle, container naming, and IPC input validation. No new features; all changes are hardening fixes.

#### Fix: Asyncio Tasks Not Cancelled on Shutdown (#116)

On SIGTERM the `asyncio.gather()` returned after `stop_event.wait()` completed, but remaining tasks (health monitor sleeping 60 s, orphan cleanup sleeping 300 s) continued until their sleep expired. On deployments with tight systemd `TimeoutStopSec`, this could cause force-kills. The fix adds an explicit task cancellation loop after `gather()` returns, with `await asyncio.gather(*pending, return_exceptions=True)` to collect all cancellations cleanly.

#### Fix: Scheduler `_fail_counts` Dict Modification Race (#117)

The `_fail_counts` pruning loop iterated directly over the dict (`for k in _fail_counts`) while `_on_task_done` callbacks could modify it concurrently, raising `RuntimeError: dictionary changed size during iteration`. Fixed by iterating over `list(_fail_counts.keys())` — a snapshot taken before the loop begins.

#### Fix: `IPC_POLL_INTERVAL=0` Causes 100% CPU Busy-Loop (#118)

`config.validate()` did not check `IPC_POLL_INTERVAL`. A value of 0 or negative causes the IPC watcher to spin without any sleep, exhausting a CPU core and making the host unresponsive. The fix adds a `< 0.01` lower-bound check in `validate()` which raises `ValueError` at startup.

#### Fix: Dashboard Server Thread Hangs on Shutdown (#119)

`run_dashboard()` looped `while t.is_alive(): await asyncio.sleep(5)`. The `HTTPServer` had no shutdown hook, so when the gather was cancelled the coroutine hung indefinitely. Fixed by storing the `HTTPServer` reference and calling `server.shutdown()` + `t.join(timeout=3)` inside the `CancelledError` handler, allowing the thread to exit promptly.

#### Fix: Container Name Can Exceed Docker's 63-Character Limit (#120)

Container names were built as `minion-{group_folder}-{13_digit_ms}-{6_hex}`. With a `group_folder` longer than 25 characters, the name exceeded Docker's limit, causing silent container creation failures. Fixed by truncating `group_folder` to 20 characters and using an 8-char UUID suffix (max total: 36 characters).

#### Fix: `schedule_value` Not Length-Validated Before Croniter (#121)

The `schedule_task` IPC handler passed `schedule_value` directly to `scheduler.add_task()` without a length guard. A pathologically long cron string could trigger catastrophic backtracking in `croniter`'s regex parser, hanging the scheduler. Fixed by rejecting `schedule_value` longer than 256 characters before any parsing occurs.

---

## v1.2.17 — 2026-03-12

### Memory Leak, Orphan Cleanup, and Security Fixes (Tenth Round)

This release addresses 6 issues spanning memory leak prevention, filesystem cleanup on group deletion, user-visible truncation notifications, and scheduler security hardening. No new features; all changes are fixes and hardening.

#### Fix: `scheduler.py` `_fail_counts` Dict Memory Leak (#103)

`run_scheduler()` kept an in-memory `_fail_counts` dict tracking consecutive failures per task ID. Deleted tasks were never removed from the dict, causing unbounded memory growth on long-running instances with many transient tasks. The fix prunes stale entries (task IDs no longer present in the DB) every 100 scheduler cycles and hard-caps the dict at 1,000 entries, evicting entries with the lowest fail counts when the cap is exceeded.

#### Fix: Orphan Genome Rows After Group Deletion (#104)

`genome` rows were not being cleaned up when the corresponding group did not exist in the DB (e.g. after direct DB manipulation or a failed cascade delete). The fix adds `db.cleanup_orphan_genomes()`, which issues a single `DELETE FROM genome WHERE group_jid NOT IN (SELECT jid FROM groups)`, and calls it from the health monitor loop alongside the WAL checkpoint and immune prune.

#### Fix: `immune.py` `_sender_timestamps` Unbounded Growth (#105)

`_sender_timestamps` was a `defaultdict(list)` with no upper bound on the number of keys. A deployment receiving messages from many unique senders over time would accumulate one key per sender indefinitely. The fix replaces it with an `OrderedDict`-based LRU pattern capped at 10,000 entries. When a new key would exceed the cap, the oldest key is evicted with `popitem(last=False)`.

#### Fix: `delete_group()` Does Not Remove Filesystem Folder (#106)

`db.delete_group()` removed all DB rows for a group atomically but left the group's folder on disk (containing `CLAUDE.md`, conversation exports, and other files). The fix reads the group's `folder` value from the DB before the delete transaction, then after a successful commit calls `shutil.rmtree()` on `GROUPS_DIR / folder`. Filesystem errors are caught and logged as warnings so a missing or read-only folder does not prevent DB cleanup.

#### Fix: Prompt Truncation Is Silent (#107)

When a user's message exceeded `MAX_PROMPT_LENGTH`, the host logged a warning and silently truncated the text. The user had no indication their message was cut. The fix sends a notification to the group immediately after truncation: `⚠️ 訊息過長（N 字元），已截斷至 M 字元。`

#### Fix: Cron Expression Bounds Validation (#108)

`_compute_next_run()` passed expressions directly to `croniter.is_valid()`, which does not check whether numeric field values are within sane bounds. A crafted expression with very large numbers could cause ReDoS. The fix adds `_validate_cron()`, which calls `croniter.is_valid()` first and then checks each field token against standard cron limits (minute 0-59, hour 0-23, day-of-month 1-31, month 1-12, day-of-week 0-7). Named values (`MON`, `JAN`, etc.) are accepted without numeric bounds checking. For `once` schedule type, datetimes more than 10 years in the future are rejected to prevent accidentally scheduling a task in year 9999.

#### Upgrade

```bash
git pull
# Host-only changes — no Docker image rebuild required
# No DB schema change
python run.py start
```

---

## v1.2.16 — 2026-03-12

### Performance Fix: Dashboard N+1 Genome Query (Issue #97)

This release resolves the N+1 database query pattern in the dashboard groups endpoint that was first documented as a known issue in v1.2.15.

#### Fix: Replace N+1 `db.get_genome()` Loop with Single Batch Query (#97)

`dashboard.py` `_get_groups()` previously called `db.get_genome(jid)` once per registered group inside a loop. With N groups, every dashboard refresh (every 5 seconds) issued N+1 database queries — one to fetch all groups, then one per group to fetch its genome row.

The fix introduces `db.get_all_genomes()` which fetches all genome rows in a single `SELECT` query and returns them as a `dict` keyed by `group_jid`. `_get_groups()` now calls `db.get_all_genomes()` once before the loop and uses `.get(jid, default)` to look up each group's genome in O(1). Total queries per dashboard refresh: 2 (groups + genomes), regardless of group count.

#### Added: `db.get_all_genomes()`

New function in `db.py` returning `dict[str, dict]` — all genome rows in one SELECT, keyed by `group_jid`. Includes all genome fields: `response_style`, `formality`, `technical_depth`, `fitness_score`.

#### Upgrade

```bash
git pull
# Host-only change — no Docker image rebuild required
# No DB schema change
python run.py start
```

---

## v1.2.15 — 2026-03-12

### Security, Reliability, and Performance Fixes (Ninth Round)

This release addresses 8 issues spanning security hardening, scheduler stability, memory leak prevention, and timestamp correctness. No new features; all changes are fixes and hardening.

#### Security: Startup Fatal on Weak Dashboard Password in Production (#93)

`config.py` now raises a fatal error at startup if `DASHBOARD_PASSWORD` is set to the default value `'changeme'` and `DASHBOARD_HOST` is anything other than `'127.0.0.1'`. Exposing the dashboard on a network interface with a known-default password is a critical misconfiguration. A WARNING is additionally logged whenever the password is shorter than 8 characters, regardless of host binding.

#### Security: `group_folder` Path Traversal Prevention (#99)

`runner.py` now validates `group_folder` against the regex `r'^[\w\-]+$'` before using it to construct Docker volume mount paths. A maliciously crafted group folder value (e.g. containing `../`) stored in the database could previously escape the intended mount prefix and expose arbitrary host directories to the container.

#### Fix: Missing Index on `tasks.status` (#94)

`db.py` now creates index `idx_tasks_status` on the `tasks.status` column. Without this index, every scheduler tick performed a full table scan of the `tasks` table to find pending/due tasks. On deployments with many tasks, this caused measurable latency on the scheduler loop and elevated SQLite CPU usage.

#### Fix: `response_ms` Clamped Before Fitness Calculation (#95)

`evolution.py` now clamps `response_ms` to `[0, 600_000]` milliseconds before passing it to `calculate_fitness()`. Integer overflow from very long-running containers or negative values from clock skew could previously produce NaN or out-of-range fitness scores, corrupting the genome and causing undefined evolution behaviour.

#### Fix: Exponential Backoff on Task Failure (#96)

`scheduler.py` now applies exponential backoff to task retry delays after a failure: `min(10 × 2^N, 3600)` seconds, capped at 1 hour. Previously, failed tasks were re-queued at their normal schedule interval, causing rapid repeated LLM calls on transient failures and risking API rate-limit exhaustion.

#### Fix: SSE Fan-out Memory Leak on Client Disconnect (#98)

`dashboard.py` SSE fan-out loop now iterates over a snapshot copy of `_sse_subscribers` and removes dead/stale subscriber queues within the same pass. Previously, clients that disconnected without triggering a `BrokenPipeError` (e.g. proxies that silently drop connections) were never removed, causing unbounded growth of the subscriber set and their associated queues.

#### Fix: Unified Timestamp Source in immune.py (#100)

`immune.py` now uses Python `int(time.time())` exclusively for all timestamp comparisons and insertions. Previously, some code paths used SQLite `strftime('%s','now')` while others used Python's `time.time()`. On systems where the SQLite and Python clocks differ slightly (e.g. different timezone handling), this caused incorrect rate-limit window calculations — senders could be blocked too early or not blocked when they should be.

#### Known Issue / Tracked: N+1 Genome Query in Dashboard (#97)

The groups dashboard endpoint issues one genome query per group (N+1 pattern). This is a known architectural issue tracked in #97. A batched single-query fix is planned for a future release. No code change in this release.

#### Upgrade

```bash
git pull
# Host-only changes — no Docker image rebuild required
# DB schema change: idx_tasks_status index is added automatically on next startup
python run.py start
```

---

## v1.2.14 — 2026-03-12

### Version Bump: Align pyproject.toml with Production Releases

This release aligns `pyproject.toml` with the actual merged state of the repository. No new features or fixes are introduced beyond what was already shipped in v1.2.12 and v1.2.13.

#### Why This Release

`pyproject.toml` was stale at `1.2.11` while the codebase had already incorporated the Docker improvements from v1.2.12 and v1.2.13. This bump brings the package metadata in sync so that `pip install`, `--version`, and published wheel metadata all reflect the correct version.

#### What's Included (carried from v1.2.12 and v1.2.13)

*Docker image is now production-ready with full MCP and tool-use support:*

- Base image upgraded from `python:3.9` to `python:3.11`
- Node.js 20 LTS pre-installed — enables MCP stdio/HTTP server subprocesses via `Bash` tool
- Complete CJK font stack: `fonts-noto-cjk`, `fonts-wqy-zenhei`, `fonts-wqy-microhei`
- Pre-installed document stack: `python-pptx`, `reportlab`, `openpyxl`, `python-docx`
- Data science stack: `pandas`, `numpy`, `matplotlib`, `scipy`, `seaborn` (headless via `MPLBACKEND=Agg`)
- Vision/OCR: `Pillow`, `pytesseract`, `opencv-python-headless`, `tesseract-ocr` with CJK language packs
- Web stack: `httpx`, `beautifulsoup4`, `lxml`, `html5lib`
- Non-root `minion` user (uid 1000), `LC_ALL=C.UTF-8`, `MPLBACKEND=Agg`

#### Upgrade

```bash
git pull
docker build -t miniondesk-agent:1.2.14 -f container/Dockerfile .
```

Update `CONTAINER_IMAGE=miniondesk-agent:1.2.14` in your `.env`.

---

## v1.2.13 — 2026-03-12

### Docker: Production-Ready Agent Container with MCP, Document, and Data Science Support

This release transforms the MinionDesk agent container from a minimal Python runtime into a fully-equipped AI agent platform capable of handling all current and anticipated future tool-use scenarios — without any runtime `pip install` calls.

#### Why This Matters

Agents use the `Bash` tool to run arbitrary shell commands. Previously, skills that needed `pandas`, `requests`, or `reportlab` would `pip install` at task time — slow (30+ seconds), fragile (PyPI outages), and a network security concern. Now all commonly-needed packages are baked into the image.

#### What's New

*Base Image*
- Upgraded from `python:3.9` to `python:3.11` — 10-60% faster execution, better error messages, active support until 2027

*Node.js 20 LTS — MCP Server Support* (#82)
- MCP (Model Context Protocol) servers are commonly Node.js processes. The container can now spawn and communicate with MCP stdio/HTTP servers as subprocesses via the `Bash` tool.

*Web Scraping Stack* (#83)
- `requests`, `aiohttp`, `httpx` — sync and async HTTP clients
- `beautifulsoup4`, `lxml`, `html5lib` — HTML/XML parsing
- Agents can scrape web pages, call APIs, and process HTML without runtime installs

*Document Generation Stack* (#84)
- `reportlab` — PDF generation with full Unicode and CJK support
- `openpyxl` — Excel .xlsx read/write
- `python-docx` — Word .docx read/write
- `python-pptx 1.0.2` — PowerPoint (already present, retained)

*Image Processing* (#85)
- `Pillow` — image resize, crop, annotate, format conversion
- `opencv-python-headless` — computer vision without GUI deps
- `pytesseract` + `tesseract-ocr` with CJK language packs — OCR for Chinese/Japanese/Korean text in images

*Data Science & Visualisation* (#86)
- `pandas`, `numpy`, `scipy` — data analysis and numerical computing
- `matplotlib`, `seaborn` — chart generation (headless via `MPLBACKEND=Agg`)
- Agents can analyse CSV/Excel data and produce charts to send via `send_file`

*CJK Fonts — Complete Coverage* (#87)
- Added `fonts-noto-cjk` alongside existing WQY fonts
- Traditional Chinese, Japanese Kanji, and Korean Hangul all render correctly in all document types

*Utility Tools* (#88)
- `ffmpeg` — audio/video processing
- `tesseract-ocr` with Simplified Chinese, Traditional Chinese, Japanese, Korean packs
- `jq`, `unzip`, `zip`, `wget` — common shell utilities

*Build Toolchain* (#90)
- `build-essential`, `gcc`, `libffi-dev`, `libssl-dev`, `pkg-config` pre-installed
- Native Python packages (cryptography, psycopg2, etc.) compile inside the container for dynamic tool installs

#### Security

Container continues to run as non-root `minion` user (uid 1000). No capabilities added.

#### Upgrade

```bash
git pull
docker build -t miniondesk-agent:1.2.13 -f container/Dockerfile .
```

Update `CONTAINER_IMAGE=miniondesk-agent:1.2.13` in your `.env`.

---

## v1.2.12 — 2026-03-12

### Docker: Upgrade Agent Container with CJK Fonts and Pre-installed python-pptx

本次版本升級 minion container 的 Docker 基礎鏡像，解決中文 PPT 生成失敗與 runtime pip 網路依賴問題。

#### 問題

1. *生成中文 PPT 時字元顯示為方塊*（#80）：舊的 `python:3.11-slim` 基礎鏡像不含任何 CJK 字型套件。`python-pptx` 在找不到對應字型時以方塊佔位符取代所有中文字元。

2. *python-pptx 在 runtime 安裝有網路依賴*（#80）：技能腳本在執行時才透過 `pip install` 安裝 `python-pptx`。PyPI 網路不穩定時安裝失敗，導致技能無法使用。

#### 修正

- 基礎鏡像從 `python:3.11-slim` 升級至 `python:3.9`（Debian Bullseye 完整版）
- 新增系統套件：`libfreetype6`、`libpng16-16`、`zlib1g`
- 新增中文字型：`fonts-wqy-zenhei`、`fonts-wqy-microhei` + `fc-cache -fv`
- 預裝 `python-pptx==1.0.2`（版本鎖定，消除 runtime 網路依賴）
- 新增 `ENV LANG=C.UTF-8`

#### 升級

重建 minion container image 後即可：

```bash
git pull
docker build -t miniondesk-agent:1.2.12 -f container/Dockerfile .
```

---

## v1.2.11 — 2026-03-12

### Reliability, Memory, and Usability Fixes (Eighth Round)

本次版本修正 7 個在 v1.2.10 後發現的新問題，涵蓋 delete_task 雙重 _conn() 呼叫、immune 記憶體字典無限增長、immune_threats 資料表無清理機制、被封鎖的發送者無法解封、技能文件注入無大小限制、排程任務失敗無使用者通知、以及 GroupQueue worker 任務在 shutdown 時被靜默丟棄。

#### Fix 1: `db.py` `delete_task()` 雙重 `_conn()` 呼叫（#72）

`delete_task()` 對 `execute()` 和 `commit()` 各自呼叫一次 `_conn()`。在極端情況下兩次呼叫可能取得不同的連線物件，導致刪除操作被提交至不同連線而靜默失敗。改為捕捉一次 `conn = _conn()` 並重用，與所有其他 DB 函數的寫法一致。

#### Fix 2: `immune.py` `_sender_timestamps` 字典無限增長（#73）

`is_allowed()` 在過濾舊時間戳之前就先將 `now` 附加至 `fresh`，導致 `fresh` 永遠非空，清理分支（`del _sender_timestamps[window_key]`）實際上無法到達。所有曾發送過訊息的發送者都會在字典中永久保留。改為先過濾再判斷是否清理，再追加 `now`，確保超過 60 秒無活動的發送者能被正確移除。

#### Fix 3: `immune_threats` 資料表無清理機制（#74）

`immune_record()` 每次訊息都插入或更新列，但從未刪除舊列。在高流量部署中（如公開群組），每個唯一發送者各占一列，永久累積。新增 `immune_prune_old_rows()` 函數，在每次健康監控循環（60 秒）中刪除 `blocked=0` 且 `last_seen` 超過 7 天的列；封鎖列保留直到明確解封。

#### Fix 4: 被封鎖的發送者無法透過程式解封（#75）

`db.immune_unblock()` 函數存在但從未被任何 IPC handler 或管理介面呼叫。自動封鎖的發送者只能透過直接操作資料庫才能解封。新增 `unblock_sender` IPC 訊息類型，允許操作員或管理員 minion 透過 IPC 發送解封請求，而無需 SSH 進入主機執行 sqlite3。

#### Fix 5: `skills_engine.py` 技能文件注入無大小限制（#76）

`get_installed_skill_docs()` 將所有已安裝技能的 SKILL.md 內容合併後注入每次容器呼叫的 system prompt，沒有任何大小限制。安裝大量技能或單一大型 SKILL.md 可能超出模型 context 上限並顯著增加 token 成本。新增 `_SKILL_DOCS_MAX_BYTES = 32KB` 上限，超出時跳過並記錄 WARNING。

#### Fix 6: 排程任務失敗時無使用者通知（#77）

`run_scheduler()` 的 done callback 在 dispatch 拋出例外時只記錄日誌，不通知使用者。一次性任務失敗後被靜默刪除，使用者無從得知。新增可選的 `notify_fn` 參數（傳入 `route_message`）；任務失敗時向群組發送錯誤訊息和提示預覽；週期性任務在連續失敗達上限後也會發送暫停通知。

#### Fix 7: `GroupQueue` worker 任務在 shutdown 時被靜默丟棄（#78）

`GroupQueue` 建立的 worker `asyncio.Task` 儲存在 `_workers` 字典但從未被取消。SIGTERM 後 event loop 關閉時，所有仍在隊列中的協程被靜默丟棄，既無日誌也無通知。新增 `GroupQueue.shutdown()` 方法取消所有 worker task 並記錄被丟棄的待處理項目數量；在 `run_host()` 關閉頻道前呼叫。

---

## v1.2.10 — 2026-03-12

### Reliability, Security, and Resource Management Fixes (Seventh Round)

本次版本修正 7 個在 v1.2.9 後發現的新問題，涵蓋 asyncio.gather 缺少 return_exceptions 導致子協程崩潰拖垮整個 host、evolution 表格無限增長耗盡磁碟、web_search 回應無大小上限造成 OOM、IPC send_file 路徑穿越導致任意 host 檔案外洩、WAL 檔案無界增長、DevEngine 會話永不清理、以及 config.validate() 缺乏 MINIONS_DIR 存在與 DATA_DIR 可寫性檢查。

#### Fix 1: `asyncio.gather()` 缺少 `return_exceptions=True`（#64）

`run_host()` 中的 `asyncio.gather()` 未加 `return_exceptions=True`。任何子協程（如 `evolution_loop`、`watch_ipc`、`run_scheduler`）拋出未處理例外時，gather 會立即取消所有其他執行中的協程，導致整個 host 進程崩潰。改為加入 `return_exceptions=True`，並在 gather 完成後逐一記錄各協程回傳的例外。

#### Fix 2: `evolution_runs` 與 `evolution_log` 表格無限增長（#65）

`record_evolution_run()` 每次訊息都插入一列且從不刪除舊列；`log_evolution()` 同樣無界增長。長期執行的實例每月可累積數十萬列，最終耗盡磁碟空間。改為在每次 insert 後保留最近 200 筆（evolution_runs）及 100 筆（evolution_log）per group，超出部分自動刪除。

#### Fix 3: `_do_web_search()` HTTP 回應無大小上限（#66）

`urllib.request.urlopen(...).read()` 無大小限制，惡意或失控的上游伺服器可回傳數 GB 資料，全部緩衝於記憶體後才解析 JSON，有 OOM 風險。改為 `resp.read(512 * 1024)` 限制最大 512 KB。

#### Fix 4: `_resolve_container_path()` fallback 允許任意 host 路徑（#67）

`_resolve_container_path()` 的 fallback `return p if os.path.exists(p) else None` 會原樣回傳容器控制的絕對路徑（如 `/etc/passwd`、`/home/user/.env`），呼叫端 `route_file()` 會直接將該 host 檔案傳送至 Telegram/Discord 群組，造成任意檔案外洩。已移除此 fallback，無法識別的路徑一律回傳 `None` 並記錄 WARNING。

#### Fix 5: SQLite WAL 檔案無界增長（#68）

MinionDesk 啟用 WAL 模式但從未顯式呼叫 `PRAGMA wal_checkpoint`。只要有活躍的讀取連線（dashboard、IPC watcher 持續運作），SQLite 自動 checkpoint 常無法完整回寫 WAL，導致 `miniondesk.db-wal` 在繁忙實例上持續膨脹。改為在 health monitor loop（每 60 秒）中加入 `PRAGMA wal_checkpoint(PASSIVE)` 促進 WAL 壓縮。

#### Fix 6: DevEngine 會話永不清理（#69）

每次 `dev_task` IPC 訊息都會建立一筆 `dev_sessions` 列，completed/failed/cancelled 會話從不刪除。改為在 `start_dev_session()` 建立新會話前呼叫 `_prune_dev_sessions()`：刪除超過 7 天的舊會話，並只保留每個群組最近 20 筆。

#### Fix 7: `config.validate()` 缺乏 MINIONS_DIR 存在與 DATA_DIR 可寫性檢查（#70）

`MINIONS_DIR` 不存在時 `runner.py` 靜默回退至預設 persona（不報錯，難以察覺配置錯誤）。`DATA_DIR` 父目錄不可寫時只拋出 `PermissionError` 而無明確指引。改為在 `validate()` 中：(1) `MINIONS_DIR` 不存在時記錄 WARNING；(2) `DATA_DIR` 父目錄不可寫時加入 errors list 並拋出 `ValueError` 附帶明確建議。

---

## v1.2.9 — 2026-03-12

### Reliability, Correctness, and Functional Fixes (Sixth Round)

本次版本修正 9 個在 v1.2.8 後發現的新問題，涵蓋 DB 雙重連線呼叫延伸修正、DELETE 事務管理錯誤、IPC kb_search 型別轉換崩潰、基因組樣式索引錯誤、容器 JSON 解析錯誤遺漏輸出標記、provider KeyError、排程雙重觸發、web-search 技能完全失效（因容器無網路存取）、以及版本號不一致。

#### Fix 1: `update_task_run()` 和 `log_evolution()` 雙重 `_conn()` 呼叫（#54）

`update_task_run()` 和 `log_evolution()` 分別對 `execute()` 和 `commit()` 各自呼叫一次 `_conn()`，若連線物件在兩次呼叫之間被重置，commit 可能無效化。改為在函式開頭指派 `conn = _conn()` 並重複使用。

#### Fix 2: `delete_group()` 使用原始字串 BEGIN/COMMIT/ROLLBACK（#59）

`delete_group()` 使用 `conn.execute("BEGIN")` 等原始字串，若呼叫時已有隱含事務開啟（WAL 模式常見），會拋出 `OperationalError: cannot start a transaction within a transaction`。改為使用 SQLite SAVEPOINT/RELEASE/ROLLBACK TO，支援重入式事務。

#### Fix 3: `ipc.py` kb_search `limit` 非整數值導致未處理 ValueError（#56）

`int(payload.get("limit", 5))` 在收到非整數值時拋出 `ValueError`，傳播至外層 `except Exception` 導致 IPC 訊息被標記已處理並刪除（靜默丟失）。改為 try/except 包裹並預設值 5。

#### Fix 4: `evolution.py` `STYLE_ORDER.index()` 未知樣式值崩潰（#57）

若 genome 表格中存有 STYLE_ORDER 以外的 `response_style` 值，`list.index()` 拋出 `ValueError` 並阻斷當輪所有群組的進化。改為先檢查成員資格，未知值記錄 warning 後重置為 `"balanced"`。

#### Fix 5: 容器 JSON 解析失敗時遺漏輸出標記（#60）

`json.JSONDecodeError` 路徑直接 `print(json.dumps(result))` 而不加輸出標記，主機解析器只看到「No valid output from container」而無法獲得實際錯誤訊息。改為加入 `<<<MINIONDESK_OUTPUT_START>>>` / `<<<MINIONDESK_OUTPUT_END>>>` 標記。

#### Fix 6: ClaudeProvider/GeminiProvider 使用 `os.environ[KEY]` 拋出 KeyError（#61）

兩個 provider 使用括號存取 `os.environ["KEY"]`，若環境變數在 `auto.py` 檢查後消失（例如 process supervisor 清除 env），會拋出未處理的 `KeyError` 且沒有輸出標記。改為 `os.getenv("KEY", "")`，讓 SDK 自行提供清晰的認證錯誤。

#### Fix 7: 排程器短間隔任務雙重觸發（#62）

`db.update_task_run()` 在 `asyncio.create_task()` 後立即呼叫（容器尚未完成），下一個 10 秒輪詢週期若任務已到期（容器比間隔慢），會再次觸發。新增 `_in_flight` 集合追蹤進行中的任務，重複輪詢時跳過。

#### Fix 8: web-search 技能在容器無網路時完全失效（#55）

容器以 `--network none` 啟動，web_search 工具直接呼叫 DuckDuckGo API 必然失敗。改為透過 IPC 機制將搜尋請求路由至主機端執行，主機完成 HTTP 呼叫後將結果寫回群組 IPC 目錄，容器輪詢讀取。

#### Fix 9: 版本號不一致（#58）

`pyproject.toml` 版本為 `1.0.0`，`miniondesk/run.py` CLI `--version` 硬編碼為 `"1.0.0"`，均未反映實際版本。更新 `pyproject.toml` 至 `1.2.9`，`run.py` 改為動態讀取 `__version__`。

---

## v1.2.8 — 2026-03-12

### Reliability, Correctness, and Security Improvements (Fifth Round)

本次版本修正 10 個在 v1.2.7 後發現的新問題，涵蓋 SSE 回應順序錯誤、IPC 原子寫入競態、LLM 設定靜默失敗、DB 雙重連線呼叫、基因組適應度未持久化、容器取消計數遺漏、技能安裝不一致回滾、排程一次性任務丟失、容器映像版本未更新及企業 IPC 類型未處理。

#### Fix 1: SSE 503 在標頭已寫入後才傳送（#43）

`_sse_stream()` 在寫入 `send_response(200)` 及 SSE 標頭後才檢查客戶端數量上限，超限時以 200 狀態傳送 503 錯誤文字，瀏覽器 EventSource 誤判成功並不斷重試。
將上限檢查移至任何標頭寫入之前，超限時正確回傳 HTTP 503。

#### Fix 2: IPC 檔案非原子寫入 TOCTOU 競態（#44）

容器以 `write_text()` 直接寫入 `.json` 檔案，主機在寫入完成前即可讀取，導致 `JSONDecodeError` 且訊息被永久標記為已處理並刪除（靜默訊息丟失）。
改為先寫入 `.tmp` 暫存檔，再以 `rename()` 原子替換為 `.json`，確保主機只讀取完整檔案。

#### Fix 3: 無 LLM 設定時靜默連線到 localhost（#45）

`get_provider()` 在所有 LLM 環境變數均未設定時，回退至 `OllamaProvider()` 嘗試連線 `localhost:11434`，在容器環境中產生難以排查的連線拒絕錯誤。
改為拋出 `RuntimeError` 並列出所有可用設定選項，快速失敗並給出明確指引。

#### Fix 4: `add_message()` 雙重 `_conn()` 呼叫（#46）

`add_message()` 和 `record_evolution_run()` 對 `execute()` 和 `commit()` 各自呼叫一次 `_conn()`，若未來加入連線輪換邏輯可能導致 commit 執行在不同連線上造成靜默資料丟失。
改為在函式開頭指派一次 `conn = _conn()` 並重複使用。

#### Fix 5: 基因組適應度分數未持久化（#47）

`evolve_genome()` 的 `changed` 檢查未包含 `fitness_score` 差異，若 style/formality/depth 維度未變但適應度顯著改變，新分數永遠不會寫入 DB，Dashboard 顯示陳舊值。
將 `abs(avg_fitness - before_fitness) > 0.001` 加入 `changed` 條件。

#### Fix 6: `CancelledError` 後容器殭屍及熔斷計數遺漏（#48）

`CancelledError` 處理只呼叫 `docker stop`（advisory），未直接終止 subprocess handle，且未增加熔斷失敗計數，導致殭屍容器及熔斷器低估失敗率。
新增 `proc.kill()` 直接終止 subprocess，並在 re-raise 前遞增失敗計數。

#### Fix 7: 技能安裝失敗無回滾（#49）

`install_skill()` 逐檔複製，中途失敗時部分檔案已複製到目標目錄但 registry 未更新，孤立檔案繞過後續安裝的衝突偵測。
新增 `copied_paths` 追蹤，任何例外時刪除所有已複製檔案後回傳錯誤。

#### Fix 8: 一次性排程任務在 dispatch 前即刪除（#50）

`once` 任務在 `create_task()` 後立即從 DB 刪除，若容器執行失敗則任務永久消失（無重試、無通知）。
將 `db.delete_task()` 移至 done callback 內，僅在成功時刪除；失敗時同樣刪除（避免重複執行）但先記錄錯誤。

#### Fix 9: 容器映像預設版本未隨版本更新（#51）

`CONTAINER_IMAGE` 預設值停在 `1.2.7`，不設定 `.env` 時主機與容器版本不一致，新 payload 欄位在舊映像中靜默忽略。
更新預設值為 `miniondesk-agent:1.2.8`；啟動時記錄當前映像標籤供驗證。

#### Fix 10: 企業 IPC 類型 `kb_search`/`workflow_trigger`/`calendar_check` 靜默忽略（#52）

容器企業工具寫入這三種 IPC 訊息類型，但主機 `_handle_ipc()` 無對應處理器，全部落入 `Unknown IPC type` 分支被丟棄，企業功能實際上完全無效。
新增三個處理器，分別呼叫 `knowledge_base.search()`、`workflow.trigger_workflow()` 和 `calendar.check_availability()`，並將結果路由回群組。

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
