"""Log viewer widget for displaying cron job execution logs."""

from __future__ import annotations

from textual.containers import Vertical
from textual.widgets import RichLog, Static

from ..logs.models import LogEntry


class LogViewer(Vertical):
    """Panel displaying cron execution logs for a selected job."""

    DEFAULT_CSS = """
    LogViewer {
        height: 12;
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
        """Display log entries for a job."""
        self.add_class("visible")
        title = self.query_one("#log-title", Static)
        title.update(f"执行日志 [{host}] {command[:50]}")

        log = self.query_one("#log-content", RichLog)
        log.clear()

        if not entries:
            log.write("[dim]无可用日志记录[/dim]")
            return

        for entry in entries:
            line_parts: list[str] = []
            if entry.timestamp:
                line_parts.append(
                    f"[cyan]{entry.timestamp.strftime('%m-%d %H:%M:%S')}[/cyan]"
                )
            if entry.user:
                line_parts.append(f"[yellow]{entry.user}[/yellow]")
            if entry.exit_code is not None:
                if entry.exit_code == 0:
                    line_parts.append("[green]成功[/green]")
                else:
                    line_parts.append(f"[red]失败(rc={entry.exit_code})[/red]")
            if entry.duration_seconds is not None:
                line_parts.append(f"[dim]{entry.duration_display}[/dim]")
            if entry.command:
                cmd_display = entry.command[:60]
                line_parts.append(cmd_display)
            elif entry.raw_line:
                line_parts.append(entry.raw_line[:80])

            log.write(" ".join(line_parts))

    def show_error(self, message: str) -> None:
        self.add_class("visible")
        log = self.query_one("#log-content", RichLog)
        log.clear()
        log.write(f"[red]{message}[/red]")

    def hide(self) -> None:
        self.remove_class("visible")
