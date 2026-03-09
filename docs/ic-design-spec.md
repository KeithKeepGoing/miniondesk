# 企業內部 IT 虛擬助理 (AI Copilot) 開發規格與需求書
> IC 設計產業專屬版 · MinionDesk 實作藍圖

---

## 壹、專案概述

| 項目 | 說明 |
|------|------|
| **專案目標** | 打造單一入口的 IT 虛擬助理，降低跨部門溝通成本，自動化處理高頻行政庶務，並提供深度的技術排障與開發輔助 |
| **目標受眾** | 全體員工（以研發工程師為主）及 IT 部門（OA、AP、ERP、AI、Infra、資安） |
| **核心技術** | LLM、RAG（檢索增強生成）、API 系統串接、Workflow Automation |

---

## 貳、核心功能模組

### 模組一：通訊與行政自動化
> 涵蓋 OA、ERP、全體 IT

| 功能 | 說明 | MinionDesk 狀態 |
|------|------|-----------------|
| **智能讀信與摘要** | 自動閱讀報修信件、系統警報；條列核心訴求、已嘗試步驟、緊急程度 | ✅ 可透過 KB + LLM 實現 |
| **自動草擬回信** | 根據來信意圖與 IT 規範生成專業回覆草稿（權限通知、報修進度、補件要求） | ✅ Phil/Kevin 具備能力 |
| **工作日誌生成** | 串接 Jira/ServiceNow/版控，撈 commit 紀錄與工單，生成 Weekly Report / Action Items | ✅ 已實作 |

---

### 模組二：技術排障與問題解決
> 涵蓋 Infra、資安、OA

| 功能 | 說明 | MinionDesk 狀態 |
|------|------|-----------------|
| **Log 智能分析** | 貼上 Kernel panic / DB error / EDA 報錯，精準指出錯誤行數並白話解釋 | ✅ 透過 RAG + LLM 可實現 |
| **IC 設計環境排障** | VNC/遠端桌面卡頓引導、.cshrc 環境變數設定、製程節點 Linux 環境 | 🔧 需 IC 專屬知識庫 |
| **資安合規指引** | 判斷開源軟體白名單、合規內外網資料交換流程、DLP 警報預防 | ⚠️ 部分：免疫系統已有，需加白名單 KB |

---

### 模組三：開發與程式輔助
> 涵蓋 AP、AI、Infra

| 功能 | 說明 | MinionDesk 狀態 |
|------|------|-----------------|
| **Code Review** | 檢查 Bug、優化複雜度、確保符合資安寫作規範 | ✅ Stuart/AI 具備能力 |
| **自動生成註解與測試** | ERP/AP 客製程式一鍵生成程式註解與 Unit Test 腳本 | ✅ 具備能力 |
| **老舊語言翻譯** | Shell Script / Perl → Python / Golang | ✅ 具備能力 |

---

### 模組四：IC 設計專屬營運支援
> 涵蓋 Infra

| 功能 | 說明 | MinionDesk 狀態 |
|------|------|-----------------|
| **HPC Job 狀態查詢** | 透過對話查詢 LSF/Slurm Job 排程進度（Pending 原因）| ✅ 已實作 |
| **EDA License 查詢** | FlexLM 授權剩餘數量即時查詢 | ✅ 已實作 |
| **Storage 管理** | NAS 空間預警、Quota 擴充申請、Snapshot 還原教學 | 🔧 需 NAS API 整合 |

---

## 參、系統架構與介面規格

### 介面渠道

| 渠道 | 說明 | MinionDesk 狀態 |
|------|------|-----------------|
| **Teams Bot** | 日常問答、讀信/回信 | ✅ Teams channel 已實作 |
| **Telegram Bot** | 行動端存取 | ✅ 已實作 |
| **Discord Bot** | 開發團隊協作 | ✅ 已實作 |
| **Web Portal** | 貼上大量 Log / Code Review | ✅ 已實作 (port 8082) |
| **VS Code 外掛** | AP/開發人員 IDE 整合 | 🔧 選配，待評估 |

### API 整合需求

