"""Abstract backend interface for crontab operations."""

from __future__ import annotations

import abc
from typing import Optional

from ..models import CrontabLine


class CrontabBackend(abc.ABC):
    """Abstract interface for crontab operations on any host."""

    @property
    @abc.abstractmethod
    def host_id(self) -> str:
        """Unique identifier for this host."""
        ...

    @property
    @abc.abstractmethod
    def display_name(self) -> str:
        """Human-readable host name for UI display."""
        ...

    @abc.abstractmethod
    async def read_crontab(self) -> list[CrontabLine]:
        """Read crontab from this host."""
        ...

    @abc.abstractmethod
    async def write_crontab(
        self, lines: list[CrontabLine], description: str = ""
    ) -> None:
        """Write crontab atomically with conflict detection."""
        ...

    @abc.abstractmethod
    async def get_content_hash(self) -> str:
        """Return hash of current crontab content for conflict detection."""
        ...

    @abc.abstractmethod
    async def test_connection(self) -> tuple[bool, str]:
        """Test connectivity. Returns (success, error_message)."""
        ...

    @abc.abstractmethod
    async def close(self) -> None:
        """Release resources."""
        ...
