"""tests/test_pre_executor_target_typing.py
==========================================
PR-E: Explicit executor target typing — unit tests.

Coverage:
  1. ExecutorTargetType enum has all required values.
  2. TaskEnvelope accepts executor_target_type field (all values + None).
  3. route_envelope() branches on android_device → _route_cross_device_envelope().
  4. route_envelope() branches on node_service → _route_cross_device_envelope().
  5. route_envelope() branches on go_worker → _route_worker_envelope() (MasterBrain).
  6. route_envelope() branches on local → _execute_command().
  7. route_envelope() falls back to metadata heuristics when executor_target_type is None.
  8. sentinel constants are importable from core.command_router.
  9. ExecutorTargetType is re-exported from core.schemas.
"""

from __future__ import annotations

import asyncio
import pytest

from core.schemas.remote_execution import ExecutorTargetType, RemoteExecutionMode
from core.schemas.task_envelope import TaskEnvelope


# ---------------------------------------------------------------------------
# 1. ExecutorTargetType enum values
# ---------------------------------------------------------------------------


class TestExecutorTargetTypeEnum:
    """ExecutorTargetType has all required values."""

    def test_android_device(self):
        assert ExecutorTargetType.android_device == "android_device"

    def test_node_service(self):
        assert ExecutorTargetType.node_service == "node_service"

    def test_go_worker(self):
        assert ExecutorTargetType.go_worker == "go_worker"

    def test_local(self):
        assert ExecutorTargetType.local == "local"

    def test_is_str_enum(self):
        assert isinstance(ExecutorTargetType.android_device, str)

    def test_all_four_values_present(self):
        values = {e.value for e in ExecutorTargetType}
        assert values == {"android_device", "node_service", "go_worker", "local"}


# ---------------------------------------------------------------------------
# 2. TaskEnvelope executor_target_type field
# ---------------------------------------------------------------------------


class TestTaskEnvelopeExecutorTargetTypeField:
    """TaskEnvelope carries executor_target_type."""

    def test_default_is_none(self):
        env = TaskEnvelope()
        assert env.executor_target_type is None

    def test_set_android_device(self):
        env = TaskEnvelope(executor_target_type=ExecutorTargetType.android_device)
        assert env.executor_target_type == ExecutorTargetType.android_device

    def test_set_node_service(self):
        env = TaskEnvelope(executor_target_type=ExecutorTargetType.node_service)
        assert env.executor_target_type == ExecutorTargetType.node_service

    def test_set_go_worker(self):
        env = TaskEnvelope(executor_target_type=ExecutorTargetType.go_worker)
        assert env.executor_target_type == ExecutorTargetType.go_worker

    def test_set_local(self):
        env = TaskEnvelope(executor_target_type=ExecutorTargetType.local)
        assert env.executor_target_type == ExecutorTargetType.local

    def test_set_by_string_value(self):
        """Pydantic coerces the string literal to the enum."""
        env = TaskEnvelope(executor_target_type="android_device")  # type: ignore[arg-type]
        assert env.executor_target_type == ExecutorTargetType.android_device

    def test_model_copy_preserves_field(self):
        env = TaskEnvelope(executor_target_type=ExecutorTargetType.go_worker)
        copy = env.model_copy()
        assert copy.executor_target_type == ExecutorTargetType.go_worker

    def test_serialises_to_string(self):
        env = TaskEnvelope(executor_target_type=ExecutorTargetType.node_service)
        data = env.model_dump(mode="json")
        assert data["executor_target_type"] == "node_service"


# ---------------------------------------------------------------------------
# Helpers shared across routing tests
# ---------------------------------------------------------------------------


def _make_mock_executor(captured_calls=None):
    """Async executor that records calls and returns success."""
    calls = captured_calls if captured_calls is not None else []

    async def _executor(target: str, command: str, params: dict) -> dict:
        calls.append({"target": target, "command": command, "params": params})
        return {"success": True, "result": "ok"}

    _executor.calls = calls
    return _executor


def _make_router(executor):
    from core.command_router import CommandRouter

    return CommandRouter(executor=executor)


# ---------------------------------------------------------------------------
# 3 & 4. android_device / node_service → _route_cross_device_envelope
# ---------------------------------------------------------------------------


