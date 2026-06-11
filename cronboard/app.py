"""Cronboard - Terminal cron manager TUI application."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Static,
)

from .cron_expr import describe_expression
from .manager import ConcurrentModificationError, CrontabError, CrontabManager
from .models import CrontabLine, LineType
from .widgets.edit_dialog import EditJobScreen
from .widgets.job_table import JobTable


class DiffScreen(ModalScreen):
    """Show diff before writing."""

    CSS = """
    DiffScreen {
        align: center middle;
    }
    #diff-container {
        width: 90%;
        height: 80%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #diff-log {
        height: 1fr;
    }
    .btn-row {
        height: 3;
        align: right middle;
    }
    .btn-row Button {
        margin-left: 1;
    }
    """

    def __init__(self, diff_text: str, **kwargs):
        super().__init__(**kwargs)
        self._diff = diff_text

    def compose(self) -> ComposeResult:
        with Vertical(id="diff-container"):
            yield Label("变更预览 (Dry-Run Diff)")
            yield RichLog(id="diff-log", highlight=True)
            with Horizontal(classes="btn-row"):
                yield Button("取消", variant="default", id="btn-cancel")
                yield Button("应用", variant="primary", id="btn-apply")

    def on_mount(self) -> None:
        log = self.query_one("#diff-log", RichLog)
        for line in self._diff.split("\n"):
            log.write(line)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(False)
        elif event.button.id == "btn-apply":
            self.dismiss(True)


class CronboardApp(App):
    """Main cronboard application."""

    TITLE = "Cronboard - Cron 任务管理器"
    SUB_TITLE = "本地 crontab 全生命周期管理"

    CSS = """
    #main-container {
        height: 1fr;
    }
    #toolbar {
        height: 3;
        dock: top;
        padding: 0 1;
    }
    #toolbar Button {
        margin-right: 1;
        min-width: 8;
    }
    #search-bar {
        dock: top;
        height: 3;
        padding: 0 1;
    }
    #search-input {
        width: 1fr;
    }
    #job-table {
        height: 1fr;
    }
    #detail-panel {
        dock: bottom;
        height: 8;
        border-top: solid $primary;
        padding: 0 1;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        background: $primary;
        color: $text;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("n", "new_job", "新建", show=True),
        Binding("e", "edit_job", "编辑", show=True),
        Binding("d", "delete_job", "删除", show=True),
        Binding("p", "toggle_job", "暂停/恢复", show=True),
        Binding("b", "batch_toggle", "批量启停", show=True),
        Binding("ctrl+z", "undo", "撤销", show=True),
        Binding("ctrl+y", "redo", "重做", show=True),
        Binding("ctrl+d", "dry_run", "Diff预览", show=True),
        Binding("ctrl+e", "export", "导出", show=True),
        Binding("ctrl+i", "import_", "导入", show=True),
        Binding("r", "refresh", "刷新", show=True),
        Binding("/", "focus_search", "搜索", show=True),
        Binding("q", "quit", "退出", show=True),
    ]

    def __init__(self):
        super().__init__()
        self.manager = CrontabManager()
        self._all_lines: list[CrontabLine] = []
        self._pending_changes: list[CrontabLine] = []
        self._filter_text = ""

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main-container"):
            with Horizontal(id="toolbar"):
                yield Button("新建[N]", variant="primary", id="btn-new")
                yield Button("编辑[E]", variant="default", id="btn-edit")
                yield Button("删除[D]", variant="error", id="btn-delete")
                yield Button("暂停/恢复[P]", variant="warning", id="btn-toggle")
                yield Button("批量启停[B]", variant="default", id="btn-batch")
                yield Button("撤销[^Z]", variant="default", id="btn-undo")
                yield Button("刷新[R]", variant="success", id="btn-refresh")
            with Horizontal(id="search-bar"):
                yield Input(placeholder="搜索过滤 (命令或表达式)...", id="search-input")
            yield JobTable(id="job-table")
            yield Static("", id="detail-panel")
        yield Static("就绪", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        self._load_crontab()

    def _load_crontab(self) -> None:
        """Load and display crontab."""
        try:
            self._all_lines = self.manager.read_crontab()
            self._pending_changes = list(self._all_lines)
            self._refresh_table()
            self._update_status(f"已加载 {self._job_count} 个任务")
        except CrontabError as e:
            self._update_status(f"错误: {e}")

    def _refresh_table(self) -> None:
        table = self.query_one("#job-table", JobTable)
        table.load_jobs(self._pending_changes, self._filter_text)

    @property
    def _job_count(self) -> int:
        return sum(1 for l in self._all_lines if l.line_type == LineType.CRON_JOB)

    def _update_status(self, msg: str) -> None:
        status = self.query_one("#status-bar", Static)
        undo_info = ""
        if self.manager.can_undo:
            undo_info = " | 可撤销"
        status.update(f" {msg}{undo_info} | {datetime.now().strftime('%H:%M:%S')}")

    def _update_detail(self, line: Optional[CrontabLine]) -> None:
        panel = self.query_one("#detail-panel", Static)
        if line is None or line.line_type != LineType.CRON_JOB:
            panel.update("")
            return

        desc = describe_expression(line.schedule or "")
        status = "启用" if line.enabled else "禁用"
        running = "是" if line.is_running else "否"
        next_run = line.next_run.strftime("%Y-%m-%d %H:%M:%S") if line.next_run else "-"
        last_run = line.last_run.strftime("%Y-%m-%d %H:%M:%S") if line.last_run else "-"

        detail = (
            f"[b]命令:[/b] {line.command}\n"
            f"[b]调度:[/b] {line.schedule} → {desc}\n"
            f"[b]状态:[/b] {status} | [b]运行中:[/b] {running}\n"
            f"[b]下次执行:[/b] {next_run} | [b]上次执行:[/b] {last_run}"
        )
        panel.update(detail)

    # --- Event handlers ---

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "btn-new": self.action_new_job,
            "btn-edit": self.action_edit_job,
            "btn-delete": self.action_delete_job,
            "btn-toggle": self.action_toggle_job,
            "btn-batch": self.action_batch_toggle,
            "btn-undo": self.action_undo,
            "btn-refresh": self.action_refresh,
        }
        action = actions.get(event.button.id)
        if action:
            action()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            self._filter_text = event.value
            self._refresh_table()

    def on_job_table_job_selected(self, event: JobTable.JobSelected) -> None:
        self._update_detail(event.line)

    def on_job_table_job_activated(self, event: JobTable.JobActivated) -> None:
        self._edit_line(event.line)

    # --- Actions ---

    def action_new_job(self) -> None:
        self.push_screen(EditJobScreen(), self._on_new_job_result)

    def _on_new_job_result(self, result: CrontabLine | None) -> None:
        if result is None:
            return
        self._pending_changes.append(result)
        self._write_and_reload("新建任务")

    def action_edit_job(self) -> None:
        table = self.query_one("#job-table", JobTable)
        line = table.get_selected_line()
        if line:
            self._edit_line(line)

    def _edit_line(self, line: CrontabLine) -> None:
        self.push_screen(EditJobScreen(existing=line), self._on_edit_job_result)

    def _on_edit_job_result(self, result: CrontabLine | None) -> None:
        if result is None:
            return
        self._write_and_reload("编辑任务")

    def action_delete_job(self) -> None:
        table = self.query_one("#job-table", JobTable)
        line = table.get_selected_line()
        if line is None:
            return
        self._pending_changes = [l for l in self._pending_changes if l is not line]
        self._write_and_reload("删除任务")

    def action_toggle_job(self) -> None:
        table = self.query_one("#job-table", JobTable)
        line = table.get_selected_line()
        if line is None:
            return
        line.enabled = not line.enabled
        self._write_and_reload("切换启停状态")

    def action_batch_toggle(self) -> None:
        table = self.query_one("#job-table", JobTable)
        checked = table.get_checked_lines()
        if not checked:
            self._update_status("请先选择任务 (Space 选择)")
            return
        any_enabled = any(l.enabled for l in checked)
        for line in checked:
            line.enabled = not any_enabled
        self._write_and_reload(f"批量{'禁用' if any_enabled else '启用'} {len(checked)} 个任务")

    def action_undo(self) -> None:
        try:
            result = self.manager.undo()
            if result is None:
                self._update_status("没有可撤销的操作")
                return
            self._all_lines = result
            self._pending_changes = list(result)
            self._refresh_table()
            self._update_status("已撤销")
        except CrontabError as e:
            self._update_status(f"撤销失败: {e}")

    def action_redo(self) -> None:
        try:
            result = self.manager.redo()
            if result is None:
                self._update_status("没有可重做的操作")
                return
            self._all_lines = result
            self._pending_changes = list(result)
            self._refresh_table()
            self._update_status("已重做")
        except CrontabError as e:
            self._update_status(f"重做失败: {e}")

    def action_dry_run(self) -> None:
        diff = self.manager.get_diff(self._pending_changes)
        self.push_screen(DiffScreen(diff), self._on_diff_result)

    def _on_diff_result(self, apply: bool) -> None:
        if apply:
            self._write_and_reload("应用 Diff 变更")

    def action_export(self) -> None:
        export_path = str(Path.home() / f"crontab_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        try:
            self.manager.export_crontab(export_path)
            self._update_status(f"已导出到: {export_path}")
        except CrontabError as e:
            self._update_status(f"导出失败: {e}")

    def action_import_(self) -> None:
        import_path = str(Path.home() / "crontab_import.txt")
        if not Path(import_path).exists():
            self._update_status(f"请将导入文件放在: {import_path}")
            return
        try:
            lines = self.manager.import_crontab(import_path)
            self._pending_changes = lines
            self._refresh_table()
            self._update_status(f"已导入 {sum(1 for l in lines if l.line_type == LineType.CRON_JOB)} 个任务 (未保存)")
        except CrontabError as e:
            self._update_status(f"导入失败: {e}")

    def action_refresh(self) -> None:
        self._load_crontab()

    def action_focus_search(self) -> None:
        self.query_one("#search-input", Input).focus()

    def _write_and_reload(self, description: str) -> None:
        """Write pending changes and reload."""
        try:
            self.manager.write_crontab(self._pending_changes, description)
            self._load_crontab()
        except ConcurrentModificationError:
            self._update_status("⚠ crontab 被外部修改，正在重新加载...")
            self._load_crontab()
        except CrontabError as e:
            self._update_status(f"写入失败: {e}")


def main():
    app = CronboardApp()
    app.run()


if __name__ == "__main__":
    main()
