"""Edit dialog for cron jobs."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static
from textual.reactive import reactive

from ..cron_expr import describe_expression, validate_expression
from ..models import CrontabLine, LineType


class EditJobScreen(ModalScreen[CrontabLine | None]):
    """Modal screen for creating/editing a cron job."""

    CSS = """
    EditJobScreen {
        align: center middle;
    }
    #edit-dialog {
        width: 80;
        height: auto;
        max-height: 30;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #edit-dialog Label {
        margin-bottom: 1;
    }
    #schedule-input {
        margin-bottom: 0;
    }
    #schedule-desc {
        color: $text-muted;
        margin-bottom: 1;
        height: 1;
    }
    #schedule-error {
        color: $error;
        margin-bottom: 1;
        height: 1;
    }
    #command-input {
        margin-bottom: 1;
    }
    .btn-row {
        height: 3;
        align: right middle;
    }
    .btn-row Button {
        margin-left: 1;
    }
    """

    def __init__(self, existing: CrontabLine | None = None, **kwargs):
        super().__init__(**kwargs)
        self._existing = existing

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-dialog"):
            yield Label("编辑 Cron 任务" if self._existing else "新建 Cron 任务")
            yield Label("调度表达式:")
            yield Input(
                placeholder="* * * * * 或 @daily",
                id="schedule-input",
                value=self._existing.schedule if self._existing else "",
            )
            yield Static("", id="schedule-desc")
            yield Static("", id="schedule-error")
            yield Label("命令:")
            yield Input(
                placeholder="/path/to/script.sh",
                id="command-input",
                value=self._existing.command if self._existing else "",
            )
            with Horizontal(classes="btn-row"):
                yield Button("取消", variant="default", id="btn-cancel")
                yield Button("确定", variant="primary", id="btn-ok")

    def on_mount(self) -> None:
        if self._existing and self._existing.schedule:
            self._validate_schedule(self._existing.schedule)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "schedule-input":
            self._validate_schedule(event.value)

    def _validate_schedule(self, value: str) -> None:
        desc_widget = self.query_one("#schedule-desc", Static)
        error_widget = self.query_one("#schedule-error", Static)

        if not value.strip():
            desc_widget.update("")
            error_widget.update("")
            return

        valid, err = validate_expression(value)
        if valid:
            desc_widget.update(f"📅 {describe_expression(value)}")
            error_widget.update("")
        else:
            desc_widget.update("")
            error_widget.update(f"⚠ {err}")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-ok":
            self._submit()

    def _submit(self) -> None:
        schedule = self.query_one("#schedule-input", Input).value.strip()
        command = self.query_one("#command-input", Input).value.strip()

        if not schedule or not command:
            error_widget = self.query_one("#schedule-error", Static)
            error_widget.update("⚠ 调度表达式和命令不能为空")
            return

        valid, err = validate_expression(schedule)
        if not valid:
            return

        if self._existing:
            self._existing.schedule = schedule
            self._existing.command = command
            self._existing.raw = f"{schedule} {command}"
            self.dismiss(self._existing)
        else:
            new_line = CrontabLine(
                raw=f"{schedule} {command}",
                line_type=LineType.CRON_JOB,
                line_number=0,
                schedule=schedule,
                command=command,
                enabled=True,
            )
            self.dismiss(new_line)
