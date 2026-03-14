"""
tests/test_remote_agent_dispatch.py
=====================================
Acceptance tests for Remote Agent Dispatch (PR155).

Covers the three acceptance gates:

  A) Remote dispatch end-to-end
     - OpenClawd dispatches ``agent_execute`` to a device and receives a
       successful result with ``trace_id`` / ``task_id`` / ``agent_id``
       preserved.

  B) Fallback behaviour
     - When device is offline or CommandRouter returns timeout/disconnect,
       OpenClawd returns a structured error **or** falls back to local
       execution (both paths are tested explicitly).

  C) Result persistence
     - The returned remote result is stored in task memory via backflow.

All LLM calls, network I/O, and external services are mocked.
No real device is required.
"""

import asyncio
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================================
# Shared fixtures
# ============================================================================

REMOTE_DEVICE_ID = "windows_remotehost"
LOCAL_DEVICE_ID = "local_openclawd"


def _make_cr_result(success: bool = True, error_code: str = None, result=None):
    """Build a minimal route_command / dispatch_agent_remote response."""
    return {
        "success": success,
        "result": result or {"output": "remote agent done", "response": "Task completed remotely"},
        "error_code": error_code,
        "error_message": None if success else f"simulated error: {error_code}",
        "task_id": "task_mock",
        "trace_id": "trace_mock",
        "agent_id": "remote_agent_mock",
        "session_id": "session_mock",
        "latency_ms": 12.3,
        "command_id": "cmd_mock",
        "device_id": REMOTE_DEVICE_ID,
        "command": "agent_execute",
        "via": "command_router",
        "request_id": "req_mock",
    }


# ============================================================================
# Gate A — Remote dispatch end-to-end
# ============================================================================

