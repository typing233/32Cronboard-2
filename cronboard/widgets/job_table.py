"""Cron job table widget."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widgets import DataTable
from textual.widgets.data_table import RowKey

from ..models import CrontabLine, LineType


class JobTable(DataTable):
    """DataTable specialized for cron job display."""

    BINDINGS = [
        Binding("space", "toggle_select", "选择/取消", show=True),
        Binding("a", "select_all", "全选", show=True),
    ]

    class JobSelected(Message):
        def __init__(self, line: CrontabLine) -> None:
            super().__init__()
            self.line = line

    class JobActivated(Message):
        def __init__(self, line: CrontabLine) -> None:
            super().__init__()
            self.line = line

    def __init__(self, **kwargs):
        super().__init__(cursor_type="row", zebra_stripes=True, **kwargs)
        self._lines: list[CrontabLine] = []
        self._row_to_line: dict[RowKey, CrontabLine] = {}
        self._selected_rows: set[RowKey] = set()

    def on_mount(self) -> None:
        self.add_columns(
            "状态", "调度表达式", "命令", "下次执行", "上次执行", "运行中"
        )

    def load_jobs(self, lines: list[CrontabLine], filter_text: str = "") -> None:
        """Load cron jobs into the table."""
        self.clear()
        self._lines = []
        self._row_to_line = {}
        self._selected_rows = set()

        jobs = [l for l in lines if l.line_type == LineType.CRON_JOB]

        if filter_text:
            filter_lower = filter_text.lower()
            jobs = [
                j for j in jobs
                if filter_lower in (j.command or "").lower()
                or filter_lower in (j.schedule or "").lower()
            ]

        for job in jobs:
            status = "✓ 启用" if job.enabled else "✗ 禁用"
            schedule = job.display_schedule
            command = job.display_command
            next_run = self._format_time(job.next_run) if job.enabled else "-"
            last_run = self._format_time(job.last_run) if job.enabled else "-"
            running = "● 运行中" if job.is_running else ""

            row_key = self.add_row(
                status, schedule, command, next_run, last_run, running
            )
            self._row_to_line[row_key] = job
            self._lines.append(job)

    def get_selected_line(self) -> Optional[CrontabLine]:
        """Get the currently highlighted line."""
        if self.cursor_row is not None and self.row_count > 0:
            row_key = self._row_keys[self.cursor_row]
            return self._row_to_line.get(row_key)
        return None

    def get_checked_lines(self) -> list[CrontabLine]:
        """Get all checked/selected lines."""
        return [self._row_to_line[rk] for rk in self._selected_rows if rk in self._row_to_line]

    @property
    def _row_keys(self) -> list[RowKey]:
        return list(self._row_to_line.keys())

    def action_toggle_select(self) -> None:
        if self.cursor_row is not None and self.row_count > 0:
            row_key = self._row_keys[self.cursor_row]
            if row_key in self._selected_rows:
                self._selected_rows.discard(row_key)
            else:
                self._selected_rows.add(row_key)
            self.refresh()

    def action_select_all(self) -> None:
        if len(self._selected_rows) == len(self._row_to_line):
            self._selected_rows.clear()
        else:
            self._selected_rows = set(self._row_to_line.keys())
        self.refresh()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        line = self._row_to_line.get(event.row_key)
        if line:
            self.post_message(self.JobActivated(line))

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        line = self._row_to_line.get(event.row_key)
        if line:
            self.post_message(self.JobSelected(line))

    @staticmethod
    def _format_time(dt: Optional[datetime]) -> str:
        if dt is None:
            return "-"
        now = datetime.now()
        diff = dt - now
        if abs(diff.total_seconds()) < 60:
            return "刚才"
        if abs(diff.total_seconds()) < 3600:
            mins = int(abs(diff.total_seconds()) / 60)
            prefix = "后" if diff.total_seconds() > 0 else "前"
            return f"{mins}分钟{prefix}"
        return dt.strftime("%m-%d %H:%M")
