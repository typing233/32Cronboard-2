"""Tests for remote backend with mocked SSH."""

import asyncio
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cronboard.backend.remote import RemoteBackend
from cronboard.manager import ConcurrentModificationError, CrontabError
from cronboard.models import LineType
from cronboard.remote.config import ServerConfig
from cronboard.remote.connection import SSHConnectionPool


SAMPLE_CRONTAB = """\
# System backup
*/5 * * * * /usr/bin/backup.sh
0 2 * * * /usr/local/bin/cleanup.sh --force
"""


@pytest.fixture
def server_config():
    return ServerConfig(
        name="test-server",
        hostname="10.0.0.1",
        port=22,
        username="deploy",
    )


@pytest.fixture
def mock_pool():
    pool = MagicMock(spec=SSHConnectionPool)
    return pool


@pytest.fixture
def mock_conn():
    conn = MagicMock()
    conn.exec_command = AsyncMock()
    conn.write_file = AsyncMock()
    return conn


class TestRemoteBackend:
    def test_host_id(self, server_config, mock_pool):
        backend = RemoteBackend(server_config, mock_pool)
        assert backend.host_id == "test-server"

    def test_display_name(self, server_config, mock_pool):
        backend = RemoteBackend(server_config, mock_pool)
        assert "test-server" in backend.display_name
        assert "10.0.0.1" in backend.display_name

    def test_read_crontab(self, server_config, mock_pool, mock_conn):
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()
        mock_conn.exec_command.return_value = (SAMPLE_CRONTAB, "", 0)

        backend = RemoteBackend(server_config, mock_pool)
        lines = asyncio.run(backend.read_crontab())

        jobs = [l for l in lines if l.line_type == LineType.CRON_JOB]
        assert len(jobs) == 2
        assert jobs[0].command == "/usr/bin/backup.sh"
        assert jobs[0].host == "test-server"
        assert jobs[1].schedule == "0 2 * * *"

    def test_read_no_crontab(self, server_config, mock_pool, mock_conn):
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()
        mock_conn.exec_command.return_value = ("", "no crontab for user", 1)

        backend = RemoteBackend(server_config, mock_pool)
        lines = asyncio.run(backend.read_crontab())
        assert lines == []

    def test_read_error(self, server_config, mock_pool, mock_conn):
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()
        mock_conn.exec_command.return_value = ("", "permission denied", 1)

        backend = RemoteBackend(server_config, mock_pool)
        with pytest.raises(CrontabError, match="读取 crontab 失败"):
            asyncio.run(backend.read_crontab())

    def test_write_crontab_success(self, server_config, mock_pool, mock_conn):
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()

        hash_val = hashlib.sha256(SAMPLE_CRONTAB.encode()).hexdigest()

        # First call: content hash check, second: install, third: rm
        mock_conn.exec_command.side_effect = [
            (SAMPLE_CRONTAB, "", 0),  # hash check
            ("", "", 0),  # crontab install
            ("", "", 0),  # rm tmp
        ]

        backend = RemoteBackend(server_config, mock_pool)
        backend._last_hash = hash_val

        from cronboard.parser import parse_crontab

        lines = parse_crontab(SAMPLE_CRONTAB)
        asyncio.run(backend.write_crontab(lines, "test write"))

        # Verify write_file was called
        mock_conn.write_file.assert_called_once()

    def test_write_concurrent_modification(
        self, server_config, mock_pool, mock_conn
    ):
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()

        # Return different content hash
        mock_conn.exec_command.return_value = (
            "different content\n",
            "",
            0,
        )

        backend = RemoteBackend(server_config, mock_pool)
        backend._last_hash = "old_hash_that_no_longer_matches"

        from cronboard.parser import parse_crontab

        lines = parse_crontab(SAMPLE_CRONTAB)
        with pytest.raises(ConcurrentModificationError):
            asyncio.run(backend.write_crontab(lines, "test"))

    def test_write_failure_cleans_tmp(
        self, server_config, mock_pool, mock_conn
    ):
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()

        hash_val = hashlib.sha256(SAMPLE_CRONTAB.encode()).hexdigest()
        mock_conn.exec_command.side_effect = [
            (SAMPLE_CRONTAB, "", 0),  # hash check
            ("", "error: bad crontab", 1),  # crontab install fails
            ("", "", 0),  # rm tmp
        ]

        backend = RemoteBackend(server_config, mock_pool)
        backend._last_hash = hash_val

        from cronboard.parser import parse_crontab

        lines = parse_crontab(SAMPLE_CRONTAB)
        with pytest.raises(CrontabError, match="写入 crontab 失败"):
            asyncio.run(backend.write_crontab(lines, "test"))

        # Verify cleanup was called (3rd exec_command)
        assert mock_conn.exec_command.call_count == 3

    def test_test_connection_success(
        self, server_config, mock_pool, mock_conn
    ):
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()
        mock_conn.exec_command.return_value = ("ok\n", "", 0)

        backend = RemoteBackend(server_config, mock_pool)
        success, msg = asyncio.run(backend.test_connection())
        assert success is True
        assert msg == ""

    def test_test_connection_failure(
        self, server_config, mock_pool, mock_conn
    ):
        mock_pool.acquire = AsyncMock(side_effect=CrontabError("timeout"))
        mock_pool.release = AsyncMock()

        backend = RemoteBackend(server_config, mock_pool)
        success, msg = asyncio.run(backend.test_connection())
        assert success is False
        assert "timeout" in msg

    def test_sudo_user_commands(self, mock_pool):
        config = ServerConfig(
            name="db",
            hostname="db.local",
            username="admin",
            sudo_user="postgres",
        )
        backend = RemoteBackend(config, mock_pool)
        assert "sudo" in backend._crontab_list_cmd()
        assert "postgres" in backend._crontab_list_cmd()
        assert "sudo" in backend._crontab_install_cmd("/tmp/test")

    def test_get_content_hash(self, server_config, mock_pool, mock_conn):
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()
        mock_conn.exec_command.return_value = (SAMPLE_CRONTAB, "", 0)

        backend = RemoteBackend(server_config, mock_pool)
        h = asyncio.run(backend.get_content_hash())
        expected = hashlib.sha256(SAMPLE_CRONTAB.encode()).hexdigest()
        assert h == expected

    def test_export_crontab(self, server_config, mock_pool, mock_conn):
        mock_pool.acquire = AsyncMock(return_value=mock_conn)
        mock_pool.release = AsyncMock()
        mock_conn.exec_command.return_value = (SAMPLE_CRONTAB, "", 0)

        backend = RemoteBackend(server_config, mock_pool)
        text = asyncio.run(backend.export_crontab())
        assert text == SAMPLE_CRONTAB
