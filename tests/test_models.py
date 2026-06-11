"""Tests for models."""

from cronboard.models import CrontabLine, CrontabState, LineType
from datetime import datetime


class TestCrontabLine:
    def test_display_command_short(self):
        line = CrontabLine(
            raw="0 2 * * * /usr/bin/cmd",
            line_type=LineType.CRON_JOB,
            line_number=1,
            command="/usr/bin/cmd",
        )
        assert line.display_command == "/usr/bin/cmd"

    def test_display_command_long(self):
        long_cmd = "/usr/bin/very-long-command-" + "x" * 100
        line = CrontabLine(
            raw=f"0 2 * * * {long_cmd}",
            line_type=LineType.CRON_JOB,
            line_number=1,
            command=long_cmd,
        )
        assert len(line.display_command) == 80
        assert line.display_command.endswith("...")

    def test_to_crontab_line_enabled(self):
        line = CrontabLine(
            raw="0 2 * * * /usr/bin/cmd",
            line_type=LineType.CRON_JOB,
            line_number=1,
            schedule="0 2 * * *",
            command="/usr/bin/cmd",
            enabled=True,
        )
        assert line.to_crontab_line() == "0 2 * * * /usr/bin/cmd"

    def test_to_crontab_line_disabled(self):
        line = CrontabLine(
            raw="0 2 * * * /usr/bin/cmd",
            line_type=LineType.CRON_JOB,
            line_number=1,
            schedule="0 2 * * *",
            command="/usr/bin/cmd",
            enabled=False,
        )
        assert line.to_crontab_line() == "# 0 2 * * * /usr/bin/cmd"

    def test_to_crontab_line_comment(self):
        line = CrontabLine(
            raw="# This is a comment",
            line_type=LineType.COMMENT,
            line_number=1,
        )
        assert line.to_crontab_line() == "# This is a comment"

    def test_to_crontab_line_blank(self):
        line = CrontabLine(
            raw="",
            line_type=LineType.BLANK,
            line_number=1,
        )
        assert line.to_crontab_line() == ""


class TestCrontabState:
    def test_to_text(self):
        lines = [
            CrontabLine(
                raw="0 2 * * * /usr/bin/cmd",
                line_type=LineType.CRON_JOB,
                line_number=1,
                schedule="0 2 * * *",
                command="/usr/bin/cmd",
                enabled=True,
            ),
            CrontabLine(
                raw="# comment",
                line_type=LineType.COMMENT,
                line_number=2,
            ),
        ]
        state = CrontabState(
            lines=lines,
            timestamp=datetime.now(),
            description="test",
        )
        text = state.to_text()
        assert text == "0 2 * * * /usr/bin/cmd\n# comment\n"
