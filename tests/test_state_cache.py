"""Tests for state cache."""

import time

import pytest

from cronboard.cache.state_cache import CrontabStateCache
from cronboard.models import CrontabLine, LineType


def _make_line(command: str, host: str = "localhost") -> CrontabLine:
    line = CrontabLine(
        raw=f"* * * * * {command}",
        line_type=LineType.CRON_JOB,
        line_number=1,
        schedule="* * * * *",
        command=command,
        host=host,
    )
    return line


class TestStateCache:
    def test_put_and_get(self):
        cache = CrontabStateCache(ttl_seconds=60)
        lines = [_make_line("/usr/bin/backup.sh")]
        cache.put("web-01", lines, "abc123")

        result = cache.get("web-01")
        assert result is not None
        assert len(result) == 1
        assert result[0].command == "/usr/bin/backup.sh"

    def test_get_nonexistent(self):
        cache = CrontabStateCache(ttl_seconds=60)
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        cache = CrontabStateCache(ttl_seconds=1)
        lines = [_make_line("/bin/test")]
        cache.put("host-01", lines, "hash1")

        assert cache.get("host-01") is not None

        # Simulate expiry
        cache._cache["host-01"].fetched_at = time.time() - 2
        assert cache.get("host-01") is None

    def test_invalidate(self):
        cache = CrontabStateCache(ttl_seconds=60)
        cache.put("host-01", [_make_line("cmd1")], "h1")
        cache.put("host-02", [_make_line("cmd2")], "h2")

        cache.invalidate("host-01")
        assert cache.get("host-01") is None
        assert cache.get("host-02") is not None

    def test_invalidate_all(self):
        cache = CrontabStateCache(ttl_seconds=60)
        cache.put("host-01", [_make_line("cmd1")], "h1")
        cache.put("host-02", [_make_line("cmd2")], "h2")

        cache.invalidate_all()
        assert cache.get("host-01") is None
        assert cache.get("host-02") is None

    def test_get_hash(self):
        cache = CrontabStateCache(ttl_seconds=60)
        cache.put("web-01", [_make_line("cmd")], "myhash123")
        assert cache.get_hash("web-01") == "myhash123"

    def test_get_hash_expired(self):
        cache = CrontabStateCache(ttl_seconds=1)
        cache.put("web-01", [_make_line("cmd")], "myhash123")
        cache._cache["web-01"].fetched_at = time.time() - 2
        assert cache.get_hash("web-01") is None

    def test_is_cached(self):
        cache = CrontabStateCache(ttl_seconds=60)
        assert cache.is_cached("foo") is False
        cache.put("foo", [], "h")
        assert cache.is_cached("foo") is True

    def test_overwrite(self):
        cache = CrontabStateCache(ttl_seconds=60)
        cache.put("host", [_make_line("old")], "h1")
        cache.put("host", [_make_line("new")], "h2")

        result = cache.get("host")
        assert result is not None
        assert result[0].command == "new"
        assert cache.get_hash("host") == "h2"
