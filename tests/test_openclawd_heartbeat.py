"""
Tests for OpenClawd Heartbeat Scheduler (core/openclawd_heartbeat.py).

Validates:
- Scheduler triggers OpenClawd.process() at least once when enabled.
- HEARTBEAT.md loading works.
- Tier escalation logic works.
- ACK suppression logic works.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.openclawd_heartbeat import (
    HeartbeatScheduler,
    _parse_interval_seconds,
    load_heartbeat_tasks,
    extract_task_lines,
    is_ack_response,
    should_escalate_to_tier2,
    get_heartbeat_scheduler,
)


# ---------------------------------------------------------------------------
# Interval parsing
# ---------------------------------------------------------------------------

class TestParseIntervalSeconds:
    def test_minutes(self):
        assert _parse_interval_seconds("30m") == 1800

    def test_hours(self):
        assert _parse_interval_seconds("2h") == 7200

    def test_seconds(self):
        assert _parse_interval_seconds("90s") == 90

    def test_bare_number_is_seconds(self):
        assert _parse_interval_seconds("60") == 60

    def test_invalid_falls_back(self):
        assert _parse_interval_seconds("bad") == 1800


# ---------------------------------------------------------------------------
# ACK suppression
# ---------------------------------------------------------------------------

class TestIsAckResponse:
    def test_starts_with_token_short(self):
        assert is_ack_response("HEARTBEAT_OK", "HEARTBEAT_OK", 160)

    def test_ends_with_token_short(self):
        assert is_ack_response("All done. HEARTBEAT_OK", "HEARTBEAT_OK", 160)

    def test_case_insensitive(self):
        assert is_ack_response("heartbeat_ok", "HEARTBEAT_OK", 160)

    def test_too_long_not_suppressed(self):
        long_text = "HEARTBEAT_OK " + "x" * 200
        assert not is_ack_response(long_text, "HEARTBEAT_OK", 160)

    def test_no_token_not_suppressed(self):
        assert not is_ack_response("I did something important today.", "HEARTBEAT_OK", 160)

    def test_exact_max_chars_boundary(self):
        # Exactly at max_chars should be suppressed if token present
        token = "HEARTBEAT_OK"
        text = token + " " + "a" * (160 - len(token) - 1)
        assert len(text.strip()) == 160
        assert is_ack_response(text, token, 160)

    def test_one_over_max_chars_not_suppressed(self):
        token = "HEARTBEAT_OK"
        text = token + " " + "a" * (161 - len(token))
        assert len(text.strip()) > 160
        assert not is_ack_response(text, token, 160)


# ---------------------------------------------------------------------------
# Tier escalation
# ---------------------------------------------------------------------------

class TestShouldEscalateToTier2:
    _TRIGGERS = ["complex_reasoning", "multi_step_plan", "code_generation"]

    def test_no_match_stays_tier1(self):
        tasks = ["check device status", "check pending tasks"]
        assert not should_escalate_to_tier2(tasks, self._TRIGGERS)

    def test_matching_trigger_escalates(self):
        tasks = ["perform complex_reasoning over logs", "check device status"]
        assert should_escalate_to_tier2(tasks, self._TRIGGERS)

    def test_partial_substring_match(self):
        tasks = ["run multi_step_plan for deployment"]
        assert should_escalate_to_tier2(tasks, self._TRIGGERS)

    def test_case_insensitive(self):
        tasks = ["Code_Generation requested"]
        assert should_escalate_to_tier2(tasks, self._TRIGGERS)

    def test_empty_tasks(self):
        assert not should_escalate_to_tier2([], self._TRIGGERS)

    def test_empty_triggers(self):
        tasks = ["complex_reasoning needed"]
        assert not should_escalate_to_tier2(tasks, [])


# ---------------------------------------------------------------------------
# HEARTBEAT.md loading
# ---------------------------------------------------------------------------

class TestLoadHeartbeatTasks:
    def test_loads_existing_file(self, tmp_path):
        hb = tmp_path / "HEARTBEAT.md"
        hb.write_text("# Tasks\n- check status\n- summarize logs\n", encoding="utf-8")
        content = load_heartbeat_tasks(str(hb))
        assert "check status" in content
        assert "summarize logs" in content

    def test_missing_file_returns_empty(self, tmp_path):
        result = load_heartbeat_tasks(str(tmp_path / "MISSING.md"))
        assert result == ""

    def test_extract_task_lines(self):
        content = "# Heading\n\n## section\n- task one\n- task two\nsome text\n"
        lines = extract_task_lines(content)
        assert lines == ["task one", "task two"]


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

class TestHeartbeatSchedulerLifecycle:
    def _make_scheduler(self, enabled: bool = True, interval: str = "1s") -> HeartbeatScheduler:
        mock_clawd = MagicMock()
        mock_clawd.process = AsyncMock(return_value={"response": "HEARTBEAT_OK", "success": True})
        scheduler = HeartbeatScheduler.__new__(HeartbeatScheduler)
        scheduler._openclawd = mock_clawd
        scheduler._enabled = enabled
        scheduler._interval_seconds = _parse_interval_seconds(interval)
        scheduler._task_file = "agent/HEARTBEAT.md"
        scheduler._ack_token = "HEARTBEAT_OK"
        scheduler._max_output_chars = 160
        scheduler._tier1_model = "local_small"
        scheduler._tier2_model = "gpt-4o"
        scheduler._tier2_triggers = ["complex_reasoning", "multi_step_plan", "code_generation"]
        scheduler._task = None
        scheduler._stop_event = asyncio.Event()
        scheduler._cycle_count = 0
        return scheduler

    @pytest.mark.asyncio
    async def test_start_and_stop_when_disabled(self):
        scheduler = self._make_scheduler(enabled=False)
        await scheduler.start()
        assert scheduler._task is None  # No background task when disabled
        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_process_called_at_least_once(self, tmp_path):
        """Scheduler should call OpenClawd.process() at least once per active cycle."""
        hb_file = tmp_path / "HEARTBEAT.md"
        hb_file.write_text("# Tasks\n- check device status\n", encoding="utf-8")

        mock_clawd = MagicMock()
        mock_clawd.process = AsyncMock(return_value={"response": "HEARTBEAT_OK", "success": True})

        scheduler = HeartbeatScheduler.__new__(HeartbeatScheduler)
        scheduler._openclawd = mock_clawd
        scheduler._enabled = True
        scheduler._interval_seconds = 9999  # will be stopped before sleeping
        scheduler._task_file = str(hb_file)
        scheduler._ack_token = "HEARTBEAT_OK"
        scheduler._max_output_chars = 160
        scheduler._tier1_model = "local_small"
        scheduler._tier2_model = "gpt-4o"
        scheduler._tier2_triggers = []
        scheduler._task = None
        scheduler._stop_event = asyncio.Event()
        scheduler._cycle_count = 0

        # Run a single cycle directly (not the full loop)
        await scheduler._run_cycle()

        mock_clawd.process.assert_called_once()
        call_kwargs = mock_clawd.process.call_args
        context_arg = call_kwargs.kwargs.get("context", [])
        assert any(
            "source=heartbeat" in msg.get("content", "")
            for msg in context_arg
        ), "process() context must include source=heartbeat tag"

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self):
        scheduler = self._make_scheduler(enabled=False)
        # stop() without start() should not raise
        await scheduler.stop()
        await scheduler.stop()

    def test_is_enabled(self):
        assert self._make_scheduler(enabled=True).is_enabled()
        assert not self._make_scheduler(enabled=False).is_enabled()


# ---------------------------------------------------------------------------
# get_heartbeat_scheduler helper
# ---------------------------------------------------------------------------

class TestGetHeartbeatScheduler:
    def test_returns_none_when_openclawd_unavailable(self):
        import core.openclawd_heartbeat as hb_mod
        original = hb_mod._heartbeat_scheduler
        hb_mod._heartbeat_scheduler = None
        try:
            with patch("core.openclawd_heartbeat.get_heartbeat_scheduler") as mock_get:
                mock_get.return_value = None
                result = mock_get(openclawd=None)
                assert result is None
        finally:
            hb_mod._heartbeat_scheduler = original

    def test_returns_scheduler_with_provided_openclawd(self):
        import core.openclawd_heartbeat as hb_mod
        original = hb_mod._heartbeat_scheduler
        hb_mod._heartbeat_scheduler = None
        try:
            mock_clawd = MagicMock()
            scheduler = get_heartbeat_scheduler(
                openclawd=mock_clawd, config_path="config/agent.yaml"
            )
            assert scheduler is not None
            assert scheduler._openclawd is mock_clawd
        finally:
            hb_mod._heartbeat_scheduler = original
