# IC 設計環境設定指南

## Linux 環境變數 (.cshrc / .bashrc)

### 台積電 N7 (7nm) 製程環境設定
```csh
# ~/.cshrc - TSMC N7 環境設定範本
setenv PDK_HOME /pdk/tsmc/N7/1.0
setenv PDK_PROCESS N7
setenv CDS_INST_DIR /tools/cadence/ICADVM20.1
setenv SYNOPSYS /tools/synopsys/L-2016.03-SP5
setenv MENTOR /tools/mentor/2022.3

# License Server
setenv LM_LICENSE_FILE 27000@license.corp.local

# EDA Tool Paths
set path = ($CDS_INST_DIR/bin $SYNOPSYS/bin $MENTOR/bin $path)

# Calibre DRC/LVS
setenv MGLS_LICENSE_FILE 1717@license.corp.local
setenv MGC_HOME /tools/mentor/calibre/2022.3

# Simulation
setenv VCS_HOME /tools/synopsys/vcs/S-2021.09
```

### 常見環境問題與解法

**問題 1：License 找不到 (Cannot find license)**
```bash
# 確認 license server 狀態
lmstat -a -c 27000@license.corp.local

# 確認環境變數正確設定
echo $LM_LICENSE_FILE

# 嘗試重連
lmreread -c $LM_LICENSE_FILE
```

**問題 2：EDA Tool 啟動失敗 (Segmentation fault)**
```bash
# 確認 library 版本
ldd $(which virtuoso)

# 清除暫存
rm -rf ~/.cds_cache
rm -rf /tmp/cds_*

# 重新設定環境
source ~/.cshrc
```

**問題 3：.cshrc 語法錯誤**
常見錯誤：
- `setenv` 不能用 `=`，正確：`setenv VAR value`
- `set` 才能用 `=`，正確：`set var = value`
- Path 設定：`set path = ($NEW_PATH $path)` 注意空格

## VNC / 遠端桌面設定

### 啟動 VNC Server
```bash
# 第一次設定
vncserver :1 -geometry 1920x1080 -depth 24

# 設定密碼
vncpasswd

# 確認 VNC 執行中
vncserver -list
```

### VNC 卡頓排障
1. **網路延遲高** → 改用 TurboVNC 或降低解析度
2. **畫面更新慢** → 設定 `-encoding tight -quality 50`
3. **連線斷線** → 確認防火牆 5901 port 開放
4. **黑屏** → 重啟 VNC: `vncserver -kill :1 && vncserver :1`

### TigerVNC 最佳化設定 (~/.vnc/config)
```
geometry=1920x1080
depth=24
```