class TestRemoteDispatchEndToEnd:
    """Acceptance Gate A: successful remote dispatch preserves correlation IDs."""

    # ------------------------------------------------------------------
    # A-1  CommandRouter.dispatch_agent_remote contract
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_dispatch_agent_remote_returns_correlation_ids(self):
        """dispatch_agent_remote must return agent_id, task_id, trace_id."""
        from core.command_router import CommandRouter

        trace_id = f"trace_{uuid.uuid4().hex[:8]}"
        task_id = f"task_{uuid.uuid4().hex[:8]}"
        agent_id = f"remote_agent_{uuid.uuid4().hex[:6]}"

        cr = CommandRouter()
        mock_result = {
            "success": True,
            "result": {"output": "done"},
            "error_code": None,
            "error_message": None,
            "latency_ms": 5.0,
            "task_id": task_id,
            "trace_id": trace_id,
            "command_id": task_id,
            "device_id": REMOTE_DEVICE_ID,
            "command": "agent_execute",
            "via": "command_router",
            "request_id": task_id,
        }

        with patch.object(cr, "route_command", return_value=mock_result) as mock_rc:
            result = await cr.dispatch_agent_remote(
                device_id=REMOTE_DEVICE_ID,
                agent_id=agent_id,
                agent_template="analyst",
                task="Analyse system logs",
                session_id="sess_1",
                trace_id=trace_id,
                task_id=task_id,
            )

        # route_command must be called with command="agent_execute"
        mock_rc.assert_called_once()
        call_kwargs = mock_rc.call_args
        assert call_kwargs.kwargs.get("command") == "agent_execute" or \
               call_kwargs.args[1] == "agent_execute" or \
               (len(call_kwargs.args) > 1 and call_kwargs.args[1] == "agent_execute"), \
               f"Expected command='agent_execute', got: {call_kwargs}"

        # Correlation IDs must be preserved
        assert result["agent_id"] == agent_id
        assert result["task_id"] == task_id
        assert result["trace_id"] == trace_id
        assert result["session_id"] == "sess_1"
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_dispatch_agent_remote_payload_includes_all_required_fields(self):
        """dispatch_agent_remote must forward all required payload fields."""
        from core.command_router import CommandRouter

        cr = CommandRouter()
        captured_payload = {}

        async def capture_route_command(device_id, command, payload, **kwargs):
            captured_payload.update(payload)
            return _make_cr_result(success=True)

        cr.route_command = capture_route_command

        trace_id = "trace_e2e_001"
        task_id = "task_e2e_001"
        agent_id = "agent_e2e_001"

        await cr.dispatch_agent_remote(
            device_id=REMOTE_DEVICE_ID,
            agent_id=agent_id,
            agent_template="executor",
            task="open notepad",
            session_id="sess_e2e",
            trace_id=trace_id,
            task_id=task_id,
            context={"window": "notepad"},
        )

        # All required fields per PR155 contract
        for field in ("agent_id", "agent_template", "task", "session_id",
                      "trace_id", "task_id", "context"):
            assert field in captured_payload, f"Payload missing field: {field}"

        assert captured_payload["agent_id"] == agent_id
        assert captured_payload["trace_id"] == trace_id
        assert captured_payload["task_id"] == task_id
        assert captured_payload["context"]["window"] == "notepad"

    # ------------------------------------------------------------------
    # A-2  OpenClawd._dispatch_remote_agent path
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_dispatch_remote_agent_preserves_trace_in_metadata(self):
        """_dispatch_remote_agent result.metadata must contain trace/task/agent IDs."""
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = True
        clawd._start_time = 0.0
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._session_memory = {}
        clawd._cancel_registry = set()

        trace_id = f"trace_{uuid.uuid4().hex[:8]}"

        mock_cr = MagicMock()
        mock_cr.dispatch_agent_remote = AsyncMock(return_value=_make_cr_result(
            success=True,
            result={"output": "remote done", "response": "Completed on remote device"},
        ))
        mock_cr.dispatch_agent_remote.return_value.update({
            "trace_id": trace_id,
            "task_id": "task_remote_001",
            "agent_id": "agent_remote_001",
            "session_id": "sess_001",
        })

        with patch("core.command_router.get_command_router", return_value=mock_cr), \
             patch("core.openclawd_memory_backflow.store_task_result", new_callable=AsyncMock):

            result = await clawd._dispatch_remote_agent(
                message="run analysis on remote device",
                intent=None,
                device_id=REMOTE_DEVICE_ID,
                session_id="sess_001",
                trace_id=trace_id,
            )

        assert result["success"] is True
        meta = result.get("metadata", {})
        assert meta.get("remote_dispatch") is True
        assert meta.get("trace_id") == trace_id
        assert "task_id" in meta
        assert "agent_id" in meta
        assert "device_id" in meta

    @pytest.mark.asyncio
    async def test_dispatch_agent_respects_remote_target_device(self):
        """_dispatch_agent must route to _dispatch_remote_agent for non-local device."""
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = True
        clawd._start_time = 0.0
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._session_memory = {}
        clawd._cancel_registry = set()

        dispatched_remote = []

        async def capture_remote(message, intent, device_id, session_id, trace_id):
            dispatched_remote.append({
                "device_id": device_id,
                "trace_id": trace_id,
            })
            return {
                "success": True,
                "response": "remote ok",
                "metadata": {"remote_dispatch": True, "task_id": "t1",
                             "trace_id": trace_id, "device_id": device_id,
                             "agent_id": "a1"},
            }

        clawd._dispatch_remote_agent = capture_remote

        mock_intent = MagicMock()
        mock_intent.targets = []
        mock_intent.intent = "analysis"
        mock_intent.params = {}
        mock_intent.target_device = None  # no explicit target_device on intent

        # Use a clearly non-local device ID
        result = await clawd._dispatch_agent(
            message="run on remote",
            intent=mock_intent,
            device_id=REMOTE_DEVICE_ID,
            session_id="s1",
            trace_id="trace_route_test",
        )

        assert len(dispatched_remote) == 1
        assert dispatched_remote[0]["device_id"] == REMOTE_DEVICE_ID
        assert result["success"] is True
        assert result["metadata"].get("remote_dispatch") is True


# ============================================================================
# Gate B — Fallback behaviour
# ============================================================================

