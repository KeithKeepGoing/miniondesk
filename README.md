# 🐤 MinionDesk

**企業 AI 助理框架** — 由 **Mini** 領軍的小小兵團隊，Docker 隔離，模型無關，資料完全自架。

> *目前版本：v1.2.19*

```
主助理 Mini + 部門小小兵（Kevin/Stuart/Bob）
每個小小兵 = 一個 Docker container，有名字、人設、專屬工具
換 Gemini / Claude / OpenAI / Ollama 只改一行設定
SQLite + Docker，資料不出公司
整個框架 < 60 個 Python 檔
對話記憶：Agent 記住最近 20 則對話，跨 container 保持上下文
DevEngine：7 階段 AI 流水線，讓 MinionDesk 自己寫程式
Superpowers：可安裝行為插件，強化所有小小兵能力
Thread-safe：circuit breaker 與 genome 更新使用 lock / 原子 SQL
穩定性：DB connection atexit 關閉、deque log buffer、正確 uptime
並行容器：Semaphore 取代全域 Lock，最多 4 個容器同時執行
架構改進：request_id 追蹤、schema 驗證、健康端點、輸入截斷
安全加固：minion 名稱路徑驗證、container stdout 大小限制、SSE fan-out 修正
背壓保護：GroupQueue 有界佇列、config 啟動驗證、ensure_future 全面替換
v1.2.19 關機可靠性：asyncio task 明確取消、scheduler dict 競態修正、IPC_POLL_INTERVAL 零值防護、dashboard shutdown hook、container name 上限、schedule_value ReDoS 防護 (#116-#121)
v1.2.18 安全與可靠性：IPC 檔案大小限制、_in_flight 過期清理、request_id 驗證、immune 單調時鐘 (#110-#114)
v1.2.17 記憶體洩漏：_fail_counts 清理、immune LRU 上限、orphan genome 清理、群組刪除清資料夾、截斷通知、cron 驗證 (#103-#108)
v1.2.16 效能：dashboard N+1 genome 查詢改為單次批次 (#97)
v1.2.15 安全強化：弱密碼保護、路徑穿越防護、tasks 索引、response_ms 箝制、指數退避、SSE 洩漏修正
```

---

## 快速開始

```bash
# 1. 安裝
pip install -e .

# 2. 設定
cp .env.example .env
# 編輯 .env，設定至少一個 LLM provider

# 3. 建立 Docker 映像檔
docker build -t miniondesk-agent:1.2.19 -f container/Dockerfile .

# 4. 檢查設定
python run.py check

# 5. 啟動
python run.py start
```

---

## Docker Container Capabilities (v1.2.19)

The agent container is production-ready with a full tool-use stack pre-installed:

| Category | Included |
|----------|---------|
| Base | Python 3.11, Node.js 20 LTS (for MCP servers) |
| Document generation | python-pptx, reportlab (PDF), openpyxl (Excel), python-docx (Word) |
| Web scraping | requests, aiohttp, httpx, beautifulsoup4, lxml, html5lib |
| Image processing | Pillow, opencv-python-headless, pytesseract |
| Data science | pandas, numpy, matplotlib, seaborn, scipy |
| CJK fonts | fonts-wqy-zenhei, fonts-wqy-microhei, fonts-noto-cjk |
| OCR | tesseract-ocr with Simplified/Traditional Chinese, Japanese, Korean |
| Media | ffmpeg |
| Utilities | jq, unzip, zip, wget, curl, git |
| Build tools | build-essential, gcc, libffi-dev, libssl-dev |
| Security | Runs as non-root `minion` user (uid 1000) |

---

## 小小兵團隊

| 小小兵 | 職責 | 觸發詞 |
|-------|------|--------|
| 🌟 **Mini** | *主助理 Boss* — 一般問答，協調各部門 | @Mini |
| **Kevin** | HR — 請假、招募、薪資 | @Kevin |
| **Stuart** | IT — 技術支援、設備、帳號 | @Stuart |
| **Bob** | 財務 — 報銷、採購、預算 | @Bob |

> **Mini** 是 MinionDesk 的頭號助理，由 `ASSISTANT_NAME=Mini` 設定（可自訂）。

