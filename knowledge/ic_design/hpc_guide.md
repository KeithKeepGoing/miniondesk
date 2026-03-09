# HPC 使用指南

## LSF (IBM Platform LSF)

### 基本指令
```bash
# 提交 job
bsub -q normal -n 8 -R "rusage[mem=16384]" -o log.%J ./run.sh

# 查看 job 狀態
bjobs -u $USER

# 查看 job 詳細資訊
bjobs -l JOB_ID

# 取消 job
bkill JOB_ID

# 查看 Queue 狀態
bqueues
```

### Job 一直 PEND 的常見原因
| 原因 | PEND Reason | 解法 |
|------|-------------|------|
| Queue 滿了 | Job slot limit reached | 換 Queue 或等待 |
| 記憶體需求過高 | Not enough hosts | 降低 -R rusage[mem=...] |
| License 不夠 | External dependency | 等 license 釋放 |
| Host 資源不足 | Resource limit reached | 拆分 Job |

### 好用的 bsub 選項
```bash
# 指定記憶體 (MB)
-R "rusage[mem=32768]"

# 指定 CPU 核心數
-n 16

# 設定 wall clock 時間限制
-W 24:00

# Job 完成後通知
-N -u your.email@corp.com

# 依賴其他 Job 完成後才執行
-w "done(JOB_ID)"
```

## Slurm

### 基本指令
```bash
# 提交 job
sbatch --partition=gpu --nodes=1 --ntasks=8 --mem=32G job.sh

# 查看 job
squeue -u $USER

# 取消 job
scancel JOB_ID

# 查看節點狀態
sinfo
```

## 儲存空間管理

### 查看使用量
```bash
# 個人使用量
du -sh ~/
du -sh ~/proj/* | sort -rh | head -20

# Quota 查詢
quota -s

# 專案目錄
df -h /proj/YOUR_PROJECT
```

### 清理暫存檔
```bash
# 清理 EDA tool cache
rm -rf ~/.cds_cache ~/.synopsys_cache
rm -rf /tmp/cds_* /tmp/syn_*

# 清理 simulation dump 檔
find ./sim/ -name "*.fsdb" -mtime +30 -delete
find ./sim/ -name "*.vcd" -mtime +7 -delete
```
