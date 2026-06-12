"""Remote backend implementing crontab operations over SSH."""

from __future__ import annotations

import hashlib
import time

from .base import CrontabBackend
from ..manager import ConcurrentModificationError, CrontabError
from ..models import CrontabLine, LineType
from ..parser import parse_crontab, serialize_crontab
from ..remote.config import ServerConfig
from ..remote.connection import SSHConnection, SSHConnectionPool


class RemoteBackend(CrontabBackend):
    """Manages crontab on a remote host via SSH."""

    def __init__(self, config: ServerConfig, pool: SSHConnectionPool):
        self._config = config
        self._pool = pool
        self._last_hash: str | None = None

    @property
    def host_id(self) -> str:
        return self._config.name

    @property
    def display_name(self) -> str:
        return f"{self._config.name} ({self._config.hostname})"

    @property
    def config(self) -> ServerConfig:
        return self._config

    async def read_crontab(self) -> list[CrontabLine]:
        conn = await self._pool.acquire(self._config)
        try:
            cmd = self._crontab_list_cmd()
            stdout, stderr, rc = await conn.exec_command(cmd)

            if rc != 0:
                if "no crontab for" in stderr.lower():
                    self._last_hash = hashlib.sha256(b"").hexdigest()
                    return []
                raise CrontabError(
                    f"[{self.host_id}] 读取 crontab 失败: {stderr.strip()}"
                )

            self._last_hash = hashlib.sha256(stdout.encode()).hexdigest()
            lines = parse_crontab(stdout)
            self._update_runtime_info(lines)
            for line in lines:
                line.host = self.host_id
            return lines
        finally:
            await self._pool.release(conn)

    async def write_crontab(
        self, lines: list[CrontabLine], description: str = ""
    ) -> None:
        conn = await self._pool.acquire(self._config)
        try:
            # Concurrent modification check
            current_hash = await self._remote_content_hash(conn)
            if self._last_hash and current_hash != self._last_hash:
                raise ConcurrentModificationError(
                    f"[{self.host_id}] crontab 已被外部修改，请重新加载后再操作"
                )

            new_text = serialize_crontab(lines)
            tmp_path = f"/tmp/cronboard_{self._config.name}_{int(time.time())}.tmp"

            # Write temp file on remote via SFTP
            await conn.write_file(tmp_path, new_text)

            # Atomic crontab install
            cmd = self._crontab_install_cmd(tmp_path)
            _, stderr, rc = await conn.exec_command(cmd)

            if rc != 0:
                # Clean up temp file
                await conn.exec_command(f"rm -f {tmp_path}")
                raise CrontabError(
                    f"[{self.host_id}] 写入 crontab 失败: {stderr.strip()}"
                )

            # Success: clean temp, update hash
            await conn.exec_command(f"rm -f {tmp_path}")
            self._last_hash = hashlib.sha256(new_text.encode()).hexdigest()
        finally:
            await self._pool.release(conn)

    async def get_content_hash(self) -> str:
        conn = await self._pool.acquire(self._config)
        try:
            return await self._remote_content_hash(conn)
        finally:
            await self._pool.release(conn)

    async def test_connection(self) -> tuple[bool, str]:
        try:
            conn = await self._pool.acquire(self._config)
            try:
                stdout, _, rc = await conn.exec_command("echo ok", timeout=10)
                if rc == 0 and "ok" in stdout:
                    return (True, "")
                return (False, "连接测试命令失败")
            finally:
                await self._pool.release(conn)
        except CrontabError as e:
            return (False, str(e))

    async def close(self) -> None:
        pass

    async def export_crontab(self) -> str:
        """Export raw crontab text from remote."""
        conn = await self._pool.acquire(self._config)
        try:
            cmd = self._crontab_list_cmd()
            stdout, stderr, rc = await conn.exec_command(cmd)
            if rc != 0:
                if "no crontab for" in stderr.lower():
                    return ""
                raise CrontabError(
                    f"[{self.host_id}] 导出失败: {stderr.strip()}"
                )
            return stdout
        finally:
            await self._pool.release(conn)

    async def import_crontab(self, text: str) -> list[CrontabLine]:
        """Parse imported text without writing. Returns parsed lines."""
        lines = parse_crontab(text)
        for line in lines:
            line.host = self.host_id
        return lines

    def _crontab_list_cmd(self) -> str:
        if self._config.sudo_user:
            return f"sudo -n -u {self._config.sudo_user} crontab -l"
        return "crontab -l"

    def _crontab_install_cmd(self, path: str) -> str:
        if self._config.sudo_user:
            return f"sudo -n -u {self._config.sudo_user} crontab {path}"
        return f"crontab {path}"

    async def _remote_content_hash(self, conn: SSHConnection) -> str:
        cmd = self._crontab_list_cmd()
        stdout, stderr, rc = await conn.exec_command(cmd)
        if rc != 0:
            if "no crontab for" in stderr.lower():
                return hashlib.sha256(b"").hexdigest()
            raise CrontabError(
                f"[{self.host_id}] 读取失败: {stderr.strip()}"
            )
        return hashlib.sha256(stdout.encode()).hexdigest()

    def _update_runtime_info(self, lines: list[CrontabLine]) -> None:
        """Update next/prev run times for remote lines."""
        from datetime import datetime

        from ..cron_expr import get_next_run, get_prev_run

        now = datetime.now()
        for line in lines:
            if line.line_type != LineType.CRON_JOB or not line.schedule:
                continue
            if line.enabled:
                line.next_run = get_next_run(line.schedule, now)
                line.last_run = get_prev_run(line.schedule, now)
