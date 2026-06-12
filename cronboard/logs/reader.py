"""Remote log readers for syslog, journald, and custom log paths.

Extracts execution status, exit codes, duration, and failure reasons from
cron logs across different Linux distributions.
"""

from __future__ import annotations

import abc
import re
from datetime import datetime, timedelta
from typing import Optional

from ..remote.connection import SSHConnection
from .models import LogEntry


class LogReader(abc.ABC):
    """Abstract base for reading cron execution logs."""

    @abc.abstractmethod
    async def fetch_logs(
        self, conn: SSHConnection, command_pattern: str, limit: int = 20
    ) -> list[LogEntry]:
        ...


class SyslogReader(LogReader):
    """Read cron logs from syslog files."""

    SYSLOG_PATHS = [
        "/var/log/syslog",
        "/var/log/cron",
        "/var/log/cron.log",
        "/var/log/messages",
    ]

    async def fetch_logs(
        self, conn: SSHConnection, command_pattern: str, limit: int = 20
    ) -> list[LogEntry]:
        for path in self.SYSLOG_PATHS:
            stdout, _, rc = await conn.exec_command(
                f"test -r {path} && echo ok"
            )
            if rc == 0 and "ok" in stdout:
                return await self._fetch_and_correlate(
                    conn, path, command_pattern, limit, sudo=False
                )

        # Try with sudo
        for path in self.SYSLOG_PATHS:
            stdout, _, rc = await conn.exec_command(
                f"sudo -n test -r {path} && echo ok"
            )
            if rc == 0 and "ok" in stdout:
                return await self._fetch_and_correlate(
                    conn, path, command_pattern, limit, sudo=True
                )

        return []

    async def _fetch_and_correlate(
        self,
        conn: SSHConnection,
        path: str,
        pattern: str,
        limit: int,
        sudo: bool,
    ) -> list[LogEntry]:
        prefix = "sudo -n " if sudo else ""
        fragment = _safe_grep_pattern(pattern)

        # Fetch CMD lines and session open/close lines together for correlation
        cmd = (
            f"{prefix}grep -E '(CRON\\[|pam_unix.*cron.*session)' {path} "
            f"| grep -i '{fragment}\\|session' "
            f"| tail -n {limit * 3}"
        )
        stdout, _, rc = await conn.exec_command(cmd, timeout=15)
        if rc not in (0, 1) or not stdout.strip():
            # Fallback: just CMD lines
            cmd = (
                f"{prefix}grep -i 'CRON' {path} "
                f"| grep -i '{fragment}' "
                f"| tail -n {limit}"
            )
            stdout, _, rc = await conn.exec_command(cmd, timeout=15)
            if rc not in (0, 1) or not stdout.strip():
                return []

        return self._parse_and_correlate(stdout, limit)

    def _parse_and_correlate(self, text: str, limit: int) -> list[LogEntry]:
        """Parse syslog lines and correlate CMD with session close for duration."""
        entries: list[LogEntry] = []
        # Track sessions by PID for duration calculation
        session_starts: dict[int, datetime] = {}

        cron_cmd_re = re.compile(
            r"^(\w+\s+\d+\s+\d+:\d+:\d+)\s+\S+\s+CRON\[(\d+)\]:\s*"
            r"\((\w+)\)\s+CMD\s+\((.+)\)\s*$",
            re.IGNORECASE,
        )
        session_open_re = re.compile(
            r"^(\w+\s+\d+\s+\d+:\d+:\d+)\s+\S+\s+.*pam_unix\(cron:session\):\s*"
            r"session opened.*uid=(\d+)",
            re.IGNORECASE,
        )
        session_close_re = re.compile(
            r"^(\w+\s+\d+\s+\d+:\d+:\d+)\s+\S+\s+.*pam_unix\(cron:session\):\s*"
            r"session closed.*",
            re.IGNORECASE,
        )

        raw_lines = text.strip().split("\n")
        cmd_entries: list[LogEntry] = []

        for line in raw_lines:
            line = line.strip()
            if not line:
                continue

            m = cron_cmd_re.match(line)
            if m:
                ts_str, pid, user, cmd = m.groups()
                ts = _parse_syslog_timestamp(ts_str)
                pid_int = int(pid)
                session_starts[pid_int] = ts if ts else datetime.now()
                cmd_entries.append(
                    LogEntry(
                        timestamp=ts,
                        raw_line=line,
                        command=cmd,
                        pid=pid_int,
                        user=user,
                        source="syslog",
                        exit_code=0,  # syslog CMD entries mean it started
                    )
                )
                continue

            m = session_close_re.match(line)
            if m:
                ts_str = m.group(1)
                close_ts = _parse_syslog_timestamp(ts_str)
                # Try to correlate with the most recent CMD entry
                if cmd_entries and close_ts:
                    last = cmd_entries[-1]
                    if last.pid and last.pid in session_starts:
                        start_ts = session_starts[last.pid]
                        if start_ts and close_ts:
                            duration = (close_ts - start_ts).total_seconds()
                            if 0 <= duration < 86400:
                                last.duration_seconds = duration

        # Return most recent entries up to limit
        return cmd_entries[-limit:]

    def _safe_grep_pattern(self, pattern: str) -> str:
        return _safe_grep_pattern(pattern)


