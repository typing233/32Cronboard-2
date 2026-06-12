"""In-memory TTL cache for remote crontab state."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from ..models import CrontabLine


@dataclass
class CachedState:
    """Cached crontab state for a single host."""

    lines: list[CrontabLine]
    content_hash: str
    fetched_at: float


class CrontabStateCache:
    """In-memory TTL cache for remote crontab states."""

    def __init__(self, ttl_seconds: int = 60):
        self._cache: dict[str, CachedState] = {}
        self._ttl = ttl_seconds

    def get(self, host_id: str) -> Optional[list[CrontabLine]]:
        entry = self._cache.get(host_id)
        if entry is None:
            return None
        if time.time() - entry.fetched_at > self._ttl:
            del self._cache[host_id]
            return None
        return entry.lines

    def get_hash(self, host_id: str) -> Optional[str]:
        entry = self._cache.get(host_id)
        if entry is None:
            return None
        if time.time() - entry.fetched_at > self._ttl:
            del self._cache[host_id]
            return None
        return entry.content_hash

    def put(
        self, host_id: str, lines: list[CrontabLine], content_hash: str
    ) -> None:
        self._cache[host_id] = CachedState(
            lines=lines,
            content_hash=content_hash,
            fetched_at=time.time(),
        )

    def invalidate(self, host_id: str) -> None:
        self._cache.pop(host_id, None)

    def invalidate_all(self) -> None:
        self._cache.clear()

    def is_cached(self, host_id: str) -> bool:
        return self.get(host_id) is not None
