"""
HPC & IC Design Infrastructure Tools for MinionDesk.
Supports LSF (bjobs/bqueues), Slurm (squeue/sinfo), FlexLM (lmstat), NAS storage.
"""
from __future__ import annotations
import os
import subprocess
import shutil
import re as _re
from .messaging import ToolContext

_HPC_ARG_RE = _re.compile(r'^[\w.\-@:]+$')
_PATH_RE = _re.compile(r'^[/\w.\-]+$')

def _validate_hpc_arg(value: str, field: str) -> str:
    """Validate HPC argument to prevent shell injection. Only allows word chars, dots, hyphens, @, colon."""
    if not value or not _HPC_ARG_RE.match(str(value)):
        raise ValueError(f"Invalid HPC argument for {field!r}: {value!r}")
    return str(value)

# Config from environment (injected into container)
LSF_HOST = os.getenv("HPC_LSF_HOST", "")          # SSH host for LSF commands
SLURM_HOST = os.getenv("HPC_SLURM_HOST", "")      # SSH host for Slurm commands
FLEXLM_SERVER = os.getenv("FLEXLM_SERVER", "")    # FlexLM server host:port
NAS_HOST = os.getenv("NAS_HOST", "")              # NAS management host
HPC_SSH_KEY = os.getenv("HPC_SSH_KEY_PATH", "")   # Path to SSH key for HPC


def _ssh_run(host: str, command: str, timeout: int = 15) -> tuple[str, str]:
    """Run a command on a remote host via SSH. Returns (stdout, stderr)."""
    if not host:
        return "", "HPC host not configured"

    ssh_cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=10",
    ]
    if HPC_SSH_KEY and os.path.exists(HPC_SSH_KEY):
        ssh_cmd += ["-i", HPC_SSH_KEY]
    ssh_cmd += [host, command]  # remote_cmd must be a safe string, not shell-expanded on local side

    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=timeout, shell=False)
        return result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return "", f"SSH command timed out after {timeout}s"
    except FileNotFoundError:
        return "", "SSH not available in container"
    except Exception as e:
        return "", str(e)


def _local_run(cmd_list: list[str], timeout: int = 15) -> tuple[str, str]:
    """Run a local command safely without shell interpolation."""
    try:
        result = subprocess.run(
            cmd_list,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,  # NEVER use shell=True
        )
        return result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return "", f"Command timed out after {timeout}s"
    except Exception as e:
        return "", str(e)


# ─── LSF Tools ────────────────────────────────────────────────────────────────

def query_lsf_jobs(args: dict, ctx: ToolContext) -> str:
    """
    Query LSF job status.
    args: {"user": "optional_username", "job_id": "optional_job_id", "queue": "optional_queue"}
    """
    user = args.get("user", "")
    job_id = args.get("job_id", "")
    queue = args.get("queue", "")

    try:
        if job_id:
            job_id = _validate_hpc_arg(job_id, "job_id")
        if user:
            user = _validate_hpc_arg(user, "user")
        if queue:
            queue = _validate_hpc_arg(queue, "queue")
    except ValueError as e:
        return f"❌ 參數錯誤：{e}"

    if job_id:
        cmd_list = ["bjobs", "-l", job_id]
    elif user:
        cmd_list = ["bjobs", "-u", user, "-a"]
    else:
        cmd_list = ["bjobs", "-a", "-noheader"]

    if queue:
        cmd_list += ["-q", queue]

    # Try local first, then SSH
    if shutil.which("bjobs"):
        stdout, stderr = _local_run(cmd_list)
    elif LSF_HOST:
        # For SSH, build the remote command as a string (executed remotely by the remote shell)
        if job_id:
            remote_cmd = f"bjobs -l {job_id}"
        elif user:
            remote_cmd = f"bjobs -u {user} -a"
        else:
            remote_cmd = "bjobs -a -noheader | head -50"
        if queue:
            remote_cmd += f" -q {queue}"
        stdout, stderr = _ssh_run(LSF_HOST, remote_cmd)
    else:
        return ("❌ LSF 未設定。請設定環境變數 HPC_LSF_HOST，或確認 bjobs 指令可用。\n"
                "範例查詢：bjobs -u username -a")

    if stderr and not stdout:
        return f"❌ LSF 查詢失敗：{stderr}"

    if not stdout.strip():
        target = f"用戶 {user}" if user else f"Job {job_id}" if job_id else "所有用戶"
        return f"✅ {target} 目前沒有 LSF jobs 在執行或排隊。"

    # Parse and format output
    lines = stdout.strip().split("\n")

    # Count status
    pending = sum(1 for l in lines if " PEND " in l)
    running = sum(1 for l in lines if " RUN " in l)
    done = sum(1 for l in lines if " DONE " in l or " EXIT " in l)

    summary = f"📊 LSF Jobs 摘要：🟡 PEND {pending} | 🟢 RUN {running} | ⚫ DONE/EXIT {done}\n\n"

    # Format top jobs
    result_lines = [summary, "```"]
    result_lines.extend(lines[:30])  # limit output
    if len(lines) > 30:
        result_lines.append(f"... (共 {len(lines)} 筆，僅顯示前 30 筆)")
    result_lines.append("```")

    return "\n".join(result_lines)


