"""Tests for tag store."""

import asyncio
from pathlib import Path

import pytest

from cronboard.metadata.tags import TagStore


@pytest.fixture
def tag_store(tmp_path):
    db_path = tmp_path / "test_tags.db"
    return TagStore(db_path=db_path)


class TestTagStore:
    def test_init_creates_db(self, tmp_path):
        db_path = tmp_path / "tags.db"
        store = TagStore(db_path=db_path)
        assert db_path.exists()

    def test_add_and_get_tags(self, tag_store):
        asyncio.run(self._test_add_and_get(tag_store))

    async def _test_add_and_get(self, store):
        await store.add_tag("web-01", "/usr/bin/backup.sh", "production")
        await store.add_tag("web-01", "/usr/bin/backup.sh", "critical")

        tags = await store.get_tags("web-01", "/usr/bin/backup.sh")
        assert set(tags) == {"production", "critical"}

    def test_remove_tag(self, tag_store):
        asyncio.run(self._test_remove_tag(tag_store))

    async def _test_remove_tag(self, store):
        await store.add_tag("host1", "cmd1", "tag1")
        await store.add_tag("host1", "cmd1", "tag2")
        await store.remove_tag("host1", "cmd1", "tag1")

        tags = await store.get_tags("host1", "cmd1")
        assert tags == ["tag2"]

    def test_duplicate_tag_ignored(self, tag_store):
        asyncio.run(self._test_duplicate(tag_store))

    async def _test_duplicate(self, store):
        await store.add_tag("h", "c", "t")
        await store.add_tag("h", "c", "t")
        tags = await store.get_tags("h", "c")
        assert tags == ["t"]

    def test_get_all_tags(self, tag_store):
        asyncio.run(self._test_get_all(tag_store))

    async def _test_get_all(self, store):
        await store.add_tag("h1", "c1", "alpha")
        await store.add_tag("h1", "c2", "beta")
        await store.add_tag("h2", "c1", "alpha")

        all_tags = await store.get_all_tags()
        assert all_tags == ["alpha", "beta"]

    def test_find_by_tag(self, tag_store):
        asyncio.run(self._test_find_by_tag(tag_store))

    async def _test_find_by_tag(self, store):
        await store.add_tag("h1", "cmd-a", "production")
        await store.add_tag("h2", "cmd-b", "production")
        await store.add_tag("h1", "cmd-c", "staging")

        results = await store.find_by_tag("production")
        assert len(results) == 2

    def test_different_hosts_same_command(self, tag_store):
        asyncio.run(self._test_different_hosts(tag_store))

    async def _test_different_hosts(self, store):
        await store.add_tag("host-a", "/usr/bin/job", "tag-a")
        await store.add_tag("host-b", "/usr/bin/job", "tag-b")

        tags_a = await store.get_tags("host-a", "/usr/bin/job")
        tags_b = await store.get_tags("host-b", "/usr/bin/job")
        assert tags_a == ["tag-a"]
        assert tags_b == ["tag-b"]

    def test_command_hash(self):
        h1 = TagStore.command_hash("/usr/bin/backup.sh")
        h2 = TagStore.command_hash("/usr/bin/backup.sh")
        h3 = TagStore.command_hash("/usr/bin/other.sh")
        assert h1 == h2
        assert h1 != h3
        assert len(h1) == 16

    def test_empty_tags(self, tag_store):
        asyncio.run(self._test_empty(tag_store))

    async def _test_empty(self, store):
        tags = await store.get_tags("nonexistent", "cmd")
        assert tags == []
