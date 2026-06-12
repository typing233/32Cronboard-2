"""Tests for audit logger."""

import asyncio
from pathlib import Path

import pytest

from cronboard.audit.logger import AuditLogger
from cronboard.audit.models import AuditRecord


@pytest.fixture
def audit_logger(tmp_path):
    db_path = tmp_path / "test_audit.db"
    return AuditLogger(db_path=db_path)


class TestAuditLogger:
    def test_init_creates_db(self, tmp_path):
        db_path = tmp_path / "audit.db"
        logger = AuditLogger(db_path=db_path)
        assert db_path.exists()

    def test_log_and_query(self, audit_logger):
        asyncio.run(self._test_log_and_query(audit_logger))

    async def _test_log_and_query(self, logger):
        await logger.log(
            host="web-01",
            operation="write",
            description="新建任务",
            success=True,
        )
        await logger.log(
            host="web-01",
            operation="read",
            success=True,
        )
        await logger.log(
            host="localhost",
            operation="write",
            success=False,
            error_message="permission denied",
        )

        # Query all
        records = await logger.query()
        assert len(records) == 3

        # Query by host
        records = await logger.query(host="web-01")
        assert len(records) == 2
        assert all(r.host == "web-01" for r in records)

        # Query by operation
        records = await logger.query(operation="write")
        assert len(records) == 2

        # Query with limit
        records = await logger.query(limit=1)
        assert len(records) == 1

    def test_log_failure(self, audit_logger):
        asyncio.run(self._test_log_failure(audit_logger))

    async def _test_log_failure(self, logger):
        await logger.log(
            host="db-master",
            operation="write",
            success=False,
            error_message="connection timeout",
            description="编辑任务",
        )
        records = await logger.query(host="db-master")
        assert len(records) == 1
        assert records[0].success is False
        assert records[0].error_message == "connection timeout"
        assert records[0].description == "编辑任务"

    def test_log_with_diff(self, audit_logger):
        asyncio.run(self._test_log_with_diff(audit_logger))

    async def _test_log_with_diff(self, logger):
        diff_text = "--- old\n+++ new\n-old line\n+new line"
        await logger.log(
            host="localhost",
            operation="write",
            diff=diff_text,
            description="修改调度",
        )
        records = await logger.query()
        assert records[0].diff == diff_text

    def test_count(self, audit_logger):
        asyncio.run(self._test_count(audit_logger))

    async def _test_count(self, logger):
        for i in range(5):
            await logger.log(host="web-01", operation="read")
        for i in range(3):
            await logger.log(host="localhost", operation="read")

        total = await logger.count()
        assert total == 8
        web_count = await logger.count(host="web-01")
        assert web_count == 5

    def test_query_order_newest_first(self, audit_logger):
        asyncio.run(self._test_query_order(audit_logger))

    async def _test_query_order(self, logger):
        await logger.log(host="h1", operation="op1", description="first")
        await logger.log(host="h1", operation="op2", description="second")
        await logger.log(host="h1", operation="op3", description="third")

        records = await logger.query()
        assert records[0].description == "third"
        assert records[2].description == "first"

    def test_audit_record_from_row(self):
        row = (
            1,
            "2024-06-15T12:00:00",
            "web-01",
            "testuser",
            "write",
            "test desc",
            "diff text",
            1,
            None,
        )
        record = AuditRecord.from_row(row)
        assert record.id == 1
        assert record.host == "web-01"
        assert record.username == "testuser"
        assert record.operation == "write"
        assert record.success is True
        assert record.error_message is None
