"""Tag management dialog for adding/removing tags on cron jobs."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from ..models import CrontabLine


class TagResult:
    """Result from the tag management dialog."""

    def __init__(self, tags_to_add: list[str], tags_to_remove: list[str]):
        self.tags_to_add = tags_to_add
        self.tags_to_remove = tags_to_remove


class TagManageScreen(ModalScreen[TagResult | None]):
    """Modal dialog for managing tags on a cron job."""

    CSS = """
    TagManageScreen {
        align: center middle;
    }
    #tag-container {
        width: 70%;
        height: auto;
        max-height: 60%;
        border: thick $accent;
        background: $surface;
        padding: 1 2;
    }
    #tag-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #tag-command-info {
        margin-bottom: 1;
        color: $text-muted;
    }
    #current-tags {
        margin-bottom: 1;
    }
    #tag-add-row {
        height: 3;
        margin-bottom: 1;
    }
    #tag-add-input {
        width: 1fr;
    }
    #tag-remove-row {
        height: 3;
        margin-bottom: 1;
    }
    #tag-remove-input {
        width: 1fr;
    }
    .btn-row {
        height: 3;
        align: right middle;
    }
    .btn-row Button {
        margin-left: 1;
    }
    .section-label {
        height: 1;
        margin-bottom: 0;
    }
    """

    def __init__(self, line: CrontabLine, all_tags: list[str], **kwargs):
        super().__init__(**kwargs)
        self._line = line
        self._all_tags = all_tags
        self._tags_to_add: list[str] = []
        self._tags_to_remove: list[str] = []

    def compose(self) -> ComposeResult:
        cmd_display = (self._line.command or "")[:60]
        current = ", ".join(self._line.tags) if self._line.tags else "无"
        available = ", ".join(
            t for t in self._all_tags if t not in self._line.tags
        )

        with Vertical(id="tag-container"):
            yield Label("标签管理", id="tag-title")
            yield Static(
                f"[b]任务:[/b] {cmd_display}\n[b]主机:[/b] {self._line.host}",
                id="tag-command-info",
            )
            yield Static(
                f"[b]当前标签:[/b] {current}",
                id="current-tags",
            )
            if available:
                yield Static(
                    f"[dim]已有标签: {available}[/dim]",
                    classes="section-label",
                )
            yield Label("添加标签 (多个用逗号分隔):", classes="section-label")
            with Horizontal(id="tag-add-row"):
                yield Input(
                    placeholder="输入标签名，如: production, backup",
                    id="tag-add-input",
                )
            if self._line.tags:
                yield Label("移除标签 (多个用逗号分隔):", classes="section-label")
                with Horizontal(id="tag-remove-row"):
                    yield Input(
                        placeholder=f"可移除: {', '.join(self._line.tags)}",
                        id="tag-remove-input",
                    )
            with Horizontal(classes="btn-row"):
                yield Button("取消 [Esc]", variant="default", id="btn-cancel")
                yield Button("确认", variant="primary", id="btn-apply")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-apply":
            self._apply()

    def _apply(self) -> None:
        add_input = self.query_one("#tag-add-input", Input)
        add_text = add_input.value.strip()

        tags_to_add = [
            t.strip()
            for t in add_text.split(",")
            if t.strip() and t.strip() not in self._line.tags
        ]

        tags_to_remove: list[str] = []
        try:
            remove_input = self.query_one("#tag-remove-input", Input)
            remove_text = remove_input.value.strip()
            tags_to_remove = [
                t.strip()
                for t in remove_text.split(",")
                if t.strip() and t.strip() in self._line.tags
            ]
        except Exception:
            pass

        if not tags_to_add and not tags_to_remove:
            self.dismiss(None)
            return

        self.dismiss(TagResult(tags_to_add, tags_to_remove))

    def key_escape(self) -> None:
        self.dismiss(None)

    def key_enter(self) -> None:
        self._apply()
