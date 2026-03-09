"""
NAS Deep API Tools for MinionDesk container runner.
Wraps NetApp ONTAP REST API and IBM Spectrum Scale (GPFS) REST API.
Provides: usage monitoring, quota management, snapshot restore guidance.
"""
from __future__ import annotations
import os
import json
import re
import ssl
import urllib.request
import urllib.parse
import base64
import logging
from typing import Optional
from .messaging import ToolContext

log = logging.getLogger(__name__)

# Config (injected into container environment)
NETAPP_URL = os.getenv("NETAPP_URL", "")
NETAPP_USER = os.getenv("NETAPP_USER", "")
NETAPP_PASSWORD = os.getenv("NETAPP_PASSWORD", "")
NETAPP_SVM = os.getenv("NETAPP_SVM", "")

GPFS_URL = os.getenv("GPFS_URL", "")
GPFS_USER = os.getenv("GPFS_USER", "")
GPFS_PASSWORD = os.getenv("GPFS_PASSWORD", "")
GPFS_FILESYSTEM = os.getenv("GPFS_FILESYSTEM", "")

NAS_SSL_VERIFY = os.getenv("NAS_SSL_VERIFY", "true").lower() != "false"
NAS_CA_BUNDLE = os.getenv("NAS_CA_BUNDLE", "")

if not NAS_SSL_VERIFY:
    log.warning("NAS SSL verification disabled — only use in trusted environments")

if NETAPP_URL and not NETAPP_USER:
    log.warning("NETAPP_URL is set but NETAPP_USER is empty")
if NETAPP_URL and not NETAPP_PASSWORD:
    log.warning("NETAPP_URL is set but NETAPP_PASSWORD is empty")


def _validate_api_url(name: str, url: str) -> bool:
    if not url:
        return True
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        log.error("NAS config: %s is not a valid URL", name)
        return False
    if p.scheme not in ("http", "https"):
        log.error("NAS config: %s must use http/https, got %r", name, p.scheme)
        return False
    if not p.hostname:
        log.error("NAS config: %s has no hostname", name)
        return False
    return True


if NETAPP_URL and not _validate_api_url("NETAPP_URL", NETAPP_URL):
    NETAPP_URL = ""
if GPFS_URL and not _validate_api_url("GPFS_URL", GPFS_URL):
    GPFS_URL = ""


def _validate_nas_name(val: str) -> str:
    """Validate NAS volume/filename/fileset name. No path separators allowed."""
    if val and not re.fullmatch(r'[\w.\-]+', val):
        raise ValueError(f"Invalid NAS name (no path separators allowed): {val!r}")
    return val


if GPFS_FILESYSTEM:
    try:
        _validate_nas_name(GPFS_FILESYSTEM)
        GPFS_FILESYSTEM = urllib.parse.quote(GPFS_FILESYSTEM, safe='')
    except ValueError:
        log.error("GPFS_FILESYSTEM contains invalid characters, disabling GPFS")
        GPFS_FILESYSTEM = ""


def _netapp_headers() -> dict:
    creds = base64.b64encode(f"{NETAPP_USER}:{NETAPP_PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Accept": "application/json", "Content-Type": "application/json"}


def _gpfs_headers() -> dict:
    creds = base64.b64encode(f"{GPFS_USER}:{GPFS_PASSWORD}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Accept": "application/json"}


def _http_get(url: str, headers: dict) -> Optional[dict]:
    try:
        ctx = ssl.create_default_context()
        if not NAS_SSL_VERIFY:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        elif NAS_CA_BUNDLE:
            ctx.load_verify_locations(NAS_CA_BUNDLE)
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            data = json.loads(resp.read(4 * 1024 * 1024).decode())  # cap at 4MB
            if isinstance(data, dict) and "error" in data:
                log.error(f"API error from {url}: {data['error']}")
            return data
    except Exception as e:
        log.error(f"HTTP GET {url}: {e}")
        return None


# ─── NetApp ONTAP ──────────────────────────────────────────────────────────────

def _netapp_get_volumes() -> list[dict]:
    if not NETAPP_URL:
        return []
    url = f"{NETAPP_URL}/api/storage/volumes?fields=name,space,svm,state&limit=100"
    result = _http_get(url, _netapp_headers())
    if not result:
        return []
    return result.get("records", [])


