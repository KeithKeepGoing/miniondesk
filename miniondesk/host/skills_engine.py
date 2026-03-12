"""
MinionDesk Skills Engine — installable behavioral plugins.

Skills are YAML-defined packages that can:
- Add new tools to container agents
- Add documentation/instructions to CLAUDE.md
- Add minion personas
- Add workflow templates

Skill manifest format (skills/{name}/manifest.yaml):
  skill: skill-name
  version: "1.0.0"
  description: "What this skill does"
  author: "author"
  adds:
    - docs/skills/name/SKILL.md
    - minions/specialist.md
  modifies: []
"""
from __future__ import annotations
import json
import logging
import shutil
from pathlib import Path

from . import config

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"
INSTALLED_REGISTRY = lambda: Path(config.DATA_DIR) / "installed_skills.json"


# ─── Registry I/O ─────────────────────────────────────────────────────────────

def _load_registry() -> dict:
    p = INSTALLED_REGISTRY()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_registry(registry: dict) -> None:
    p = INSTALLED_REGISTRY()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")


# ─── Manifest parsing ─────────────────────────────────────────────────────────

def _parse_manifest(skill_dir: Path) -> dict | None:
    manifest_path = skill_dir / "manifest.yaml"
    if not manifest_path.exists():
        return None
    try:
        # Simple YAML parser (avoid pyyaml dependency)
        data = {}
        current_list_key = None
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("  - "):
                if current_list_key:
                    data.setdefault(current_list_key, []).append(line[4:].strip())
            elif ":" in line:
                key, _, val = line.partition(":")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if val:
                    data[key] = val
                    current_list_key = None
                else:
                    current_list_key = key
                    data.setdefault(key, [])
        return data
    except Exception as exc:
        logger.error("Failed to parse manifest %s: %s", manifest_path, exc)
        return None


# ─── Public API ───────────────────────────────────────────────────────────────

def list_available_skills() -> list[dict]:
    """List all skills in the skills/ directory."""
    if not SKILLS_DIR.exists():
        return []
    # Load registry once outside the loop (was loading once per skill dir — O(n) reads)
    registry = _load_registry()
    skills = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        manifest = _parse_manifest(skill_dir)
        if not manifest:
            continue
        installed = manifest.get("skill", skill_dir.name) in registry
        skills.append({
            "name": manifest.get("skill", skill_dir.name),
            "version": manifest.get("version", "?"),
            "description": manifest.get("description", ""),
            "author": manifest.get("author", ""),
            "installed": installed,
            "adds": manifest.get("adds", []),
            "container_tools": manifest.get("container_tools", []),
        })
    return skills


def list_installed_skills() -> list[dict]:
    """List all installed skills."""
    registry = _load_registry()
    return list(registry.values())


