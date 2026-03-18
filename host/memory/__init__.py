"""Three-tier memory system for MinionDesk v2.x (OpenClaw-inspired)."""
from .hot import get_hot_memory, update_hot_memory
from .warm import append_warm_log, run_micro_sync
from .search import memory_search

try:
    from .summarizer import MemorySummarizer
    __all__ = ["get_hot_memory", "update_hot_memory", "append_warm_log", "run_micro_sync", "memory_search", "MemorySummarizer"]
except ImportError:
    __all__ = ["get_hot_memory", "update_hot_memory", "append_warm_log", "run_micro_sync", "memory_search"]
