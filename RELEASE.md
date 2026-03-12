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
