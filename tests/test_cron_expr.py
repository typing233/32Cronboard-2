"""Tests for cron expression validation and description, including L/#/W extensions."""

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


class TestValidationExtended:
    """Test validation of L, #, W extensions."""

    def test_last_day_of_month(self):
        valid, _ = validate_expression("0 0 L * *")
        assert valid

    def test_last_weekday_of_month(self):
        valid, _ = validate_expression("0 0 LW * *")
        assert valid

    def test_nearest_weekday(self):
        valid, _ = validate_expression("0 0 15W * *")
        assert valid

    def test_nth_weekday(self):
        # Second Monday of every month
        valid, _ = validate_expression("0 9 * * 1#2")
        assert valid

    def test_last_weekday_in_dow(self):
        # Last Friday of the month
        valid, _ = validate_expression("0 9 * * 5L")
        assert valid

    def test_l_offset(self):
        # 3 days before end of month
        valid, _ = validate_expression("0 0 L-3 * *")
        assert valid

    def test_invalid_nth_too_high(self):
        # 6th Monday doesn't exist
        valid, _ = validate_expression("0 9 * * 1#6")
        assert not valid

    def test_invalid_dow_for_hash(self):
        valid, _ = validate_expression("0 9 * * 8#2")
        assert not valid


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


class TestDescriptionExtended:
    """Test human-readable descriptions for L/#/W extensions."""

    def test_last_day_of_month(self):
        desc = describe_expression("0 0 L * *")
        assert "最后一天" in desc

    def test_last_weekday(self):
        desc = describe_expression("0 0 LW * *")
        assert "最后一个工作日" in desc

    def test_nearest_weekday(self):
        desc = describe_expression("0 0 15W * *")
        assert "工作日" in desc
        assert "15" in desc

    def test_nth_weekday_second_monday(self):
        desc = describe_expression("0 9 * * 1#2")
        assert "第二个" in desc
        assert "周一" in desc

    def test_nth_weekday_third_friday(self):
        desc = describe_expression("0 17 * * 5#3")
        assert "第三个" in desc
        assert "周五" in desc

    def test_last_friday(self):
        desc = describe_expression("0 9 * * 5L")
        assert "最后一个" in desc
        assert "周五" in desc

    def test_l_offset(self):
        desc = describe_expression("0 0 L-3 * *")
        assert "倒数第3天" in desc

    def test_no_raw_symbols_in_description(self):
        """Descriptions should not contain raw L, #, W symbols."""
        cases = [
            "0 0 L * *",
            "0 0 LW * *",
            "0 0 15W * *",
            "0 9 * * 1#2",
            "0 9 * * 5L",
            "0 0 L-3 * *",
        ]
        for expr in cases:
            desc = describe_expression(expr)
            # Should not have raw symbols as standalone tokens
            assert "#" not in desc, f"'{expr}' produced description with #: {desc}"
            assert desc != expr, f"'{expr}' returned raw expression as description"


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

    def test_extended_expression_returns_none(self):
        """Extended expressions (L/#/W) cannot compute next run via croniter."""
        assert get_next_run("0 0 L * *") is None
        assert get_next_run("0 9 * * 1#2") is None
        assert get_prev_run("0 0 15W * *") is None