class TestRouteEnvelopeAndroidDevice:
    """executor_target_type=android_device routes via _route_cross_device_envelope."""

    @pytest.mark.asyncio
    async def test_android_device_calls_cross_device_path(self):
        captured: list = []
        router = _make_router(_make_mock_executor())

        async def _fake_cross_device(envelope, command_id, request_id):
            captured.append({"via": "cross_device", "envelope": envelope})
            return {
                "request_id": request_id,
                "task_id": envelope.task_id,
                "trace_id": envelope.trace_id,
                "command_id": command_id,
                "device_id": "",
                "command": envelope.tool_name,
                "via": "command_router.cross_device_substrate",
                "success": True,
                "result": {},
                "error_code": None,
                "error_message": None,
                "latency_ms": 0.0,
            }

        router._route_cross_device_envelope = _fake_cross_device

        env = TaskEnvelope(
            task_id="t-android-1",
            trace_id="tr-1",
            source="test",
            targets=["device_android_001"],
            tool_name="screenshot",
            args={},
            executor_target_type=ExecutorTargetType.android_device,
        )
        result = await router.route_envelope(env)

        assert len(captured) == 1, "cross-device path should have been called once"
        assert captured[0]["via"] == "cross_device"
        assert result["success"] is True


class TestRouteEnvelopeNodeService:
    """executor_target_type=node_service routes via _route_cross_device_envelope."""

    @pytest.mark.asyncio
    async def test_node_service_calls_cross_device_path(self):
        captured: list = []
        router = _make_router(_make_mock_executor())

        async def _fake_cross_device(envelope, command_id, request_id):
            captured.append({"via": "cross_device", "envelope": envelope})
            return {
                "request_id": request_id,
                "task_id": envelope.task_id,
                "trace_id": envelope.trace_id,
                "command_id": command_id,
                "device_id": "",
                "command": envelope.tool_name,
                "via": "command_router.cross_device_substrate",
                "success": True,
                "result": {},
                "error_code": None,
                "error_message": None,
                "latency_ms": 0.0,
            }

        router._route_cross_device_envelope = _fake_cross_device

        env = TaskEnvelope(
            task_id="t-node-1",
            trace_id="tr-node-1",
            source="test",
            targets=["node_04_router"],
            tool_name="status",
            args={},
            executor_target_type=ExecutorTargetType.node_service,
        )
        result = await router.route_envelope(env)

        assert len(captured) == 1
        assert result["success"] is True


# ---------------------------------------------------------------------------
# 5. go_worker → _route_worker_envelope (MasterBrain boundary)
# ---------------------------------------------------------------------------


class TestRouteEnvelopeGoWorker:
    """executor_target_type=go_worker routes via _route_worker_envelope."""

    @pytest.mark.asyncio
    async def test_go_worker_calls_worker_path(self):
        captured: list = []
        router = _make_router(_make_mock_executor())

        async def _fake_worker(envelope, command_id, request_id):
            captured.append({"via": "worker", "envelope": envelope})
            return {
                "request_id": request_id,
                "task_id": envelope.task_id,
                "trace_id": envelope.trace_id,
                "command_id": command_id,
                "device_id": envelope.target,
                "command": envelope.tool_name,
                "via": "command_router.worker_masterbrain",
                "success": True,
                "result": {},
                "error_code": None,
                "error_message": None,
                "latency_ms": 0.0,
            }

        router._route_worker_envelope = _fake_worker

        env = TaskEnvelope(
            task_id="t-worker-1",
            trace_id="tr-worker-1",
            source="test",
            targets=["worker_go_001"],
            tool_name="execute_task",
            args={"param": "value"},
            executor_target_type=ExecutorTargetType.go_worker,
        )
        result = await router.route_envelope(env)

        assert len(captured) == 1
        assert captured[0]["via"] == "worker"
        assert result["via"] == "command_router.worker_masterbrain"
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_go_worker_does_not_call_cross_device(self):
        """go_worker must NOT route via _route_cross_device_envelope."""
        cross_device_called: list = []
        worker_called: list = []
        router = _make_router(_make_mock_executor())

        async def _fake_cross_device(envelope, command_id, request_id):
            cross_device_called.append(True)
            return {"success": True, "task_id": envelope.task_id, "trace_id": envelope.trace_id,
                    "command_id": command_id, "request_id": request_id,
                    "command": envelope.tool_name, "via": "cross_device", "device_id": "",
                    "result": None, "error_code": None, "error_message": None, "latency_ms": 0.0}

        async def _fake_worker(envelope, command_id, request_id):
            worker_called.append(True)
            return {"success": True, "task_id": envelope.task_id, "trace_id": envelope.trace_id,
                    "command_id": command_id, "request_id": request_id,
                    "command": envelope.tool_name, "via": "worker", "device_id": "",
                    "result": None, "error_code": None, "error_message": None, "latency_ms": 0.0}

        router._route_cross_device_envelope = _fake_cross_device
        router._route_worker_envelope = _fake_worker

        env = TaskEnvelope(
            task_id="t-w2",
            trace_id="tr-w2",
            targets=["worker_go_002"],
            tool_name="run",
            executor_target_type=ExecutorTargetType.go_worker,
        )
        await router.route_envelope(env)

        assert not cross_device_called, "cross_device must not be called for go_worker"
        assert worker_called, "_route_worker_envelope must be called for go_worker"


