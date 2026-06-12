"""Tests for remote server configuration loading."""

import tempfile
from pathlib import Path

import pytest
import yaml

from cronboard.remote.config import (
    JumpHostConfig,
    ServerConfig,
    load_server_configs,
)


class TestServerConfig:
    def test_minimal_config(self, tmp_path):
        config_file = tmp_path / "servers.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "servers": [
                        {"name": "web-01", "hostname": "192.168.1.10"}
                    ]
                }
            )
        )
        configs = load_server_configs(config_file)
        assert len(configs) == 1
        assert configs[0].name == "web-01"
        assert configs[0].hostname == "192.168.1.10"
        assert configs[0].port == 22
        assert configs[0].username == "root"
        assert configs[0].password is None
        assert configs[0].private_key_path is None
        assert configs[0].jump_host is None
        assert configs[0].sudo_user is None
        assert configs[0].log_source == "auto"

    def test_full_config(self, tmp_path):
        config_file = tmp_path / "servers.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "defaults": {"port": 2222, "connect_timeout": 15},
                    "servers": [
                        {
                            "name": "db-master",
                            "hostname": "db.example.com",
                            "port": 5022,
                            "username": "admin",
                            "private_key_path": "~/.ssh/id_rsa",
                            "passphrase": "secret",
                            "sudo_user": "postgres",
                            "connect_timeout": 20,
                            "log_source": "journald",
                            "custom_log_path": "/var/log/app.log",
                            "tags": ["production", "database"],
                        }
                    ],
                }
            )
        )
        configs = load_server_configs(config_file)
        assert len(configs) == 1
        c = configs[0]
        assert c.name == "db-master"
        assert c.hostname == "db.example.com"
        assert c.port == 5022
        assert c.username == "admin"
        assert c.passphrase == "secret"
        assert c.sudo_user == "postgres"
        assert c.connect_timeout == 20
        assert c.log_source == "journald"
        assert c.custom_log_path == "/var/log/app.log"
        assert c.tags == ["production", "database"]
        assert c.private_key_path == Path.home() / ".ssh" / "id_rsa"

    def test_jump_host_config(self, tmp_path):
        config_file = tmp_path / "servers.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "servers": [
                        {
                            "name": "internal",
                            "hostname": "10.0.5.20",
                            "username": "ubuntu",
                            "jump_host": {
                                "hostname": "bastion.example.com",
                                "port": 2222,
                                "username": "jump-user",
                                "private_key_path": "~/.ssh/bastion_key",
                            },
                        }
                    ]
                }
            )
        )
        configs = load_server_configs(config_file)
        assert len(configs) == 1
        c = configs[0]
        assert c.jump_host is not None
        assert c.jump_host.hostname == "bastion.example.com"
        assert c.jump_host.port == 2222
        assert c.jump_host.username == "jump-user"
        assert c.jump_host.private_key_path == Path.home() / ".ssh" / "bastion_key"

    def test_empty_file(self, tmp_path):
        config_file = tmp_path / "servers.yaml"
        config_file.write_text("")
        configs = load_server_configs(config_file)
        assert configs == []

    def test_missing_file(self, tmp_path):
        config_file = tmp_path / "nonexistent.yaml"
        configs = load_server_configs(config_file)
        assert configs == []

    def test_no_servers_key(self, tmp_path):
        config_file = tmp_path / "servers.yaml"
        config_file.write_text(yaml.dump({"version": 1}))
        configs = load_server_configs(config_file)
        assert configs == []

    def test_invalid_entry_skipped(self, tmp_path):
        config_file = tmp_path / "servers.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "servers": [
                        {"name": "valid", "hostname": "1.2.3.4"},
                        {"name": "no-host"},  # Missing hostname
                        {"hostname": "no-name.com"},  # Missing name
                    ]
                }
            )
        )
        configs = load_server_configs(config_file)
        assert len(configs) == 1
        assert configs[0].name == "valid"

    def test_defaults_applied(self, tmp_path):
        config_file = tmp_path / "servers.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "defaults": {
                        "port": 3022,
                        "connect_timeout": 30,
                        "log_source": "syslog",
                    },
                    "servers": [
                        {"name": "s1", "hostname": "host1.com"},
                        {"name": "s2", "hostname": "host2.com", "port": 22},
                    ],
                }
            )
        )
        configs = load_server_configs(config_file)
        assert configs[0].port == 3022
        assert configs[0].connect_timeout == 30
        assert configs[0].log_source == "syslog"
        assert configs[1].port == 22  # Overridden

    def test_multiple_servers(self, tmp_path):
        config_file = tmp_path / "servers.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "servers": [
                        {"name": f"server-{i}", "hostname": f"10.0.0.{i}"}
                        for i in range(5)
                    ]
                }
            )
        )
        configs = load_server_configs(config_file)
        assert len(configs) == 5

    def test_password_auth(self, tmp_path):
        config_file = tmp_path / "servers.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "servers": [
                        {
                            "name": "legacy",
                            "hostname": "old-server.local",
                            "username": "root",
                            "password": "hunter2",
                        }
                    ]
                }
            )
        )
        configs = load_server_configs(config_file)
        assert configs[0].password == "hunter2"
        assert configs[0].private_key_path is None
