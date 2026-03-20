"""
tests/test_pr4_manifest_presentation.py
=========================================

PR-4: Standardize manifest presentation outputs.

Validates that:
  1. ``execution_path`` is always present in every response from
     :meth:`~core.openclawd.OpenClawd.process`.
  2. ``execution_result`` is always present and fully JSON-serialisable.
  3. A text-only (chat) flow yields ``execution_path="none"``.
  4. Local execution (action_taken != noop) yields ``execution_path="local"``.
  5. Cross-device entry mode yields ``execution_path="cross_device"``.
  6. ``_determine_execution_path`` correctly maps combinations.
  7. Observability log is emitted at INFO level when execution_path is set.
  8. Error path response always includes execution_path and execution_result.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.execution.decision_executor import ExecutionResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_openclawd():
    """Return a minimal OpenClawd instance with heavy init suppressed."""
    with patch("core.openclawd.OpenClawd.__init__", return_value=None):
        from core.openclawd import OpenClawd
        oc = OpenClawd.__new__(OpenClawd)
    oc._continuum_orchestrator = None
    oc._decision_executor = None
    oc._request_count = 0
    oc._error_count = 0
    oc._session_memory = {}
    return oc


def _make_fake_process(
    *,
    entry_mode: str = "local",
    action_taken: str = "noop",
    skipped_reason: Optional[str] = "enable_system_actions=false",
    cross_device: bool = False,
    raise_error: bool = False,
) -> dict:
    """Return the result of a stubbed OpenClawd.process() call."""
    from core.openclawd import OpenClawd

    oc = _make_openclawd()

    # --- stub helpers that are too heavy to import ---
    oc._record_turn = AsyncMock()
    oc._get_kernel = lambda: None
    oc._get_router = lambda: None
    oc._ensure_initialized = lambda: None

    # _run_continuum returns a trivial state
    oc._run_continuum = lambda **kw: {
        "decision": {"action_level": "observe"},
        "metadata": {},
    }

    # _run_execution returns a mocked result dict
    exec_dict = {
        "action_taken": action_taken,
        "target": None,
        "success": action_taken not in ("noop", "none"),
        "skipped_reason": skipped_reason,
        "metadata": {},
    }
    oc._run_execution = lambda state, entry_mode=None: exec_dict  # type: ignore[assignment]

    return oc


# ---------------------------------------------------------------------------
# A) _determine_execution_path unit tests
# ---------------------------------------------------------------------------

class TestDetermineExecutionPath:
    """Unit-test the static helper directly."""

    def _ep(self, entry_mode, action_taken, cross_device=False):
        from core.openclawd import OpenClawd
        result = {"action_taken": action_taken}
        return OpenClawd._determine_execution_path(
            entry_mode=entry_mode,
            execution_result=result,
            cross_device_dispatched=cross_device,
        )

    def test_local_noop_gives_none(self):
        assert self._ep("local", "noop") == "none"

    def test_local_action_gives_local(self):
        assert self._ep("local", "focus_window") == "local"

    def test_cross_device_entry_gives_cross_device(self):
        assert self._ep("cross_device", "noop") == "cross_device"

    def test_cross_device_dispatch_flag_gives_cross_device(self):
        assert self._ep("local", "noop", cross_device=True) == "cross_device"

    def test_hybrid_entry_gives_hybrid(self):
        assert self._ep("hybrid", "noop") == "hybrid"

    def test_local_action_with_cross_device_dispatch_gives_hybrid(self):
        assert self._ep("local", "launch_app", cross_device=True) == "hybrid"

    def test_error_action_gives_none(self):
        assert self._ep("local", "error") == "none"

    def test_none_action_gives_none(self):
        assert self._ep("local", "none") == "none"


# ---------------------------------------------------------------------------
# B) _run_execution returns a serialisable dict (not None)
# ---------------------------------------------------------------------------

class TestRunExecutionReturnType:
    def test_returns_dict(self):
        oc = _make_openclawd()
        mock_exec = MagicMock()
        mock_exec.execute.return_value = ExecutionResult(
            action_taken="noop", success=True, skipped_reason="observe"
        )
        oc._decision_executor = mock_exec
        result = oc._run_execution({"decision": {"action_level": "observe"}})
        assert isinstance(result, dict)

    def test_result_is_json_serialisable(self):
        oc = _make_openclawd()
        mock_exec = MagicMock()
        mock_exec.execute.return_value = ExecutionResult(
            action_taken="noop",
            success=True,
            skipped_reason="enable_system_actions=false",
            metadata={"pid": None, "error": None},
        )
        oc._decision_executor = mock_exec
        result = oc._run_execution(None, entry_mode="local")
        serialised = json.dumps(result)  # must not raise
        assert "action_taken" in json.loads(serialised)

    def test_executor_unavailable_returns_dict(self):
        oc = _make_openclawd()
        oc._decision_executor = None
        with patch.dict("sys.modules", {"core.execution.decision_executor": None}):  # type: ignore[dict-item]
            result = oc._run_execution(None)
        assert isinstance(result, dict)
        assert result.get("skipped_reason") is not None

    def test_executor_exception_returns_dict(self):
        oc = _make_openclawd()
        mock_exec = MagicMock()
        mock_exec.execute.side_effect = RuntimeError("boom")
        oc._decision_executor = mock_exec
        result = oc._run_execution({}, entry_mode="local")
        assert isinstance(result, dict)
        assert result["action_taken"] == "error"

    def test_required_keys_present(self):
        oc = _make_openclawd()
        mock_exec = MagicMock()
        mock_exec.execute.return_value = ExecutionResult(
            action_taken="launch_app", target="notepad.exe", success=True
        )
        oc._decision_executor = mock_exec
        result = oc._run_execution(
            {"decision": {"action_level": "execute"}}, entry_mode="local"
        )
        for key in ("action_taken", "success", "skipped_reason"):
            assert key in result, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# C) process() response always contains execution_path + execution_result
# ---------------------------------------------------------------------------

def _stub_process_internals(oc, *, action_taken="noop", skipped_reason=None):
    """Attach lightweight stubs so oc.process() can run end-to-end."""
    oc._request_count = 0
    oc._error_count = 0
    oc._session_memory = {}
    oc._record_turn = AsyncMock()
    oc._get_kernel = lambda: None
    oc._get_router = lambda: None
    oc._ensure_initialized = lambda: None
    oc._parse_intent = AsyncMock(return_value=None)
    oc._run_continuum = lambda **kw: {
        "decision": {"action_level": "observe"},
        "metadata": {},
    }
    exec_result = {
        "action_taken": action_taken,
        "target": None,
        "success": False,
        "skipped_reason": skipped_reason,
        "metadata": {},
    }
    oc._run_execution = lambda state, entry_mode=None: dict(exec_result)  # type: ignore[assignment]

    async def _fake_dispatch_chat(message, intent=None, device_id=None,
                                   session_id=None, trace_id=None):
        return {"success": True, "response": "hello", "metadata": {}}

    oc._dispatch_chat = _fake_dispatch_chat


class TestProcessResponseSchema:
    @pytest.mark.asyncio
    async def test_execution_path_always_present(self):
        oc = _make_openclawd()
        _stub_process_internals(oc)
        result = await oc.process(message="hello", session_id="s1")
        assert "execution_path" in result, "execution_path missing from response"

    @pytest.mark.asyncio
    async def test_execution_result_always_present(self):
        oc = _make_openclawd()
        _stub_process_internals(oc)
        result = await oc.process(message="hello", session_id="s1")
        assert "execution_result" in result, "execution_result missing from response"

    @pytest.mark.asyncio
    async def test_execution_result_is_serialisable(self):
        oc = _make_openclawd()
        _stub_process_internals(oc)
        result = await oc.process(message="hello", session_id="s1")
        exec_res = result["execution_result"]
        assert isinstance(exec_res, dict)
        json.dumps(exec_res)  # must not raise

    @pytest.mark.asyncio
    async def test_text_only_flow_gives_execution_path_none(self):
        """Chat (text-only) flow with noop executor → execution_path='none'."""
        oc = _make_openclawd()
        _stub_process_internals(oc, action_taken="noop", skipped_reason="enable_system_actions=false")
        result = await oc.process(message="tell me a joke", session_id="s2", entry_mode="local")
        assert result["execution_path"] == "none", (
            f"Expected 'none', got {result['execution_path']!r}"
        )

    @pytest.mark.asyncio
    async def test_execution_result_has_skipped_reason_when_none(self):
        oc = _make_openclawd()
        _stub_process_internals(oc, action_taken="noop", skipped_reason="enable_system_actions=false")
        result = await oc.process(message="hello", session_id="s3", entry_mode="local")
        exec_res = result["execution_result"]
        assert exec_res.get("skipped_reason"), (
            "skipped_reason should be set when execution_path='none'"
        )

    @pytest.mark.asyncio
    async def test_cross_device_entry_gives_cross_device_path(self):
        oc = _make_openclawd()
        _stub_process_internals(oc, action_taken="noop", skipped_reason="entry_mode=cross_device")
        result = await oc.process(
            message="run on device", session_id="s4", entry_mode="cross_device"
        )
        assert result["execution_path"] == "cross_device", (
            f"Expected 'cross_device', got {result['execution_path']!r}"
        )

    @pytest.mark.asyncio
    async def test_execution_path_in_metadata(self):
        """execution_path must also appear inside metadata for observability."""
        oc = _make_openclawd()
        _stub_process_internals(oc)
        result = await oc.process(message="hello", session_id="s5")
        meta = result.get("metadata", {})
        assert "execution_path" in meta, "execution_path missing from metadata"

    @pytest.mark.asyncio
    async def test_local_action_gives_local_path(self):
        """When executor takes a real action, execution_path should be 'local'."""
        oc = _make_openclawd()
        _stub_process_internals(oc, action_taken="launch_app", skipped_reason=None)
        result = await oc.process(message="open notepad", session_id="s6", entry_mode="local")
        assert result["execution_path"] == "local", (
            f"Expected 'local', got {result['execution_path']!r}"
        )


# ---------------------------------------------------------------------------
# D) Error path includes execution_path and execution_result
# ---------------------------------------------------------------------------

class TestErrorPathSchema:
    @pytest.mark.asyncio
    async def test_error_response_has_execution_path(self):
        oc = _make_openclawd()

        # Force an error inside the main try block (after _entry_mode is set)
        # by raising in _run_continuum which is called deep in the flow.
        oc._ensure_initialized = lambda: None
        oc._request_count = 0
        oc._error_count = 0
        oc._session_memory = {}
        oc._record_turn = AsyncMock()
        oc._get_kernel = lambda: None
        oc._get_router = lambda: None
        oc._parse_intent = AsyncMock(return_value=None)

        def _bad_continuum(**kw):
            raise RuntimeError("simulated continuum failure")

        oc._run_continuum = _bad_continuum

        async def _fake_dispatch_chat(message, intent=None, device_id=None,
                                       session_id=None, trace_id=None):
            return {"success": True, "response": "ok", "metadata": {}}

        oc._dispatch_chat = _fake_dispatch_chat

        result = await oc.process(message="hello", session_id="err_sess")
        assert "execution_path" in result
        assert result["execution_path"] == "none"

    @pytest.mark.asyncio
    async def test_error_response_has_execution_result(self):
        oc = _make_openclawd()

        oc._ensure_initialized = lambda: None
        oc._request_count = 0
        oc._error_count = 0
        oc._session_memory = {}
        oc._record_turn = AsyncMock()
        oc._get_kernel = lambda: None
        oc._get_router = lambda: None
        oc._parse_intent = AsyncMock(return_value=None)

        def _bad_continuum(**kw):
            raise RuntimeError("simulated continuum failure")

        oc._run_continuum = _bad_continuum

        async def _fake_dispatch_chat(message, intent=None, device_id=None,
                                       session_id=None, trace_id=None):
            return {"success": True, "response": "ok", "metadata": {}}

        oc._dispatch_chat = _fake_dispatch_chat

        result = await oc.process(message="hello", session_id="err_sess2")
        assert "execution_result" in result
        exec_res = result["execution_result"]
        assert isinstance(exec_res, dict)
        json.dumps(exec_res)  # must be serialisable


# ---------------------------------------------------------------------------
# E) Observability: structured log emitted when execution_path is set
# ---------------------------------------------------------------------------

class TestObservabilityLog:
    @pytest.mark.asyncio
    async def test_info_log_emitted_with_execution_path(self, caplog):
        oc = _make_openclawd()
        _stub_process_internals(oc)

        with caplog.at_level(logging.DEBUG):
            await oc.process(message="hello", session_id="obs_sess", entry_mode="local")

        log_messages = " ".join(caplog.messages)
        assert "execution_path" in log_messages, (
            "Expected 'execution_path' in log output; got: " + log_messages[:200]
        )

    @pytest.mark.asyncio
    async def test_log_contains_entry_mode(self, caplog):
        oc = _make_openclawd()
        _stub_process_internals(oc)

        with caplog.at_level(logging.DEBUG):
            await oc.process(message="hello", session_id="obs_sess2", entry_mode="cross_device")

        log_messages = " ".join(caplog.messages)
        assert "cross_device" in log_messages
