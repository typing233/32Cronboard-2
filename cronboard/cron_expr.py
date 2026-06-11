"""Cron expression validation and human-readable translation.

Supports standard 5-field cron, @special schedules, and non-standard
extensions (L, #, W) commonly used in Quartz/Spring-style cron.
"""

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

DOW_NAMES_CN = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
MONTH_NAMES_CN = [
    "", "1月", "2月", "3月", "4月", "5月", "6月",
    "7月", "8月", "9月", "10月", "11月", "12月",
]

# Extended field detection (L, #, W, ?)
_HAS_EXTENSION_RE = re.compile(r"[LlWw#?]")


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

    # For extended expressions (L, #, W), do manual validation
    if _HAS_EXTENSION_RE.search(normalized):
        return _validate_extended(normalized)

    try:
        croniter(normalized)
        return True, ""
    except (ValueError, KeyError) as e:
        return False, f"无效的 Cron 表达式: {e}"


def _validate_extended(expr: str) -> tuple[bool, str]:
    """Validate extended cron expressions with L, #, W tokens."""
    parts = expr.split()
    if len(parts) != 5:
        return False, f"需要5个字段，实际有{len(parts)}个"

    minute, hour, dom, month, dow = parts

    # Validate minute (0-59)
    if not _validate_standard_field(minute, 0, 59):
        return False, f"分钟字段无效: {minute}"

    # Validate hour (0-23)
    if not _validate_standard_field(hour, 0, 23):
        return False, f"小时字段无效: {hour}"

    # Validate DOM - allows L, W, LW
    if not _validate_dom_field(dom):
        return False, f"日期字段无效: {dom}"

    # Validate month (1-12)
    if not _validate_standard_field(month, 1, 12):
        return False, f"月份字段无效: {month}"

    # Validate DOW - allows L, #
    if not _validate_dow_field(dow):
        return False, f"星期字段无效: {dow}"

    return True, ""


def _validate_standard_field(field: str, min_val: int, max_val: int) -> bool:
    """Validate a standard cron field (no extensions)."""
    if field == "*" or field == "?":
        return True
    if field.startswith("*/"):
        try:
            step = int(field[2:])
            return 1 <= step <= max_val
        except ValueError:
            return False
    for part in field.split(","):
        if "-" in part:
            if "/" in part:
                range_part, step = part.rsplit("/", 1)
            else:
                range_part, step = part, None
            pieces = range_part.split("-", 1)
            if len(pieces) != 2:
                return False
            try:
                a, b = int(pieces[0]), int(pieces[1])
                if not (min_val <= a <= max_val and min_val <= b <= max_val):
                    return False
                if step and not (1 <= int(step) <= max_val):
                    return False
            except ValueError:
                return False
        else:
            try:
                v = int(part)
                if not (min_val <= v <= max_val):
                    return False
            except ValueError:
                return False
    return True


def _validate_dom_field(field: str) -> bool:
    """Validate day-of-month field (allows L, W, LW)."""
    if field in ("*", "?", "L", "LW", "lw"):
        return True
    if field.startswith("*/"):
        try:
            return 1 <= int(field[2:]) <= 31
        except ValueError:
            return False
    # L-N (N days before last day)
    if re.match(r"^[Ll]-\d+$", field):
        return True
    # NW (nearest weekday to Nth)
    if re.match(r"^\d+[Ww]$", field):
        try:
            return 1 <= int(field[:-1]) <= 31
        except ValueError:
            return False
    return _validate_standard_field(field, 1, 31)


def _validate_dow_field(field: str) -> bool:
    """Validate day-of-week field (allows L, #)."""
    if field in ("*", "?"):
        return True
    # NL (last Nth weekday of month)
    if re.match(r"^\d[Ll]$", field):
        return 0 <= int(field[0]) <= 7
    # N#M (Mth occurrence of weekday N)
    hash_match = re.match(r"^(\d)#(\d)$", field)
    if hash_match:
        dow_val = int(hash_match.group(1))
        nth = int(hash_match.group(2))
        return 0 <= dow_val <= 7 and 1 <= nth <= 5
    return _validate_standard_field(field, 0, 7)


