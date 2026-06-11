"""Tests for timezone validation."""

import pytest

from cronboard.timezone import validate_timezone, get_timezone_info


class TestValidateTimezone:
    """Test timezone validation logic."""

    def test_valid_iana_timezone(self):
        assert validate_timezone("Asia/Shanghai") is None
        assert validate_timezone("America/New_York") is None
        assert validate_timezone("Europe/London") is None
        assert validate_timezone("UTC") is None

    def test_valid_with_quotes(self):
        assert validate_timezone("'Asia/Shanghai'") is None
        assert validate_timezone('"UTC"') is None

    def test_empty_timezone(self):
        result = validate_timezone("")
        assert result is not None
        assert "空" in result

    def test_whitespace_only(self):
        result = validate_timezone("   ")
        assert result is not None
        assert "空" in result

    def test_invalid_abbreviation(self):
        result = validate_timezone("CST")
        assert result is not None
        assert "缩写" in result or "无效" in result

    def test_invalid_timezone_name(self):
        result = validate_timezone("Fake/City")
        assert result is not None
        assert "无效时区" in result

    def test_invalid_gives_suggestion(self):
        result = validate_timezone("Asia/Shanghia")
        assert result is not None
        # Should suggest similar timezone
        assert "Shanghai" in result or "无效" in result

    def test_partial_match_suggestion(self):
        result = validate_timezone("Tokyo")
        assert result is not None
        assert "Asia/Tokyo" in result

    def test_gmt_valid(self):
        assert validate_timezone("GMT") is None

    def test_utc_valid(self):
        assert validate_timezone("UTC") is None


class TestGetTimezoneInfo:
    """Test timezone info display."""

    def test_valid_timezone(self):
        info = get_timezone_info("UTC")
        assert info is not None
        assert "UTC" in info

    def test_invalid_timezone(self):
        info = get_timezone_info("Fake/Zone")
        assert info is None
