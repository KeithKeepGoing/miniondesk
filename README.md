# MinionDesk 🍌

> 企業內部 IT AI Copilot — IC 設計產業專屬 × 模型無關 × Docker 隔離 × 完全自架

### Recent Releases

| 版本 | 摘要 |
|------|------|
| **v2.4.19** | Reliability + security fixes: rate limiter skip bug, hardcoded timeouts, sequential scheduler, IPC cleanup, notification purge, SQLite busy_timeout |
| **v2.4.18** | Agent will — persistent identity, MEMORY.md enforcer v3, host auto-write fallback |
| **v2.4.17** | Refactor: extract soul rules to soul.md |
| **v2.4.16** | Milestone enforcer v2 — anti-fabrication detection |
| **v2.4.15** | Soul enforcement — MEMORY.md injection, milestone enforcer, Level B heuristic |

---

每個小小兵是一個獨立的 Docker container，有名字、人設、專屬工具。
支援 Gemini / Claude / OpenAI / Ollama，一行設定切換模型。資料完全不出公司。

---

## 功能特色

### 🤖 小小兵人格系統
- **Phil** 🍌 — 首席助理，協調所有部門，一般問題首選
- **Kevin** 🤓 — HR 人資，請假 / 薪資 / 福利
- **Stuart** 🔧 — IT 工程師，電腦 / 帳號 / 環境排障
- **Bob** 💰 — 財務，報帳 / 預算 / 採購

### 🧠 三層記憶系統（OpenClaw MemSearch 架構）
- 🔥 **熱記憶（Hot）** — 每群組 8KB，每次啟動自動注入
- 🌡️ **暖記憶（Warm）** — 30 天每日對話日誌
- ❄️ **冷記憶搜尋（Cold）** — FTS5 BM25 全文搜尋 + 時間衰減排序
- 🔄 微同步每 3 小時 / 週複合摘要每 7 天

### 📊 Web Dashboard — 10+ 分頁
- 📊 **Overview** — 系統狀態總覽
- 📋 **Tasks** — 任務列表（含執行歷史）
- 💬 **Messages** — 對話記錄
- 🧠 **Memory** — 熱 / 暖記憶查看 + 全文搜尋
- 📚 **Knowledge Base** — 知識庫管理
- 🤖 **Minions 瀏覽器** — 小小兵設定一覽
- ⚙️ **Features 總覽** — 所有功能開關狀態
- 📈 **使用統計** — 用量分析圖表
- 🐳 **Container Logs** — 完整 stderr 展開查看器（📋 展開 Modal，32KB 儲存）

### 🔑 安全與可觀測性
- Container 啟動自動執行 `gh auth login --with-token`（GITHUB_TOKEN 自動認證）
- 結構化 container logging — `_slog()` 函數，分類輸出至 stderr
- 完整 log 類型：USER / SYSTEM / HISTORY / LLM / TOOL / REPLY
- stderr 儲存上限 32KB，Dashboard Modal 展開完整查看

### 🏢 企業功能（Enterprise）
- 📅 **日曆整合** — 請假 / 會議排程
- 🔐 **RBAC 角色權限** — 與 AD / LDAP 群組動態對齊
- 🔄 **工作流程引擎** — 審批流程（請假 / 報帳 / IT 工單）
- 📖 **知識庫 RAG** — FTS5 + 語義搜尋，支援 Confluence / SharePoint 同步

### 🌐 平台與部署
- 📱 **多平台** — Telegram / Discord / Microsoft Teams / Web Portal
- 🔄 **模型無關** — Claude / Gemini / OpenAI / Ollama 一鍵切換
- 🐳 **Docker 隔離** — 每次對話 = 新 container，無狀態、安全
- 💾 **完全自架** — SQLite + Docker，資料不出公司
- 🐍 **純 Python** — 90+ 個 Python 檔，易讀易改

---

## 快速開始