def query_lsf_queues(args: dict, ctx: ToolContext) -> str:
    """Query LSF queue status and load."""
    if args.get("verbose"):
        cmd_list = ["bqueues", "-l"]
    else:
        cmd_list = ["bqueues"]

    if shutil.which("bqueues"):
        stdout, stderr = _local_run(cmd_list)
    elif LSF_HOST:
        cmd_str = "bqueues -l" if args.get("verbose") else "bqueues"
        stdout, stderr = _ssh_run(LSF_HOST, cmd_str)
    else:
        return "❌ LSF 未設定（HPC_LSF_HOST）"

    if not stdout.strip():
        return f"❌ bqueues 查詢失敗：{stderr}"

    return f"📋 LSF Queue 狀態：\n```\n{stdout[:2000]}\n```"


# ─── Slurm Tools ──────────────────────────────────────────────────────────────

def query_slurm_jobs(args: dict, ctx: ToolContext) -> str:
    """
    Query Slurm job status.
    args: {"user": "optional", "job_id": "optional", "partition": "optional"}
    """
    user = args.get("user", "")
    job_id = args.get("job_id", "")
    partition = args.get("partition", "")

    try:
        if job_id:
            job_id = _validate_hpc_arg(job_id, "job_id")
        if user:
            user = _validate_hpc_arg(user, "user")
        if partition:
            partition = _validate_hpc_arg(partition, "partition")
    except ValueError as e:
        return f"❌ 參數錯誤：{e}"

    if job_id:
        cmd_list = ["scontrol", "show", "job", job_id]
    else:
        fmt = "--format=%.18i %.9P %.30j %.8u %.8T %.10M %.6D %R"
        cmd_list = ["squeue", fmt]
        if user:
            cmd_list += ["-u", user]
        if partition:
            cmd_list += ["-p", partition]

    if shutil.which("squeue"):
        stdout, stderr = _local_run(cmd_list)
    elif SLURM_HOST:
        if job_id:
            remote_cmd = f"scontrol show job {job_id}"
        else:
            remote_cmd = "squeue --format='%.18i %.9P %.30j %.8u %.8T %.10M %.6D %R'"
            if user:
                remote_cmd += f" -u {user}"
            if partition:
                remote_cmd += f" -p {partition}"
        stdout, stderr = _ssh_run(SLURM_HOST, remote_cmd)
    else:
        return ("❌ Slurm 未設定。請設定環境變數 HPC_SLURM_HOST，或確認 squeue 指令可用。")

    if stderr and not stdout:
        return f"❌ Slurm 查詢失敗：{stderr}"

    if not stdout.strip() or stdout.strip() == "JOBID PARTITION NAME USER ST TIME NODES REASON":
        return f"✅ 目前沒有 Slurm jobs。"

    lines = stdout.strip().split("\n")
    pending = sum(1 for l in lines if " PD " in l)
    running = sum(1 for l in lines if " R " in l)

    summary = f"📊 Slurm Jobs：🟡 PENDING {pending} | 🟢 RUNNING {running}\n\n"
    return summary + f"```\n{stdout[:2000]}\n```"


def query_slurm_nodes(args: dict, ctx: ToolContext) -> str:
    """Query Slurm node/partition availability."""
    fmt = "--format=%.15P %.5a %.10l %.6D %.6t %N"
    cmd_list = ["sinfo", fmt]

    if shutil.which("sinfo"):
        stdout, stderr = _local_run(cmd_list)
    elif SLURM_HOST:
        stdout, stderr = _ssh_run(SLURM_HOST, f"sinfo --format='{fmt.split('=',1)[1]}'")
    else:
        return "❌ Slurm 未設定（HPC_SLURM_HOST）"

    if not stdout.strip():
        return f"❌ sinfo 查詢失敗：{stderr}"

    return f"🖥️ Slurm 節點狀態：\n```\n{stdout[:2000]}\n```"


# ─── FlexLM Tools ─────────────────────────────────────────────────────────────

