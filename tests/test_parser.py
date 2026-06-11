"""Tests for crontab parser - lossless round-trip parsing."""

import pytest

from cronboard.models import CrontabLine, LineType
from cronboard.parser import parse_crontab, serialize_crontab


SAMPLE_CRONTAB = """\
# System maintenance
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
MAILTO=admin@example.com

# Backup database every day at 2am
0 2 * * * /usr/local/bin/backup.sh --full

# Disabled cleanup job
# */5 * * * * /tmp/cleanup.sh

# Every Monday at 9am
0 9 * * 1 /opt/report/weekly.py --send-email

@reboot /usr/local/bin/startup-check.sh

*/10 * * * * curl -s https://example.com/health | logger

some unknown line that we preserve
"""


class TestParserLossless:
    """Test that parsing and serializing is lossless."""

    def test_round_trip(self):
        """Parse then serialize should produce identical output."""
        lines = parse_crontab(SAMPLE_CRONTAB)
        output = serialize_crontab(lines)
        assert output == SAMPLE_CRONTAB

    def test_blank_lines_preserved(self):
        lines = parse_crontab(SAMPLE_CRONTAB)
        blank_lines = [l for l in lines if l.line_type == LineType.BLANK]
        assert len(blank_lines) == 6

    def test_comments_preserved(self):
        lines = parse_crontab(SAMPLE_CRONTAB)
        comments = [l for l in lines if l.line_type == LineType.COMMENT]
        assert len(comments) >= 3

    def test_env_vars_parsed(self):
        lines = parse_crontab(SAMPLE_CRONTAB)
        env_vars = [l for l in lines if l.line_type == LineType.ENV_VAR]
        assert len(env_vars) == 3
        names = {l.env_name for l in env_vars}
        assert names == {"SHELL", "PATH", "MAILTO"}

    def test_cron_jobs_parsed(self):
        lines = parse_crontab(SAMPLE_CRONTAB)
        jobs = [l for l in lines if l.line_type == LineType.CRON_JOB]
        assert len(jobs) == 5

    def test_enabled_jobs(self):
        lines = parse_crontab(SAMPLE_CRONTAB)
        jobs = [l for l in lines if l.line_type == LineType.CRON_JOB]
        enabled = [j for j in jobs if j.enabled]
        assert len(enabled) == 4

    def test_disabled_job(self):
        lines = parse_crontab(SAMPLE_CRONTAB)
        jobs = [l for l in lines if l.line_type == LineType.CRON_JOB]
        disabled = [j for j in jobs if not j.enabled]
        assert len(disabled) == 1
        assert disabled[0].command == "/tmp/cleanup.sh"
        assert disabled[0].schedule == "*/5 * * * *"

    def test_special_schedule(self):
        lines = parse_crontab(SAMPLE_CRONTAB)
        jobs = [l for l in lines if l.line_type == LineType.CRON_JOB]
        reboot_jobs = [j for j in jobs if j.schedule and j.schedule.startswith("@")]
        assert len(reboot_jobs) == 1
        assert reboot_jobs[0].schedule == "@reboot"
        assert reboot_jobs[0].command == "/usr/local/bin/startup-check.sh"

    def test_unknown_lines_preserved(self):
        lines = parse_crontab(SAMPLE_CRONTAB)
        unknown = [l for l in lines if l.line_type == LineType.UNKNOWN]
        assert len(unknown) == 1
        assert "some unknown line" in unknown[0].raw

    def test_empty_crontab(self):
        lines = parse_crontab("")
        assert lines == []

    def test_only_comments(self):
        text = "# comment 1\n# comment 2\n"
        lines = parse_crontab(text)
        assert len(lines) == 2
        assert all(l.line_type == LineType.COMMENT for l in lines)
        assert serialize_crontab(lines) == text

    def test_complex_commands(self):
        text = "0 * * * * /bin/bash -c 'echo \"hello world\" | tee /tmp/out.log'\n"
        lines = parse_crontab(text)
        assert len(lines) == 1
        assert lines[0].line_type == LineType.CRON_JOB
        assert lines[0].command == "/bin/bash -c 'echo \"hello world\" | tee /tmp/out.log'"

    def test_toggle_disabled_round_trip(self):
        """Disabling a job and serializing should produce a commented line."""
        text = "0 2 * * * /usr/bin/backup.sh\n"
        lines = parse_crontab(text)
        lines[0].enabled = False
        output = serialize_crontab(lines)
        assert output == "# 0 2 * * * /usr/bin/backup.sh\n"

        # Re-parse the disabled version
        lines2 = parse_crontab(output)
        assert len(lines2) == 1
        assert lines2[0].line_type == LineType.CRON_JOB
        assert not lines2[0].enabled
        assert lines2[0].schedule == "0 2 * * *"
        assert lines2[0].command == "/usr/bin/backup.sh"


class TestParserEdgeCases:
    """Test edge cases in parsing."""

    def test_tab_separated_fields(self):
        text = "0\t2\t*\t*\t*\t/usr/bin/cmd\n"
        lines = parse_crontab(text)
        assert len(lines) == 1
        # Tabs are treated as whitespace in split
        assert lines[0].line_type == LineType.CRON_JOB

    def test_multiple_spaces_in_schedule(self):
        text = "0  2  *  *  *  /usr/bin/cmd\n"
        lines = parse_crontab(text)
        assert len(lines) == 1
        assert lines[0].command == "/usr/bin/cmd"

    def test_command_with_env_like_syntax(self):
        """A command that looks like KEY=value but is actually a cron job."""
        text = "0 2 * * * HOME=/tmp /usr/bin/cmd\n"
        lines = parse_crontab(text)
        assert len(lines) == 1
        assert lines[0].line_type == LineType.CRON_JOB

    def test_ranges_and_lists(self):
        text = "0 9-17 * * 1-5 /usr/bin/work.sh\n"
        lines = parse_crontab(text)
        assert len(lines) == 1
        assert lines[0].schedule == "0 9-17 * * 1-5"

    def test_step_values(self):
        text = "*/15 */2 1,15 * * /usr/bin/check.sh\n"
        lines = parse_crontab(text)
        assert len(lines) == 1
        assert lines[0].schedule == "*/15 */2 1,15 * *"