```bash
# 1. 複製設定檔
cp .env.example .env
# 編輯 .env，填入 LLM API key 和通訊平台 token

# 2. 執行 setup（建 Docker 映像檔）
python run.py setup

# 3. 驗證設定
python run.py validate

# 4. 啟動
python run.py start
```

> **注意**：使用 `docker-compose.yml` 啟動時，host container 需要存取 Docker socket。
> 若有安全顧慮，建議直接在主機執行：`python run.py start`（不透過 docker-compose）。

---

## 小小兵

| 名字 | 職責 | 對應部門 |
|------|------|----------|
| **Phil** 🍌 | 首席助理，協調所有部門 | 一般 |
| **Kevin** 🤓 | HR 人資，請假 / 薪資 / 福利 | 人資 |
| **Stuart** 🔧 | IT 工程師，電腦 / 帳號 / 環境排障 | 資訊 |
| **Bob** 💰 | 財務，報帳 / 預算 / 採購 | 財務 |

對話中可自動路由（關鍵字 + LLM 判斷），或手動切換：
- Telegram：`/minion stuart`
- Discord：`!minion bob`

---

## 架構

```
miniondesk/
├── container/              Docker 映像檔（模型無關 runner）
│   └── runner/
│       ├── providers/      LLM 抽象層（Claude / Gemini / OpenAI / Ollama）
│       └── tools/          工具系統
│           ├── filesystem.py   讀寫檔案、執行 Bash（含安全黑名單）
│           ├── enterprise.py   KB 搜尋、工作流程、行事曆、員工查詢
│           ├── hpc.py          HPC 工具（LSF / Slurm / FlexLM / NAS）
│           └── integrations.py Jira / ServiceNow / GitLab / Log 分析
├── host/                   主機程序（orchestrator）
│   ├── channels/           頻道（Telegram / Discord / Teams / Web）
│   ├── enterprise/         企業模組
│   │   ├── knowledge_base.py   RAG 知識庫（FTS5 + 語義搜尋）
│   │   ├── workflow.py         審批流程（請假 / 報帳 / IT 工單）
│   │   ├── dept_router.py      部門自動路由
│   │   ├── ldap.py             AD / LDAP 整合
│   │   └── confluence.py       Confluence / SharePoint KB 爬取
│   ├── immune.py           Prompt Injection + IC DLP 防護
│   ├── ratelimit.py        速率限制
│   ├── webportal.py        Web Portal（FastAPI + WebSocket）
│   └── health.py           健康檢查 + Prometheus metrics
├── docs/
│   └── ic-design-spec.md   IC 設計 IT Copilot 規格書
├── minions/                小小兵人設（Markdown）
├── tests/                  單元測試（28 tests）
└── workflows/              工作流程定義（YAML）
```

---

## 支援的 LLM

```bash
# Claude（預設首選）
ANTHROPIC_API_KEY=sk-ant-...

# Gemini（免費額度）
GOOGLE_API_KEY=AIza...

# OpenAI / Azure OpenAI
OPENAI_API_KEY=sk-...

# Ollama（本地，完全離線）
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
```

---

## IC 設計專屬功能

### HPC 資源管理
```
用戶：我的 Job 怎麼 PEND 了這麼久？
Stuart：查詢中... bjobs 結果：Queue 'normal' 目前 PEND 47 個 Job，
        RUN slot 已滿。建議改用 'short' Queue（目前有 12 個空位）。
```

### EDA License 查詢
```
用戶：現在 VCS license 夠用嗎？
Stuart：FlexLM 查詢結果：VCS — 共 20 licenses，使用 18，剩餘 2 個。
        高峰時段（10-12am）建議預先排程。
```

### 智能 Log 分析
```
用戶：[貼上 Kernel panic log]
Stuart：分析完成！錯誤原因：OOM Killer 在 14:32 強制終止 synopsys_dc。
        記憶體峰值 47.2GB 超出節點 48GB 限制。
        建議：降低 set_max_dynamic_power，或換用 mem_large Queue。
```

