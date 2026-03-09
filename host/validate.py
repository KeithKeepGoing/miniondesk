"""
MinionDesk Pre-flight Validation
Checks that the system is correctly configured before starting.
"""
from __future__ import annotations
import os
import signal
import subprocess
import sys
from pathlib import Path


def validate_all(verbose: bool = True) -> bool:
    """Run all validation checks. Returns True if system is ready to start."""
    issues: list[tuple[str, str]] = []  # (severity, message)
    passed: list[str] = []

    def check(label: str, condition: bool, error: str, severity: str = "ERROR") -> None:
        if condition:
            passed.append(label)
        else:
            issues.append((severity, f"{label}: {error}"))

    # ── LLM Provider ──────────────────────────────────────────────
    has_provider = any([
        os.getenv("ANTHROPIC_API_KEY"),
        os.getenv("GOOGLE_API_KEY"),
        os.getenv("OPENAI_API_KEY"),
        os.getenv("OLLAMA_URL"),
        os.getenv("OPENAI_BASE_URL"),
    ])
    check("LLM Provider", has_provider,
          "Set ANTHROPIC_API_KEY, GOOGLE_API_KEY, OPENAI_API_KEY, or OLLAMA_URL")

    # ── Channels ──────────────────────────────────────────────────
    has_channel = any([
        os.getenv("TELEGRAM_TOKEN"),
        os.getenv("DISCORD_TOKEN"),
        os.getenv("TEAMS_APP_ID"),
    ])
    check("Messaging Channel", has_channel,
          "Set TELEGRAM_TOKEN, DISCORD_TOKEN, or TEAMS_APP_ID",
          severity="WARNING")

    # ── Docker ────────────────────────────────────────────────────
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=5
        )
        check("Docker daemon", result.returncode == 0,
              "Docker is not running. Start Docker and try again.")
    except FileNotFoundError:
        issues.append(("ERROR", "Docker: Docker is not installed"))
    except subprocess.TimeoutExpired:
        issues.append(("ERROR", "Docker: daemon not responding (timeout)"))

    # ── Docker image ──────────────────────────────────────────────
    from host import config
    try:
        result = subprocess.run(
            ["docker", "images", "-q", config.DOCKER_IMAGE],
            capture_output=True, text=True, timeout=5,
        )
        image_exists = bool(result.stdout.strip())
        check(
            f"Docker image ({config.DOCKER_IMAGE})",
            image_exists,
            f"Build it first: docker build -t {config.DOCKER_IMAGE} container/",
        )
    except Exception as e:
        issues.append(("ERROR", f"Docker image check: {e}"))

    # ── Persona files ─────────────────────────────────────────────
    for minion in config.AVAILABLE_MINIONS:
        persona = config.MINIONS_DIR / f"{minion}.md"
        check(f"Persona: {minion}.md", persona.exists(),
              f"Missing file: {persona}")

    # ── Data directory ────────────────────────────────────────────
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        passed.append(f"Data dir: {config.DATA_DIR}")
    except Exception as e:
        issues.append(("ERROR", f"Data dir ({config.DATA_DIR}): {e}"))

    # ── IPC directory ─────────────────────────────────────────────
    try:
        config.IPC_DIR.mkdir(parents=True, exist_ok=True)
        passed.append(f"IPC dir: {config.IPC_DIR}")
    except Exception as e:
        issues.append(("ERROR", f"IPC dir ({config.IPC_DIR}): {e}"))

    # ── LLM API key validity (quick ping) ─────────────────────────
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        try:
            import anthropic

            def _timeout_handler(signum, frame):
                raise TimeoutError("Anthropic API validation timed out after 10s")

            client = anthropic.Anthropic(api_key=anthropic_key)
            if hasattr(signal, "SIGALRM"):
                signal.signal(signal.SIGALRM, _timeout_handler)
                signal.alarm(10)
            try:
                client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=1,
                    messages=[{"role": "user", "content": "hi"}],
                )
                if hasattr(signal, "SIGALRM"):
                    signal.alarm(0)
                print("  ✅ Anthropic API key valid")
                passed.append("Anthropic API key: valid")
            except TimeoutError:
                print("  ⚠️  Anthropic API validation timed out (API may be slow) — continuing anyway")
                if hasattr(signal, "SIGALRM"):
                    signal.alarm(0)
            except anthropic.AuthenticationError:
                if hasattr(signal, "SIGALRM"):
                    signal.alarm(0)
                issues.append(("WARNING", "Anthropic API key: invalid (AuthenticationError)"))
            except Exception as e:
                if hasattr(signal, "SIGALRM"):
                    signal.alarm(0)
                print(f"  ⚠️  Anthropic API check failed: {e} — continuing anyway")
        except Exception as e:
            issues.append(("WARNING", f"Anthropic API key: {e}"))

    # ── Print results ─────────────────────────────────────────────
    if verbose:
        print("\n🍌 MinionDesk Pre-flight Check")
        print("=" * 50)
        for label in passed:
            print(f"  ✅ {label}")
        for severity, msg in issues:
            icon = "❌" if severity == "ERROR" else "⚠️ "
            print(f"  {icon} {msg}")
        print()

    errors = [m for s, m in issues if s == "ERROR"]
    if errors:
        if verbose:
            print(f"❌ {len(errors)} error(s) found. Fix them before starting MinionDesk.\n")
        return False
    else:
        warnings = [m for s, m in issues if s == "WARNING"]
        if verbose:
            if warnings:
                print(f"⚠️  Ready with {len(warnings)} warning(s).\n")
            else:
                print("✅ All checks passed! Ready to start.\n")
        return True