def query_flexlm_licenses(args: dict, ctx: ToolContext) -> str:
    """
    Query FlexLM EDA license availability.
    args: {"tool": "tool_name (e.g. vcs, dc_shell, icc2)", "server": "optional override"}
    """
    tool = args.get("tool", "")
    server = args.get("server", "") or FLEXLM_SERVER

    if not server:
        return ("❌ FlexLM 伺服器未設定。\n"
                "請設定環境變數 FLEXLM_SERVER=host:port\n"
                "例如：FLEXLM_SERVER=license.corp.local:27000")

    try:
        server = _validate_hpc_arg(server, "server")
        if tool:
            tool = _validate_hpc_arg(tool, "tool")
    except ValueError as e:
        return f"❌ 參數錯誤：{e}"

    if tool:
        lmstat_args = ["-a", "-c", server, "-f", tool]
    else:
        lmstat_args = ["-a", "-c", server]

    if shutil.which("lmstat"):
        stdout, stderr = _local_run(["lmstat"] + lmstat_args, timeout=20)
    elif LSF_HOST:
        remote_cmd = f"lmstat -a -c {server}"
        if tool:
            remote_cmd += f" -f {tool}"
        stdout, stderr = _ssh_run(LSF_HOST, remote_cmd, timeout=20)
    else:
        # Try lmutil lmstat
        lmutil = shutil.which("lmutil")
        if lmutil:
            stdout, stderr = _local_run([lmutil, "lmstat"] + lmstat_args, timeout=20)
        else:
            return "❌ lmstat/lmutil 指令不可用，且未設定 HPC_LSF_HOST。"

    if not stdout.strip():
        return f"❌ FlexLM 查詢失敗：{stderr or '無回應'}"

    # Parse lmstat output
    lines = stdout.split("\n")
    result = []
    current_feature = None

    for line in lines:
        line = line.strip()
        if "Users of" in line:
            # Parse: "Users of vcs: (Total of 10 licenses issued; Total of 3 licenses in use)"
            current_feature = line
            result.append(f"\n🔧 {line}")
        elif "Total of" in line and "license" in line and current_feature:
            result.append(f"   {line}")
        elif "(v" in line and "Users" not in line and current_feature:
            # User currently using license
            result.append(f"   👤 {line[:100]}")

    if not result:
        return f"📋 FlexLM 輸出：\n```\n{stdout[:2000]}\n```"

    header = f"🔑 FlexLM License 狀態（{server}）：\n"
    if tool:
        header = f"🔑 FlexLM License 狀態 - {tool}（{server}）：\n"

    return header + "\n".join(result[:50])


# ─── NAS Storage Tools ────────────────────────────────────────────────────────

def query_nas_storage(args: dict, ctx: ToolContext) -> str:
    """
    Query NAS storage usage and quota.
    args: {"path": "/path/to/check", "user": "optional_username"}
    """
    path = args.get("path", "/")
    user = args.get("user", "")

    # Validate path argument to prevent injection
    if not _PATH_RE.match(str(path)):
        return "[error: invalid path argument]"

    if user:
        try:
            user = _validate_hpc_arg(user, "user")
        except ValueError as e:
            return f"❌ 參數錯誤：{e}"

    # Try df first (works locally or via SSH)
    # For SSH execution the remote shell handles the command string safely
    # since all arguments have been validated above
    if user:
        remote_cmd = f"quota -s {user} 2>/dev/null || df -h {path}"
    else:
        remote_cmd = f"df -h {path}"

    if NAS_HOST:
        stdout, stderr = _ssh_run(NAS_HOST, remote_cmd)
    elif LSF_HOST:
        stdout, stderr = _ssh_run(LSF_HOST, remote_cmd)
    else:
        # Local: use list form (no shell=True)
        stdout, stderr = _local_run(["df", "-h", path])

    if not stdout.strip():
        return f"❌ 儲存空間查詢失敗：{stderr or '無法連線'}"

    # Simple threshold warning
    result = f"💾 儲存空間狀態（{path}）：\n```\n{stdout.strip()}\n```"

    # Check if usage is high (>80%)
    for line in stdout.split("\n"):
        if "%" in line:
            parts = line.split()
            for part in parts:
                if part.endswith("%"):
                    try:
                        pct = int(part.rstrip("%"))
                        if pct >= 90:
                            result += f"\n⚠️ *警告：使用率 {pct}%，空間即將耗盡！*"
                        elif pct >= 80:
                            result += f"\n⚠️ 注意：使用率 {pct}%，建議清理或申請擴充。"
                    except ValueError:
                        pass

    result += "\n\n💡 如需申請 Quota 擴充，請聯絡 IT Infra 部門。"
    return result


