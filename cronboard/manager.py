"""Crontab manager with locking, atomic writes, and backup/rollback."""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .cron_expr import get_next_run, get_prev_run
from .models import CrontabLine, CrontabState, LineType
from .parser import parse_crontab, serialize_crontab


BACKUP_DIR = Path.home() / ".local" / "share" / "cronboard" / "backups"
MAX_BACKUPS = 50
LOCK_PATH = Path(tempfile.gettempdir()) / "cronboard.lock"


class CrontabError(Exception):
    """Base exception for crontab operations."""
    pass


class PermissionError_(CrontabError):
    pass


class ConcurrentModificationError(CrontabError):
    pass


class WriteFailedRolledBack(CrontabError):
    """Write failed but was successfully rolled back from backup."""
    pass


class CrontabManager:
    """Manages the user's crontab with safety features."""

    def __init__(self):
        self._undo_stack: list[CrontabState] = []
        self._redo_stack: list[CrontabState] = []
        self._last_known_text: Optional[str] = None
        self._lock_fd: Optional[int] = None
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    def read_crontab(self) -> list[CrontabLine]:
        """Read current user crontab."""
        try:
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                if "no crontab for" in result.stderr.lower():
                    self._last_known_text = ""
                    return []
                raise CrontabError(f"读取 crontab 失败: {result.stderr.strip()}")
            text = result.stdout
        except subprocess.TimeoutExpired:
            raise CrontabError("读取 crontab 超时")
        except FileNotFoundError:
            raise CrontabError("未找到 crontab 命令")

        self._last_known_text = text
        lines = parse_crontab(text)
        self._update_runtime_info(lines)
        return lines

    def write_crontab(self, lines: list[CrontabLine], description: str = "") -> None:
        """Write crontab atomically with locking, backup, and auto-rollback on failure."""
        new_text = serialize_crontab(lines)
        backup_path: Optional[Path] = None

        self._acquire_lock()
        try:
            self._check_concurrent_modification()

            # Create backup before writing
            if self._last_known_text is not None:
                backup_path = self._create_backup(self._last_known_text)
                self._undo_stack.append(CrontabState(
                    lines=parse_crontab(self._last_known_text),
                    timestamp=datetime.now(),
                    description=description or "修改 crontab",
                ))
                self._redo_stack.clear()

            # Attempt atomic write
            try:
                self._atomic_write(new_text)
                self._last_known_text = new_text
            except CrontabError as write_err:
                # Write failed — attempt rollback from backup
                if backup_path and backup_path.exists():
                    rollback_text = backup_path.read_text(encoding="utf-8")
                    try:
                        self._atomic_write(rollback_text)
                        self._last_known_text = rollback_text
                        # Remove the undo entry we just added since write failed
                        if self._undo_stack:
                            self._undo_stack.pop()
                        raise WriteFailedRolledBack(
                            f"写入失败已自动回滚: {write_err}"
                        ) from write_err
                    except WriteFailedRolledBack:
                        raise
                    except CrontabError:
                        pass
                raise
        finally:
            self._release_lock()

    def undo(self) -> Optional[list[CrontabLine]]:
        """Undo last change. Returns new state or None if nothing to undo."""
        if not self._undo_stack:
            return None

        current_text = self._read_raw_crontab()
        self._redo_stack.append(CrontabState(
            lines=parse_crontab(current_text),
            timestamp=datetime.now(),
            description="撤销前状态",
        ))

        prev_state = self._undo_stack.pop()
        prev_text = prev_state.to_text()

        self._acquire_lock()
        try:
            self._atomic_write(prev_text)
            self._last_known_text = prev_text
        finally:
            self._release_lock()

        lines = parse_crontab(prev_text)
        self._update_runtime_info(lines)
        return lines

    def redo(self) -> Optional[list[CrontabLine]]:
        """Redo last undone change."""
        if not self._redo_stack:
            return None

        current_text = self._read_raw_crontab()
        self._undo_stack.append(CrontabState(
            lines=parse_crontab(current_text),
            timestamp=datetime.now(),
            description="重做前状态",
        ))

        next_state = self._redo_stack.pop()
        next_text = next_state.to_text()

        self._acquire_lock()
        try:
            self._atomic_write(next_text)
            self._last_known_text = next_text
        finally:
            self._release_lock()

        lines = parse_crontab(next_text)
        self._update_runtime_info(lines)
        return lines

    def get_diff(self, new_lines: list[CrontabLine]) -> str:
        """Get diff between current crontab and proposed changes."""
        current = self._last_known_text or ""
        proposed = serialize_crontab(new_lines)

        if current == proposed:
            return "无变更"

        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".old", delete=False) as f1:
                f1.write(current)
                old_path = f1.name
            with tempfile.NamedTemporaryFile(mode="w", suffix=".new", delete=False) as f2:
                f2.write(proposed)
                new_path = f2.name

            result = subprocess.run(
                ["diff", "-u", "--label=当前", old_path, "--label=修改后", new_path],
                capture_output=True,
                text=True,
            )
            return result.stdout if result.stdout else "无变更"
        finally:
            for p in [old_path, new_path]:
                try:
                    os.unlink(p)
                except OSError:
                    pass

    def export_crontab(self, path: str) -> None:
        """Export current crontab to a file."""
        text = self._read_raw_crontab()
        Path(path).write_text(text, encoding="utf-8")

    def import_crontab(self, path: str) -> list[CrontabLine]:
        """Import crontab from file (does not write, returns parsed lines)."""
        file_path = Path(path)
        if not file_path.exists():
            raise CrontabError(f"文件不存在: {path}")
        text = file_path.read_text(encoding="utf-8")
        return parse_crontab(text)

    def list_backups(self) -> list[Path]:
        """List available backups sorted by time (newest first)."""
        if not BACKUP_DIR.exists():
            return []
        backups = sorted(BACKUP_DIR.glob("crontab_*.bak"), reverse=True)
        return backups

    def restore_backup(self, backup_path: Path) -> list[CrontabLine]:
        """Restore from a backup file."""
        if not backup_path.exists():
            raise CrontabError(f"备份文件不存在: {backup_path}")
        text = backup_path.read_text(encoding="utf-8")
        lines = parse_crontab(text)
        self.write_crontab(lines, description=f"从备份恢复: {backup_path.name}")
        return lines

    def get_backup_preview(self, backup_path: Path) -> str:
        """Get the content of a backup file for preview."""
        if not backup_path.exists():
            raise CrontabError(f"备份文件不存在: {backup_path}")
        return backup_path.read_text(encoding="utf-8")

    def check_running(self, lines: list[CrontabLine]) -> None:
        """Check which cron jobs are currently running."""
        try:
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return
            ps_output = result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return

        for line in lines:
            if line.line_type != LineType.CRON_JOB or not line.command:
                continue
            cmd_fragment = line.command.split()[0] if line.command.split() else ""
            if cmd_fragment and cmd_fragment in ps_output:
                line.is_running = True
            else:
                line.is_running = False

    def _update_runtime_info(self, lines: list[CrontabLine]) -> None:
        """Update next/prev run times and running status."""
        now = datetime.now()
        for line in lines:
            if line.line_type != LineType.CRON_JOB or not line.schedule:
                continue
            if line.enabled:
                line.next_run = get_next_run(line.schedule, now)
                line.last_run = get_prev_run(line.schedule, now)
        self.check_running(lines)

    def _acquire_lock(self) -> None:
        """Acquire file lock for crontab operations."""
        try:
            self._lock_fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_RDWR)
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if self._lock_fd is not None:
                os.close(self._lock_fd)
                self._lock_fd = None
            raise CrontabError("另一个 cronboard 实例正在运行，无法获取锁")
        except PermissionError:
            raise PermissionError_("无权限创建锁文件")

    def _release_lock(self) -> None:
        """Release file lock."""
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

    def _check_concurrent_modification(self) -> None:
        """Check if crontab was modified externally since last read."""
        if self._last_known_text is None:
            return
        current = self._read_raw_crontab()
        if current != self._last_known_text:
            raise ConcurrentModificationError(
                "crontab 已被外部修改。请重新加载后再操作。"
            )

    def _read_raw_crontab(self) -> str:
        """Read raw crontab text."""
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            if "no crontab for" in result.stderr.lower():
                return ""
            raise CrontabError(f"读取 crontab 失败: {result.stderr.strip()}")
        return result.stdout

    def _atomic_write(self, text: str) -> None:
        """Atomically write crontab using temp file."""
        tmp_fd = None
        tmp_path = None
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(prefix="cronboard_", suffix=".tmp")
            os.write(tmp_fd, text.encode("utf-8"))
            os.close(tmp_fd)
            tmp_fd = None

            result = subprocess.run(
                ["crontab", tmp_path],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                raise CrontabError(f"写入 crontab 失败: {result.stderr.strip()}")
        except PermissionError:
            raise PermissionError_("无权限写入 crontab")
        finally:
            if tmp_fd is not None:
                os.close(tmp_fd)
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _create_backup(self, text: str) -> Path:
        """Create a timestamped backup. Returns the backup path."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"crontab_{timestamp}.bak"
        backup_path.write_text(text, encoding="utf-8")

        # Prune old backups
        backups = sorted(BACKUP_DIR.glob("crontab_*.bak"))
        while len(backups) > MAX_BACKUPS:
            backups[0].unlink()
            backups.pop(0)

        return backup_path

    @property
    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    @property
    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0
