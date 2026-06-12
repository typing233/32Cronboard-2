"""Tests for log reader implementations with exit code and duration extraction."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from cronboard.logs.models import LogEntry
from cronboard.logs.reader import (
    AutoLogReader,
    CustomPathReader,
    JournaldReader,
    SyslogReader,
    create_log_reader,
    _safe_grep_pattern,
    _parse_syslog_timestamp,
)


@pytest.fixture
def mock_conn():
    conn = MagicMock()
    conn.exec_command = AsyncMock()
    return conn


SYSLOG_OUTPUT = """\
Jun 12 09:30:01 web-01 CRON[12345]: (root) CMD (/usr/bin/backup.sh)
Jun 12 09:30:01 web-01 pam_unix(cron:session): session opened for user root
Jun 12 09:30:05 web-01 pam_unix(cron:session): session closed for user root
Jun 12 10:00:01 web-01 CRON[12400]: (root) CMD (/usr/bin/backup.sh)
Jun 12 10:00:01 web-01 pam_unix(cron:session): session opened for user root
Jun 12 10:00:03 web-01 pam_unix(cron:session): session closed for user root
"""

JOURNAL_OUTPUT = """\
Jun 12 09:30:01.123456 web-01 CRON[12345]: (root) CMD (/usr/bin/backup.sh)
Jun 12 10:00:01.654321 web-01 CRON[12400]: (root) CMD (/usr/bin/backup.sh)
"""

JOURNAL_WITH_EXIT = """\
Jun 12 09:30:01.000 web-01 CRON[12345]: (root) CMD (/usr/bin/backup.sh)
Jun 12 09:30:05.000 web-01 CROND[12345]: (root) CMDEND (/usr/bin/backup.sh exit status 0)
Jun 12 10:00:01.000 web-01 CRON[12400]: (root) CMD (/usr/bin/cleanup.sh)
Jun 12 10:00:08.000 web-01 CROND[12400]: (root) CMDOUT (Error: disk full)
Jun 12 10:00:08.000 web-01 CROND[12400]: (root) CMDEND (/usr/bin/cleanup.sh exit status 1)
"""


class TestSyslogReader:
    def test_fetch_logs_with_duration(self, mock_conn):
        mock_conn.exec_command.side_effect = [
            ("ok\n", "", 0),
            (SYSLOG_OUTPUT, "", 0),
        ]
        reader = SyslogReader()
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "/usr/bin/backup.sh", limit=10)
        )
        assert len(entries) == 2
        assert entries[0].source == "syslog"
        assert entries[0].user == "root"
        assert entries[0].command == "/usr/bin/backup.sh"
        assert entries[0].pid == 12345

    def test_fetch_logs_no_file(self, mock_conn):
        mock_conn.exec_command.return_value = ("", "", 1)
        reader = SyslogReader()
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "test-cmd", limit=10)
        )
        assert entries == []

    def test_fetch_logs_with_sudo(self, mock_conn):
        responses = [
            ("", "", 1),  # test -r /var/log/syslog
            ("", "", 1),  # test -r /var/log/cron
            ("", "", 1),  # test -r /var/log/cron.log
            ("", "", 1),  # test -r /var/log/messages
            ("ok\n", "", 0),  # sudo test -r /var/log/syslog
            (SYSLOG_OUTPUT, "", 0),  # sudo grep
        ]
        mock_conn.exec_command.side_effect = responses
        reader = SyslogReader()
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "backup", limit=10)
        )
        assert len(entries) == 2


class TestJournaldReader:
    def test_fetch_with_exit_status(self, mock_conn):
        """Test RHEL-style CMDEND with exit status parsing."""
        mock_conn.exec_command.side_effect = [
            ("", "", 1),  # JSON attempt fails
            (JOURNAL_WITH_EXIT, "", 0),  # text output succeeds
        ]
        reader = JournaldReader()
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "/usr/bin", limit=10)
        )
        # Should have 2 CMD entries with exit codes correlated
        cmd_entries = [e for e in entries if e.command]
        assert len(cmd_entries) == 2
        assert cmd_entries[0].exit_code == 0
        assert cmd_entries[0].duration_seconds is not None
        assert cmd_entries[1].exit_code == 1
        # CMDOUT message "Error: disk full" should be preserved (not overwritten by CMDEND)
        assert cmd_entries[1].message == "Error: disk full"

    def test_fetch_text_basic(self, mock_conn):
        mock_conn.exec_command.side_effect = [
            ("", "", 1),  # JSON fails
            (JOURNAL_OUTPUT, "", 0),
        ]
        reader = JournaldReader()
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "/usr/bin/backup.sh", limit=10)
        )
        assert len(entries) == 2
        assert entries[0].source == "journald"
        assert entries[0].pid == 12345

    def test_fetch_logs_empty(self, mock_conn):
        mock_conn.exec_command.side_effect = [
            ("", "", 1),  # JSON attempt fails
            ("", "", 0),  # journalctl -u cron text empty
            ("", "", 0),  # journalctl -t CROND text empty
            ("", "", 0),  # journalctl _COMM=cron text empty
            ("", "", 0),  # sudo journalctl -u cron text empty
            ("", "", 0),  # sudo journalctl -t CROND text empty
            ("", "", 0),  # sudo journalctl _COMM=cron text empty
        ]
        reader = JournaldReader()
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "test-cmd", limit=10)
        )
        assert entries == []


class TestCustomPathReader:
    def test_structured_log_with_exit_code(self, mock_conn):
        custom_output = (
            "2024-06-15 10:00:00 [INFO] backup.sh completed (exit=0, duration=5.2s)\n"
            "2024-06-15 11:00:00 [ERROR] cleanup.sh failed (exit=1, duration=2.0s)\n"
        )
        mock_conn.exec_command.side_effect = [
            ("ok\n", "", 0),
            (custom_output, "", 0),
        ]
        reader = CustomPathReader("/var/log/app/cron.log")
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "backup", limit=10)
        )
        assert len(entries) == 2
        assert entries[0].exit_code == 0
        assert entries[0].duration_seconds == 5.2
        assert entries[1].exit_code == 1
        assert entries[1].duration_seconds == 2.0
        assert entries[1].message is not None

    def test_log_with_rc_pattern(self, mock_conn):
        custom_output = "Jun 12 10:00:00 backup finished (rc=0)\n"
        mock_conn.exec_command.side_effect = [
            ("ok\n", "", 0),
            (custom_output, "", 0),
        ]
        reader = CustomPathReader("/var/log/cron.log")
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "backup", limit=10)
        )
        assert len(entries) == 1
        assert entries[0].exit_code == 0

    def test_log_with_error_keyword(self, mock_conn):
        custom_output = "2024-06-15 10:00:00 backup.sh error: permission denied\n"
        mock_conn.exec_command.side_effect = [
            ("ok\n", "", 0),
            (custom_output, "", 0),
        ]
        reader = CustomPathReader("/var/log/app.log")
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "backup", limit=10)
        )
        assert len(entries) == 1
        assert entries[0].exit_code == 1  # Inferred from "error" keyword

    def test_fetch_logs_no_permission(self, mock_conn):
        mock_conn.exec_command.side_effect = [
            ("", "", 1),
            ("", "", 1),
        ]
        reader = CustomPathReader("/var/log/secure.log")
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "cmd", limit=10)
        )
        assert entries == []


class TestAutoLogReader:
    def test_prefers_journald(self, mock_conn):
        mock_conn.exec_command.side_effect = [
            ("", "", 1),  # JSON fails
            (JOURNAL_OUTPUT, "", 0),
        ]
        reader = AutoLogReader()
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "backup.sh", limit=10)
        )
        assert len(entries) == 2
        assert entries[0].source == "journald"

    def test_falls_back_to_syslog(self, mock_conn):
        responses = [
            ("", "", 1),  # journald JSON attempt
            ("", "", 0),  # journalctl -u cron text empty
            ("", "", 0),  # journalctl -t CROND text empty
            ("", "", 0),  # journalctl _COMM=cron text empty
            ("", "", 0),  # sudo journalctl -u cron text empty
            ("", "", 0),  # sudo journalctl -t CROND text empty
            ("", "", 0),  # sudo journalctl _COMM=cron text empty
            ("ok\n", "", 0),  # syslog: test -r /var/log/syslog
            (SYSLOG_OUTPUT, "", 0),  # syslog: grep output
        ]
        mock_conn.exec_command.side_effect = responses
        reader = AutoLogReader()
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "backup.sh", limit=10)
        )
        assert len(entries) == 2
        assert entries[0].source == "syslog"


class TestLogEntry:
    def test_status_display_success(self):
        entry = LogEntry(exit_code=0)
        assert entry.status_display == "成功"

    def test_status_display_failure(self):
        entry = LogEntry(exit_code=1)
        assert "失败" in entry.status_display
        assert "1" in entry.status_display

    def test_status_display_unknown(self):
        entry = LogEntry()
        assert entry.status_display == "未知"

    def test_duration_display_seconds(self):
        entry = LogEntry(duration_seconds=45.3)
        assert entry.duration_display == "45.3s"

    def test_duration_display_minutes(self):
        entry = LogEntry(duration_seconds=125.0)
        assert "2m" in entry.duration_display

    def test_duration_display_none(self):
        entry = LogEntry()
        assert entry.duration_display == "-"


class TestCreateLogReader:
    def test_journald(self):
        reader = create_log_reader("journald")
        assert isinstance(reader, JournaldReader)

    def test_syslog(self):
        reader = create_log_reader("syslog")
        assert isinstance(reader, SyslogReader)

    def test_custom(self):
        reader = create_log_reader("custom", "/var/log/app.log")
        assert isinstance(reader, CustomPathReader)

    def test_auto(self):
        reader = create_log_reader("auto")
        assert isinstance(reader, AutoLogReader)

    def test_unknown_defaults_to_auto(self):
        reader = create_log_reader("unknown")
        assert isinstance(reader, AutoLogReader)


class TestHelperFunctions:
    def test_safe_grep_pattern(self):
        assert _safe_grep_pattern("/usr/bin/backup.sh") == "/usr/bin/backup.sh"
        assert _safe_grep_pattern("cmd arg1 arg2") == "cmd"
        assert "'" not in _safe_grep_pattern("cmd's test")

    def test_parse_syslog_timestamp(self):
        ts = _parse_syslog_timestamp("Jun 12 09:30:01")
        assert ts is not None
        assert ts.month == 6
        assert ts.day == 12
        assert ts.hour == 9
        assert ts.minute == 30

    def test_parse_syslog_timestamp_invalid(self):
        assert _parse_syslog_timestamp("not a date") is None