def _netapp_get_volume_usage(volume_name: str) -> Optional[dict]:
    if not NETAPP_URL:
        return None
    url = f"{NETAPP_URL}/api/storage/volumes?" + urllib.parse.urlencode({"name": volume_name, "fields": "name,space,svm,snapshots"})
    result = _http_get(url, _netapp_headers())
    if not result:
        return None
    records = result.get("records", [])
    return records[0] if records else None


def _netapp_list_snapshots(volume_name: str) -> list[dict]:
    if not NETAPP_URL:
        return []
    vol = _netapp_get_volume_usage(volume_name)
    if not vol:
        return []
    vol_uuid = vol.get("uuid", "")
    if not vol_uuid:
        return []
    url = f"{NETAPP_URL}/api/storage/volumes/{urllib.parse.quote(vol_uuid, safe='')}/snapshots?fields=name,create_time,size"
    result = _http_get(url, _netapp_headers())
    if not result:
        return []
    return result.get("records", [])


def _netapp_quota_report(volume_name: str = "") -> list[dict]:
    if not NETAPP_URL:
        return []
    url = f"{NETAPP_URL}/api/storage/quota/reports?fields=volume,space,files"
    if volume_name:
        url += "&" + urllib.parse.urlencode({"volume.name": volume_name})
    result = _http_get(url, _netapp_headers())
    if not result:
        return []
    return result.get("records", [])


# ─── IBM Spectrum Scale (GPFS) ────────────────────────────────────────────────

def _gpfs_get_filesystem_usage() -> Optional[dict]:
    if not GPFS_URL or not GPFS_FILESYSTEM:
        return None
    url = f"{GPFS_URL}/scalemgmt/v2/filesystems/{GPFS_FILESYSTEM}"
    return _http_get(url, _gpfs_headers())


def _gpfs_get_quotas(fileset: str = "") -> list[dict]:
    if not GPFS_URL or not GPFS_FILESYSTEM:
        return []
    url = f"{GPFS_URL}/scalemgmt/v2/filesystems/{GPFS_FILESYSTEM}/quotas"
    if fileset:
        filter_value = f"filesystemName={GPFS_FILESYSTEM},filesetName={fileset}"
        url += "?" + urllib.parse.urlencode({"filter": filter_value})
    result = _http_get(url, _gpfs_headers())
    if not result:
        return []
    return result.get("quotas", [])


def _gpfs_list_snapshots(fileset: str = "") -> list[dict]:
    if not GPFS_URL or not GPFS_FILESYSTEM:
        return []
    base = f"{GPFS_URL}/scalemgmt/v2/filesystems/{GPFS_FILESYSTEM}/snapshots"
    if fileset:
        base += f"/{urllib.parse.quote(fileset, safe='')}"
    result = _http_get(base, _gpfs_headers())
    if not result:
        return []
    return result.get("snapshots", [])


# ─── Tool Implementations ─────────────────────────────────────────────────────

def query_nas_deep(args: dict, ctx: ToolContext) -> str:
    """Deep NAS query using REST API."""
    action = args.get("action", "overview")
    volume = args.get("volume", "")
    filename = args.get("filename", "")
    fileset = args.get("fileset", "")
    try:
        if volume:
            _validate_nas_name(volume)
        if filename:
            _validate_nas_name(filename)
        if fileset:
            _validate_nas_name(fileset)
    except ValueError as e:
        return f"❌ 參數錯誤: {e}"

    if action == "overview":
        return _get_storage_overview()
    elif action == "snapshots":
        return _get_snapshot_restore_guide(volume, filename)
    elif action == "quota":
        if NETAPP_URL and volume:
            quotas = _netapp_quota_report(volume)
            if quotas:
                lines = [f"📊 {volume} Quota 報告："]
                for q in quotas[:10]:
                    lines.append(str(q)[:100])
                return "\n".join(lines)
        if GPFS_URL:
            quotas = _gpfs_get_quotas(fileset)
            if quotas:
                lines = [f"📊 GPFS Quota ({fileset or 'all'})："]
                for q in quotas[:10]:
                    lines.append(str(q)[:100])
                return "\n".join(lines)
        return "❌ Quota 查詢失敗，請確認 NAS API 設定"
    else:
        return _get_storage_overview()


