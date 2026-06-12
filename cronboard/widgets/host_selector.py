"""Host selector widget for switching between servers."""

from __future__ import annotations

from textual.message import Message
from textual.widgets import Select


class HostSelector(Select[str]):
    """Dropdown for choosing which host to view."""

    class HostChanged(Message):
        def __init__(self, host_id: str) -> None:
            super().__init__()
            self.host_id = host_id

    def __init__(self, **kwargs):
        super().__init__(
            options=[("全部主机", "__all__")],
            value="__all__",
            allow_blank=False,
            **kwargs,
        )

    def set_hosts(self, hosts: list[tuple[str, str]]) -> None:
        """Update the host list. hosts = [(host_id, display_name), ...]"""
        options = [("全部主机", "__all__")]
        for host_id, display in hosts:
            options.append((display, host_id))
        self.set_options(options)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.value is not None:
            self.post_message(self.HostChanged(str(event.value)))
