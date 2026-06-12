"""Local backend wrapping existing CrontabManager."""

from __future__ import annotations

import asyncio
import hashlib

from .base import CrontabBackend
from ..manager import CrontabManager
from ..models import CrontabLine


class LocalBackend(CrontabBackend):
    """Local crontab operations via existing CrontabManager."""

    def __init__(self):
        self._manager = CrontabManager()

    @property
    def host_id(self) -> str:
        return "localhost"

    @property
    def display_name(self) -> str:
        return "本机 (localhost)"

    async def read_crontab(self) -> list[CrontabLine]:
        lines = await asyncio.to_thread(self._manager.read_crontab)
        for line in lines:
            line.host = self.host_id
        return lines

    async def write_crontab(
        self, lines: list[CrontabLine], description: str = ""
    ) -> None:
        await asyncio.to_thread(self._manager.write_crontab, lines, description)

    async def get_content_hash(self) -> str:
        text = await asyncio.to_thread(self._manager._read_raw_crontab)
        return hashlib.sha256(text.encode()).hexdigest()

    async def test_connection(self) -> tuple[bool, str]:
        return (True, "")

    async def close(self) -> None:
        pass

    @property
    def manager(self) -> CrontabManager:
        return self._manager