class TestFallbackBehaviour:
    """Acceptance Gate B: structured error or local fallback on remote failure."""

    @pytest.mark.asyncio
    async def test_fallback_to_local_on_device_offline(self):
        """_dispatch_remote_agent falls back to local when DEVICE_OFFLINE."""
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = True
        clawd._start_time = 0.0
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._session_memory = {}
        clawd._cancel_registry = set()

        mock_cr = MagicMock()
        mock_cr.dispatch_agent_remote = AsyncMock(return_value=_make_cr_result(
            success=False, error_code="DEVICE_OFFLINE"
        ))

        local_called = []

        async def fake_handle_agent_task(message, intent, **kwargs):
            local_called.append(kwargs)
            return {
                "success": True,
                "response": "local fallback result",
                "metadata": {"task_id": "task_local", "trace_id": kwargs.get("trace_id", ""),
                             "device_id": kwargs.get("device_id", ""), "session_id": ""},
            }

        clawd.handle_agent_task = fake_handle_agent_task

        with patch("core.command_router.get_command_router", return_value=mock_cr), \
             patch("core.openclawd_memory_backflow.store_task_result", new_callable=AsyncMock):

            result = await clawd._dispatch_remote_agent(
                message="some task",
                intent=None,
                device_id=REMOTE_DEVICE_ID,
                session_id="sess_fb",
                trace_id="trace_fb",
            )

        # Must fall back to local execution
        assert len(local_called) == 1, "handle_agent_task must be called for fallback"
        assert result["success"] is True  # local fallback succeeded
        assert result["metadata"].get("remote_fallback") is True
        assert result["metadata"].get("fallback_reason") == "DEVICE_OFFLINE"

    @pytest.mark.asyncio
    async def test_fallback_to_local_on_command_timeout(self):
        """_dispatch_remote_agent falls back to local on COMMAND_TIMEOUT."""
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = True
        clawd._start_time = 0.0
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._session_memory = {}
        clawd._cancel_registry = set()

        mock_cr = MagicMock()
        mock_cr.dispatch_agent_remote = AsyncMock(return_value=_make_cr_result(
            success=False, error_code="COMMAND_TIMEOUT"
        ))

        async def fake_handle_agent_task(message, intent, **kwargs):
            return {
                "success": True,
                "response": "local ok",
                "metadata": {"task_id": "t", "trace_id": "", "device_id": "", "session_id": ""},
            }

        clawd.handle_agent_task = fake_handle_agent_task

        with patch("core.command_router.get_command_router", return_value=mock_cr), \
             patch("core.openclawd_memory_backflow.store_task_result", new_callable=AsyncMock):

            result = await clawd._dispatch_remote_agent(
                message="task",
                intent=None,
                device_id=REMOTE_DEVICE_ID,
                session_id="s",
                trace_id="t",
            )

        assert result["metadata"].get("remote_fallback") is True
        assert result["metadata"].get("fallback_reason") == "COMMAND_TIMEOUT"

    @pytest.mark.asyncio
    async def test_fallback_when_command_router_raises(self):
        """_dispatch_remote_agent falls back gracefully when CommandRouter import fails."""
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = True
        clawd._start_time = 0.0
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._session_memory = {}
        clawd._cancel_registry = set()

        local_called = []

        async def fake_handle_agent_task(message, intent, **kwargs):
            local_called.append(True)
            return {
                "success": True,
                "response": "local fallback",
                "metadata": {"task_id": "t", "trace_id": "", "device_id": "", "session_id": ""},
            }

        clawd.handle_agent_task = fake_handle_agent_task

        with patch("core.command_router.get_command_router", side_effect=ImportError("no command_router")):
            result = await clawd._dispatch_remote_agent(
                message="test",
                intent=None,
                device_id=REMOTE_DEVICE_ID,
                session_id="s",
                trace_id="t",
            )

        assert len(local_called) == 1
        assert result["success"] is True
        assert result["metadata"].get("remote_fallback") is True

    @pytest.mark.asyncio
    async def test_local_device_stays_local(self):
        """_dispatch_agent must NOT remote-dispatch for local device IDs."""
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = True
        clawd._start_time = 0.0
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._session_memory = {}
        clawd._cancel_registry = set()

        remote_called = []

        async def fail_if_remote(*args, **kwargs):
            remote_called.append(True)
            return {"success": True, "response": "should not reach", "metadata": {}}

        clawd._dispatch_remote_agent = fail_if_remote

        async def fake_handle_agent_task(message, intent, **kwargs):
            return {
                "success": True,
                "response": "local ok",
                "metadata": {"task_id": "t", "trace_id": "", "device_id": "", "session_id": ""},
            }

        clawd.handle_agent_task = fake_handle_agent_task

        # "local_openclawd" should be treated as local → no remote dispatch
        await clawd._dispatch_agent(
            message="do something",
            intent=None,
            device_id=LOCAL_DEVICE_ID,
            session_id="s",
            trace_id="t",
        )

        assert len(remote_called) == 0, "_dispatch_remote_agent must NOT be called for local device"


# ============================================================================
# Gate C — Result persistence (backflow)
# ============================================================================

