"""Tests for local backend."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from cronboard.backend.local import LocalBackend
from cronboard.models import LineType


SAMPLE_CRONTAB = """\
# test
*/5 * * * * /usr/bin/test.sh
"""


class TestLocalBackend:
    def test_host_id(self):
        backend = LocalBackend()
        assert backend.host_id == "localhost"

    def test_display_name(self):
        backend = LocalBackend()
        assert "localhost" in backend.display_name

    @patch("cronboard.manager.subprocess.run")
    def test_read_crontab(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout=SAMPLE_CRONTAB, stderr=""
        )
        backend = LocalBackend()
        lines = asyncio.run(backend.read_crontab())

        jobs = [l for l in lines if l.line_type == LineType.CRON_JOB]
        assert len(jobs) == 1
        assert jobs[0].command == "/usr/bin/test.sh"
        assert jobs[0].host == "localhost"

    def test_test_connection(self):
        backend = LocalBackend()
        success, msg = asyncio.run(backend.test_connection())
        assert success is True

    @patch("cronboard.manager.subprocess.run")
    def test_get_content_hash(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout=SAMPLE_CRONTAB, stderr=""
        )
        backend = LocalBackend()
        h = asyncio.run(backend.get_content_hash())
        assert len(h) == 64  # sha256 hex

    def test_manager_accessible(self):
        backend = LocalBackend()
        assert backend.manager is not None
