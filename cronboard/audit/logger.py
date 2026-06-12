"""Audit logger backed by SQLite."""

from __future__ import annotations

import asyncio
import getpass
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import AuditRecord


AUDIT_DB_PATH = Path.home() / ".local" / "share" / "cronboard" / "audit.db"


class AuditLogger:
    """Thread-safe audit logger backed by SQLite."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or AUDIT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._username = getpass.getuser()
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    host TEXT NOT NULL,
                    username TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    description TEXT,
                    diff TEXT,
                    success INTEGER NOT NULL DEFAULT 1,
                    error_message TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_audit_host_ts
                    ON audit_log(host, timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_timestamp
                    ON audit_log(timestamp DESC);
                """
            )
            conn.commit()
        finally:
            conn.close()

    async def log(
        self,
        host: str,
        operation: str,
        success: bool = True,
        description: Optional[str] = None,
        diff: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        record = AuditRecord(
            timestamp=datetime.now(),
            host=host,
            username=self._username,
            operation=operation,
            description=description,
            diff=diff,
            success=success,
            error_message=error_message,
        )
        await asyncio.to_thread(self._write_record, record)

    def _write_record(self, record: AuditRecord) -> None:
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute(
                """INSERT INTO audit_log
                   (timestamp, host, username, operation, description, diff, success, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.timestamp.isoformat(),
                    record.host,
                    record.username,
                    record.operation,
                    record.description,
                    record.diff,
                    1 if record.success else 0,
                    record.error_message,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    async def query(
        self,
        host: Optional[str] = None,
        operation: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditRecord]:
        return await asyncio.to_thread(
            self._query_records, host, operation, limit, offset
        )

    def _query_records(
        self,
        host: Optional[str],
        operation: Optional[str],
        limit: int,
        offset: int,
    ) -> list[AuditRecord]:
        conn = sqlite3.connect(str(self._db_path))
        try:
            conditions = []
            params: list = []
            if host:
                conditions.append("host = ?")
                params.append(host)
            if operation:
                conditions.append("operation = ?")
                params.append(operation)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            sql = f"SELECT * FROM audit_log {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            rows = conn.execute(sql, params).fetchall()
            return [AuditRecord.from_row(r) for r in rows]
        finally:
            conn.close()

    async def count(self, host: Optional[str] = None) -> int:
        return await asyncio.to_thread(self._count, host)

    def _count(self, host: Optional[str]) -> int:
        conn = sqlite3.connect(str(self._db_path))
        try:
            if host:
                row = conn.execute(
                    "SELECT COUNT(*) FROM audit_log WHERE host = ?", (host,)
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()
            return row[0] if row else 0
        finally:
            conn.close()
