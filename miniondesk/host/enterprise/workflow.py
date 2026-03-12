"""Enterprise workflow engine — YAML-defined workflows."""
from __future__ import annotations
import logging
import string
import yaml
from pathlib import Path

from .. import config

logger = logging.getLogger(__name__)


def load_workflow(name: str) -> dict | None:
    """Load a workflow definition by name."""
    wf_dir = Path(config.BASE_DIR) / "workflows"
    path = wf_dir / f"{name}.yaml"
    if not path.exists():
        logger.warning("Workflow not found: %s", name)
        return None
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Failed to load workflow %s: %s", name, exc)
        return None


async def trigger_workflow(name: str, data: dict, group_jid: str) -> str:
    """Trigger a workflow and return a status message."""
    wf = load_workflow(name)
    if not wf:
        return f"❌ Workflow '{name}' not found."

    wf_name = wf.get("name", name)
    steps = wf.get("steps", [])
    logger.info("Triggering workflow '%s' with %d steps for group %s", wf_name, len(steps), group_jid)

    # Simple sequential execution (extend for complex flows)
    results = []
    for step in steps:
        step_name = step.get("name", "step")
        step_type = step.get("type", "notify")
        if step_type == "notify":
            # Use safe_substitute to prevent format-string injection via user-controlled data
            msg = string.Template(step.get("message", "")).safe_substitute(data)
            results.append(f"✅ {step_name}: {msg}")
        elif step_type == "approval":
            results.append(f"⏳ {step_name}: Awaiting approval from {step.get('approver', 'manager')}")
        else:
            results.append(f"ℹ️ {step_name}: {step_type}")

    return f"🔄 Workflow '{wf_name}' started:\n" + "\n".join(results)


def list_workflows() -> list[str]:
    """List available workflow names."""
    wf_dir = Path(config.BASE_DIR) / "workflows"
    if not wf_dir.exists():
        return []
    return [f.stem for f in wf_dir.glob("*.yaml")]
