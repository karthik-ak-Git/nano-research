"""In-memory and persistent caching with SHA-256 content deduplication."""

import hashlib
import json
import time
from typing import Optional, Any, Dict
from company_agent.budgets import budget_manager


def hash_content(content: str) -> str:
    """Computes SHA-256 hex digest of string content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class ResponseCache:
    """In-memory cache for web requests and LLM extractions with TTL."""

    def __init__(self, default_ttl_seconds: int = 86400):
        self.default_ttl = default_ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        """Retrieves cached item if present and unexpired."""
        entry = self._cache.get(key)
        if entry is None:
            budget_manager.record_cache_miss()
            return None

        if time.time() > entry["expires_at"]:
            del self._cache[key]
            budget_manager.record_cache_miss()
            return None

        budget_manager.record_cache_hit()
        return entry["data"]

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Stores item in cache with TTL."""
        ttl = ttl_seconds or self.default_ttl
        self._cache[key] = {
            "data": value,
            "expires_at": time.time() + ttl,
        }

    def clear(self) -> None:
        self._cache.clear()


# Global response cache
cache = ResponseCache()
