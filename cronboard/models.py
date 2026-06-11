"""Data models for crontab entries."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from enum import Enum
from typing import Optional


class LineType(Enum):
    CRON_JOB = "cron_job"
    COMMENT = "comment"
    ENV_VAR = "env_var"
    BLANK = "blank"
    UNKNOWN = "unknown"


@dataclasses.dataclass
class CrontabLine:
    """A single line in the crontab, preserving original format."""

    raw: str
    line_type: LineType
    line_number: int

    # For CRON_JOB lines
    schedule: Optional[str] = None
    command: Optional[str] = None
    enabled: bool = True
    comment_above: Optional[str] = None

    # For ENV_VAR lines
    env_name: Optional[str] = None
    env_value: Optional[str] = None

    # Runtime state (not persisted)
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    is_running: bool = False
    pid: Optional[int] = None

    @property
    def display_command(self) -> str:
        if self.command is None:
            return ""
        if len(self.command) > 80:
            return self.command[:77] + "..."
        return self.command

    @property
    def display_schedule(self) -> str:
        return self.schedule or ""

    def to_crontab_line(self) -> str:
        if self.line_type == LineType.CRON_JOB:
            base = f"{self.schedule} {self.command}"
            if not self.enabled:
                return f"# {base}"
            return base
        return self.raw


@dataclasses.dataclass
class CrontabState:
    """Complete crontab state for undo/redo."""

    lines: list[CrontabLine]
    timestamp: datetime
    description: str

    def to_text(self) -> str:
        return "\n".join(line.to_crontab_line() for line in self.lines) + "\n"