class TestResultPersistence:
    """Acceptance Gate C: remote result is persisted via memory backflow."""

    @pytest.mark.asyncio
    async def test_remote_success_triggers_backflow(self):
        """store_task_result must be called after a successful remote execution."""
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = True
        clawd._start_time = 0.0
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._session_memory = {}
        clawd._cancel_registry = set()

        trace_id = f"trace_{uuid.uuid4().hex[:8]}"
        session_id = "sess_backflow_001"
        device_id = REMOTE_DEVICE_ID

        mock_cr = MagicMock()
        mock_cr.dispatch_agent_remote = AsyncMock(return_value={
            "success": True,
            "result": {"output": "done remotely", "response": "Completed"},
            "error_code": None,
            "error_message": None,
            "latency_ms": 20.0,
            "task_id": "task_bf_001",
            "trace_id": trace_id,
            "agent_id": "agent_bf_001",
            "session_id": session_id,
            "device_id": device_id,
            "command": "agent_execute",
            "via": "command_router",
        })

        backflow_calls = []

        async def mock_store_task_result(**kwargs):
            backflow_calls.append(kwargs)

        with patch("core.command_router.get_command_router", return_value=mock_cr), \
             patch(
                 "core.openclawd_memory_backflow.store_task_result",
                 side_effect=mock_store_task_result,
             ):
            result = await clawd._dispatch_remote_agent(
                message="remote task for backflow",
                intent=None,
                device_id=device_id,
                session_id=session_id,
                trace_id=trace_id,
            )

        assert result["success"] is True
        assert len(backflow_calls) == 1, "store_task_result must be called once"

        bf = backflow_calls[0]
        assert bf["device_id"] == device_id
        assert bf["route_mode"] == "remote_agent"
        assert bf["session_id"] == session_id
        assert bf["task_id"].startswith("task_")
        assert "agent_id" in bf["result"]
        assert bf["result"]["task_type"] == "agent_execute"

    @pytest.mark.asyncio
    async def test_backflow_not_triggered_on_fallback(self):
        """store_task_result must NOT be called by _dispatch_remote_agent on fallback.

        (Backflow is handled by handle_agent_task in the local path.)
        """
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = True
        clawd._start_time = 0.0
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._session_memory = {}
        clawd._cancel_registry = set()

        mock_cr = MagicMock()
        mock_cr.dispatch_agent_remote = AsyncMock(return_value=_make_cr_result(
            success=False, error_code="DEVICE_NOT_FOUND"
        ))

        async def fake_handle_agent_task(message, intent, **kwargs):
            return {
                "success": True,
                "response": "local",
                "metadata": {"task_id": "t", "trace_id": "", "device_id": "", "session_id": ""},
            }

        clawd.handle_agent_task = fake_handle_agent_task

        remote_backflow_calls = []

        async def capture_backflow(**kwargs):
            remote_backflow_calls.append(kwargs)

        with patch("core.command_router.get_command_router", return_value=mock_cr), \
             patch(
                 "core.openclawd_memory_backflow.store_task_result",
                 side_effect=capture_backflow,
             ):
            result = await clawd._dispatch_remote_agent(
                message="test",
                intent=None,
                device_id=REMOTE_DEVICE_ID,
                session_id="s",
                trace_id="t",
            )

        # Fallback path — remote backflow should NOT be called
        assert len(remote_backflow_calls) == 0, \
            "store_task_result must not be called in the remote path when falling back"
        assert result["metadata"].get("remote_fallback") is True

    @pytest.mark.asyncio
    async def test_backflow_store_task_result_route_mode(self):
        """Backflow route_mode for remote agent dispatch must be 'remote_agent'."""
        from core.openclawd_memory_backflow import store_task_result

        with patch("core.openclawd_memory_backflow.get_task_memory") as mock_get_mem:
            mock_mem = MagicMock()
            mock_mem.record_task = MagicMock()
            mock_get_mem.return_value = mock_mem

            await store_task_result(
                task_id="task_route_mode_test",
                device_id=REMOTE_DEVICE_ID,
                route_mode="remote_agent",
                result={
                    "status": "completed",
                    "task_type": "agent_execute",
                    "task_description": "remote agent task",
                    "result_summary": "done",
                    "agent_id": "agent_xxx",
                    "trace_id": "trace_xxx",
                },
                session_id="sess_yyy",
            )

        mock_mem.record_task.assert_called_once()
        call_kwargs = mock_mem.record_task.call_args[1]
        assert call_kwargs.get("strategy") == "remote_agent"
        assert "remote_agent" in call_kwargs.get("tags", [])
        assert REMOTE_DEVICE_ID in call_kwargs.get("tags", [])


# ============================================================================
# Gate A (device side) — WindowsAIPClient agent_execute handler
# ============================================================================

