"""Cronboard - Terminal cron manager TUI application with remote cluster support."""

from __future__ import annotations

import asyncio
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
    OptionList,
    RichLog,
    Static,
)
from textual.widgets.option_list import Option
from textual import work

from .audit.logger import AuditLogger
from .backend.base import CrontabBackend
from .backend.local import LocalBackend
from .backend.remote import RemoteBackend
from .cache.state_cache import CrontabStateCache
from .cron_expr import describe_expression
from .logs.reader import create_log_reader
from .manager import (
    ConcurrentModificationError,
    CrontabError,
    CrontabManager,
    WriteFailedRolledBack,
)
from .metadata.tags import TagStore
from .models import CrontabLine, LineType
from .remote.config import ServerConfig, load_server_configs
from .remote.connection import SSHConnectionPool
from .widgets.audit_panel import AuditPanel
from .widgets.edit_dialog import EditJobScreen
from .widgets.host_selector import HostSelector
from .widgets.job_table import JobTable
from .widgets.log_viewer import LogViewer
from .widgets.tag_dialog import TagManageScreen, TagResult


class DiffConfirmScreen(ModalScreen[bool]):
    """Show diff and require confirmation before writing."""

    CSS = """
    DiffConfirmScreen {
        align: center middle;
    }
    #diff-container {
        width: 90%;
        height: 80%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #diff-title {
        text-style: bold;
        margin-bottom: 1;
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

    def __init__(self, diff_text: str, description: str = "", **kwargs):
        super().__init__(**kwargs)
        self._diff = diff_text
        self._description = description

    def compose(self) -> ComposeResult:
        with Vertical(id="diff-container"):
            title = (
                f"确认变更: {self._description}"
                if self._description
                else "确认变更"
            )
            yield Label(title, id="diff-title")
            yield RichLog(id="diff-log", highlight=True)
            with Horizontal(classes="btn-row"):
                yield Button("取消 [Esc]", variant="default", id="btn-cancel")
                yield Button("确认写入", variant="primary", id="btn-apply")

    def on_mount(self) -> None:
        log = self.query_one("#diff-log", RichLog)
        for line in self._diff.split("\n"):
            log.write(line)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(False)
        elif event.button.id == "btn-apply":
            self.dismiss(True)

    def key_escape(self) -> None:
        self.dismiss(False)


class BackupScreen(ModalScreen[Path | None]):
    """Screen for browsing and selecting backups to restore."""

    CSS = """
    BackupScreen {
        align: center middle;
    }
    #backup-container {
        width: 80%;
        height: 70%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #backup-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #backup-list {
        height: 1fr;
    }
    #backup-preview {
        height: 8;
        border-top: solid $primary;
        margin-top: 1;
    }
    .btn-row {
        height: 3;
        align: right middle;
    }
    .btn-row Button {
        margin-left: 1;
    }
    """

    def __init__(self, backups: list[Path], **kwargs):
        super().__init__(**kwargs)
        self._backups = backups

    def compose(self) -> ComposeResult:
        with Vertical(id="backup-container"):
            yield Label("选择备份进行恢复", id="backup-title")
            yield OptionList(id="backup-list")
            yield Static("", id="backup-preview")
            with Horizontal(classes="btn-row"):
                yield Button("取消", variant="default", id="btn-cancel")
                yield Button("恢复选中", variant="primary", id="btn-restore")

    def on_mount(self) -> None:
        option_list = self.query_one("#backup-list", OptionList)
        for backup in self._backups:
            name = backup.stem
            parts = name.split("_", 1)
            if len(parts) == 2:
                ts = parts[1]
                display = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}:{ts[13:15]}"
            else:
                display = backup.name
            size = backup.stat().st_size
            option_list.add_option(
                Option(f"{display}  ({size} bytes)", id=str(backup))
            )

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option and event.option.id:
            path = Path(event.option.id)
            try:
                content = path.read_text(encoding="utf-8")
                lines = content.strip().split("\n")
                preview = "\n".join(lines[:6])
                if len(lines) > 6:
                    preview += f"\n... ({len(lines)} 行)"
                self.query_one("#backup-preview", Static).update(preview)
            except Exception:
                self.query_one("#backup-preview", Static).update("无法读取")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-restore":
            option_list = self.query_one("#backup-list", OptionList)
            idx = option_list.highlighted
            if idx is not None and 0 <= idx < len(self._backups):
                self.dismiss(self._backups[idx])
            else:
                self.dismiss(None)

    def key_escape(self) -> None:
        self.dismiss(None)


class CronboardApp(App):
    """Main cronboard application with multi-host support."""

    TITLE = "Cronboard - Cron 任务管理器"
    SUB_TITLE = "本地/远程 crontab 全生命周期管理"

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
    #host-selector {
        dock: top;
        height: 3;
        padding: 0 1;
        width: 40;
    }
    #top-bar {
        dock: top;
        height: 3;
        padding: 0 1;
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
    #page-info {
        width: auto;
        padding: 0 2;
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
        Binding("ctrl+e", "export", "导出", show=True),
        Binding("ctrl+i", "import_", "导入", show=True),
        Binding("ctrl+b", "show_backups", "备份", show=True),
        Binding("l", "view_logs", "日志", show=True),
        Binding("t", "manage_tags", "标签", show=True),
        Binding("ctrl+a", "show_audit", "审计", show=True),
        Binding("r", "refresh", "刷新", show=True),
        Binding("/", "focus_search", "搜索", show=True),
        Binding("q", "quit", "退出", show=True),
    ]

    def __init__(self):
        super().__init__()
        # Infrastructure
        self._pool = SSHConnectionPool()
        self._audit = AuditLogger()
        self._cache = CrontabStateCache(ttl_seconds=60)
        self._tags = TagStore()

        # Build backends
        self._backends: list[CrontabBackend] = [LocalBackend()]
        self._server_configs: list[ServerConfig] = []
        try:
            self._server_configs = load_server_configs()
            for cfg in self._server_configs:
                self._backends.append(RemoteBackend(cfg, self._pool))
        except Exception:
            pass

        self._multi_host = len(self._backends) > 1

        # State
        self._all_lines: list[CrontabLine] = []
        self._pending_changes: list[CrontabLine] = []
        self._filter_text = ""
        self._selected_host = "__all__"
        self._tag_filter = ""

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="main-container"):
            with Horizontal(id="top-bar"):
                if self._multi_host:
                    yield HostSelector(id="host-selector")
                yield Static("", id="page-info")
            with Horizontal(id="toolbar"):
                yield Button("新建[N]", variant="primary", id="btn-new")
                yield Button("编辑[E]", variant="default", id="btn-edit")
                yield Button("删除[D]", variant="error", id="btn-delete")
                yield Button("暂停/恢复[P]", variant="warning", id="btn-toggle")
                yield Button("批量启停[B]", variant="default", id="btn-batch")
                yield Button("撤销[^Z]", variant="default", id="btn-undo")
                yield Button("备份[^B]", variant="default", id="btn-backups")
                yield Button("日志[L]", variant="default", id="btn-logs")
                yield Button("审计[^A]", variant="default", id="btn-audit")
                yield Button("刷新[R]", variant="success", id="btn-refresh")
            with Horizontal(id="search-bar"):
                yield Input(
                    placeholder="搜索 (关键词 / tag:标签名 按标签过滤)...",
                    id="search-input",
                )
            yield JobTable(multi_host=self._multi_host, id="job-table")
            yield Static("", id="detail-panel")
            yield LogViewer(id="log-viewer")
        yield Static("就绪", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        if self._multi_host:
            selector = self.query_one("#host-selector", HostSelector)
            hosts = [
                (b.host_id, b.display_name) for b in self._backends
            ]
            selector.set_hosts(hosts)
        self._load_all_crontabs()

    @work(exclusive=True, thread=False)
    async def _load_all_crontabs(self) -> None:
        """Load crontab from all backends concurrently."""
        all_lines: list[CrontabLine] = []

        async def load_one(backend: CrontabBackend) -> list[CrontabLine]:
            # Check cache first
            cached = self._cache.get(backend.host_id)
            if cached is not None:
                return cached
            try:
                lines = await backend.read_crontab()
                # Cache the result
                content_hash = await backend.get_content_hash()
                self._cache.put(backend.host_id, lines, content_hash)
                # Load tags for each job
                await self._load_tags_for_lines(lines)
                return lines
            except CrontabError as e:
                self._update_status(f"[{backend.host_id}] {e}")
                await self._audit.log(
                    host=backend.host_id,
                    operation="read",
                    success=False,
                    error_message=str(e),
                )
                return []

        tasks = [load_one(b) for b in self._backends]
        results = await asyncio.gather(*tasks)

        for lines in results:
            all_lines.extend(lines)

        self._all_lines = all_lines
        self._pending_changes = list(all_lines)
        self._refresh_table()

        job_count = sum(1 for l in all_lines if l.line_type == LineType.CRON_JOB)
        host_count = len(self._backends)
        if self._multi_host:
            self._update_status(
                f"已加载 {job_count} 个任务 (来自 {host_count} 台主机)"
            )
        else:
            self._update_status(f"已加载 {job_count} 个任务")
        self._check_tz_warnings()

    async def _load_tags_for_lines(self, lines: list[CrontabLine]) -> None:
        """Load saved tags for each cron job line."""
        for line in lines:
            if line.line_type == LineType.CRON_JOB and line.command:
                line.tags = await self._tags.get_tags(line.host, line.command)

    def _check_tz_warnings(self) -> None:
        for line in self._all_lines:
            if line.tz_warning:
                self._update_status(
                    f"⚠ [{line.host}] 第{line.line_number}行 "
                    f"{line.env_name}={line.env_value}: {line.tz_warning}"
                )
                break

    def _refresh_table(self) -> None:
        table = self.query_one("#job-table", JobTable)
        table.load_jobs(
            self._pending_changes,
            filter_text=self._filter_text,
            host_filter=self._selected_host,
            tag_filter=self._tag_filter,
        )

    @property
    def _job_count(self) -> int:
        return sum(1 for l in self._all_lines if l.line_type == LineType.CRON_JOB)

    def _update_status(self, msg: str) -> None:
        status = self.query_one("#status-bar", Static)
        undo_info = ""
        local_backend = self._get_local_backend()
        if local_backend and local_backend.manager.can_undo:
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
        next_run = (
            line.next_run.strftime("%Y-%m-%d %H:%M:%S") if line.next_run else "-"
        )
        last_run = (
            line.last_run.strftime("%Y-%m-%d %H:%M:%S") if line.last_run else "-"
        )

        host_info = f" | [b]主机:[/b] {line.host}" if self._multi_host else ""
        tags_info = f" | [b]标签:[/b] {', '.join(line.tags)}" if line.tags else ""

        detail = (
            f"[b]命令:[/b] {line.command}\n"
            f"[b]调度:[/b] {line.schedule} → {desc}\n"
            f"[b]状态:[/b] {status} | [b]运行中:[/b] {running}{host_info}{tags_info}\n"
            f"[b]下次执行:[/b] {next_run} | [b]上次执行:[/b] {last_run}"
        )
        panel.update(detail)

    def _get_local_backend(self) -> Optional[LocalBackend]:
        for b in self._backends:
            if isinstance(b, LocalBackend):
                return b
        return None

    def _get_backend_for_host(self, host_id: str) -> Optional[CrontabBackend]:
        for b in self._backends:
            if b.host_id == host_id:
                return b
        return None

    def _get_lines_for_host(self, host_id: str) -> list[CrontabLine]:
        """Get all lines belonging to a specific host."""
        return [l for l in self._pending_changes if l.host == host_id]

    # --- Event handlers ---

    def on_button_pressed(self, event: Button.Pressed) -> None:
        actions = {
            "btn-new": self.action_new_job,
            "btn-edit": self.action_edit_job,
            "btn-delete": self.action_delete_job,
            "btn-toggle": self.action_toggle_job,
            "btn-batch": self.action_batch_toggle,
            "btn-undo": self.action_undo,
            "btn-backups": self.action_show_backups,
            "btn-logs": self.action_view_logs,
            "btn-audit": self.action_show_audit,
            "btn-refresh": self.action_refresh,
        }
        action = actions.get(event.button.id)
        if action:
            action()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "search-input":
            value = event.value
            # Support tag: prefix for tag filtering
            if value.lower().startswith("tag:"):
                self._tag_filter = value[4:].strip()
                self._filter_text = ""
            else:
                self._tag_filter = ""
                self._filter_text = value
            self._refresh_table()

    def on_host_selector_host_changed(self, event: HostSelector.HostChanged) -> None:
        self._selected_host = event.host_id
        self._refresh_table()

    def on_job_table_job_selected(self, event: JobTable.JobSelected) -> None:
        self._update_detail(event.line)

    def on_job_table_job_activated(self, event: JobTable.JobActivated) -> None:
        self._edit_line(event.line)

    def on_job_table_page_changed(self, event: JobTable.PageChanged) -> None:
        page_info = self.query_one("#page-info", Static)
        page_info.update(
            f"第 {event.page}/{event.total_pages} 页 "
            f"({event.total_jobs} 个任务)"
        )

    # --- Actions ---

    def action_new_job(self) -> None:
        self.push_screen(EditJobScreen(), self._on_new_job_result)

    def _on_new_job_result(self, result: CrontabLine | None) -> None:
        if result is None:
            return
        # Assign to currently selected host (or localhost)
        target_host = (
            self._selected_host
            if self._selected_host != "__all__"
            else "localhost"
        )
        result.host = target_host
        self._pending_changes.append(result)
        self._confirm_and_write("新建任务", target_host)

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
        self._confirm_and_write("编辑任务", result.host)

    def action_delete_job(self) -> None:
        table = self.query_one("#job-table", JobTable)
        line = table.get_selected_line()
        if line is None:
            return
        host = line.host
        self._pending_changes = [l for l in self._pending_changes if l is not line]
        self._confirm_and_write("删除任务", host)

    def action_toggle_job(self) -> None:
        table = self.query_one("#job-table", JobTable)
        line = table.get_selected_line()
        if line is None:
            return
        line.enabled = not line.enabled
        self._confirm_and_write("切换启停状态", line.host)

    def action_batch_toggle(self) -> None:
        table = self.query_one("#job-table", JobTable)
        checked = table.get_checked_lines()
        if not checked:
            self._update_status("请先选择任务 (Space 选择)")
            return

        # Group by host
        hosts_affected: set[str] = set()
        any_enabled = any(l.enabled for l in checked)
        for line in checked:
            line.enabled = not any_enabled
            hosts_affected.add(line.host)

        desc = f"批量{'禁用' if any_enabled else '启用'} {len(checked)} 个任务"
        # Write to each affected host
        for host in hosts_affected:
            self._confirm_and_write(desc, host)

    def action_undo(self) -> None:
        local = self._get_local_backend()
        if not local:
            return
        try:
            result = local.manager.undo()
            if result is None:
                self._update_status("没有可撤销的操作")
                return
            for line in result:
                line.host = "localhost"
            # Replace localhost lines
            self._all_lines = [
                l for l in self._all_lines if l.host != "localhost"
            ] + result
            self._pending_changes = list(self._all_lines)
            self._cache.invalidate("localhost")
            self._refresh_table()
            self._update_status("已撤销")
        except CrontabError as e:
            self._update_status(f"撤销失败: {e}")

    def action_redo(self) -> None:
        local = self._get_local_backend()
        if not local:
            return
        try:
            result = local.manager.redo()
            if result is None:
                self._update_status("没有可重做的操作")
                return
            for line in result:
                line.host = "localhost"
            self._all_lines = [
                l for l in self._all_lines if l.host != "localhost"
            ] + result
            self._pending_changes = list(self._all_lines)
            self._cache.invalidate("localhost")
            self._refresh_table()
            self._update_status("已重做")
        except CrontabError as e:
            self._update_status(f"重做失败: {e}")

    def action_show_backups(self) -> None:
        local = self._get_local_backend()
        if not local:
            return
        backups = local.manager.list_backups()
        if not backups:
            self._update_status("没有可用备份")
            return
        self.push_screen(BackupScreen(backups), self._on_backup_selected)

    def _on_backup_selected(self, backup_path: Path | None) -> None:
        if backup_path is None:
            return
        local = self._get_local_backend()
        if not local:
            return
        try:
            lines = local.manager.restore_backup(backup_path)
            for line in lines:
                line.host = "localhost"
            self._all_lines = [
                l for l in self._all_lines if l.host != "localhost"
            ] + lines
            self._pending_changes = list(self._all_lines)
            self._cache.invalidate("localhost")
            self._refresh_table()
            self._update_status(f"已从备份恢复: {backup_path.name}")
        except CrontabError as e:
            self._update_status(f"恢复失败: {e}")

    def action_export(self) -> None:
        target_host = (
            self._selected_host
            if self._selected_host != "__all__"
            else "localhost"
        )
        export_path = str(
            Path.home()
            / f"crontab_export_{target_host}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        if target_host == "localhost":
            local = self._get_local_backend()
            if not local:
                return
            try:
                local.manager.export_crontab(export_path)
                self._update_status(f"已导出到: {export_path}")
            except CrontabError as e:
                self._update_status(f"导出失败: {e}")
        else:
            self._export_remote(target_host, export_path)

    @work(thread=False)
    async def _export_remote(self, host_id: str, export_path: str) -> None:
        backend = self._get_backend_for_host(host_id)
        if not isinstance(backend, RemoteBackend):
            return
        try:
            text = await backend.export_crontab()
            Path(export_path).write_text(text, encoding="utf-8")
            self._update_status(f"已导出 [{host_id}] 到: {export_path}")
            await self._audit.log(
                host=host_id, operation="export", description=export_path
            )
        except CrontabError as e:
            self._update_status(f"导出失败: {e}")

    def action_import_(self) -> None:
        import_path = str(Path.home() / "crontab_import.txt")
        if not Path(import_path).exists():
            self._update_status(f"请将导入文件放在: {import_path}")
            return
        target_host = (
            self._selected_host
            if self._selected_host != "__all__"
            else "localhost"
        )
        if target_host == "localhost":
            local = self._get_local_backend()
            if not local:
                return
            try:
                lines = local.manager.import_crontab(import_path)
                for line in lines:
                    line.host = "localhost"
                self._pending_changes = [
                    l for l in self._pending_changes if l.host != "localhost"
                ] + lines
                self._refresh_table()
                job_count = sum(
                    1 for l in lines if l.line_type == LineType.CRON_JOB
                )
                self._update_status(
                    f"已导入 {job_count} 个任务，正在确认写入..."
                )
                self._confirm_and_write(f"导入 {job_count} 个任务", "localhost")
            except CrontabError as e:
                self._update_status(f"导入失败: {e}")
        else:
            self._import_remote(target_host, import_path)

    @work(thread=False)
    async def _import_remote(self, host_id: str, path: str) -> None:
        backend = self._get_backend_for_host(host_id)
        if not isinstance(backend, RemoteBackend):
            self._update_status(f"未找到远程主机: {host_id}")
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
            lines = await backend.import_crontab(text)
            self._pending_changes = [
                l for l in self._pending_changes if l.host != host_id
            ] + lines
            self._refresh_table()
            job_count = sum(1 for l in lines if l.line_type == LineType.CRON_JOB)
            self._update_status(
                f"已导入 [{host_id}] {job_count} 个任务，正在确认写入..."
            )
            # Trigger the full confirm-and-write flow
            self.call_later(
                lambda: self._confirm_and_write(
                    f"导入 {job_count} 个任务", host_id
                )
            )
        except CrontabError as e:
            self._update_status(f"导入失败: {e}")
        except OSError as e:
            self._update_status(f"读取导入文件失败: {e}")

    def action_view_logs(self) -> None:
        table = self.query_one("#job-table", JobTable)
        line = table.get_selected_line()
        if line is None or not line.command:
            self._update_status("请先选择一个任务")
            return
        self._fetch_logs(line)

    @work(thread=False)
    async def _fetch_logs(self, line: CrontabLine) -> None:
        log_viewer = self.query_one("#log-viewer", LogViewer)
        backend = self._get_backend_for_host(line.host)

        if line.host == "localhost":
            # For local, use the same structured readers via subprocess
            import subprocess

            try:
                fragment = line.command.split()[0] if line.command else ""
                # Try journald first, then syslog
                result = await asyncio.to_thread(
                    subprocess.run,
                    [
                        "bash", "-c",
                        f"journalctl -u cron --no-pager -n 40 -o short-precise 2>/dev/null"
                        f" | grep -i '{fragment}' | tail -20"
                        f" || grep -i 'CRON' /var/log/syslog 2>/dev/null"
                        f" | grep -i '{fragment}' | tail -20"
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                from .logs.reader import SyslogReader
                reader = SyslogReader()
                if result.stdout.strip():
                    entries = reader._parse_and_correlate(result.stdout, 20)
                else:
                    entries = []
                log_viewer.show_logs(line.host, line.command or "", entries)
            except Exception:
                log_viewer.show_logs(line.host, line.command or "", [])
            return

        if not isinstance(backend, RemoteBackend):
            log_viewer.show_error("无法获取日志: 未知后端")
            return

        try:
            config = backend.config
            reader = create_log_reader(config.log_source, config.custom_log_path)
            conn = await self._pool.acquire(config)
            try:
                entries = await reader.fetch_logs(
                    conn, line.command or "", limit=20
                )
                log_viewer.show_logs(line.host, line.command or "", entries)
            finally:
                await self._pool.release(conn)
        except CrontabError as e:
            log_viewer.show_error(f"获取日志失败: {e}")

    def action_manage_tags(self) -> None:
        table = self.query_one("#job-table", JobTable)
        line = table.get_selected_line()
        if line is None or not line.command:
            self._update_status("请先选择一个任务")
            return
        self._open_tag_dialog(line)

    @work(thread=False)
    async def _open_tag_dialog(self, line: CrontabLine) -> None:
        all_tags = await self._tags.get_all_tags()
        self.app.push_screen(
            TagManageScreen(line, all_tags),
            lambda result: self._on_tag_result(result, line),
        )

    def _on_tag_result(self, result: TagResult | None, line: CrontabLine) -> None:
        if result is None:
            return
        self._apply_tag_changes(result, line)

    @work(thread=False)
    async def _apply_tag_changes(
        self, result: TagResult, line: CrontabLine
    ) -> None:
        """Apply tag additions and removals, then refresh UI."""
        changes_made: list[str] = []

        for tag in result.tags_to_add:
            await self._tags.add_tag(line.host, line.command, tag)
            if tag not in line.tags:
                line.tags.append(tag)
            changes_made.append(f"+{tag}")

        for tag in result.tags_to_remove:
            await self._tags.remove_tag(line.host, line.command, tag)
            if tag in line.tags:
                line.tags.remove(tag)
            changes_made.append(f"-{tag}")

        if changes_made:
            await self._audit.log(
                host=line.host,
                operation="tag",
                description=f"标签变更: {', '.join(changes_made)} | {line.command[:40]}",
                success=True,
            )
            self._refresh_table()
            self._update_detail(line)
            current = ", ".join(line.tags) if line.tags else "无"
            self._update_status(
                f"标签已更新 ({', '.join(changes_made)}) → 当前: {current}"
            )

    def action_show_audit(self) -> None:
        self._show_audit_panel()

    @work(thread=False)
    async def _show_audit_panel(self) -> None:
        records = await self._audit.query(limit=100)
        self.app.push_screen(AuditPanel(records))

    def action_refresh(self) -> None:
        self._cache.invalidate_all()
        self._load_all_crontabs()

    def action_focus_search(self) -> None:
        self.query_one("#search-input", Input).focus()

    def _confirm_and_write(self, description: str, host_id: str) -> None:
        """Show diff and require confirmation before writing."""
        host_lines = self._get_lines_for_host(host_id)

        if host_id == "localhost":
            local = self._get_local_backend()
            if not local:
                return
            diff = local.manager.get_diff(host_lines)
            if diff == "无变更":
                self._update_status("无变更")
                self._reload_host("localhost")
                return
            display_desc = description
        else:
            # For remote, we generate a simple description
            diff = f"将要写入到远程主机 [{host_id}]\n变更: {description}"
            display_desc = f"[{host_id}] {description}"

        self.push_screen(
            DiffConfirmScreen(diff, display_desc),
            lambda confirmed: self._on_write_confirmed(
                confirmed, description, host_id
            ),
        )

    def _on_write_confirmed(
        self, confirmed: bool, description: str, host_id: str
    ) -> None:
        if not confirmed:
            self._pending_changes = list(self._all_lines)
            self._refresh_table()
            self._update_status("已取消")
            return
        self._do_write(description, host_id)

    @work(thread=False)
    async def _do_write(self, description: str, host_id: str) -> None:
        """Write pending changes to the target host."""
        backend = self._get_backend_for_host(host_id)
        if backend is None:
            self._update_status(f"未找到主机: {host_id}")
            return

        host_lines = self._get_lines_for_host(host_id)

        try:
            await backend.write_crontab(host_lines, description)
            await self._audit.log(
                host=host_id,
                operation="write",
                description=description,
                success=True,
            )
            self._cache.invalidate(host_id)
            self._update_status(f"[{host_id}] 写入成功: {description}")
            # Reload this host's data
            await self._reload_host_async(host_id)
        except WriteFailedRolledBack as e:
            await self._audit.log(
                host=host_id,
                operation="write",
                success=False,
                error_message=str(e),
                description=description,
            )
            self._update_status(f"⚠ [{host_id}] {e}")
            await self._reload_host_async(host_id)
        except ConcurrentModificationError as e:
            await self._audit.log(
                host=host_id,
                operation="write",
                success=False,
                error_message=str(e),
                description=description,
            )
            self._update_status(f"⚠ [{host_id}] crontab 被外部修改，正在重新加载...")
            self._cache.invalidate(host_id)
            await self._reload_host_async(host_id)
        except CrontabError as e:
            await self._audit.log(
                host=host_id,
                operation="write",
                success=False,
                error_message=str(e),
                description=description,
            )
            self._update_status(f"[{host_id}] 写入失败: {e}")
            await self._reload_host_async(host_id)

    def _reload_host(self, host_id: str) -> None:
        """Synchronous reload wrapper."""
        self._cache.invalidate(host_id)
        self._load_all_crontabs()

    async def _reload_host_async(self, host_id: str) -> None:
        """Reload a single host's crontab data."""
        backend = self._get_backend_for_host(host_id)
        if backend is None:
            return
        try:
            lines = await backend.read_crontab()
            content_hash = await backend.get_content_hash()
            self._cache.put(host_id, lines, content_hash)
            await self._load_tags_for_lines(lines)

            # Replace lines for this host
            self._all_lines = [
                l for l in self._all_lines if l.host != host_id
            ] + lines
            self._pending_changes = list(self._all_lines)
            self._refresh_table()
        except CrontabError as e:
            self._update_status(f"[{host_id}] 重新加载失败: {e}")

    async def _cleanup(self) -> None:
        """Clean up resources on exit."""
        await self._pool.close_all()

    def on_unmount(self) -> None:
        asyncio.ensure_future(self._cleanup())


def main():
    app = CronboardApp()
    app.run()


if __name__ == "__main__":
    main()
