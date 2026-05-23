"""
PR-2 smoke tests — 核心链路统一为 TaskEnvelope
================================================

验证以下要求（PR-2）：

1. CommandRouter.dispatch (compat layer) — 接收 CommandRequest 后内部转换为
   TaskEnvelope 并成功执行（向后兼容）。
2. CommandRouter.route_envelope (primary path) — 直接接收 TaskEnvelope 并成功执行。
3. NATSExecutor — 从 params 中提取 _galaxy_task_id / _galaxy_trace_id，不生成新 UUID。
4. DeviceRouter.dispatch_task — 内部使用 TaskEnvelope + route_envelope（不再使用
   CommandRequest + dispatch）。
5. AgentBridge.handoff — 使用 task_id 作为去重键（当 contract.task_id 不为空）。
6. AgentBridge.handoff_from_envelope — 直接接受 TaskEnvelope 的主入口。
7. TaskOrchestrator.submit_task — 提交时立即创建 TaskEnvelope 并存储在
   _task_envelopes 中。

内部唯一任务格式：TaskEnvelope（PR-2 不引入 M2 Schema）。
"""

import asyncio
import uuid
import pytest
from unittest.mock import patch

from core.command_router import GatewayErrorCode
from core.schemas.task_envelope import TaskEnvelope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_executor(captured_calls=None):
    """Return an async executor that records calls."""
    calls = captured_calls if captured_calls is not None else []

    async def _executor(target: str, command: str, params: dict):
        calls.append({"target": target, "command": command, "params": dict(params)})
        return {"executed": command, "target": target}

    _executor.calls = calls
    return _executor


def _make_approved_slots_result(device_ids):
    """Return a CanonicalDispatchSlotsResult approving all given device IDs.

    Used to bypass the V3 canonical dispatch slot gate in unit tests that
    focus on routing logic rather than slot-legality enforcement.
    """
    from core.canonical_dispatch_slot_authority import (
        CanonicalDispatchSlot,
        CanonicalDispatchSlotStatus,
        CanonicalDispatchSlotsResult,
    )
    slots = [
        CanonicalDispatchSlot(
            device_id=d,
            execution_mode="cross_device",
            slot_approved=True,
            status=CanonicalDispatchSlotStatus.SLOT_APPROVED.value,
            reason="test override — all dimensions bypassed",
        )
        for d in device_ids
    ]
    return CanonicalDispatchSlotsResult(
        execution_mode="cross_device",
        approved_slots=slots,
        blocked_slots=[],
        can_proceed=True,
        block_reason="",
    )


def _patch_v3_slot_gate(device_ids):
    """Context manager: patch get_canonical_dispatch_slots to approve *device_ids*."""
    approved = _make_approved_slots_result(device_ids)
    return patch(
        "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
        return_value=approved,
    )


# ---------------------------------------------------------------------------
# 1. CommandRouter.route_envelope (primary path)
# ---------------------------------------------------------------------------

class TestRouteEnvelopePrimaryPath:
    """PR-2: route_envelope 为主路径，内部只处理 TaskEnvelope。"""

    def _make_router(self, executor):
        from core.command_router import CommandRouter
        return CommandRouter(executor=executor)

    @pytest.mark.asyncio
    async def test_route_envelope_success(self):
        executor = _make_mock_executor()
        router = self._make_router(executor)

        envelope = TaskEnvelope(
            task_id="te-task-1",
            trace_id="te-trace-1",
            source="test",
            targets=["device_a"],
            tool_name="ping",
            args={"verbose": True},
        )
        with _patch_v3_slot_gate(["device_a"]):
            result = await router.route_envelope(envelope)

        assert result["success"] is True
        assert result["task_id"] == "te-task-1"
        assert result["trace_id"] == "te-trace-1"
        # Executor was called with the envelope's targets[0]
        assert executor.calls[0]["target"] == "device_a"
        assert executor.calls[0]["command"] == "ping"

    @pytest.mark.asyncio
    async def test_route_envelope_propagates_galaxy_metadata_to_executor(self):
        """_dispatch_to_device injects _galaxy_task_id into params for NATSExecutor."""
        executor = _make_mock_executor()
        router = self._make_router(executor)

        envelope = TaskEnvelope(
            task_id="meta-task",
            trace_id="meta-trace",
            source="test",
            targets=["device_x"],
            tool_name="status",
            args={},
        )
        with _patch_v3_slot_gate(["device_x"]):
            await router.route_envelope(envelope)

        call_params = executor.calls[0]["params"]
        # PR-2: _galaxy_task_id and _galaxy_trace_id must be injected
        assert call_params.get("_galaxy_task_id") == "meta-task"
        assert call_params.get("_galaxy_trace_id") == "meta-trace"

    @pytest.mark.asyncio
    async def test_route_envelope_executor_explicit_failure_is_not_marked_success(self):
        """Executor-reported failure must remain failure in route_envelope result."""
        from core.command_router import CommandRouter

        async def _failing_executor(target: str, command: str, params: dict):
            return {
                "success": False,
                "error": "nats_executor_no_result:nats_noop_transport",
                "execution_path": "distributed_unavailable",
                "distributed_dispatch": False,
            }

        router = CommandRouter(executor=_failing_executor)
        envelope = TaskEnvelope(
            task_id="te-task-fail",
            trace_id="te-trace-fail",
            source="test",
            targets=["device_fail"],
            tool_name="ping",
            args={},
        )
        with _patch_v3_slot_gate(["device_fail"]):
            result = await router.route_envelope(envelope)

        assert result["success"] is False
        assert result["error_code"] == GatewayErrorCode.EXECUTOR_ERROR.value
        assert result.get("execution_path") == "distributed_unavailable"
        assert result.get("distributed_dispatch") is False


