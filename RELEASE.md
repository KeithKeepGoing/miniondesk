# MinionDesk Release Notes

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
| v1.2.3 | 2026-03-12 | 穩定性修正（thread safety / db cleanup / error handling） |
| v1.2.2 | 2026-03-11 | 對話記憶持久化（get_history 正式啟用） |
| v1.2.1 | 2026-03-11 | dynamic_tools 熱插拔 + container_tools manifest |
| v1.2.0 | 2026-03-11 | DevEngine 7 階段流水線 + Superpowers Skills |
| v1.1.0 | 2026-03-11 | Mini 主助理 + 演化 + 免疫 + Dashboard |
| v1.0.0 | 2026-03-11 | 初次發布 |
