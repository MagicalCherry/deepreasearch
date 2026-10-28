"""Shared stop flags; independent of router import order."""
from core.redis_client import cache

CANCEL_KEY_PREFIX = "research:cancel:"


def is_research_cancelled(session_id: str) -> bool:
    result = cache.get(f"{CANCEL_KEY_PREFIX}{session_id}")
    return bool(result and result.get("cancelled", False))


def clear_cancel_flag(session_id: str):
    cache.delete(f"{CANCEL_KEY_PREFIX}{session_id}")