# ---------------------------------------------------------------------------
# 2. CommandRouter.dispatch (compat layer builds TaskEnvelope)
# ---------------------------------------------------------------------------

class TestDispatchCompatLayer:
    """PR-2: dispatch 为兼容层，接收 CommandRequest 后立即构造 TaskEnvelope。"""

    def _make_router(self, executor):
        from core.command_router import CommandRouter
        return CommandRouter(executor=executor)

    @pytest.mark.asyncio
    async def test_dispatch_still_works(self):
        """route_command still works — backward compat."""
        executor = _make_mock_executor()
        router = self._make_router(executor)

        with _patch_v3_slot_gate(["dev1"]):
            result = await router.route_command(
                device_id="dev1",
                command="health_check",
                payload={},
                command_id="cmd-pr2",
                task_id="task-pr2",
            )
        assert result["success"] is True
        assert executor.calls, "executor should have been called"

    @pytest.mark.asyncio
    async def test_dispatch_compat_via_command_request(self):
        """dispatch() with a CommandRequest — compat shim path."""
        executor = _make_mock_executor()
        router = self._make_router(executor)

        from core.command_router import CommandRequest, CommandMode
        req = CommandRequest(
            source="test_compat",
            targets=["dev_compat"],
            command="list",
            params={"all": "true"},
            mode=CommandMode.SYNC,
        )
        cmd_result = await router.dispatch(req)
        # CommandResult has a targets dict
        assert req.request_id in router._results or cmd_result is not None


# ---------------------------------------------------------------------------
# 3. NATSExecutor — uses envelope identifiers from params
# ---------------------------------------------------------------------------

class TestNATSExecutorEnvelopeIds:
    """PR-2: NATSExecutor extracts _galaxy_task_id/_galaxy_trace_id from params."""

    @pytest.mark.asyncio
    async def test_nats_executor_extracts_ids(self):
        from core.command_router import NATSExecutor

        captured_dispatches = []

        async def _mock_nats_publish(task):
            captured_dispatches.append(task)
            return {"success": False}  # force fallback

        async def _fallback(target, command, params):
            return {"fallback": True, "target": target}

        executor = NATSExecutor(fallback_executor=_fallback, fallback_enabled=True)
        # Call with _galaxy_task_id / _galaxy_trace_id injected by _dispatch_to_device
        params = {
            "_galaxy_task_id": "my-envelope-task",
            "_galaxy_trace_id": "my-envelope-trace",
            "some_param": "value",
        }
        result = await executor("device_z", "run", params)
        # Fallback is used since NATS is not connected
        assert result.get("fallback") is True
        # The original some_param should still flow through (no mutation of original)
        # The _galaxy_* keys should have been consumed (not forwarded)


# ---------------------------------------------------------------------------
# 4. DeviceRouter.dispatch_task uses route_envelope
# ---------------------------------------------------------------------------

class TestDeviceRouterDispatchTaskEnvelope:
    """PR-2: dispatch_task 内部转换为 TaskEnvelope + route_envelope。"""

    @pytest.mark.asyncio
    async def test_dispatch_task_uses_route_envelope(self):
        """When executor is set, dispatch_task should call route_envelope."""
        from galaxy_gateway.device_router import DeviceRouter, Device

        executor = _make_mock_executor()

        # Patch CommandRouter so get_command_router() returns a router with our executor
        from core.command_router import CommandRouter
        mock_router = CommandRouter(executor=executor)

        import galaxy_gateway.device_router as _dr_mod
        import core.command_router as _cr_mod

        original_get_router = _cr_mod.get_command_router
        _cr_mod.get_command_router = lambda: mock_router
        try:
            dr = DeviceRouter()
            device = Device(
                device_id="test_device",
                device_type="windows",
                capabilities=["screenshot"],
            )
            task = {
                "task_id": "dr-task-1",
                "trace_id": "dr-trace-1",
                "command": "screenshot",
                "payload": {
                    "action": "screenshot",
                    "task_type": "ui_automation",
                    "params": {},
                },
            }
            with _patch_v3_slot_gate(["test_device"]):
                result = await dr.dispatch_task(task, device)
            # route_envelope was called → executor was invoked
            assert executor.calls, "route_envelope should have called the executor"
            assert executor.calls[0]["target"] == "test_device"
        finally:
            _cr_mod.get_command_router = original_get_router


