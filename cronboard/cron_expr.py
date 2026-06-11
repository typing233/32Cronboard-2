"""Cron expression validation and human-readable translation."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from croniter import croniter


SPECIAL_SCHEDULES = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
    "@reboot": None,
}

DOW_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def normalize_schedule(expr: str) -> Optional[str]:
    """Normalize special @-schedules to 5-field form. Returns None for @reboot."""
    stripped = expr.strip().lower()
    if stripped in SPECIAL_SCHEDULES:
        return SPECIAL_SCHEDULES[stripped]
    return expr.strip()


def validate_expression(expr: str) -> tuple[bool, str]:
    """Validate a cron expression. Returns (is_valid, error_message)."""
    if not expr or not expr.strip():
        return False, "表达式不能为空"

    stripped = expr.strip()

    if stripped.lower() == "@reboot":
        return True, ""

    if stripped.lower() in SPECIAL_SCHEDULES:
        return True, ""

    normalized = normalize_schedule(stripped)
    if normalized is None:
        return True, ""

    try:
        croniter(normalized)
        return True, ""
    except (ValueError, KeyError) as e:
        return False, f"无效的 Cron 表达式: {e}"


def get_next_run(expr: str, base: Optional[datetime] = None) -> Optional[datetime]:
    """Get the next run time for a cron expression."""
    if not expr:
        return None

    normalized = normalize_schedule(expr)
    if normalized is None:
        return None

    base = base or datetime.now()
    try:
        cron = croniter(normalized, base)
        return cron.get_next(datetime)
    except (ValueError, KeyError):
        return None


def get_prev_run(expr: str, base: Optional[datetime] = None) -> Optional[datetime]:
    """Get the previous run time for a cron expression."""
    if not expr:
        return None

    normalized = normalize_schedule(expr)
    if normalized is None:
        return None

    base = base or datetime.now()
    try:
        cron = croniter(normalized, base)
        return cron.get_prev(datetime)
    except (ValueError, KeyError):
        return None


def describe_expression(expr: str) -> str:
    """Translate a cron expression to human-readable Chinese description."""
    if not expr or not expr.strip():
        return "无效表达式"

    stripped = expr.strip().lower()

    special_desc = {
        "@yearly": "每年1月1日 00:00",
        "@annually": "每年1月1日 00:00",
        "@monthly": "每月1日 00:00",
        "@weekly": "每周日 00:00",
        "@daily": "每天 00:00",
        "@midnight": "每天 00:00",
        "@hourly": "每小时整点",
        "@reboot": "系统启动时",
    }
    if stripped in special_desc:
        return special_desc[stripped]

    normalized = normalize_schedule(stripped)
    if normalized is None:
        return "系统启动时"

    parts = normalized.split()
    if len(parts) != 5:
        return "无效表达式"

    minute, hour, dom, month, dow = parts

    try:
        return _build_description(minute, hour, dom, month, dow)
    except Exception:
        return f"Cron: {expr.strip()}"


def _build_description(minute: str, hour: str, dom: str, month: str, dow: str) -> str:
    """Build human-readable description from 5 cron fields."""
    segments = []

    # Month
    if month != "*":
        segments.append(_describe_field(month, MONTH_NAMES, "月"))

    # Day of week
    if dow != "*":
        segments.append("每" + _describe_field(dow, DOW_NAMES, ""))

    # Day of month
    if dom != "*":
        if dom == "*/2":
            segments.append("每隔一天")
        else:
            segments.append(f"每月{_describe_numeric_field(dom)}日")

    # Hour and minute
    time_desc = _describe_time(minute, hour)
    segments.append(time_desc)

    if not segments:
        return "未知调度"

    return " ".join(segments)


def _describe_time(minute: str, hour: str) -> str:
    """Describe the time portion."""
    if hour == "*" and minute == "*":
        return "每分钟"
    if hour == "*":
        if minute.startswith("*/"):
            interval = minute[2:]
            return f"每{interval}分钟"
        return f"每小时的第{minute}分钟"

    if hour.startswith("*/"):
        interval = hour[2:]
        if minute == "0":
            return f"每{interval}小时"
        return f"每{interval}小时的第{minute}分钟"

    if minute == "*":
        return f"{hour}点的每分钟"

    if "," in hour:
        hours = hour.split(",")
        times = [f"{h}:{minute.zfill(2)}" for h in hours]
        return "在 " + ", ".join(times)

    if "-" in hour:
        start, end = hour.split("-", 1)
        if minute == "0":
            return f"{start}点到{end}点之间每小时"
        return f"{start}点到{end}点之间每小时的第{minute}分钟"

    return f"{hour}:{minute.zfill(2)}"


def _describe_field(field: str, names: list[str], suffix: str) -> str:
    """Describe a named field (month or dow)."""
    if "," in field:
        parts = field.split(",")
        named = []
        for p in parts:
            try:
                idx = int(p)
                if 0 <= idx < len(names):
                    named.append(names[idx] + suffix)
            except ValueError:
                named.append(p)
        return ", ".join(named)

    if "-" in field and "/" not in field:
        start, end = field.split("-", 1)
        try:
            s, e = int(start), int(end)
            if 0 <= s < len(names) and 0 <= e < len(names):
                return f"{names[s]}{suffix}到{names[e]}{suffix}"
        except ValueError:
            pass

    if field.startswith("*/"):
        return f"每隔{field[2:]}{suffix}"

    try:
        idx = int(field)
        if 0 <= idx < len(names):
            return names[idx] + suffix
    except ValueError:
        pass

    return field


def _describe_numeric_field(field: str) -> str:
    """Describe a numeric field like dom."""
    if "," in field:
        return ", ".join(field.split(","))
    if "-" in field:
        start, end = field.split("-", 1)
        return f"{start}到{end}"
    return field
