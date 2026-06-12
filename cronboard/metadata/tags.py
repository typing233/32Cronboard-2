"""Tag/label storage for cron jobs backed by SQLite."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional


TAGS_DB_PATH = Path.home() / ".local" / "share" / "cronboard" / "tags.db"


class TagStore:
    """Per-job tag/label storage."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or TAGS_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS job_tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    host TEXT NOT NULL,
                    command_hash TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(host, command_hash, tag)
                );
                CREATE INDEX IF NOT EXISTS idx_tags_host
                    ON job_tags(host);
                CREATE INDEX IF NOT EXISTS idx_tags_tag
                    ON job_tags(tag);
                """
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def command_hash(command: str) -> str:
        return hashlib.sha256(command.encode()).hexdigest()[:16]

    async def add_tag(self, host: str, command: str, tag: str) -> None:
        await asyncio.to_thread(self._add_tag, host, command, tag)

    def _add_tag(self, host: str, command: str, tag: str) -> None:
        cmd_hash = self.command_hash(command)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute(
                """INSERT OR IGNORE INTO job_tags
                   (host, command_hash, tag, created_at) VALUES (?, ?, ?, ?)""",
                (host, cmd_hash, tag, datetime.now().isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    async def remove_tag(self, host: str, command: str, tag: str) -> None:
        await asyncio.to_thread(self._remove_tag, host, command, tag)

    def _remove_tag(self, host: str, command: str, tag: str) -> None:
        cmd_hash = self.command_hash(command)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute(
                "DELETE FROM job_tags WHERE host=? AND command_hash=? AND tag=?",
                (host, cmd_hash, tag),
            )
            conn.commit()
        finally:
            conn.close()

    async def get_tags(self, host: str, command: str) -> list[str]:
        return await asyncio.to_thread(self._get_tags, host, command)

    def _get_tags(self, host: str, command: str) -> list[str]:
        cmd_hash = self.command_hash(command)
        conn = sqlite3.connect(str(self._db_path))
        try:
            rows = conn.execute(
                "SELECT tag FROM job_tags WHERE host=? AND command_hash=?",
                (host, cmd_hash),
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    async def get_all_tags(self) -> list[str]:
        return await asyncio.to_thread(self._get_all_tags)

    def _get_all_tags(self) -> list[str]:
        conn = sqlite3.connect(str(self._db_path))
        try:
            rows = conn.execute(
                "SELECT DISTINCT tag FROM job_tags ORDER BY tag"
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            conn.close()

    async def find_by_tag(self, tag: str) -> list[tuple[str, str]]:
        """Return list of (host, command_hash) matching the tag."""
        return await asyncio.to_thread(self._find_by_tag, tag)

    def _find_by_tag(self, tag: str) -> list[tuple[str, str]]:
        conn = sqlite3.connect(str(self._db_path))
        try:
            rows = conn.execute(
                "SELECT host, command_hash FROM job_tags WHERE tag=?", (tag,)
            ).fetchall()
            return [(r[0], r[1]) for r in rows]
        finally:
            conn.close()
