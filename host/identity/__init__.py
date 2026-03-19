"""Agent Identity Layer for MinionDesk — Phase 1."""
from .agent_identity import AgentIdentity
from .bot_registry import BotRegistry, bootstrap_known_bots

__all__ = ["AgentIdentity", "BotRegistry", "bootstrap_known_bots"]
