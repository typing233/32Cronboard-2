"""Remote log readers for syslog, journald, and custom log paths."""

from __future__ import annotations

import abc
import re
from datetime import datetime
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
                return await self._parse_syslog(
                    conn, path, command_pattern, limit, sudo=False
                )

        # Try with sudo
        for path in self.SYSLOG_PATHS:
            stdout, _, rc = await conn.exec_command(
                f"sudo -n test -r {path} && echo ok"
            )
            if rc == 0 and "ok" in stdout:
                return await self._parse_syslog(
                    conn, path, command_pattern, limit, sudo=True
                )

        return []

    async def _parse_syslog(
        self,
        conn: SSHConnection,
        path: str,
        pattern: str,
        limit: int,
        sudo: bool,
    ) -> list[LogEntry]:
        prefix = "sudo -n " if sudo else ""
        fragment = self._safe_grep_pattern(pattern)
        cmd = (
            f"{prefix}grep -i 'CRON' {path} "
            f"| grep -i '{fragment}' "
            f"| tail -n {limit}"
        )
        stdout, _, rc = await conn.exec_command(cmd, timeout=15)
        if rc not in (0, 1) or not stdout.strip():
            return []
        return self._parse_lines(stdout)

    def _parse_lines(self, text: str) -> list[LogEntry]:
        entries: list[LogEntry] = []
        # Pattern: "Jun 12 09:30:01 hostname CRON[12345]: (user) CMD (command)"
        cron_re = re.compile(
            r"^(\w+\s+\d+\s+\d+:\d+:\d+)\s+\S+\s+CRON\[(\d+)\]:\s*"
            r"\((\w+)\)\s+CMD\s+\((.+)\)\s*$",
            re.IGNORECASE,
        )
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            m = cron_re.match(line)
            if m:
                ts_str, pid, user, cmd = m.groups()
                ts = self._parse_syslog_timestamp(ts_str)
                entries.append(
                    LogEntry(
                        timestamp=ts,
                        raw_line=line,
                        command=cmd,
                        pid=int(pid),
                        user=user,
                        source="syslog",
                    )
                )
            else:
                entries.append(LogEntry(raw_line=line, source="syslog"))
        return entries

    def _parse_syslog_timestamp(self, ts_str: str) -> Optional[datetime]:
        try:
            now = datetime.now()
            dt = datetime.strptime(ts_str, "%b %d %H:%M:%S")
            return dt.replace(year=now.year)
        except ValueError:
            return None

    def _safe_grep_pattern(self, pattern: str) -> str:
        parts = pattern.split()
        fragment = parts[0] if parts else pattern
        return re.sub(r"[^\w/.\-]", ".", fragment)


class JournaldReader(LogReader):
    """Read cron logs from systemd journal."""

    async def fetch_logs(
        self, conn: SSHConnection, command_pattern: str, limit: int = 20
    ) -> list[LogEntry]:
        fragment = self._safe_grep_pattern(command_pattern)

        # Try different journalctl invocations
        commands = [
            f"journalctl -u cron --no-pager -n {limit} -o short-precise 2>/dev/null",
            f"journalctl -t CROND --no-pager -n {limit} -o short-precise 2>/dev/null",
            f"journalctl _COMM=cron --no-pager -n {limit} -o short-precise 2>/dev/null",
        ]

        for cmd in commands:
            if fragment:
                cmd += f" | grep -i '{fragment}'"
            stdout, _, rc = await conn.exec_command(cmd, timeout=15)
            if stdout.strip():
                return self._parse_journal_output(stdout)

        # Try with sudo
        cmd = (
            f"sudo -n journalctl -u cron --no-pager -n {limit} -o short-precise 2>/dev/null"
        )
        if fragment:
            cmd += f" | grep -i '{fragment}'"
        stdout, _, rc = await conn.exec_command(cmd, timeout=15)
        if stdout.strip():
            return self._parse_journal_output(stdout)

        return []

    def _parse_journal_output(self, text: str) -> list[LogEntry]:
        entries: list[LogEntry] = []
        # journald short-precise: "Jun 12 09:30:01.123456 hostname CRON[1234]: ..."
        cron_re = re.compile(
            r"^(\w+\s+\d+\s+\d+:\d+:\d+)\S*\s+\S+\s+CRON\[(\d+)\]:\s*"
            r"\((\w+)\)\s+CMD\s+\((.+)\)\s*$",
            re.IGNORECASE,
        )
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            m = cron_re.match(line)
            if m:
                ts_str, pid, user, cmd = m.groups()
                ts = self._parse_timestamp(ts_str)
                entries.append(
                    LogEntry(
                        timestamp=ts,
                        raw_line=line,
                        command=cmd,
                        pid=int(pid),
                        user=user,
                        source="journald",
                    )
                )
            else:
                entries.append(
                    LogEntry(raw_line=line, source="journald")
                )
        return entries

    def _parse_timestamp(self, ts_str: str) -> Optional[datetime]:
        try:
            now = datetime.now()
            dt = datetime.strptime(ts_str, "%b %d %H:%M:%S")
            return dt.replace(year=now.year)
        except ValueError:
            return None

    def _safe_grep_pattern(self, pattern: str) -> str:
        parts = pattern.split()
        fragment = parts[0] if parts else pattern
        return re.sub(r"[^\w/.\-]", ".", fragment)


class CustomPathReader(LogReader):
    """Read from a user-specified log file path."""

    def __init__(self, log_path: str):
        self._path = log_path

    async def fetch_logs(
        self, conn: SSHConnection, command_pattern: str, limit: int = 20
    ) -> list[LogEntry]:
        fragment = re.sub(
            r"[^\w/.\-]", ".", command_pattern.split()[0]
        ) if command_pattern.split() else ""

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

        entries: list[LogEntry] = []
        for line in stdout.strip().split("\n"):
            if line.strip():
                entries.append(
                    LogEntry(raw_line=line.strip(), source="custom")
                )
        return entries


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


def create_log_reader(config_log_source: str, custom_path: Optional[str] = None) -> LogReader:
    """Factory function to create the appropriate log reader."""
    if config_log_source == "journald":
        return JournaldReader()
    elif config_log_source == "syslog":
        return SyslogReader()
    elif config_log_source == "custom" and custom_path:
        return CustomPathReader(custom_path)
    else:
        return AutoLogReader()