def request_quota_expansion(args: dict, ctx: ToolContext) -> str:
    """
    Guide user through quota expansion request process.
    args: {"path": "/path", "current_size": "1TB", "requested_size": "2TB", "reason": "..."}
    """
    path = args.get("path", "")
    current = args.get("current_size", "未知")
    requested = args.get("requested_size", "未知")
    reason = args.get("reason", "")

    # Create a workflow ticket
    ticket_info = (
        f"📋 *NAS Quota 擴充申請*\n\n"
        f"• 路徑：{path or '(請指定)'}\n"
        f"• 目前配額：{current}\n"
        f"• 申請配額：{requested}\n"
        f"• 原因：{reason or '(請說明用途)'}\n\n"
        f"*申請流程：*\n"
        f"1️⃣ 填寫 ServiceNow 單據（IT-STORAGE 類別）\n"
        f"2️⃣ 部門主管審批\n"
        f"3️⃣ Infra 團隊 2 個工作日內完成\n\n"
        f"💡 提示：定期執行 `du -sh /your/path/*` 找出佔用空間最大的目錄。"
    )
    return ticket_info


# ─── Tool Registry ────────────────────────────────────────────────────────────

HPC_TOOLS = {
    "query_lsf_jobs": {
        "fn": query_lsf_jobs,
        "schema": {
            "name": "query_lsf_jobs",
            "description": "查詢 LSF HPC 叢集的 Job 狀態。可查特定用戶、特定 Job ID 或整體狀態。",
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {"type": "string", "description": "查詢特定用戶的 jobs（可選）"},
                    "job_id": {"type": "string", "description": "查詢特定 Job ID（可選）"},
                    "queue": {"type": "string", "description": "篩選特定 Queue（可選）"},
                },
            },
        },
    },
    "query_lsf_queues": {
        "fn": query_lsf_queues,
        "schema": {
            "name": "query_lsf_queues",
            "description": "查詢 LSF Queue 清單與狀態",
            "parameters": {
                "type": "object",
                "properties": {
                    "verbose": {"type": "boolean", "description": "顯示詳細資訊"},
                },
            },
        },
    },
    "query_slurm_jobs": {
        "fn": query_slurm_jobs,
        "schema": {
            "name": "query_slurm_jobs",
            "description": "查詢 Slurm HPC 叢集的 Job 狀態",
            "parameters": {
                "type": "object",
                "properties": {
                    "user": {"type": "string", "description": "查詢特定用戶（可選）"},
                    "job_id": {"type": "string", "description": "查詢特定 Job ID（可選）"},
                    "partition": {"type": "string", "description": "篩選特定 Partition（可選）"},
                },
            },
        },
    },
    "query_slurm_nodes": {
        "fn": query_slurm_nodes,
        "schema": {
            "name": "query_slurm_nodes",
            "description": "查詢 Slurm 節點與 Partition 可用狀態",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    "query_flexlm_licenses": {
        "fn": query_flexlm_licenses,
        "schema": {
            "name": "query_flexlm_licenses",
            "description": "查詢 EDA 工具授權（FlexLM）剩餘數量。例如查詢 VCS、DC Shell、ICC2 等授權。",
            "parameters": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string", "description": "EDA 工具名稱（例：vcs, dc_shell, icc2, calibre）。留空查詢全部。"},
                    "server": {"type": "string", "description": "FlexLM 伺服器 host:port（覆蓋預設值）"},
                },
            },
        },
    },
    "query_nas_storage": {
        "fn": query_nas_storage,
        "schema": {
            "name": "query_nas_storage",
            "description": "查詢 NAS 儲存空間使用量與配額。偵測空間不足並給出建議。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "要查詢的路徑（例：/proj/design）"},
                    "user": {"type": "string", "description": "查詢特定用戶配額（可選）"},
                },
            },
        },
    },
    "request_quota_expansion": {
        "fn": request_quota_expansion,
        "schema": {
            "name": "request_quota_expansion",
            "description": "引導用戶申請 NAS Quota 擴充，產生申請單資訊",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "需要擴充的路徑"},
                    "current_size": {"type": "string", "description": "目前配額大小"},
                    "requested_size": {"type": "string", "description": "申請的新配額大小"},
                    "reason": {"type": "string", "description": "申請原因"},
                },
            },
        },
    },
}


def get_hpc_tools() -> list:
    """Return HPC tools as a list of Tool instances for the registry."""
    from . import Tool
    tools = []
    for name, entry in HPC_TOOLS.items():
        schema = entry["schema"]
        tools.append(Tool(
            name=name,
            description=schema["description"],
            schema=schema["parameters"],
            execute=entry["fn"],
        ))
    return tools