class JournaldReader(LogReader):
    """Read cron logs from systemd journal.

    Uses JSON output format to extract structured fields including exit codes.
    """

    async def fetch_logs(
        self, conn: SSHConnection, command_pattern: str, limit: int = 20
    ) -> list[LogEntry]:
        fragment = _safe_grep_pattern(command_pattern)

        # Try structured JSON output first for richer data
        entries = await self._fetch_json(conn, fragment, limit)
        if entries:
            return entries

        # Fallback to text parsing
        entries = await self._fetch_text(conn, fragment, limit)
        if entries:
            return entries

        # Try with sudo
        entries = await self._fetch_text(conn, fragment, limit, sudo=True)
        return entries

    async def _fetch_json(
        self, conn: SSHConnection, fragment: str, limit: int
    ) -> list[LogEntry]:
        """Try journalctl with JSON output for structured exit code info."""
        cmd = (
            f"journalctl -u cron --no-pager -n {limit * 2} "
            f"-o json 2>/dev/null"
        )
        stdout, _, rc = await conn.exec_command(cmd, timeout=15)
        if not stdout.strip():
            return []

        import json

        entries: list[LogEntry] = []
        for line in stdout.strip().split("\n"):
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            message = obj.get("MESSAGE", "")
            if not message:
                continue

            # Filter by command pattern
            if fragment and fragment.lower() not in message.lower():
                continue

            # Parse CMD pattern from message
            cmd_m = re.match(
                r"\((\w+)\)\s+CMD\s+\((.+)\)", message, re.IGNORECASE
            )
            if not cmd_m:
                continue

            user, cmd_text = cmd_m.groups()

            # Extract timestamp
            ts = None
            ts_usec = obj.get("__REALTIME_TIMESTAMP")
            if ts_usec:
                try:
                    ts = datetime.fromtimestamp(int(ts_usec) / 1_000_000)
                except (ValueError, OSError):
                    pass

            pid = None
            pid_str = obj.get("_PID") or obj.get("SYSLOG_PID")
            if pid_str:
                try:
                    pid = int(pid_str)
                except ValueError:
                    pass

            # Exit code from EXIT_STATUS field (if crond reports it)
            exit_code = None
            exit_str = obj.get("EXIT_STATUS")
            if exit_str:
                try:
                    exit_code = int(exit_str)
                except ValueError:
                    pass

            entries.append(
                LogEntry(
                    timestamp=ts,
                    raw_line=message,
                    command=cmd_text,
                    pid=pid,
                    user=user,
                    exit_code=exit_code,
                    source="journald",
                )
            )

        return entries[-limit:]

    async def _fetch_text(
        self, conn: SSHConnection, fragment: str, limit: int, sudo: bool = False
    ) -> list[LogEntry]:
        prefix = "sudo -n " if sudo else ""
        commands = [
            f"{prefix}journalctl -u cron --no-pager -n {limit * 2} -o short-precise 2>/dev/null",
            f"{prefix}journalctl -t CROND --no-pager -n {limit * 2} -o short-precise 2>/dev/null",
            f"{prefix}journalctl _COMM=cron --no-pager -n {limit * 2} -o short-precise 2>/dev/null",
        ]

        for cmd in commands:
            stdout, _, rc = await conn.exec_command(cmd, timeout=15)
            if stdout.strip():
                return self._parse_and_correlate(stdout, fragment, limit)

        return []

    def _parse_and_correlate(
        self, text: str, fragment: str, limit: int
    ) -> list[LogEntry]:
        """Parse journald text output and correlate start/end for duration."""
        entries: list[LogEntry] = []
        session_starts: dict[int, datetime] = {}

        cron_cmd_re = re.compile(
            r"^(\w+\s+\d+\s+\d+:\d+:\d+)\S*\s+\S+\s+CRON\[(\d+)\]:\s*"
            r"\((\w+)\)\s+CMD\s+\((.+)\)\s*$",
            re.IGNORECASE,
        )
        # CROND logs exit status on some distros (RHEL/CentOS)
        cmdout_re = re.compile(
            r"^(\w+\s+\d+\s+\d+:\d+:\d+)\S*\s+\S+\s+CROND\[(\d+)\]:\s*"
            r"\((\w+)\)\s+CMDOUT\s+\((.+)\)\s*$",
            re.IGNORECASE,
        )
        cmdend_re = re.compile(
            r"^(\w+\s+\d+\s+\d+:\d+:\d+)\S*\s+\S+\s+CROND\[(\d+)\]:\s*"
            r"\((\w+)\)\s+CMDEND\s+\(.*exit\s+status\s+(\d+).*\)\s*$",
            re.IGNORECASE,
        )

        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            # Check for CMD END with exit status (RHEL-style)
            m = cmdend_re.match(line)
            if m:
                ts_str, pid, user, exit_code_str = m.groups()
                ts = _parse_syslog_timestamp(ts_str)
                pid_int = int(pid)
                exit_code = int(exit_code_str)
                # Update the matching CMD entry
                for entry in reversed(entries):
                    if entry.pid == pid_int:
                        entry.exit_code = exit_code
                        if ts and entry.timestamp:
                            entry.duration_seconds = (
                                ts - entry.timestamp
                            ).total_seconds()
                        if exit_code != 0 and not entry.message:
                            entry.message = f"进程退出码 {exit_code}"
                        break
                continue

            # Check for CMDOUT (command output, often error messages)
            m = cmdout_re.match(line)
            if m:
                ts_str, pid, user, output = m.groups()
                pid_int = int(pid)
                for entry in reversed(entries):
                    if entry.pid == pid_int:
                        entry.message = output.strip()
                        break
                continue

            m = cron_cmd_re.match(line)
            if m:
                ts_str, pid, user, cmd = m.groups()
                if fragment and fragment.lower() not in cmd.lower():
                    continue
                ts = _parse_syslog_timestamp(ts_str)
                pid_int = int(pid)
                session_starts[pid_int] = ts if ts else datetime.now()
                entries.append(
                    LogEntry(
                        timestamp=ts,
                        raw_line=line,
                        command=cmd,
                        pid=pid_int,
                        user=user,
                        source="journald",
                    )
                )

        return entries[-limit:]


