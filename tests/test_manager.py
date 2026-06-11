"""Tests for crontab manager operations."""

import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cronboard.manager import (
    ConcurrentModificationError,
    CrontabError,
    CrontabManager,
    WriteFailedRolledBack,
)
from cronboard.models import CrontabLine, CrontabState, LineType
from cronboard.parser import parse_crontab, serialize_crontab


SAMPLE_CRONTAB = "0 2 * * * /usr/bin/backup.sh\n*/5 * * * * /usr/bin/monitor.sh\n"


class TestManagerRead:
    """Test reading crontab."""

    @patch("cronboard.manager.subprocess.run")
    def test_read_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=SAMPLE_CRONTAB,
            stderr="",
        )
        mgr = CrontabManager()
        lines = mgr.read_crontab()
        assert len(lines) == 2
        assert lines[0].schedule == "0 2 * * *"
        assert lines[1].schedule == "*/5 * * * *"

    @patch("cronboard.manager.subprocess.run")
    def test_read_no_crontab(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="no crontab for user",
        )
        mgr = CrontabManager()
        lines = mgr.read_crontab()
        assert lines == []

    @patch("cronboard.manager.subprocess.run")
    def test_read_error(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="permission denied",
        )
        mgr = CrontabManager()
        with pytest.raises(CrontabError, match="permission denied"):
            mgr.read_crontab()

    @patch("cronboard.manager.subprocess.run")
    def test_read_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("crontab", 10)
        mgr = CrontabManager()
        with pytest.raises(CrontabError, match="超时"):
            mgr.read_crontab()


class TestManagerWrite:
    """Test writing crontab with safety features."""

    @patch("cronboard.manager.subprocess.run")
    @patch("cronboard.manager.fcntl.flock")
    def test_write_creates_backup(self, mock_flock, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout=SAMPLE_CRONTAB, stderr="")

        mgr = CrontabManager()
        mgr._last_known_text = SAMPLE_CRONTAB

        lines = parse_crontab(SAMPLE_CRONTAB)
        lines[0].enabled = False  # Make a change
        mgr.write_crontab(lines, "test write")

        assert mgr.can_undo

    @patch("cronboard.manager.subprocess.run")
    @patch("cronboard.manager.fcntl.flock")
    def test_concurrent_modification_detected(self, mock_flock, mock_run):
        mgr = CrontabManager()
        mgr._last_known_text = "old content\n"

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="modified by someone else\n",
            stderr="",
        )

        lines = parse_crontab(SAMPLE_CRONTAB)
        with pytest.raises(ConcurrentModificationError):
            mgr.write_crontab(lines)

    @patch("cronboard.manager.subprocess.run")
    @patch("cronboard.manager.fcntl.flock")
    def test_write_failure_triggers_rollback(self, mock_flock, mock_run):
        """When write fails, manager should try to rollback from backup."""
        mgr = CrontabManager()
        mgr._last_known_text = SAMPLE_CRONTAB

        write_calls = []

        def side_effect(*args, **kwargs):
            cmd = args[0]
            if cmd == ["crontab", "-l"]:
                return MagicMock(returncode=0, stdout=SAMPLE_CRONTAB, stderr="")
            if isinstance(cmd, list) and len(cmd) == 2 and cmd[0] == "crontab" and cmd[1] != "-l":
                write_calls.append(cmd[1])
                if len(write_calls) == 1:
                    # First write attempt: fail
                    return MagicMock(returncode=1, stdout="", stderr="disk full")
                else:
                    # Rollback write: succeed
                    return MagicMock(returncode=0, stdout="", stderr="")
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect

        lines = parse_crontab(SAMPLE_CRONTAB)
        lines[0].enabled = False

        with pytest.raises(WriteFailedRolledBack, match="回滚"):
            mgr.write_crontab(lines, "test")

        assert len(write_calls) == 2


class TestManagerUndoRedo:
    """Test undo/redo operations."""

    def test_undo_empty_stack(self):
        mgr = CrontabManager()
        assert mgr.undo() is None

    def test_redo_empty_stack(self):
        mgr = CrontabManager()
        assert mgr.redo() is None

    def test_can_undo_redo_flags(self):
        mgr = CrontabManager()
        assert not mgr.can_undo
        assert not mgr.can_redo

        mgr._undo_stack.append(CrontabState(
            lines=[],
            timestamp=datetime.now(),
            description="test",
        ))
        assert mgr.can_undo


class TestManagerDiff:
    """Test diff generation."""

    @patch("cronboard.manager.subprocess.run")
    def test_diff_no_changes(self, mock_run):
        mgr = CrontabManager()
        mgr._last_known_text = SAMPLE_CRONTAB

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        lines = parse_crontab(SAMPLE_CRONTAB)
        diff = mgr.get_diff(lines)
        assert diff == "无变更"

    @patch("cronboard.manager.subprocess.run")
    def test_diff_with_changes(self, mock_run):
        mgr = CrontabManager()
        mgr._last_known_text = SAMPLE_CRONTAB

        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="--- 当前\n+++ 修改后\n@@ -1 +1 @@\n-old\n+new\n",
            stderr="",
        )

        lines = parse_crontab("0 3 * * * /new/cmd\n")
        diff = mgr.get_diff(lines)
        assert "---" in diff


class TestManagerExportImport:
    """Test export/import operations."""

    def test_export_import_round_trip(self, tmp_path):
        export_file = tmp_path / "export.txt"
        export_file.write_text(SAMPLE_CRONTAB)

        mgr = CrontabManager()
        lines = mgr.import_crontab(str(export_file))
        assert len(lines) == 2
        assert lines[0].schedule == "0 2 * * *"

    def test_import_nonexistent(self):
        mgr = CrontabManager()
        with pytest.raises(CrontabError, match="不存在"):
            mgr.import_crontab("/nonexistent/file.txt")

    @patch("cronboard.manager.subprocess.run")
    def test_export(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=SAMPLE_CRONTAB,
            stderr="",
        )
        mgr = CrontabManager()
        export_path = tmp_path / "out.txt"
        mgr.export_crontab(str(export_path))
        assert export_path.read_text() == SAMPLE_CRONTAB


class TestManagerBackups:
    """Test backup management."""

    def test_list_backups_empty(self, tmp_path):
        with patch("cronboard.manager.BACKUP_DIR", tmp_path / "backups"):
            mgr = CrontabManager()
            assert mgr.list_backups() == []

    def test_list_backups(self, tmp_path):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        (backup_dir / "crontab_20240101_120000.bak").write_text("test")
        (backup_dir / "crontab_20240102_120000.bak").write_text("test2")

        with patch("cronboard.manager.BACKUP_DIR", backup_dir):
            mgr = CrontabManager()
            backups = mgr.list_backups()
            assert len(backups) == 2
            # Newest first
            assert "20240102" in backups[0].name

    def test_get_backup_preview(self, tmp_path):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        bak = backup_dir / "crontab_20240101_120000.bak"
        bak.write_text(SAMPLE_CRONTAB)

        with patch("cronboard.manager.BACKUP_DIR", backup_dir):
            mgr = CrontabManager()
            content = mgr.get_backup_preview(bak)
            assert content == SAMPLE_CRONTAB

    def test_backup_created_on_write_returns_path(self, tmp_path):
        with patch("cronboard.manager.BACKUP_DIR", tmp_path):
            mgr = CrontabManager()
            path = mgr._create_backup("test content\n")
            assert path.exists()
            assert path.read_text() == "test content\n"
