"""Audit trail viewer widget."""

from __future__ import annotations

from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Label, Static
from textual.containers import Horizontal

from ..audit.models import AuditRecord


class AuditPanel(ModalScreen[None]):
    """Modal screen for viewing audit trail."""

    CSS = """
    AuditPanel {
        align: center middle;
    }
    #audit-container {
        width: 90%;
        height: 80%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #audit-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #audit-table {
        height: 1fr;
    }
    #audit-detail {
        height: 6;
        border-top: solid $primary;
        margin-top: 1;
    }
    .btn-row {
        height: 3;
        align: right middle;
    }
    """

    def __init__(self, records: list[AuditRecord], **kwargs):
        super().__init__(**kwargs)
        self._records = records

    def compose(self):
        with Vertical(id="audit-container"):
            yield Label("审计记录", id="audit-title")
            yield DataTable(id="audit-table", cursor_type="row", zebra_stripes=True)
            yield Static("", id="audit-detail")
            with Horizontal(classes="btn-row"):
                yield Button("关闭 [Esc]", variant="default", id="btn-close")

    def on_mount(self) -> None:
        table = self.query_one("#audit-table", DataTable)
        table.add_columns("时间", "主机", "操作", "描述", "结果")

        for record in self._records:
            ts = record.timestamp.strftime("%m-%d %H:%M:%S")
            result = "✓ 成功" if record.success else "✗ 失败"
            desc = (record.description or "")[:40]
            table.add_row(ts, record.host, record.operation, desc, result)

    def on_data_table_row_highlighted(
        self, event: DataTable.RowHighlighted
    ) -> None:
        if event.cursor_row is not None and event.cursor_row < len(self._records):
            record = self._records[event.cursor_row]
            detail_parts = [f"[b]用户:[/b] {record.username}"]
            if record.description:
                detail_parts.append(f"[b]描述:[/b] {record.description}")
            if record.error_message:
                detail_parts.append(f"[b]错误:[/b] [red]{record.error_message}[/red]")
            if record.diff:
                diff_preview = record.diff[:200]
                detail_parts.append(f"[b]变更:[/b] {diff_preview}")
            self.query_one("#audit-detail", Static).update("\n".join(detail_parts))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close":
            self.dismiss(None)

    def key_escape(self) -> None:
        self.dismiss(None)