# ---------------------------------------------------------------------------
# 6. local → _execute_command
# ---------------------------------------------------------------------------


class TestRouteEnvelopeLocal:
    """executor_target_type=local routes via _execute_command (direct executor)."""

    @pytest.mark.asyncio
    async def test_local_calls_executor_directly(self):
        executor = _make_mock_executor()
        router = _make_router(executor)

        env = TaskEnvelope(
            task_id="t-local-1",
            trace_id="tr-local-1",
            source="test",
            targets=["local"],
            tool_name="ping",
            args={"verbose": True},
            executor_target_type=ExecutorTargetType.local,
        )
        result = await router.route_envelope(env)

        assert result["success"] is True
        # Executor was called directly (not via cross-device/worker)
        assert executor.calls, "executor must be called for local target"
        assert executor.calls[0]["target"] == "local"
        assert executor.calls[0]["command"] == "ping"


# ---------------------------------------------------------------------------
# 7. Backward compatibility: None falls back to metadata heuristics
# ---------------------------------------------------------------------------


class TestRouteEnvelopeFallbackHeuristics:
    """When executor_target_type is None, existing metadata heuristics still work."""

    @pytest.mark.asyncio
    async def test_cross_device_metadata_heuristic_still_works(self):
        captured: list = []
        router = _make_router(_make_mock_executor())

        async def _fake_cross_device(envelope, command_id, request_id):
            captured.append(True)
            return {
                "request_id": request_id,
                "task_id": envelope.task_id,
                "trace_id": envelope.trace_id,
                "command_id": command_id,
                "device_id": "",
                "command": envelope.tool_name,
                "via": "command_router.cross_device_substrate",
                "success": True,
                "result": {},
                "error_code": None,
                "error_message": None,
                "latency_ms": 0.0,
            }

        router._route_cross_device_envelope = _fake_cross_device

        env = TaskEnvelope(
            task_id="t-compat-1",
            trace_id="tr-compat-1",
            targets=["some_device"],
            tool_name="ping",
            # no executor_target_type — use legacy metadata flag
            metadata={"cross_device": "true"},
        )
        result = await router.route_envelope(env)

        assert captured, "cross_device metadata heuristic should still route via cross_device"
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_no_target_type_no_metadata_uses_executor(self):
        executor = _make_mock_executor()
        router = _make_router(executor)

        env = TaskEnvelope(
            task_id="t-plain-1",
            trace_id="tr-plain-1",
            targets=["device_x"],
            tool_name="run",
        )
        result = await router.route_envelope(env)

        assert result["success"] is True
        assert executor.calls, "default path must call executor"


# ---------------------------------------------------------------------------
# 8. Sentinel constants importable
# ---------------------------------------------------------------------------


class TestSentinelConstants:
    """PR-E sentinel constants are importable and non-empty."""

    def test_executor_target_type_routing_policy(self):
        from core.command_router import EXECUTOR_TARGET_TYPE_ROUTING_POLICY

        assert EXECUTOR_TARGET_TYPE_ROUTING_POLICY
        assert "EXECUTOR_TARGET_TYPE_ROUTING" in EXECUTOR_TARGET_TYPE_ROUTING_POLICY

    def test_masterbrain_worker_dispatch_boundary(self):
        from core.command_router import MASTERBRAIN_WORKER_DISPATCH_BOUNDARY

        assert MASTERBRAIN_WORKER_DISPATCH_BOUNDARY
        assert "MASTERBRAIN" in MASTERBRAIN_WORKER_DISPATCH_BOUNDARY

    def test_sentinels_are_strings(self):
        from core.command_router import (
            EXECUTOR_TARGET_TYPE_ROUTING_POLICY,
            MASTERBRAIN_WORKER_DISPATCH_BOUNDARY,
        )

        assert isinstance(EXECUTOR_TARGET_TYPE_ROUTING_POLICY, str)
        assert isinstance(MASTERBRAIN_WORKER_DISPATCH_BOUNDARY, str)


# ---------------------------------------------------------------------------
# 9. Re-export from core.schemas
# ---------------------------------------------------------------------------


class TestCoreSchemaReExport:
    """ExecutorTargetType and RemoteExecutionMode are re-exported from core.schemas."""

    def test_executor_target_type_importable(self):
        from core.schemas import ExecutorTargetType as ETT  # noqa: F401

        assert ETT.android_device == "android_device"

    def test_remote_execution_mode_importable(self):
        from core.schemas import RemoteExecutionMode as REM  # noqa: F401

        assert REM.agent_runtime == "agent_runtime"
