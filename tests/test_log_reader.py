"""Tests for log reader implementations."""

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
)


@pytest.fixture
def mock_conn():
    conn = MagicMock()
    conn.exec_command = AsyncMock()
    return conn


SYSLOG_OUTPUT = """\
Jun 12 09:30:01 web-01 CRON[12345]: (root) CMD (/usr/bin/backup.sh)
Jun 12 10:00:01 web-01 CRON[12400]: (root) CMD (/usr/bin/backup.sh)
Jun 12 10:30:01 web-01 CRON[12500]: (root) CMD (/usr/bin/backup.sh)
"""

JOURNAL_OUTPUT = """\
Jun 12 09:30:01.123456 web-01 CRON[12345]: (root) CMD (/usr/bin/backup.sh)
Jun 12 10:00:01.654321 web-01 CRON[12400]: (root) CMD (/usr/bin/backup.sh)
"""


class TestSyslogReader:
    def test_fetch_logs_success(self, mock_conn):
        # First call: test -r /var/log/syslog => ok
        # Second call: grep output
        mock_conn.exec_command.side_effect = [
            ("ok\n", "", 0),  # test -r succeeds
            (SYSLOG_OUTPUT, "", 0),  # grep output
        ]
        reader = SyslogReader()
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "/usr/bin/backup.sh", limit=10)
        )
        assert len(entries) == 3
        assert entries[0].source == "syslog"
        assert entries[0].user == "root"
        assert entries[0].command == "/usr/bin/backup.sh"
        assert entries[0].pid == 12345

    def test_fetch_logs_no_file(self, mock_conn):
        # All file checks fail
        mock_conn.exec_command.return_value = ("", "", 1)
        reader = SyslogReader()
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "test-cmd", limit=10)
        )
        assert entries == []

    def test_fetch_logs_with_sudo(self, mock_conn):
        # Normal reads fail, sudo succeeds
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
        assert len(entries) == 3


class TestJournaldReader:
    def test_fetch_logs_success(self, mock_conn):
        mock_conn.exec_command.side_effect = [
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
            ("", "", 0),  # journalctl -u cron empty
            ("", "", 0),  # journalctl -t CROND empty
            ("", "", 0),  # journalctl _COMM=cron empty
            ("", "", 0),  # sudo journalctl empty
        ]
        reader = JournaldReader()
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "test-cmd", limit=10)
        )
        assert entries == []


class TestCustomPathReader:
    def test_fetch_logs_success(self, mock_conn):
        custom_output = "2024-06-15 10:00:00 [INFO] backup.sh completed\n"
        mock_conn.exec_command.side_effect = [
            ("ok\n", "", 0),  # test -r
            (custom_output, "", 0),  # tail + grep
        ]
        reader = CustomPathReader("/var/log/app/cron.log")
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "backup.sh", limit=10)
        )
        assert len(entries) == 1
        assert entries[0].source == "custom"

    def test_fetch_logs_no_permission(self, mock_conn):
        mock_conn.exec_command.side_effect = [
            ("", "", 1),  # test -r fails
            ("", "", 1),  # sudo test -r fails
        ]
        reader = CustomPathReader("/var/log/secure.log")
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "cmd", limit=10)
        )
        assert entries == []


class TestAutoLogReader:
    def test_prefers_journald(self, mock_conn):
        mock_conn.exec_command.side_effect = [
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
            ("", "", 0),  # journalctl -u cron empty
            ("", "", 0),  # journalctl -t CROND empty
            ("", "", 0),  # journalctl _COMM=cron empty
            ("", "", 0),  # sudo journalctl empty
            ("ok\n", "", 0),  # test -r /var/log/syslog
            (SYSLOG_OUTPUT, "", 0),  # grep
        ]
        mock_conn.exec_command.side_effect = responses
        reader = AutoLogReader()
        entries = asyncio.run(
            reader.fetch_logs(mock_conn, "backup.sh", limit=10)
        )
        assert len(entries) == 3
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
