"""
Tests for the HEARTBEAT.md parser helpers in core/openclawd_heartbeat.py.

Validates:
- load_heartbeat_tasks() correctly reads file content.
- extract_task_lines() correctly extracts bullet lines.
- _load_yaml_config() correctly loads and merges YAML config.
- _parse_interval_seconds() handles all unit variants and edge cases.
"""

import os
import pytest

from core.openclawd_heartbeat import (
    load_heartbeat_tasks,
    extract_task_lines,
    _load_yaml_config,
    _parse_interval_seconds,
    _DEFAULT_CONFIG,
)


# ---------------------------------------------------------------------------
# load_heartbeat_tasks
# ---------------------------------------------------------------------------

class TestLoadHeartbeatTasks:
    def test_reads_file_content(self, tmp_path):
        hb = tmp_path / "HEARTBEAT.md"
        hb.write_text("# Tasks\n- check status\n", encoding="utf-8")
        content = load_heartbeat_tasks(str(hb))
        assert "check status" in content

    def test_returns_empty_for_missing_file(self, tmp_path):
        result = load_heartbeat_tasks(str(tmp_path / "MISSING.md"))
        assert result == ""

    def test_preserves_sections(self, tmp_path):
        text = "# Heartbeat Tasks\n\n## system check\n- check devices\n\n## jobs\n- every 30m: ping\n"
        hb = tmp_path / "HEARTBEAT.md"
        hb.write_text(text, encoding="utf-8")
        content = load_heartbeat_tasks(str(hb))
        assert "## system check" in content
        assert "## jobs" in content

    def test_unicode_content(self, tmp_path):
        hb = tmp_path / "HEARTBEAT.md"
        hb.write_text("- 检查设备状态\n- summarize logs\n", encoding="utf-8")
        content = load_heartbeat_tasks(str(hb))
        assert "检查设备状态" in content


# ---------------------------------------------------------------------------
# extract_task_lines
# ---------------------------------------------------------------------------

class TestExtractTaskLines:
    def test_basic_bullets(self):
        content = "# Heading\n- task one\n- task two\n"
        lines = extract_task_lines(content)
        assert lines == ["task one", "task two"]

    def test_ignores_headings_and_blanks(self):
        content = "# Top\n\n## Section\n\n- do this\n\n- do that\n"
        lines = extract_task_lines(content)
        assert lines == ["do this", "do that"]

    def test_indented_bullets(self):
        content = "  - indented task\n    - deeper\n"
        lines = extract_task_lines(content)
        assert lines == ["indented task", "deeper"]

    def test_empty_content(self):
        assert extract_task_lines("") == []

    def test_no_bullets(self):
        assert extract_task_lines("# No tasks here\nsome prose\n") == []

    def test_strips_task_text(self):
        lines = extract_task_lines("-   padded task   \n")
        assert lines == ["padded task"]

    def test_complex_dsl_entries(self):
        content = "- every 30m: check notifications\n- every 2h: check device health\n"
        lines = extract_task_lines(content)
        assert "every 30m: check notifications" in lines
        assert "every 2h: check device health" in lines


# ---------------------------------------------------------------------------
# _parse_interval_seconds
# ---------------------------------------------------------------------------

class TestParseIntervalSecondsExtended:
    def test_1m(self):
        assert _parse_interval_seconds("1m") == 60

    def test_1h(self):
        assert _parse_interval_seconds("1h") == 3600

    def test_1s(self):
        assert _parse_interval_seconds("1s") == 1

    def test_30_no_unit_is_seconds(self):
        assert _parse_interval_seconds("30") == 30

    def test_large_value(self):
        assert _parse_interval_seconds("120m") == 7200

    def test_garbage_defaults(self):
        assert _parse_interval_seconds("abc") == 1800

    def test_empty_string_defaults(self):
        assert _parse_interval_seconds("") == 1800


# ---------------------------------------------------------------------------
# _load_yaml_config
# ---------------------------------------------------------------------------

class TestLoadYamlConfig:
    def test_falls_back_to_defaults_when_file_missing(self, tmp_path):
        config = _load_yaml_config(str(tmp_path / "nonexistent.yaml"))
        assert config["heartbeat"]["enabled"] == _DEFAULT_CONFIG["heartbeat"]["enabled"]

    def test_loads_and_merges_yaml(self, tmp_path):
        yaml_text = "heartbeat:\n  enabled: false\n  interval: 5m\n"
        cfg_file = tmp_path / "agent.yaml"
        cfg_file.write_text(yaml_text, encoding="utf-8")
        try:
            config = _load_yaml_config(str(cfg_file))
            assert config["heartbeat"]["enabled"] is False
            assert config["heartbeat"]["interval"] == "5m"
            # Unspecified keys should be carried from defaults
            assert "ack_token" in config["heartbeat"]
        except ImportError:
            pytest.skip("PyYAML not installed")

    def test_absolute_path_resolution(self, tmp_path):
        """Absolute paths should be used as-is."""
        config = _load_yaml_config(str(tmp_path / "does_not_exist.yaml"))
        # Should gracefully return defaults
        assert "heartbeat" in config
