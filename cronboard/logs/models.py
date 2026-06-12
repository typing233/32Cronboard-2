"""Log entry data model."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Optional


@dataclasses.dataclass
class LogEntry:
    """A single cron execution log entry."""

    timestamp: Optional[datetime] = None
    raw_line: str = ""
    command: Optional[str] = None
    exit_code: Optional[int] = None
    duration_seconds: Optional[float] = None
    pid: Optional[int] = None
    user: Optional[str] = None
    message: Optional[str] = None
    source: str = ""  # "syslog", "journald", "custom"

    @property
    def status_display(self) -> str:
        if self.exit_code is None:
            return "未知"
        if self.exit_code == 0:
            return "成功"
        return f"失败 (退出码: {self.exit_code})"

    @property
    def duration_display(self) -> str:
        if self.duration_seconds is None:
            return "-"
        if self.duration_seconds < 60:
            return f"{self.duration_seconds:.1f}s"
        minutes = int(self.duration_seconds // 60)
        seconds = self.duration_seconds % 60
        return f"{minutes}m{seconds:.0f}s"