def install_skill(skill_name: str) -> tuple[bool, str]:
    """
    Install a skill from the skills/ directory.
    Copies files listed in manifest.adds to the project root.
    Returns (success, message).
    """
    skill_dir = SKILLS_DIR / skill_name
    if not skill_dir.exists():
        return False, f"Skill not found: {skill_name}"

    manifest = _parse_manifest(skill_dir)
    if not manifest:
        return False, f"Invalid manifest for skill: {skill_name}"

    name = manifest.get("skill", skill_name)
    registry = _load_registry()
    if name in registry:
        return False, f"Skill '{name}' is already installed (v{registry[name]['version']})"

    # Copy added files (host-side: docs, personas, workflows, CLAUDE.md)
    base_dir = Path(config.BASE_DIR)
    add_dir = skill_dir / "add"
    # Track successfully copied files so we can roll back on failure.
    copied_paths: list[Path] = []
    copied = []

    adds = manifest.get("adds", [])
    try:
        for rel_path in adds:
            src = add_dir / rel_path
            if not src.exists():
                logger.warning("Skill %s: file not found: %s", name, src)
                continue
            dst = base_dir / rel_path
            # Security: prevent path traversal — dst must stay within base_dir
            try:
                dst.resolve().relative_to(base_dir.resolve())
            except ValueError:
                logger.error(
                    "Skill %s: rejected path traversal in adds: %r (resolves outside BASE_DIR)",
                    name, rel_path,
                )
                raise RuntimeError(f"Skill '{name}' manifest contains unsafe path: {rel_path!r}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied_paths.append(dst)
            copied.append(rel_path)
            logger.info("Skill %s: installed %s", name, rel_path)

        # Copy container_tools files → dynamic_tools/ (hot-loaded by container at runtime)
        container_tools = manifest.get("container_tools", [])
        dynamic_tools_dir = base_dir / "dynamic_tools"
        dynamic_tools_dir.mkdir(parents=True, exist_ok=True)
        for tool_path in container_tools:
            src = add_dir / tool_path
            if not src.exists():
                logger.warning("Skill %s: container_tool not found: %s", name, src)
                continue
            # Always flatten into dynamic_tools/ (just filename)
            # Security: reject filenames with path separators (no subdirectory traversal)
            if "/" in src.name or "\\" in src.name or src.name.startswith("."):
                logger.error("Skill %s: rejected unsafe container_tool filename: %r", name, src.name)
                raise RuntimeError(f"Skill '{name}' has unsafe container_tool filename: {src.name!r}")
            dst = dynamic_tools_dir / src.name
            # Collision check: if file already exists and belongs to a different skill, refuse
            if dst.exists():
                owner = next(
                    (sk for sk, info in registry.items()
                     if src.name in [Path(t).name for t in info.get("container_tools", [])]),
                    None,
                )
                if owner and owner != name:
                    logger.error(
                        "Skill %s: container_tool %r conflicts with skill '%s' — install aborted",
                        name, src.name, owner,
                    )
                    raise RuntimeError(
                        f"Skill '{name}' container_tool '{src.name}' conflicts with "
                        f"already-installed skill '{owner}'. Uninstall '{owner}' first."
                    )
            shutil.copy2(src, dst)
            copied_paths.append(dst)
            copied.append(f"dynamic_tools/{src.name}")
            logger.info("Skill %s: installed container tool %s → %s", name, src.name, dst)

    except Exception as exc:
        # Rollback: remove all files copied so far to avoid partial-install state
        for p in copied_paths:
            try:
                p.unlink(missing_ok=True)
                logger.info("Skill %s: rolled back %s", name, p)
            except Exception:
                pass
        return False, str(exc)

    # Update registry
    registry[name] = {
        "name": name,
        "version": manifest.get("version", "1.0.0"),
        "description": manifest.get("description", ""),
        "author": manifest.get("author", ""),
        "adds": adds,
        "container_tools": container_tools,
        "installed_at": __import__("time").time(),
    }
    _save_registry(registry)

    tool_note = f", {len(container_tools)} container tool(s)" if container_tools else ""
    return True, f"✅ Skill '{name}' v{manifest.get('version', '?')} installed ({len(copied)} files{tool_note})"


def uninstall_skill(skill_name: str) -> tuple[bool, str]:
    """
    Uninstall a skill (removes files it added).
    Returns (success, message).
    """
    registry = _load_registry()
    if skill_name not in registry:
        return False, f"Skill '{skill_name}' is not installed"

    skill_info = registry[skill_name]
    base_dir = Path(config.BASE_DIR)
    removed = []

    for rel_path in skill_info.get("adds", []):
        target = base_dir / rel_path
        if target.exists():
            target.unlink()
            removed.append(rel_path)
            logger.info("Skill %s: removed %s", skill_name, rel_path)

    # Remove container_tools from dynamic_tools/
    dynamic_tools_dir = base_dir / "dynamic_tools"
    for tool_path in skill_info.get("container_tools", []):
        tool_name = Path(tool_path).name
        target = dynamic_tools_dir / tool_name
        if target.exists():
            target.unlink()
            removed.append(f"dynamic_tools/{tool_name}")
            logger.info("Skill %s: removed container tool %s", skill_name, tool_name)

    del registry[skill_name]
    _save_registry(registry)

    return True, f"✅ Skill '{skill_name}' uninstalled ({len(removed)} files removed)"


# Maximum combined size of all injected skill docs (bytes, UTF-8 encoded).
# Prevents unbounded system prompt inflation when many large skills are installed.
_SKILL_DOCS_MAX_BYTES = 32 * 1024  # 32 KB


def get_installed_skill_docs(group_jid: str | None = None) -> str:
    """
    Return combined SKILL.md content for all installed skills.
    This gets injected into the container system prompt.

    The combined result is capped at _SKILL_DOCS_MAX_BYTES to prevent
    unbounded system prompt growth when many or large skills are installed.
    """
    registry = _load_registry()
    base_dir = Path(config.BASE_DIR)
    docs = []
    total_bytes = 0

    for name, info in registry.items():
        for rel_path in info.get("adds", []):
            if "SKILL.md" in rel_path or rel_path.endswith(".md"):
                p = base_dir / rel_path
                if p.exists():
                    content = p.read_text(encoding="utf-8").strip()
                    entry = f"### Skill: {name}\n{content}"
                    entry_bytes = len(entry.encode("utf-8"))
                    if total_bytes + entry_bytes > _SKILL_DOCS_MAX_BYTES:
                        logger.warning(
                            "Skill docs size limit reached (%d bytes) — "
                            "skipping skill '%s' docs to prevent system prompt overflow",
                            _SKILL_DOCS_MAX_BYTES, name,
                        )
                        continue
                    docs.append(entry)
                    total_bytes += entry_bytes

    return "\n\n".join(docs)