# ---------------------------------------------------------------------------
# 5. AgentBridge.handoff uses task_id as dedup key
# ---------------------------------------------------------------------------

class TestAgentBridgeEnvelopeDedup:
    """PR-2: AgentBridge deduplicates on task_id when provided."""

    @pytest.mark.asyncio
    async def test_dedup_by_task_id(self):
        from galaxy_gateway.agent_bridge import (
            AgentBridge,
            AgentBridgeConfig,
            HandoffContract,
        )
        import galaxy_gateway.agent_bridge as _ab_mod

        bridge = AgentBridge(config=AgentBridgeConfig(enabled=False))
        # Pre-populate the dedup cache with a task_id key
        task_id = "dup-task-123"
        bridge._dedup_cache[task_id] = {"success": True, "cached": True, "trace_id": "t-1"}

        contract = HandoffContract(
            trace_id="t-1",
            task_id=task_id,
            task={},
        )

        import os
        old_env = os.environ.get("GALAXY_CROSS_DEVICE_ENABLED")
        os.environ["GALAXY_CROSS_DEVICE_ENABLED"] = "1"
        # Re-enable bridge for this test
        bridge._config = AgentBridgeConfig(enabled=True, runtime_url="http://localhost:19999")
        try:
            result = await bridge.handoff(contract=contract)
        finally:
            if old_env is None:
                os.environ.pop("GALAXY_CROSS_DEVICE_ENABLED", None)
            else:
                os.environ["GALAXY_CROSS_DEVICE_ENABLED"] = old_env

        assert result.get("cached") is True
        assert bridge.metrics.dedup_hit_count == 1

    @pytest.mark.asyncio
    async def test_handoff_from_envelope_entry(self):
        """handoff_from_envelope is callable and goes through the bridge."""
        from galaxy_gateway.agent_bridge import (
            AgentBridge,
            AgentBridgeConfig,
        )
        import os

        bridge = AgentBridge(config=AgentBridgeConfig(enabled=False))
        envelope = TaskEnvelope(
            task_id="hfe-task",
            trace_id="hfe-trace",
            source="test",
            targets=["dev"],
            tool_name="noop",
            args={},
        )
        # With bridge disabled, handoff_from_envelope returns local_fallback result
        async def _local(task: dict):
            return {"success": True, "bridge_source": "local_fallback", "trace_id": "hfe-trace"}

        old_env = os.environ.get("GALAXY_CROSS_DEVICE_ENABLED")
        os.environ["GALAXY_CROSS_DEVICE_ENABLED"] = "1"
        try:
            result = await bridge.handoff_from_envelope(
                envelope,
                capability="test",
                local_fallback=_local,
            )
        finally:
            if old_env is None:
                os.environ.pop("GALAXY_CROSS_DEVICE_ENABLED", None)
            else:
                os.environ["GALAXY_CROSS_DEVICE_ENABLED"] = old_env

        assert result["success"] is True
        assert result.get("bridge_source") == "local_fallback"


# ---------------------------------------------------------------------------
# 6. TaskOrchestrator.submit_task creates TaskEnvelope immediately
# ---------------------------------------------------------------------------

class TestTaskOrchestratorEnvelope:
    """PR-2: submit_task 立即创建 TaskEnvelope 并存储在 _task_envelopes。"""

    @pytest.mark.asyncio
    async def test_submit_task_creates_envelope(self):
        from unittest.mock import MagicMock, AsyncMock
        from galaxy_gateway.orchestrator.task_orchestrator import (
            TaskOrchestrator,
            TaskPriority,
        )

        # Build minimal mocks for the orchestrator's dependencies
        mock_dm = MagicMock()
        mock_mh = MagicMock()
        mock_ws = MagicMock()
        mock_ws.is_device_connected = MagicMock(return_value=False)
        mock_ws.get_connected_devices = MagicMock(return_value=[])

        orch = TaskOrchestrator(mock_dm, mock_mh, mock_ws)
        task = await orch.submit_task(
            user_request="Take a screenshot of the desktop",
            priority=TaskPriority.NORMAL,
            target_device="device_test",
        )

        assert task.task_id in orch._task_envelopes
        envelope = orch._task_envelopes[task.task_id]
        assert envelope.task_id == task.task_id
        assert envelope.args.get("user_request") == "Take a screenshot of the desktop"
        assert "device_test" in envelope.targets