---

## 支援 LLM Provider

MinionDesk 自動偵測並使用第一個可用的 provider：

| Provider | 設定 | 說明 |
|----------|------|------|
| Google Gemini | `GOOGLE_API_KEY` | **首選**，有免費額度 |
| Anthropic Claude | `ANTHROPIC_API_KEY` | 高品質推理 |
| OpenAI | `OPENAI_API_KEY` | 廣泛相容 |
| Ollama | `OLLAMA_URL` | 本地模型，完全離線 |
| vLLM / LM Studio | `OPENAI_BASE_URL` | 自架 OpenAI-compatible |

---

## 架構

```
miniondesk/
├── minions/          小小兵人設（Markdown）
│   ├── phil.md
│   ├── kevin.md
│   ├── stuart.md
│   └── bob.md
│
├── miniondesk/
│   └── host/         主機程序（orchestrator）
│       ├── main.py   asyncio 主循環
│       ├── config.py 環境變數設定
│       ├── db.py     SQLite（WAL 模式）
│       ├── ipc.py    IPC 檔案監控
│       ├── queue.py  per-group 序列化佇列
│       ├── runner.py Docker spawn + 結果解析
│       ├── scheduler.py cron/interval/once 排程
│       ├── channels/ Telegram / Discord / Teams
│       └── enterprise/ KB / workflow / RBAC / 部門路由
│
├── container/        Docker 映像檔
│   ├── Dockerfile
│   └── runner/
│       ├── runner.py  模型無關 agentic loop（最多 30 輪）
│       ├── providers/ Gemini / Claude / OpenAI / Ollama
│       └── tools/     Bash / Read / Write / Edit / send_message / send_file
│
├── workflows/        YAML 工作流程定義
└── knowledge/raw/    知識庫原始文件
```

---

## 核心設計

### 模型無關 Provider 抽象層

```python
from container.runner.providers.auto import get_provider

provider = get_provider()  # 自動選擇
response = await provider.complete(messages, tools, system)
```

### 工具系統

```python
from container.runner.tools import Tool, register_tool

register_tool(Tool(
    name="my_tool",
    description="Does something useful",
    schema={"type": "object", "properties": {"input": {"type": "string"}}},
    execute=lambda args, ctx: f"Result: {args['input']}",
))
```

### IPC 訊息格式

小小兵透過 JSON 檔案發送 IPC 訊息（放在 `/workspace/group/.ipc/`）：

```json
// 發送訊息
{"type": "message", "text": "Hello!", "sender": "Phil", "chatJid": "tg:123"}

// 發送檔案
{"type": "send_file", "filePath": "/workspace/group/output/report.pdf", "caption": "報告"}

// 排程任務
{"type": "schedule_task", "prompt": "每日摘要", "schedule_type": "cron", "schedule_value": "0 9 * * *"}

// 啟動 DevEngine
{"type": "dev_task", "prompt": "新增 OAuth2 登入支援", "mode": "auto"}

// 安裝 Skill
{"type": "apply_skill", "skill": "systematic-debugging"}

// 卸載 Skill
{"type": "uninstall_skill", "skill": "systematic-debugging"}

// 列出 Skills
{"type": "list_skills", "filter": "available"}
```

### 企業工作流程

```yaml
# workflows/leave_request.yaml
name: 請假申請
steps:
  - name: 主管審批
    type: approval
    approver: manager
  - name: HR 確認
    type: approval
    approver: kevin
```

---

## DevEngine — AI 開發流水線

讓小小兵自己寫程式。7 個階段，從需求到部署全自動。

```json
// 觸發 DevEngine（IPC 訊息）
{"type": "dev_task", "prompt": "新增 Slack 頻道整合", "mode": "auto"}
```

| 階段 | 說明 |
|------|------|
| ANALYZE | 需求分析、驗收條件、風險評估 |
| DESIGN | 架構設計、模組結構、資料流圖 |
| IMPLEMENT | 完整 Python 程式碼（含 imports、docstrings） |
| TEST | pytest 測試案例，目標 >80% 覆蓋率 |
| REVIEW | 安全性 + 品質審查（PASS / FAIL / PASS_WITH_NOTES） |
| DOCUMENT | README 段落、CHANGELOG 條目、API 文件 |
| DEPLOY | 將 `--- FILE: path ---` 區塊寫入磁碟（路徑安全防護） |

