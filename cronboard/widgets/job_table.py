"""Cron job table widget with multi-host, pagination, and tag filtering."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from textual.binding import Binding
from textual.message import Message
from textual.widgets import DataTable
from textual.widgets.data_table import RowKey

from ..models import CrontabLine, LineType


PAGE_SIZE = 100


class JobTable(DataTable):
    """DataTable specialized for cron job display with multi-host support."""

    BINDINGS = [
        Binding("space", "toggle_select", "选择/取消", show=True),
        Binding("a", "select_all", "全选", show=True),
        Binding("pagedown", "next_page", "下一页", show=False),
        Binding("pageup", "prev_page", "上一页", show=False),
    ]

    class JobSelected(Message):
        def __init__(self, line: CrontabLine) -> None:
            super().__init__()
            self.line = line

    class JobActivated(Message):
        def __init__(self, line: CrontabLine) -> None:
            super().__init__()
            self.line = line

    class PageChanged(Message):
        def __init__(self, page: int, total_pages: int, total_jobs: int) -> None:
            super().__init__()
            self.page = page
            self.total_pages = total_pages
            self.total_jobs = total_jobs

    def __init__(self, multi_host: bool = False, **kwargs):
        super().__init__(cursor_type="row", zebra_stripes=True, **kwargs)
        self._lines: list[CrontabLine] = []
        self._filtered_lines: list[CrontabLine] = []
        self._row_to_line: dict[RowKey, CrontabLine] = {}
        self._selected_rows: set[RowKey] = set()
        self._multi_host = multi_host
        self._page = 0
        self._page_size = PAGE_SIZE

    def on_mount(self) -> None:
        self._setup_columns()

    def _setup_columns(self) -> None:
        if self._multi_host:
            self.add_columns(
                "状态", "主机", "调度表达式", "命令", "下次执行", "上次执行", "运行中"
            )
        else:
            self.add_columns(
                "状态", "调度表达式", "命令", "下次执行", "上次执行", "运行中"
            )

    def set_multi_host(self, multi_host: bool) -> None:
        """Switch between single-host and multi-host column layout."""
        if self._multi_host != multi_host:
            self._multi_host = multi_host
            self.clear(columns=True)
            self._setup_columns()

    def load_jobs(
        self,
        lines: list[CrontabLine],
        filter_text: str = "",
        host_filter: str = "__all__",
        tag_filter: str = "",
    ) -> None:
        """Load cron jobs into the table with filtering and pagination."""
        self.clear()
        self._row_to_line = {}
        self._selected_rows = set()

        jobs = [l for l in lines if l.line_type == LineType.CRON_JOB]

        # Host filter
        if host_filter and host_filter != "__all__":
            jobs = [j for j in jobs if j.host == host_filter]

        # Keyword search
        if filter_text:
            filter_lower = filter_text.lower()
            jobs = [
                j
                for j in jobs
                if filter_lower in (j.command or "").lower()
                or filter_lower in (j.schedule or "").lower()
                or filter_lower in j.host.lower()
                or any(filter_lower in t.lower() for t in j.tags)
            ]

        # Tag filter
        if tag_filter:
            tag_lower = tag_filter.lower()
            jobs = [j for j in jobs if any(tag_lower == t.lower() for t in j.tags)]

        self._filtered_lines = jobs
        self._page = 0
        self._render_page()

    def _render_page(self) -> None:
        """Render current page of data."""
        self.clear()
        self._row_to_line = {}
        self._lines = []

        total = len(self._filtered_lines)
        start = self._page * self._page_size
        end = min(start + self._page_size, total)
        page_jobs = self._filtered_lines[start:end]

        for job in page_jobs:
            row_data = self._build_row(job)
            row_key = self.add_row(*row_data)
            self._row_to_line[row_key] = job
            self._lines.append(job)

        self.post_message(
            self.PageChanged(
                page=self._page + 1,
                total_pages=self.total_pages,
                total_jobs=total,
            )
        )

    def _build_row(self, job: CrontabLine) -> tuple:
        status = "✓ 启用" if job.enabled else "✗ 禁用"
        schedule = job.display_schedule
        command = job.display_command
        next_run = self._format_time(job.next_run) if job.enabled else "-"
        last_run = self._format_time(job.last_run) if job.enabled else "-"
        running = "● 运行中" if job.is_running else ""

        if self._multi_host:
            host = job.host if job.host != "localhost" else "本机"
            return (status, host, schedule, command, next_run, last_run, running)
        return (status, schedule, command, next_run, last_run, running)

    @property
    def total_pages(self) -> int:
        total = len(self._filtered_lines)
        if total == 0:
            return 1
        return (total + self._page_size - 1) // self._page_size

    @property
    def current_page(self) -> int:
        return self._page + 1

    @property
    def total_jobs(self) -> int:
        return len(self._filtered_lines)

    def action_next_page(self) -> None:
        if self._page < self.total_pages - 1:
            self._page += 1
            self._render_page()

    def action_prev_page(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._render_page()

    def get_selected_line(self) -> Optional[CrontabLine]:
        """Get the currently highlighted line."""
        if self.cursor_row is not None and self.row_count > 0:
            row_key = self._row_keys[self.cursor_row]
            return self._row_to_line.get(row_key)
        return None

    def get_checked_lines(self) -> list[CrontabLine]:
        """Get all checked/selected lines."""
        return [
            self._row_to_line[rk]
            for rk in self._selected_rows
            if rk in self._row_to_line
        ]

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

    def on_data_table_row_highlighted(
        self, event: DataTable.RowHighlighted
    ) -> None:
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
