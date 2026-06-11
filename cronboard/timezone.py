"""Timezone validation for CRON_TZ/TZ environment variables."""

from __future__ import annotations

import re
from typing import Optional

try:
    from zoneinfo import ZoneInfo, available_timezones
except ImportError:
    from backports.zoneinfo import ZoneInfo, available_timezones


def validate_timezone(tz_value: str) -> Optional[str]:
    """Validate a timezone string. Returns warning message or None if valid."""
    if not tz_value or not tz_value.strip():
        return "时区值为空"

    value = tz_value.strip().strip("'\"")

    if not value:
        return "时区值为空"

    # Check against known timezones
    try:
        valid_zones = available_timezones()
    except Exception:
        return None

    if value in valid_zones:
        return None

    # Check for common mistakes
    if re.match(r"^[A-Z]{2,5}$", value) and value not in ("UTC", "GMT"):
        return f"无效时区 '{value}': 缩写时区不可靠，请使用 IANA 格式如 'Asia/Shanghai'"

    if "/" not in value and value not in ("UTC", "GMT", "UCT", "Universal", "Zulu"):
        suggestions = _find_similar_timezones(value)
        suggestion_text = ""
        if suggestions:
            suggestion_text = f"，您是否指: {', '.join(suggestions[:3])}"
        return f"无效时区 '{value}'{suggestion_text}"

    # Has slash but not recognized
    suggestions = _find_similar_timezones(value)
    suggestion_text = ""
    if suggestions:
        suggestion_text = f"，您是否指: {', '.join(suggestions[:3])}"
    return f"无效时区 '{value}'{suggestion_text}"


def _find_similar_timezones(value: str) -> list[str]:
    """Find similar timezone names for suggestions."""
    try:
        valid_zones = available_timezones()
    except Exception:
        return []

    value_lower = value.lower()
    matches = []

    # Exact substring match
    for tz in sorted(valid_zones):
        if value_lower in tz.lower():
            matches.append(tz)
            if len(matches) >= 5:
                break

    if not matches:
        # Try matching the last segment (city name)
        for tz in sorted(valid_zones):
            parts = tz.split("/")
            if len(parts) >= 2 and value_lower in parts[-1].lower():
                matches.append(tz)
                if len(matches) >= 5:
                    break

    return matches


def get_timezone_info(tz_value: str) -> Optional[str]:
    """Get display info for a valid timezone."""
    value = tz_value.strip().strip("'\"")
    try:
        from datetime import datetime
        tz = ZoneInfo(value)
        now = datetime.now(tz)
        offset = now.strftime("%z")
        return f"{value} (UTC{offset[:3]}:{offset[3:]})"
    except Exception:
        return None
