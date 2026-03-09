# 資安與合規指引

## 開源軟體使用規範

### 需要審查的情境
- 使用 GitHub/PyPI/npm 下載套件
- 使用 Docker Hub public image
- 引入外部 Verilog/SystemVerilog IP

### 審查流程
1. 提交申請至 IT 資安部門（ServiceNow: 類別 = 開源軟體審查）
2. 說明用途、版本、License 類型（MIT/Apache/GPL 注意差異）
3. 等待 3-5 個工作日審核
4. 核准後可下載至 **內網白名單伺服器**，再從內部使用

### 禁止直接從外網下載
所有外部軟體必須透過公司 Nexus/Artifactory proxy 下載，不得直接存取 GitHub/PyPI。

## 內外網資料交換

### 允許的方式
- **IT 核可的 FTP/SFTP server**：上傳至指定位置後通知對方
- **企業 OneDrive/SharePoint**：分享連結給外部合作夥伴
- **VPN + 加密壓縮**：敏感文件需先加密（7zip AES-256）

### 禁止的方式
- 將 RTL / GDS / SPICE netlist 上傳至個人雲端（Google Drive/Dropbox）
- 透過個人 email 傳送設計檔案
- 使用 USB 裝置（需先向 IT 申請解鎖）

## 機密設計資料保護

### DLP 自動偵測規則
系統會自動攔截以下內容：
- Verilog/VHDL RTL 原始碼（module/endmodule）
- GDS/GDSII layout 檔案引用
- NRE 成本與財務預測數字
- Tape-out 時間表
- Foundry NDA 相關文件

### Tape-out 專案保密
- 所有 Tape-out 相關資訊分類為 **機密 (Confidential)**
- 僅有核准的專案成員可存取
- 禁止在非加密通訊管道討論 Tape-out 時程與良率

## 帳號與存取管理

### 離職人員處理
IT 在收到 HR 通知後 **24 小時內** 完成：
1. 停用 AD 帳號
2. 撤銷所有 VPN 存取
3. 備份並移交工作資料
4. 撤銷 EDA License 綁定

### 多因素驗證 (MFA)
- VPN 登入：強制 MFA
- Confluence / Jira：強制 MFA
- EDA License Server：AD 帳號控管