**模式**：
- `auto` — 全自動跑完 7 個階段
- `interactive` — 每階段暫停，等 `/dev resume <session_id>` 繼續

```bash
# Python API
from miniondesk.host.dev_engine import start_dev_session
session_id = await start_dev_session(group_jid, "新增 Webhook 支援", mode="interactive")
```

---

## Superpowers Skills Engine

可安裝的行為插件，裝一次，所有小小兵都會用。

### 內建 Skills

| Skill | 功能 |
|-------|------|
| `brainstorming` | 動手前先設計，設計優先 |
| `systematic-debugging` | 4 階段根因分析（觀察→假設→隔離→修復） |
| `planning` | 任務拆解為原子步驟 |
| `verification` | 宣稱完成前必須驗證 |
| `subagent-delegation` | 平行子代理模式加速複雜任務 |

### 安裝 Skill

```json
// IPC 訊息
{"type": "apply_skill", "skill": "systematic-debugging"}

// 或 Python
from miniondesk.host.skills_engine import install_skill
ok, msg = install_skill("systematic-debugging")
```

### 自訂 Skill

```
skills/my-skill/
├── manifest.yaml
└── add/
    └── docs/superpowers/my-skill/SKILL.md
```

```yaml
# manifest.yaml
skill: my-skill
version: "1.0.0"
description: "我的自訂技能"
author: "你的名字"
adds:
  - docs/superpowers/my-skill/SKILL.md
```

---

## 與其他框架比較

| 特性 | nanoclaw | evoclaw | MinionDesk |
|------|---------|--------|------------|
| 語言 | TypeScript | Python | Python |
| 模型 | Claude only | Gemini+Claude | **任意（自動偵測）** |
| 隔離 | OS process | Docker | Docker |
| 對話記憶 | ❌ | ❌ | ✅ 最近 20 則歷史 |
| 企業 KB | ❌ | ❌ | ✅ FTS5+LIKE |
| 工作流程 | ❌ | ❌ | ✅ YAML 定義 |
| 部門路由 | ❌ | ❌ | ✅ 關鍵字+LLM |
| RBAC | ❌ | ❌ | ✅ |
| DevEngine | ❌ | ❌ | ✅ 7 階段 AI 流水線 |
| Skills Engine | ❌ | ❌ | ✅ 可安裝行為插件 |
| 基因組演化 | ❌ | ❌ | ✅ 3D 自適應 |
| 免疫系統 | ❌ | ❌ | ✅ 滑動視窗限速 |
| Dashboard | ❌ | ❌ | ✅ SSE 即時監控 |
| 資料量 | < 30 檔 | ~60 檔 | **< 60 檔** |

---

## 企業模組

### 知識庫

```python
from miniondesk.host.enterprise.knowledge_base import index_document, search

index_document("請假政策", "員工每年享有14天年假...", dept="hr")
results = search("年假天數", limit=5)
```

### RBAC

```python
from miniondesk.host.enterprise.rbac import can, set_user_role

set_user_role("user123", "manager")
if can("user123", "workflow_trigger"):
    # 執行操作
```

### 部門路由

```python
from miniondesk.host.enterprise.dept_router import route_to_minion

minion = route_to_minion("我想申請年假")  # → "kevin"
```

---

## 驗證

```bash
# Provider 測試
cd container
python3 -c "from runner.providers.auto import get_provider; print(type(get_provider()).__name__)"

# 工具系統
python3 -c "
import sys; sys.path.insert(0, 'runner')
import tools.filesystem
from tools import get_registry
r = get_registry()
print('Tools:', r.all_names())
"

# 知識庫
python3 -c "
import sys; sys.path.insert(0, '.')
import os; os.environ['DATA_DIR'] = '/tmp/md_test'
from miniondesk.host import db
db.init('/tmp/md_test/test.db')
db.kb_add('Test', 'Hello world', dept='test')
results = db.kb_search('Hello')
print('KB results:', results)
"

# 系統檢查
python run.py check
```

---

## License

MIT