class CustomPathReader(LogReader):
    """Read from a user-specified log file path.

    Attempts to extract timestamps, exit codes, and duration from common
    log formats.
    """

    # Common log patterns
    LOG_PATTERNS = [
        # "2024-06-15 10:00:00 [INFO] command completed (exit=0, duration=5.2s)"
        re.compile(
            r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+"
            r"\[(\w+)\]\s+(.+?)(?:\s*\(exit=(\d+)(?:,\s*duration=([\d.]+)s?)?\))?\s*$"
        ),
        # "Jun 12 10:00:00 command started/finished (rc=0)"
        re.compile(
            r"^(\w+\s+\d+\s+\d{2}:\d{2}:\d{2})\s+(.+?)(?:\s*\(?(?:rc|exit|status)=(\d+)\)?)?\s*$"
        ),
        # Generic: "timestamp anything exit_code"
        re.compile(
            r"^(\d{4}[-/]\d{2}[-/]\d{2}[\sT]\d{2}:\d{2}:\d{2})\s+(.+)"
        ),
    ]

    def __init__(self, log_path: str):
        self._path = log_path

    async def fetch_logs(
        self, conn: SSHConnection, command_pattern: str, limit: int = 20
    ) -> list[LogEntry]:
        fragment = _safe_grep_pattern(command_pattern)

        # Check readability
        stdout, _, rc = await conn.exec_command(
            f"test -r {self._path} && echo ok"
        )
        sudo = ""
        if rc != 0:
            stdout, _, rc = await conn.exec_command(
                f"sudo -n test -r {self._path} && echo ok"
            )
            if rc == 0:
                sudo = "sudo -n "
            else:
                return []

        cmd = f"{sudo}tail -n 500 {self._path}"
        if fragment:
            cmd += f" | grep -i '{fragment}'"
        cmd += f" | tail -n {limit}"

        stdout, _, rc = await conn.exec_command(cmd, timeout=15)
        if not stdout.strip():
            return []

        return self._parse_custom_lines(stdout, limit)

    def _parse_custom_lines(self, text: str, limit: int) -> list[LogEntry]:
        entries: list[LogEntry] = []
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            entry = self._parse_single_line(line)
            entries.append(entry)
        return entries[-limit:]

    def _parse_single_line(self, line: str) -> LogEntry:
        # Pattern 1: ISO timestamp with structured fields
        m = self.LOG_PATTERNS[0].match(line)
        if m:
            ts_str, level, message, exit_str, dur_str = m.groups()
            ts = self._parse_iso_timestamp(ts_str)
            exit_code = int(exit_str) if exit_str else None
            duration = float(dur_str) if dur_str else None
            failure_msg = None
            if exit_code and exit_code != 0:
                failure_msg = f"退出码 {exit_code}: {message}"
            elif level in ("ERROR", "FATAL", "CRITICAL"):
                failure_msg = message
                if exit_code is None:
                    exit_code = 1
            return LogEntry(
                timestamp=ts,
                raw_line=line,
                command=message,
                exit_code=exit_code,
                duration_seconds=duration,
                message=failure_msg,
                source="custom",
            )

        # Pattern 2: syslog-style with rc= marker
        m = self.LOG_PATTERNS[1].match(line)
        if m:
            ts_str, message = m.group(1), m.group(2)
            exit_str = m.group(3) if m.lastindex >= 3 else None
            ts = _parse_syslog_timestamp(ts_str)
            exit_code = int(exit_str) if exit_str else None
            failure_msg = None
            if exit_code and exit_code != 0:
                failure_msg = f"退出码 {exit_code}"
            return LogEntry(
                timestamp=ts,
                raw_line=line,
                command=message,
                exit_code=exit_code,
                message=failure_msg,
                source="custom",
            )

        # Pattern 3: ISO timestamp generic
        m = self.LOG_PATTERNS[2].match(line)
        if m:
            ts_str, rest = m.groups()
            ts = self._parse_iso_timestamp(ts_str)
            # Look for exit code patterns in the rest
            exit_code = self._extract_exit_code(rest)
            duration = self._extract_duration(rest)
            failure_msg = None
            if exit_code is not None and exit_code != 0:
                failure_msg = rest.strip()
            return LogEntry(
                timestamp=ts,
                raw_line=line,
                command=rest.strip()[:80],
                exit_code=exit_code,
                duration_seconds=duration,
                message=failure_msg,
                source="custom",
            )

        # No pattern matched
        return LogEntry(raw_line=line, source="custom")

    def _parse_iso_timestamp(self, ts_str: str) -> Optional[datetime]:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(ts_str, fmt)
            except ValueError:
                continue
        return None

    def _extract_exit_code(self, text: str) -> Optional[int]:
        m = re.search(r'(?:exit|rc|status|code)[=:\s]+(\d+)', text, re.IGNORECASE)
        if m:
            return int(m.group(1))
        if re.search(r'\b(error|fail|fatal|exception)\b', text, re.IGNORECASE):
            return 1
        return None

    def _extract_duration(self, text: str) -> Optional[float]:
        m = re.search(r'(?:duration|elapsed|took)[=:\s]+([\d.]+)\s*s', text, re.IGNORECASE)
        if m:
            return float(m.group(1))
        m = re.search(r'([\d.]+)\s*(?:sec|seconds)', text, re.IGNORECASE)
        if m:
            return float(m.group(1))
        return None


