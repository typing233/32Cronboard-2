"""Log viewer widget for displaying cron job execution logs."""

from __future__ import annotations

from textual.containers import Vertical
from textual.widgets import RichLog, Static

from ..logs.models import LogEntry


class LogViewer(Vertical):
    """Panel displaying cron execution logs for a selected job."""

    DEFAULT_CSS = """
    LogViewer {
        height: 14;
        border-top: solid $primary;
        display: none;
    }
    LogViewer.visible {
        display: block;
    }
    #log-title {
        text-style: bold;
        height: 1;
        padding: 0 1;
    }
    #log-content {
        height: 1fr;
    }
    """

    def compose(self):
        yield Static("执行日志", id="log-title")
        yield RichLog(id="log-content", highlight=True, wrap=True)

    def show_logs(self, host: str, command: str, entries: list[LogEntry]) -> None:
        """Display log entries for a job with status, duration, exit code, failure."""
        self.add_class("visible")
        title = self.query_one("#log-title", Static)
        title.update(f"执行日志 [{host}] {command[:50]}")

        log = self.query_one("#log-content", RichLog)
        log.clear()

        if not entries:
            log.write("[dim]无可用日志记录[/dim]")
            return

        # Summary header
        success_count = sum(1 for e in entries if e.exit_code == 0)
        fail_count = sum(1 for e in entries if e.exit_code is not None and e.exit_code != 0)
        unknown_count = len(entries) - success_count - fail_count
        summary_parts = [f"共 {len(entries)} 条记录"]
        if success_count:
            summary_parts.append(f"[green]{success_count} 成功[/green]")
        if fail_count:
            summary_parts.append(f"[red]{fail_count} 失败[/red]")
        if unknown_count:
            summary_parts.append(f"[dim]{unknown_count} 未知[/dim]")
        log.write(" | ".join(summary_parts))
        log.write("─" * 60)

        for entry in entries:
            line_parts: list[str] = []

            # Timestamp
            if entry.timestamp:
                line_parts.append(
                    f"[cyan]{entry.timestamp.strftime('%m-%d %H:%M:%S')}[/cyan]"
                )

            # User
            if entry.user:
                line_parts.append(f"[yellow]{entry.user}[/yellow]")

            # Exit code with color-coded status
            if entry.exit_code is not None:
                if entry.exit_code == 0:
                    line_parts.append("[green]✓ 成功[/green]")
                else:
                    line_parts.append(f"[red]✗ 失败(rc={entry.exit_code})[/red]")
            else:
                line_parts.append("[dim]? 状态未知[/dim]")

            # Duration
            if entry.duration_seconds is not None:
                line_parts.append(f"[blue]耗时:{entry.duration_display}[/blue]")

            # PID
            if entry.pid:
                line_parts.append(f"[dim]pid={entry.pid}[/dim]")

            log.write(" ".join(line_parts))

            # Command (second line, indented)
            if entry.command:
                cmd_display = entry.command[:70]
                log.write(f"  [dim]CMD:[/dim] {cmd_display}")

            # Failure reason / error message (third line, highlighted)
            if entry.message:
                log.write(f"  [red]原因: {entry.message[:80]}[/red]")
            elif entry.exit_code is not None and entry.exit_code != 0 and not entry.message:
                log.write(f"  [red]原因: 进程异常退出 (退出码 {entry.exit_code})[/red]")

    def show_error(self, message: str) -> None:
        self.add_class("visible")
        log = self.query_one("#log-content", RichLog)
        log.clear()
        log.write(f"[red]{message}[/red]")

    def hide(self) -> None:
        self.remove_class("visible")