class TestWindowsAIPClientAgentExecute:
    """Acceptance Gate A (device side): agent_execute handled with IDs preserved."""

    def test_execute_agent_task_preserves_correlation_ids(self):
        """_execute_agent_task must echo agent_id / task_id / trace_id back."""
        from windows_client.windows_aip_client import _execute_agent_task

        payload = {
            "agent_id": "agent_win_001",
            "task_id": "task_win_001",
            "trace_id": "trace_win_001",
            "session_id": "sess_win_001",
            "task": "open notepad",
            "agent_template": "executor",
            "context": {},
        }

        # autonomy_manager unavailable in test env
        with patch("windows_client.windows_aip_client._get_manager", return_value=None):
            result = _execute_agent_task(payload)

        assert result["agent_id"] == "agent_win_001"
        assert result["task_id"] == "task_win_001"
        assert result["trace_id"] == "trace_win_001"
        assert result["session_id"] == "sess_win_001"
        assert "success" in result or "error" in result

    def test_execute_agent_task_handles_manager_error_gracefully(self):
        """_execute_agent_task must not raise even when autonomy manager throws."""
        from windows_client.windows_aip_client import _execute_agent_task

        mock_manager = MagicMock()
        mock_manager.execute_agent_task = MagicMock(side_effect=RuntimeError("simulated crash"))
        mock_manager.execute_action = MagicMock(side_effect=RuntimeError("simulated crash"))

        payload = {
            "agent_id": "agent_err",
            "task_id": "task_err",
            "trace_id": "trace_err",
            "session_id": "sess_err",
            "task": "do something",
            "agent_template": "analyst",
        }

        with patch("windows_client.windows_aip_client._get_manager", return_value=mock_manager):
            result = _execute_agent_task(payload)

        assert result["agent_id"] == "agent_err"
        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_handle_message_routes_agent_execute_command(self):
        """_handle_message must route command='agent_execute' to _execute_agent_task."""
        import socket
        from windows_client.windows_aip_client import WindowsAIPClient

        client = WindowsAIPClient(host="127.0.0.1", port=9999)
        sent_messages = []

        async def mock_send(msg):
            sent_messages.append(msg)

        client._send = mock_send

        agent_execute_msg = {
            "type": "command",
            "command": "agent_execute",
            "command_id": "cmd_test_001",
            "payload": {
                "agent_id": "agent_test_001",
                "task_id": "task_test_001",
                "trace_id": "trace_test_001",
                "session_id": "sess_test_001",
                "task": "test task",
                "agent_template": "analyst",
                "context": {},
            },
        }

        with patch(
            "windows_client.windows_aip_client._execute_agent_task",
            return_value={
                "success": True,
                "output": "done",
                "agent_id": "agent_test_001",
                "task_id": "task_test_001",
                "trace_id": "trace_test_001",
                "session_id": "sess_test_001",
            },
        ) as mock_exec:
            await client._handle_message(agent_execute_msg)

        mock_exec.assert_called_once()
        assert len(sent_messages) == 1
        sent = sent_messages[0]
        assert sent["type"] == "agent_execute_result"
        assert sent["agent_id"] == "agent_test_001"
        assert sent["task_id"] == "task_test_001"
        assert sent["trace_id"] == "trace_test_001"

    def test_agent_execute_result_msg_contains_all_fields(self):
        """_agent_execute_result_msg must include all required correlation fields."""
        import socket
        from windows_client.windows_aip_client import WindowsAIPClient

        client = WindowsAIPClient(host="127.0.0.1", port=9999)

        agent_payload = {
            "agent_id": "agt_001",
            "task_id": "tsk_001",
            "trace_id": "trc_001",
            "session_id": "ses_001",
        }
        result = {
            "success": True,
            "output": "result",
            "agent_id": "agt_001",
            "task_id": "tsk_001",
            "trace_id": "trc_001",
            "session_id": "ses_001",
        }

        msg = client._agent_execute_result_msg("cmd_001", agent_payload, result)

        assert msg["type"] == "agent_execute_result"
        assert msg["agent_id"] == "agt_001"
        assert msg["task_id"] == "tsk_001"
        assert msg["trace_id"] == "trc_001"
        assert msg["session_id"] == "ses_001"
        assert msg["status"] == "completed"


# ============================================================================
# _is_local_device helper
# ============================================================================

class TestIsLocalDevice:
    """Unit tests for the _is_local_device helper."""

    def test_empty_device_id_is_local(self):
        from core.openclawd import _is_local_device
        assert _is_local_device("") is True
        assert _is_local_device(None) is True

    def test_local_prefix_is_local(self):
        from core.openclawd import _is_local_device
        assert _is_local_device("local_openclawd") is True
        assert _is_local_device("openclawd") is True
        assert _is_local_device("server_main") is True

    def test_remote_device_is_not_local(self):
        from core.openclawd import _is_local_device
        assert _is_local_device("windows_remotehost_abc") is False
        assert _is_local_device("android_phone_123") is False
        assert _is_local_device("tablet_device_xyz") is False
