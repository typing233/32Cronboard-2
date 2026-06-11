"""Lossless crontab parser that preserves all formatting."""

from __future__ import annotations

import re
from typing import Optional

from .models import CrontabLine, LineType


# Cron schedule patterns
CRON_FIELD = r"(?:[\d\*,/\-]+|(?:@\w+))"
FIVE_FIELD_RE = re.compile(
    r"^(\S+\s+\S+\s+\S+\s+\S+\s+\S+)\s+(.+)$"
)
SPECIAL_RE = re.compile(r"^(@(?:reboot|yearly|annually|monthly|weekly|daily|midnight|hourly))\s+(.+)$", re.IGNORECASE)
ENV_VAR_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")
DISABLED_CRON_RE = re.compile(r"^#\s*(" + r"\S+\s+\S+\s+\S+\s+\S+\s+\S+" + r")\s+(.+)$")
DISABLED_SPECIAL_RE = re.compile(
    r"^#\s*(@(?:reboot|yearly|annually|monthly|weekly|daily|midnight|hourly))\s+(.+)$", re.IGNORECASE
)


def parse_crontab(text: str) -> list[CrontabLine]:
    """Parse crontab text into structured lines, preserving everything."""
    lines = []
    raw_lines = text.split("\n")

    # Remove trailing empty line that comes from trailing newline
    if raw_lines and raw_lines[-1] == "":
        raw_lines = raw_lines[:-1]

    pending_comment: Optional[str] = None

    for i, raw in enumerate(raw_lines):
        line_num = i + 1
        stripped = raw.strip()

        # Blank line
        if not stripped:
            pending_comment = None
            lines.append(CrontabLine(
                raw=raw,
                line_type=LineType.BLANK,
                line_number=line_num,
            ))
            continue

        # Disabled cron job (commented out with #)
        disabled_special = DISABLED_SPECIAL_RE.match(stripped)
        if disabled_special:
            schedule, command = disabled_special.group(1), disabled_special.group(2)
            entry = CrontabLine(
                raw=raw,
                line_type=LineType.CRON_JOB,
                line_number=line_num,
                schedule=schedule,
                command=command,
                enabled=False,
                comment_above=pending_comment,
            )
            pending_comment = None
            lines.append(entry)
            continue

        disabled_match = DISABLED_CRON_RE.match(stripped)
        if disabled_match:
            schedule, command = disabled_match.group(1), disabled_match.group(2)
            if _is_valid_schedule(schedule):
                entry = CrontabLine(
                    raw=raw,
                    line_type=LineType.CRON_JOB,
                    line_number=line_num,
                    schedule=schedule,
                    command=command,
                    enabled=False,
                    comment_above=pending_comment,
                )
                pending_comment = None
                lines.append(entry)
                continue

        # Pure comment
        if stripped.startswith("#"):
            pending_comment = stripped[1:].strip()
            lines.append(CrontabLine(
                raw=raw,
                line_type=LineType.COMMENT,
                line_number=line_num,
            ))
            continue

        # Environment variable
        env_match = ENV_VAR_RE.match(stripped)
        if env_match and not _looks_like_cron_line(stripped):
            lines.append(CrontabLine(
                raw=raw,
                line_type=LineType.ENV_VAR,
                line_number=line_num,
                env_name=env_match.group(1),
                env_value=env_match.group(2),
            ))
            pending_comment = None
            continue

        # Special schedule (@reboot, @daily, etc.)
        special_match = SPECIAL_RE.match(stripped)
        if special_match:
            schedule, command = special_match.group(1), special_match.group(2)
            entry = CrontabLine(
                raw=raw,
                line_type=LineType.CRON_JOB,
                line_number=line_num,
                schedule=schedule,
                command=command,
                enabled=True,
                comment_above=pending_comment,
            )
            pending_comment = None
            lines.append(entry)
            continue

        # Standard 5-field cron
        five_match = FIVE_FIELD_RE.match(stripped)
        if five_match:
            schedule, command = five_match.group(1), five_match.group(2)
            if _is_valid_schedule(schedule):
                entry = CrontabLine(
                    raw=raw,
                    line_type=LineType.CRON_JOB,
                    line_number=line_num,
                    schedule=schedule,
                    command=command,
                    enabled=True,
                    comment_above=pending_comment,
                )
                pending_comment = None
                lines.append(entry)
                continue

        # Unknown line
        pending_comment = None
        lines.append(CrontabLine(
            raw=raw,
            line_type=LineType.UNKNOWN,
            line_number=line_num,
        ))

    return lines


def serialize_crontab(lines: list[CrontabLine]) -> str:
    """Serialize lines back to crontab text."""
    result = []
    for line in lines:
        result.append(line.to_crontab_line())
    return "\n".join(result) + "\n"


def _is_valid_schedule(schedule: str) -> bool:
    """Check if a string looks like a valid cron schedule.

    Each field must be a cron token: digits, *, ranges, lists, steps,
    or abbreviated day/month names (mon-sun, jan-dec). Rejects arbitrary words.
    """
    parts = schedule.strip().split()
    if len(parts) != 5:
        return False
    cron_field_re = re.compile(
        r"^(?:\*|(?:\d+|(?:mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))"
        r"(?:-(?:\d+|(?:mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)))?)"
        r"(?:/\d+)?(?:,(?:\*|\d+|(?:mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec))"
        r"(?:-(?:\d+|(?:mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)))?(?:/\d+)?)*$",
        re.IGNORECASE,
    )
    for part in parts:
        if not cron_field_re.match(part):
            return False
    return True


def _looks_like_cron_line(line: str) -> bool:
    """Check if a line that matches env var pattern is actually a cron command."""
    parts = line.split()
    if len(parts) >= 6:
        potential_schedule = " ".join(parts[:5])
        if _is_valid_schedule(potential_schedule):
            return True
    return False
