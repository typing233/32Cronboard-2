"""Tests for cron expression validation and description."""

import pytest
from datetime import datetime

from cronboard.cron_expr import (
    describe_expression,
    get_next_run,
    get_prev_run,
    normalize_schedule,
    validate_expression,
)


class TestValidation:
    """Test cron expression validation."""

    def test_valid_standard(self):
        assert validate_expression("* * * * *") == (True, "")
        assert validate_expression("0 2 * * *") == (True, "")
        assert validate_expression("*/15 * * * *") == (True, "")
        assert validate_expression("0 9-17 * * 1-5") == (True, "")
        assert validate_expression("0 0 1,15 * *") == (True, "")

    def test_valid_special(self):
        assert validate_expression("@reboot") == (True, "")
        assert validate_expression("@daily") == (True, "")
        assert validate_expression("@hourly") == (True, "")
        assert validate_expression("@weekly") == (True, "")
        assert validate_expression("@monthly") == (True, "")
        assert validate_expression("@yearly") == (True, "")

    def test_invalid_expressions(self):
        valid, _ = validate_expression("")
        assert not valid

        valid, _ = validate_expression("not a cron")
        assert not valid

        valid, _ = validate_expression("60 * * * *")
        assert not valid

        valid, _ = validate_expression("* 25 * * *")
        assert not valid

    def test_empty(self):
        valid, msg = validate_expression("")
        assert not valid
        assert "空" in msg


class TestNormalize:
    def test_special_to_standard(self):
        assert normalize_schedule("@daily") == "0 0 * * *"
        assert normalize_schedule("@hourly") == "0 * * * *"
        assert normalize_schedule("@weekly") == "0 0 * * 0"

    def test_reboot_returns_none(self):
        assert normalize_schedule("@reboot") is None

    def test_standard_passes_through(self):
        assert normalize_schedule("0 2 * * *") == "0 2 * * *"


class TestDescription:
    """Test human-readable descriptions."""

    def test_every_minute(self):
        desc = describe_expression("* * * * *")
        assert "每分钟" in desc

    def test_daily_at_time(self):
        desc = describe_expression("30 2 * * *")
        assert "2:30" in desc

    def test_special_daily(self):
        desc = describe_expression("@daily")
        assert "每天" in desc

    def test_special_hourly(self):
        desc = describe_expression("@hourly")
        assert "每小时" in desc

    def test_special_reboot(self):
        desc = describe_expression("@reboot")
        assert "启动" in desc

    def test_every_n_minutes(self):
        desc = describe_expression("*/5 * * * *")
        assert "5" in desc and "分钟" in desc

    def test_every_n_hours(self):
        desc = describe_expression("0 */2 * * *")
        assert "2" in desc and "小时" in desc

    def test_invalid_returns_fallback(self):
        desc = describe_expression("")
        assert "无效" in desc

    def test_weekday(self):
        desc = describe_expression("0 9 * * 1-5")
        assert "9:00" in desc or "9" in desc


class TestNextPrevRun:
    """Test next/prev run time calculation."""

    def test_next_run_basic(self):
        base = datetime(2024, 6, 15, 10, 0, 0)
        next_time = get_next_run("0 * * * *", base)
        assert next_time is not None
        assert next_time > base
        assert next_time.minute == 0

    def test_prev_run_basic(self):
        base = datetime(2024, 6, 15, 10, 30, 0)
        prev_time = get_prev_run("0 * * * *", base)
        assert prev_time is not None
        assert prev_time < base
        assert prev_time.minute == 0

    def test_reboot_returns_none(self):
        assert get_next_run("@reboot") is None
        assert get_prev_run("@reboot") is None

    def test_invalid_returns_none(self):
        assert get_next_run("invalid expr") is None
        assert get_prev_run("invalid expr") is None

    def test_daily_next_run(self):
        base = datetime(2024, 6, 15, 3, 0, 0)
        next_time = get_next_run("0 2 * * *", base)
        assert next_time is not None
        assert next_time.day == 16
        assert next_time.hour == 2

    def test_every_5_minutes(self):
        base = datetime(2024, 6, 15, 10, 3, 0)
        next_time = get_next_run("*/5 * * * *", base)
        assert next_time is not None
        assert next_time.minute == 5