class AutoLogReader(LogReader):
    """Auto-detect log source: try journald first, then syslog."""

    def __init__(self):
        self._journald = JournaldReader()
        self._syslog = SyslogReader()

    async def fetch_logs(
        self, conn: SSHConnection, command_pattern: str, limit: int = 20
    ) -> list[LogEntry]:
        entries = await self._journald.fetch_logs(conn, command_pattern, limit)
        if entries:
            return entries
        return await self._syslog.fetch_logs(conn, command_pattern, limit)


def create_log_reader(
    config_log_source: str, custom_path: Optional[str] = None
) -> LogReader:
    """Factory function to create the appropriate log reader."""
    if config_log_source == "journald":
        return JournaldReader()
    elif config_log_source == "syslog":
        return SyslogReader()
    elif config_log_source == "custom" and custom_path:
        return CustomPathReader(custom_path)
    else:
        return AutoLogReader()


def _safe_grep_pattern(pattern: str) -> str:
    """Extract a safe grep fragment from a command pattern."""
    parts = pattern.split()
    fragment = parts[0] if parts else pattern
    return re.sub(r"[^\w/.\-]", ".", fragment)


def _parse_syslog_timestamp(ts_str: str) -> Optional[datetime]:
    """Parse syslog-style timestamp (e.g. 'Jun 12 09:30:01')."""
    try:
        now = datetime.now()
        dt = datetime.strptime(ts_str.strip(), "%b %d %H:%M:%S")
        return dt.replace(year=now.year)
    except ValueError:
        return None
