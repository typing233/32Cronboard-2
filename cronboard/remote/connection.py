"""SSH connection pool with Paramiko."""

from __future__ import annotations

import asyncio
from typing import Optional

import paramiko

from ..manager import CrontabError
from .config import ServerConfig


class SSHConnection:
    """Wraps a Paramiko SSHClient with async execution."""

    def __init__(self, client: paramiko.SSHClient, config: ServerConfig):
        self._client = client
        self._config = config
        self._in_use = False
        self._jump_client: Optional[paramiko.SSHClient] = None

    async def exec_command(
        self, cmd: str, timeout: int = 30
    ) -> tuple[str, str, int]:
        """Execute command, return (stdout, stderr, return_code)."""

        def _run():
            _, stdout, stderr = self._client.exec_command(cmd, timeout=timeout)
            rc = stdout.channel.recv_exit_status()
            return stdout.read().decode("utf-8"), stderr.read().decode("utf-8"), rc

        return await asyncio.to_thread(_run)

    async def write_file(self, remote_path: str, content: str) -> None:
        """Write content to a file on the remote host via SFTP."""

        def _write():
            sftp = self._client.open_sftp()
            try:
                with sftp.open(remote_path, "w") as f:
                    f.write(content)
            finally:
                sftp.close()

        await asyncio.to_thread(_write)

    def is_alive(self) -> bool:
        transport = self._client.get_transport()
        return transport is not None and transport.is_active()

    def close(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
        if self._jump_client:
            try:
                self._jump_client.close()
            except Exception:
                pass


class SSHConnectionPool:
    """Connection pool keyed by server name."""

    def __init__(self, max_per_host: int = 2):
        self._pools: dict[str, list[SSHConnection]] = {}
        self._max_per_host = max_per_host
        self._lock = asyncio.Lock()

    async def acquire(self, config: ServerConfig) -> SSHConnection:
        async with self._lock:
            pool = self._pools.setdefault(config.name, [])

            for conn in pool:
                if not conn._in_use and conn.is_alive():
                    conn._in_use = True
                    return conn

            # Remove dead connections
            self._pools[config.name] = [c for c in pool if c.is_alive()]
            pool = self._pools[config.name]

            if len(pool) < self._max_per_host:
                conn = await self._create_connection(config)
                conn._in_use = True
                pool.append(conn)
                return conn

            raise CrontabError(f"连接池已满: {config.name}")

    async def release(self, conn: SSHConnection) -> None:
        conn._in_use = False

    async def _create_connection(self, config: ServerConfig) -> SSHConnection:
        def _connect() -> SSHConnection:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs: dict = {
                "hostname": config.hostname,
                "port": config.port,
                "username": config.username,
                "timeout": config.connect_timeout,
            }

            # Authentication
            if config.private_key_path:
                key_path = str(config.private_key_path)
                try:
                    pkey = paramiko.Ed25519Key.from_private_key_file(
                        key_path, password=config.passphrase
                    )
                except (paramiko.SSHException, ValueError):
                    try:
                        pkey = paramiko.RSAKey.from_private_key_file(
                            key_path, password=config.passphrase
                        )
                    except (paramiko.SSHException, ValueError):
                        pkey = paramiko.ECDSAKey.from_private_key_file(
                            key_path, password=config.passphrase
                        )
                connect_kwargs["pkey"] = pkey
            elif config.password:
                connect_kwargs["password"] = config.password

            jump_client: Optional[paramiko.SSHClient] = None

            # Jump host (ProxyJump)
            if config.jump_host:
                jump_client = paramiko.SSHClient()
                jump_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

                jump_kwargs: dict = {
                    "hostname": config.jump_host.hostname,
                    "port": config.jump_host.port,
                    "username": config.jump_host.username or config.username,
                    "timeout": config.connect_timeout,
                }
                if config.jump_host.private_key_path:
                    jump_kwargs["key_filename"] = str(
                        config.jump_host.private_key_path
                    )

                jump_client.connect(**jump_kwargs)
                transport = jump_client.get_transport()
                channel = transport.open_channel(
                    "direct-tcpip",
                    (config.hostname, config.port),
                    ("127.0.0.1", 0),
                )
                connect_kwargs["sock"] = channel

            client.connect(**connect_kwargs)
            conn = SSHConnection(client, config)
            conn._jump_client = jump_client
            return conn

        try:
            return await asyncio.to_thread(_connect)
        except paramiko.AuthenticationException as e:
            raise CrontabError(f"[{config.name}] 认证失败: {e}")
        except paramiko.SSHException as e:
            raise CrontabError(f"[{config.name}] SSH连接错误: {e}")
        except OSError as e:
            raise CrontabError(f"[{config.name}] 网络连接失败: {e}")

    async def close_all(self) -> None:
        for pool in self._pools.values():
            for conn in pool:
                conn.close()
        self._pools.clear()
