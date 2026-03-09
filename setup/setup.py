#!/usr/bin/env python3
"""
MinionDesk Interactive Setup
"""
from __future__ import annotations
import os
import sys
from pathlib import Path


def run_setup():
    print("\n🎉 Welcome to MinionDesk Setup!\n")
    print("This will help you configure your MinionDesk instance.\n")

    env_path = Path(".env")
    config: dict[str, str] = {}

    # LLM Provider
    print("=== LLM Provider ===")
    print("1. Anthropic Claude (recommended)")
    print("2. Google Gemini (free tier available)")
    print("3. OpenAI")
    print("4. Ollama (local, offline)")
    choice = input("Choose provider [1]: ").strip() or "1"

    if choice == "1":
        key = input("ANTHROPIC_API_KEY: ").strip()
        config["ANTHROPIC_API_KEY"] = key
    elif choice == "2":
        key = input("GOOGLE_API_KEY: ").strip()
        config["GOOGLE_API_KEY"] = key
    elif choice == "3":
        key = input("OPENAI_API_KEY: ").strip()
        config["OPENAI_API_KEY"] = key
    elif choice == "4":
        url = input("OLLAMA_URL [http://localhost:11434]: ").strip() or "http://localhost:11434"
        model = input("OLLAMA_MODEL [llama3.2]: ").strip() or "llama3.2"
        config["OLLAMA_URL"] = url
        config["OLLAMA_MODEL"] = model

    # Channels
    print("\n=== Channels ===")
    tg = input("Telegram bot token (leave blank to skip): ").strip()
    if tg:
        config["TELEGRAM_TOKEN"] = tg

    discord = input("Discord bot token (leave blank to skip): ").strip()
    if discord:
        config["DISCORD_TOKEN"] = discord

    teams = input("Teams App ID (leave blank to skip): ").strip()
    if teams:
        config["TEAMS_APP_ID"] = teams
        pw = input("Teams App Password: ").strip()
        config["TEAMS_APP_PASSWORD"] = pw

    # Write .env
    lines = [f"{k}={v}" for k, v in config.items()]
    env_path.write_text("\n".join(lines) + "\n")
    print(f"\n✅ Configuration saved to {env_path}")

    # Build Docker image
    build = input("\nBuild Docker image now? [Y/n]: ").strip().lower()
    if build != "n":
        print("Building miniondesk-runner Docker image...")
        os.system("docker build -t miniondesk-runner:latest container/")
        print("✅ Docker image built!")

    print("\n✅ Setup complete! Run: python run.py\n")


if __name__ == "__main__":
    run_setup()