def _get_storage_overview() -> str:
    results = []

    if NETAPP_URL:
        volumes = _netapp_get_volumes()
        if volumes:
            results.append("*📦 NetApp ONTAP 卷冊狀態：*")
            for v in volumes[:10]:
                name = v.get("name", "")
                space = v.get("space", {})
                used = space.get("used", 0)
                total = space.get("size", 0)
                pct = round(used / total * 100) if total else 0
                used_gb = round(used / 1024**3, 1)
                total_gb = round(total / 1024**3, 1)
                warn = " ⚠️" if pct >= 80 else ""
                results.append(f"• {name}: {used_gb}GB / {total_gb}GB ({pct}%){warn}")

    if GPFS_URL and GPFS_FILESYSTEM:
        fs = _gpfs_get_filesystem_usage()
        if fs and isinstance(fs.get("filesystems"), list) and fs["filesystems"]:
            results.append(f"\n*📦 IBM GPFS ({GPFS_FILESYSTEM}) 狀態：*")
            results.append(str(fs["filesystems"][0])[:300])

    if not results:
        return ("❌ NAS API 未設定。\n"
                "設定 NETAPP_URL + NETAPP_PASSWORD 使用 NetApp ONTAP\n"
                "或 GPFS_URL + GPFS_FILESYSTEM 使用 IBM Spectrum Scale")

    return "\n".join(results)


def _get_snapshot_restore_guide(volume: str, filename: str = "") -> str:
    try:
        _validate_nas_name(volume)
        if filename:
            _validate_nas_name(filename)
    except ValueError as e:
        return f"❌ 參數錯誤: {e}"

    guide = [
        f"📸 *Snapshot 還原指南*\n",
        f"**目標：** {'還原檔案 ' + filename if filename else '還原 Volume ' + volume}\n",
    ]

    if NETAPP_URL:
        snapshots = _netapp_list_snapshots(volume)
        if snapshots:
            guide.append("**可用的 Snapshots：**")
            for snap in snapshots[:5]:
                name = snap.get("name", "")
                created = snap.get("create_time", "")[:16]
                size_mb = round(snap.get("size", 0) / 1024**2, 1)
                guide.append(f"• `{name}` — 建立時間：{created}，大小：{size_mb}MB")
            guide.append("")

    if filename:
        guide.extend([
            "**還原單一檔案步驟：**",
            "```bash",
            f"# 進入 .snapshot 目錄",
            f"cd /vol/{volume}/.snapshot",
            f"ls -la  # 列出可用 snapshots",
            f"",
            f"# 選擇最近的 snapshot，複製檔案",
            f"cp ./SNAPSHOT_NAME/{filename} /original/path/{filename}",
            f"```",
            "",
            "**或使用 NetApp CLI：**",
            "```bash",
            f"# 聯絡 IT Infra 執行",
            f"volume snapshot restore-file -volume {volume} -snapshot SNAPSHOT_NAME -path /{filename}",
            "```",
        ])
    else:
        guide.extend([
            "**還原整個 Volume 步驟（需 IT 管理員執行）：**",
            "```bash",
            f"# 1. 確認要還原的 snapshot",
            f"volume snapshot show -volume {volume}",
            f"",
            f"# 2. 執行還原（會覆蓋當前資料！）",
            f"volume snapshot restore -volume {volume} -snapshot SNAPSHOT_NAME",
            "```",
            "",
            "⚠️ *整個 Volume 還原會覆蓋現有資料，請先確認 snapshot 時間點正確！*",
            "💡 如需協助，請開 ServiceNow 工單（類別：Storage/NAS）",
        ])

    return "\n".join(guide)


# ─── Tool Registry ────────────────────────────────────────────────────────────

NAS_DEEP_TOOLS = {
    "query_nas_deep": {
        "fn": query_nas_deep,
        "schema": {
            "name": "query_nas_deep",
            "description": "深度查詢 NAS 儲存系統（NetApp ONTAP / IBM GPFS）。支援：overview（整體狀態）、snapshots（列出 snapshot 並給出還原步驟）、quota（配額報告）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "動作：overview, snapshots, quota"},
                    "volume": {"type": "string", "description": "Volume 或路徑名稱（snapshots/quota 需要）"},
                    "filename": {"type": "string", "description": "要還原的檔案名稱（可選）"},
                    "fileset": {"type": "string", "description": "GPFS fileset 名稱（可選）"},
                },
            },
        },
    },
}


def get_nas_deep_tools() -> list:
    """Return NAS deep tools as a list of Tool instances for the registry."""
    from . import Tool
    tools = []
    for name, entry in NAS_DEEP_TOOLS.items():
        schema = entry["schema"]
        tools.append(Tool(
            name=name,
            description=schema["description"],
            schema=schema["parameters"],
            execute=entry["fn"],
        ))
    return tools
