# MinionDesk Copilot — VS Code Extension

IC 設計 IT AI Copilot，整合 MinionDesk 到 VS Code。

## 功能

- **Code Review** — 右鍵選取程式碼 → Review
- **解釋程式碼** — 白話文說明選取區塊
- **生成單元測試** — 自動產生 Test Case
- **Log 分析** — 智能分析 Kernel/EDA/應用程式 Log
- **腳本翻譯** — Shell/Perl → Python/Go

## 設定

```json
{
  "miniondesk.serverUrl": "http://your-miniondesk-server:8082",
  "miniondesk.defaultMinion": "stuart"
}
```

## 需求

- MinionDesk 服務執行中（Web Portal enabled）
- VS Code 1.85+
