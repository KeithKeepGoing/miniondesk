# EDA 工具排障指南

## Synopsys Design Compiler (DC)

### 常見錯誤

**Error: Cannot find library**
```tcl
# 在 .synopsys_dc.setup 中設定
set_app_var search_path ". /pdk/tsmc/N7/sc/lib $search_path"
set_app_var link_library "* typical.db"
set_app_var target_library "typical.db"
```

**Error: Unmapped logic**
```tcl
# 確認 library 版本與 corner 一致
report_lib typical.db
```

**Timing violation 處理**
```tcl
# 分析 timing path
report_timing -max_paths 10 -slack_lesser_than 0
# 找出 critical path
report_timing -from [get_pins reg*/Q] -to [get_pins reg*/D]
```

## Cadence Virtuoso

### 啟動失敗 (CDS-1: Technology file error)
```bash
# 確認 PDK 版本
ls $PDK_HOME/tech/
# 重新載入 PDK
cds_relink_pdk
```

### Schematic Editor 無法開啟
```bash
# 清除 lock 檔
find ~/cdsLibs -name "*.cdslck" -delete
# 重新啟動
virtuoso &
```

## VCS / Simulation

### 編譯錯誤 (Syntax error)
```bash
# 確認 Verilog 語法版本
vcs -sverilog -full64 test.v
# 使用 SystemVerilog
vcs -sv -full64 test.sv
```

### 記憶體不足 (OOM during simulation)
```bash
# 查看記憶體使用
top -u $USER
# 限制 VCS 記憶體
vcs -Mupdate -Mdir=csrc -full64 +memcbk test.v
```

## Calibre DRC/LVS

### License 不夠用
```bash
# 查詢 Calibre license 狀態
lmstat -a -c $MGLS_LICENSE_FILE -f mgcvf

# 批次執行時排程避開高峰
# 建議在 22:00-06:00 提交 calibre job
```

### DRC 跑太慢
```bash
# 使用多核心加速
calibre -drc -hier -turbo 8 drc.rule gds.db
```
