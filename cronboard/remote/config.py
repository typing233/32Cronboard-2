"""Server configuration dataclass and YAML loader."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Optional

import yaml


CONFIG_PATH = Path.home() / ".config" / "cronboard" / "servers.yaml"


@dataclasses.dataclass
class JumpHostConfig:
    """SSH jump host (bastion) configuration."""

    hostname: str
    port: int = 22
    username: Optional[str] = None
    private_key_path: Optional[Path] = None


@dataclasses.dataclass
class ServerConfig:
    """Remote server connection configuration."""

    name: str
    hostname: str
    port: int = 22
    username: str = "root"
    password: Optional[str] = None
    private_key_path: Optional[Path] = None
    passphrase: Optional[str] = None
    jump_host: Optional[JumpHostConfig] = None
    sudo_user: Optional[str] = None
    connect_timeout: int = 10
    log_source: str = "auto"
    custom_log_path: Optional[str] = None
    tags: list[str] = dataclasses.field(default_factory=list)


def load_server_configs(path: Optional[Path] = None) -> list[ServerConfig]:
    """Load server configurations from YAML file."""
    if path is None:
        path = CONFIG_PATH
    if not path.exists():
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or "servers" not in data:
        return []

    defaults = data.get("defaults", {})
    default_port = defaults.get("port", 22)
    default_timeout = defaults.get("connect_timeout", 10)
    default_log_source = defaults.get("log_source", "auto")

    configs: list[ServerConfig] = []
    for entry in data["servers"]:
        if not entry.get("name") or not entry.get("hostname"):
            continue

        jump = None
        if "jump_host" in entry:
            jh = entry["jump_host"]
            jump = JumpHostConfig(
                hostname=jh["hostname"],
                port=jh.get("port", 22),
                username=jh.get("username"),
                private_key_path=Path(jh["private_key_path"]).expanduser()
                if jh.get("private_key_path")
                else None,
            )

        configs.append(
            ServerConfig(
                name=entry["name"],
                hostname=entry["hostname"],
                port=entry.get("port", default_port),
                username=entry.get("username", "root"),
                password=entry.get("password"),
                private_key_path=Path(entry["private_key_path"]).expanduser()
                if entry.get("private_key_path")
                else None,
                passphrase=entry.get("passphrase"),
                jump_host=jump,
                sudo_user=entry.get("sudo_user"),
                connect_timeout=entry.get("connect_timeout", default_timeout),
                log_source=entry.get("log_source", default_log_source),
                custom_log_path=entry.get("custom_log_path"),
                tags=entry.get("tags", []),
            )
        )

    return configs