### RTL / 機密資料 DLP
系統內建 IC 設計專屬 DLP 規則，自動攔截：
- RTL 原始碼（`module` / `wire` / `reg` 宣告）
- GDS layout 檔案引用
- NRE 成本 / 財務預測數據
- Tape-out 時間表 / Foundry NDA

---

## 企業整合

### Jira / ServiceNow
```
用戶：幫我開一張 IT 工單，VPN 掛了
Stuart：已在 Jira 建立 IT-456：「VPN 連線異常」，優先級 High，指派給 it-infra。
        🔗 https://corp.atlassian.net/browse/IT-456
```

### GitLab Weekly Report
```
用戶：幫我生成本週工作日誌
Stuart：已整合 GitLab commits（14 筆）和 Jira 工單（8 張），生成週報如下...
```

### AD / LDAP SSO
- 自動同步 AD 用戶到員工資料庫
- 群組對應 MinionDesk 角色（admin / supervisor / employee）
- RBAC 權限與 AD 群組動態對齊

### Confluence / SharePoint 知識庫
```bash
python run.py confluence-sync   # 同步 Confluence → RAG 知識庫
python run.py sharepoint-sync   # 同步 SharePoint → RAG 知識庫
```

---

## Web Portal

瀏覽器介面，適合貼上大型 Log 或進行 Code Review：

```bash
# 啟用 Web Portal
WEBPORTAL_ENABLED=true python run.py start

# 或單獨啟動測試
python run.py portal
```

開啟 `http://localhost:8082` 即可使用，支援：
- 選擇助理（Phil / Kevin / Stuart / Bob）
- 貼上長篇 Log / 程式碼（無字數限制）
- WebSocket 即時回應
- Ctrl+Enter 送出

---

## 管理員指令

```bash
# 系統
python run.py validate                         # 啟動前環境驗證
python run.py admin status                     # 系統狀態
python run.py admin add-employee <jid> <name>  # 新增員工

# 知識庫
python run.py ingest ./knowledge/              # 匯入本地知識
python run.py confluence-sync                  # 同步 Confluence
python run.py sharepoint-sync                  # 同步 SharePoint
python run.py admin kb-search "VPN 設定"       # 知識庫搜尋

# LDAP
python run.py ldap-test <username>             # 測試 LDAP 連線

# 審計
python run.py admin audit-log                  # 操作記錄

# 監控
curl http://localhost:8080/health              # 健康檢查
curl http://localhost:8080/metrics             # Prometheus metrics
```

---

## 安全說明

| 項目 | 說明 |
|------|------|
| **Docker 隔離** | `--network=none` 確保容器無法存取外部網路 |
| **IC DLP** | 自動攔截 RTL / GDS / NRE / 財務敏感資料 |
| **Prompt Injection** | 免疫系統掃描中英文攻擊模式（20+ 規則）|
| **RBAC** | 員工需先登記才能提交審批；角色與 AD 群組對齊 |
| **Teams HMAC** | Teams Webhook 使用 HMAC-SHA256 驗證 |
| **速率限制** | 每用戶 10 req/min 防止濫用 |
| **Allowlist** | 可限制特定 Telegram / Discord 帳號才能使用 |
| **Docker socket** | 建議直接 `python run.py` 避免 docker socket 掛載 |

---

## 測試

```bash
python -m pytest tests/ -v   # 28 tests，全部通過
```

---

## Roadmap

- [x] **Phase 1**：知識庫 RAG、審批流程、多渠道、AD/LDAP、Confluence/SharePoint
- [x] **Phase 2**：HPC 工具、EDA License、Jira/GitLab、Web Portal、Log 分析器
- [ ] **Phase 3**：VS Code 外掛、Email 摘要自動化、NAS API（NetApp/IBM）

詳細規格：[docs/ic-design-spec.md](docs/ic-design-spec.md)

---

## License

MIT