| 系統 | 用途 | 優先級 |
|------|------|--------|
| **AD / LDAP** | SSO 單一登入、RBAC 權限控管 | 🔴 Phase 1 |
| **Confluence / SharePoint** | RAG 知識庫來源 | 🔴 Phase 1 |
| **Jira / ServiceNow** | 自動開單、工單狀態追蹤 | 🟠 Phase 2 |
| **LSF / Slurm** | HPC Job 排程查詢 | 🟠 Phase 2 |
| **FlexLM** | EDA License 查詢 | 🟠 Phase 2 |
| **NAS API** | 儲存空間監控 | 🟡 Phase 2 |
| **Git / GitLab** | Commit 記錄、Weekly Report | 🟡 Phase 2 |

---

## 肆、資訊安全與權限控管

| 需求 | 說明 | MinionDesk 狀態 |
|------|------|-----------------|
| **資料隱私** | 對話/Log/程式碼不可作外部 LLM 訓練資料；On-premise 或企業私有雲 | ✅ Docker 隔離 + Ollama 支援 on-prem |
| **RBAC** | 回覆內容與 AD 權限對齊；一般員工無法查機密 Tape-out 資料 | ✅ RBAC 已實作，需串接 AD |
| **DLP 機制** | 偵測未授權 RTL 原始碼或敏感財務數據，拒絕處理並觸發資安紀錄 | ⚠️ 免疫系統有基礎，需加 IC 專屬規則 |

---

## 伍、階段性實作藍圖 (Roadmap)

### Phase 1：知識檢索與文書自動化 *(PoC)*
**目標**：讓團隊快速體驗 AI 減輕行政與溝通負擔的效益

- [ ] AD/LDAP SSO 整合
- [ ] Confluence / SharePoint RAG 知識庫串接
- [ ] 讀信總結 + 草擬回信 workflow
- [ ] 工作日誌生成（Jira/Git 資料源）
- [ ] OA / 資安 / ERP 常見問題 QA
- [ ] IC 專屬知識庫建置（.cshrc 設定、EDA 排錯指引）
- [ ] DLP 規則強化（RTL / 財務敏感詞）

### Phase 2：深度除錯與系統串接 *(擴大導入)*
**目標**：打通系統 API，解決複雜技術問題

- [ ] Log 智能分析（Kernel / DB / EDA）
- [ ] HPC Job 狀態查詢（LSF / Slurm API）
- [ ] EDA License 查詢（FlexLM API）
- [ ] NAS 空間監控與申請 workflow
- [ ] Code Review + Unit Test 生成
- [ ] Shell/Perl → Python/Go 翻譯工具
- [ ] Jira / ServiceNow 自動開單整合
- [ ] Web Portal 開發

---

## 陸、MinionDesk 差距分析 (Gap Analysis)

### ✅ 已具備能力
- 多渠道（Telegram / Discord / Teams）
- Docker 容器隔離執行
- RBAC 角色控管
- 知識庫 RAG（FTS5 + 語義搜尋）
- Workflow 申請/審核流程
- 免疫系統（Prompt Injection 防護）
- On-premise LLM 支援（Ollama）
- 速率限制 + 審計日誌

### 🔧 需新增開發

#### 高優先（Phase 1）
1. **AD/LDAP 整合** — ✅ 已實作 (host/enterprise/ldap.py)
2. **Confluence/SharePoint 爬取器** — ✅ 已實作
3. **DLP 強化規則** — IC 設計專屬：RTL 關鍵字、製程資料、財務敏感詞
4. **IC 知識庫** — .cshrc 範本、EDA 工具排錯、VNC 設定指引

#### 中優先（Phase 2）
5. **LSF/Slurm 工具** — ✅ 已實作
6. **FlexLM 工具** — ✅ 已實作
7. **Jira API 工具** — ✅ 已實作
8. **Git/GitLab 工具** — ✅ 已實作
9. **Web Portal** — ✅ 已實作 (port 8082)

#### 選配（Phase 2+）
10. **VS Code 外掛** — Language Server Protocol 整合
11. **NAS API** — 依廠商而定（NetApp / IBM Spectrum）

---

*文件版本：v1.0 · 2026-03-08 · MinionDesk IC Design Edition*
