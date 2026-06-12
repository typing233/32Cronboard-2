"""Audit record data model."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Optional


@dataclasses.dataclass
class AuditRecord:
    """A single audit trail entry."""

    timestamp: datetime
    host: str
    username: str
    operation: str
    description: Optional[str] = None
    diff: Optional[str] = None
    success: bool = True
    error_message: Optional[str] = None
    id: Optional[int] = None

    @classmethod
    def from_row(cls, row: tuple) -> AuditRecord:
        return cls(
            id=row[0],
            timestamp=datetime.fromisoformat(row[1]),
            host=row[2],
            username=row[3],
            operation=row[4],
            description=row[5],
            diff=row[6],
            success=bool(row[7]),
            error_message=row[8],
        )