def get_next_run(expr: str, base: Optional[datetime] = None) -> Optional[datetime]:
    """Get the next run time for a cron expression."""
    if not expr:
        return None

    normalized = normalize_schedule(expr)
    if normalized is None:
        return None

    # Cannot compute next run for extended expressions
    if _HAS_EXTENSION_RE.search(normalized):
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

    if _HAS_EXTENSION_RE.search(normalized):
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
    if month != "*" and month != "?":
        segments.append(_describe_month(month))

    # Day of week (with extensions)
    if dow != "*" and dow != "?":
        segments.append(_describe_dow(dow))

    # Day of month (with extensions)
    if dom != "*" and dom != "?":
        segments.append(_describe_dom(dom))

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
    if hour == "*" or hour == "?":
        if minute.startswith("*/"):
            interval = minute[2:]
            return f"每{interval}分钟"
        if "," in minute:
            return f"每小时的第{minute}分钟"
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

    if "-" in hour and "/" not in hour:
        start, end = hour.split("-", 1)
        if minute == "0":
            return f"{start}点到{end}点之间每小时"
        return f"{start}点到{end}点之间每小时的第{minute}分钟"

    if "-" in hour and "/" in hour:
        range_part, step = hour.rsplit("/", 1)
        start, end = range_part.split("-", 1)
        if minute == "0":
            return f"{start}点到{end}点之间每{step}小时"
        return f"{start}点到{end}点之间每{step}小时的第{minute}分钟"

    return f"{hour}:{minute.zfill(2)}"


def _describe_month(month: str) -> str:
    """Describe month field."""
    if "," in month:
        parts = month.split(",")
        names = [_month_name(p) for p in parts]
        return "在" + ", ".join(names)

    if "-" in month:
        start, end = month.split("-", 1)
        return f"{_month_name(start)}到{_month_name(end)}"

    return _month_name(month)


def _month_name(val: str) -> str:
    """Convert month value to Chinese name."""
    month_abbr = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    try:
        idx = int(val)
    except ValueError:
        idx = month_abbr.get(val.lower(), 0)
    if 1 <= idx <= 12:
        return MONTH_NAMES_CN[idx]
    return val


def _describe_dow(dow: str) -> str:
    """Describe day-of-week field, including L and # extensions."""
    # N#M - Mth occurrence of weekday N in the month
    hash_match = re.match(r"^(\d)#(\d)$", dow)
    if hash_match:
        weekday = int(hash_match.group(1))
        nth = int(hash_match.group(2))
        ordinals = ["", "第一个", "第二个", "第三个", "第四个", "第五个"]
        dow_name = _dow_name(weekday)
        nth_text = ordinals[nth] if nth < len(ordinals) else f"第{nth}个"
        return f"每月{nth_text}{dow_name}"

    # NL - last Nth weekday of the month
    if re.match(r"^\d[Ll]$", dow):
        weekday = int(dow[0])
        return f"每月最后一个{_dow_name(weekday)}"

    # Comma-separated list
    if "," in dow:
        parts = dow.split(",")
        names = [_dow_name(p) for p in parts]
        return "每" + ", ".join(names)

    # Range
    if "-" in dow:
        start, end = dow.split("-", 1)
        return f"{_dow_name(start)}到{_dow_name(end)}"

    return f"每{_dow_name(dow)}"


def _dow_name(val: str) -> str:
    """Convert day-of-week value to Chinese name."""
    dow_abbr = {
        "sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6,
    }
    try:
        idx = int(val)
    except ValueError:
        idx = dow_abbr.get(val.lower()[:3], -1)

    if idx == 7:
        idx = 0
    if 0 <= idx <= 6:
        return DOW_NAMES_CN[idx]
    return val


def _describe_dom(dom: str) -> str:
    """Describe day-of-month field, including L and W extensions."""
    dom_lower = dom.lower()

    # L - last day of the month
    if dom_lower == "l":
        return "每月最后一天"

    # LW - last weekday of the month
    if dom_lower == "lw":
        return "每月最后一个工作日"

    # L-N - Nth day before end of month
    l_offset = re.match(r"^[Ll]-(\d+)$", dom)
    if l_offset:
        n = l_offset.group(1)
        return f"每月倒数第{n}天"

    # NW - nearest weekday to the Nth
    w_match = re.match(r"^(\d+)[Ww]$", dom)
    if w_match:
        day = w_match.group(1)
        return f"每月{day}日最近的工作日"

    # */N - every N days
    if dom.startswith("*/"):
        interval = dom[2:]
        return f"每隔{interval}天"

    # Comma-separated
    if "," in dom:
        return f"每月{dom.replace(',', ', ')}日"

    # Range
    if "-" in dom:
        start, end = dom.split("-", 1)
        return f"每月{start}到{end}日"

    return f"每月{dom}日"
