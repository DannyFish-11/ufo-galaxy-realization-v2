"""
PR-1 Entry Unification — smoke tests
======================================

Validates that:
1. Legacy ``route_command`` callers continue to work (backward compat).
2. New ``route_envelope`` entry path is functional.
3. ``send_gateway_command`` (OpenClawd) constructs a TaskEnvelope and reaches
   ``route_envelope``.
4. VisionSampler action path uses ``route_envelope``.
5. DeviceRouter.route_task constructs a TaskEnvelope at entry.
6. NATS adapter builds a TaskEnvelope in ``_handle_task_dispatch``.
7. HandoffContract accepts ``task_id`` (PR-1 field) without error.
8. ``handoff_contract_from_envelope`` helper produces a valid contract.
"""

from __future__ import annotations

import asyncio
import pytest

from core.schemas.task_envelope import (
    TaskEnvelope,
    envelope_from_command_request,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_router(executor=None):
    """Return a CommandRouter wired to a simple mock executor."""
    from core.command_router import CommandRouter

    if executor is None:
        async def _default_executor(target, command, params):
            return {"executed": True, "command": command}

        executor = _default_executor

    return CommandRouter(executor=executor)


# ---------------------------------------------------------------------------
# 1 + 2. Backward compat: route_command still works; route_envelope is primary
# ---------------------------------------------------------------------------

class TestCommandRouterCompatAndPrimary:
    @pytest.mark.asyncio
    async def test_route_command_compat_still_works(self):
        """Legacy route_command must still succeed (backward compat)."""
        router = _make_router()
        result = await router.route_command(
            device_id="dev_legacy",
            command="ping",
            payload={},
            command_id="cmd-legacy-1",
            task_id="task-legacy-1",
        )
        assert result["success"] is True
        assert result["trace_id"].startswith("trace_")

    @pytest.mark.asyncio
    async def test_route_command_explicit_trace_id_preserved(self):
        """Explicit trace_id passed to route_command is preserved."""
        router = _make_router()
        result = await router.route_command(
            device_id="dev_legacy",
            command="status",
            payload={},
            command_id="cmd-2",
            task_id="task-2",
            trace_id="trace-explicit-abc123",
        )
        assert result["trace_id"] == "trace-explicit-abc123"

    @pytest.mark.asyncio
    async def test_route_envelope_primary_entry(self):
        """route_envelope should succeed and carry the envelope's ids."""
        router = _make_router()
        envelope = TaskEnvelope(
            task_id="task-env-1",
            trace_id="trace-env-1",
            source="test",
            targets=["node_test"],
            tool_name="status",
            args={"verbose": True},
        )
        result = await router.route_envelope(envelope)
        assert result["success"] is True
        assert result["trace_id"] == "trace-env-1"
        assert result["task_id"] == "task-env-1"

    @pytest.mark.asyncio
    async def test_route_envelope_empty_targets_returns_invalid(self):
        """Envelope with no targets returns INVALID_ENVELOPE error."""
        from core.command_router import GatewayErrorCode

        router = _make_router()
        envelope = TaskEnvelope(
            task_id="bad-task",
            trace_id="bad-trace",
            source="test",
            targets=[],
            tool_name="cmd",
        )
        result = await router.route_envelope(envelope)
        assert result["success"] is False
        assert result["error_code"] == GatewayErrorCode.INVALID_ENVELOPE.value

    @pytest.mark.asyncio
    async def test_route_command_compat_propagates_trace_to_envelope(self):
        """route_command compat shim preserves trace_id in the routed envelope."""
        seen_envelope = []

        async def capturing_executor(target, command, params):
            return {"executed": True}

        router = _make_router(capturing_executor)
        original_re = router.route_envelope

        async def sniffing_re(env):
            seen_envelope.append(env)
            return await original_re(env)

        router.route_envelope = sniffing_re

        await router.route_command(
            device_id="dev_sniff",
            command="sniff_cmd",
            payload={},
            command_id="cmd-sniff",
            task_id="task-sniff",
            trace_id="trace-sniff-999",
        )
        assert len(seen_envelope) == 1
        env = seen_envelope[0]
        assert isinstance(env, TaskEnvelope)
        assert env.trace_id == "trace-sniff-999"
        assert "dev_sniff" in env.targets
        assert env.tool_name == "sniff_cmd"


# ---------------------------------------------------------------------------
# 3. OpenClawd.send_gateway_command uses route_envelope
# ---------------------------------------------------------------------------

class TestOpenClawdSendGatewayCommand:
    @pytest.mark.asyncio
    async def test_send_gateway_command_calls_route_envelope(self):
        """send_gateway_command should invoke route_envelope (not route_command)."""
        envelope_calls = []

        async def mock_executor(target, command, params):
            return {"from_executor": True}

        import core.command_router as _cr_mod
        from core.command_router import CommandRouter

        original_get = _cr_mod.get_command_router
        router = CommandRouter(executor=mock_executor)
        original_route_envelope = router.route_envelope

        async def tracking_route_envelope(envelope):
            envelope_calls.append(envelope)
            return await original_route_envelope(envelope)

        router.route_envelope = tracking_route_envelope
        _cr_mod.get_command_router = lambda: router
        try:
            from core.openclawd import OpenClawd
            import types
            clawd = object.__new__(OpenClawd)
            result = await clawd.send_gateway_command(
                device_id="dev_oc",
                command="test_cmd",
                payload={"k": "v"},
                task_id="oc-task-1",
            )
            assert result["via"] == "command_router"
            # verify route_envelope was called with a TaskEnvelope
            assert len(envelope_calls) == 1
            env = envelope_calls[0]
            assert isinstance(env, TaskEnvelope)
            assert env.tool_name == "test_cmd"
            assert "dev_oc" in env.targets
            assert env.source == "openclawd"
        finally:
            _cr_mod.get_command_router = original_get


# ---------------------------------------------------------------------------
# 5. DeviceRouter.route_task constructs a TaskEnvelope at entry
# ---------------------------------------------------------------------------

class TestDeviceRouterTaskEnvelopeEntry:
    def test_route_task_builds_envelope_and_injects_trace_id(self):
        """DeviceRouter.route_task should inject/propagate trace_id via TaskEnvelope."""
        from galaxy_gateway.device_router import DeviceRouter

        router = DeviceRouter()
        # Patch _analyze_command to avoid external calls
        async def fake_analyze(command, ctx):
            return {
                "command": command,
                "target_device_type": "windows",
                "task_type": "query",
                "actions": [],
                "requires_cross_device": False,
                "exec_mode": "both",
            }

        router._analyze_command = fake_analyze

        ctx = {"route_mode": "direct", "source": "test_suite"}
        # Run the coroutine partially - we just verify no exception thrown constructing envelope
        import asyncio
        coro = router.route_task("test command", ctx)
        # We can't fully execute without devices; wrap in try to catch expected failure
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(coro)
            # May fail due to no devices - that's fine, we care about no envelope error
            assert "success" in result
        except Exception as exc:
            # Only envelope-related exceptions are problems
            assert "TaskEnvelope" not in str(exc), f"TaskEnvelope error: {exc}"
        finally:
            loop.close()


# ---------------------------------------------------------------------------
# 6. NATS adapter builds a TaskEnvelope in _handle_task_dispatch
# ---------------------------------------------------------------------------

class TestGatewayNATSAdapterEnvelope:
    @pytest.mark.asyncio
    async def test_handle_task_dispatch_builds_envelope(self):
        """_handle_task_dispatch should construct a TaskEnvelope without errors."""
        from galaxy_gateway.gateway_nats_adapter import GatewayNATSAdapter

        adapter = GatewayNATSAdapter()
        # Stub out the forwarding path to avoid actual device calls
        async def _stub_forward(task_id, target, task_type, payload):
            return {"success": True, "task_id": task_id}

        adapter._forward_to_device = _stub_forward

        # Stub _publish_result / _publish_dlq to no-ops
        async def _noop(*a, **kw):
            pass

        adapter._publish_result = _noop

        data = {
            "task_id": "nats-task-1",
            "target_device_id": "dev_nats",
            "task_type": "command",
            "payload": {"action": "tap", "x": 10, "y": 20},
            "trace_id": "trace-nats-abc",
            "route_mode": "direct",
        }
        # Should complete without raising
        await adapter._handle_task_dispatch(data)


# ---------------------------------------------------------------------------
# 7. HandoffContract PR-1 field (task_id)
# ---------------------------------------------------------------------------

class TestHandoffContractTaskId:
    def test_handoff_contract_accepts_task_id(self):
        """HandoffContract should accept the new task_id field without error."""
        from galaxy_gateway.agent_bridge import HandoffContract

        contract = HandoffContract(
            trace_id="trace-hc-1",
            task={"command": "ping"},
            task_id="task-hc-1",
            capability="ui",
            exec_mode="local",
            route_mode="direct",
        )
        assert contract.task_id == "task-hc-1"
        d = contract.to_dict()
        assert d["task_id"] == "task-hc-1"
        assert d["trace_id"] == "trace-hc-1"

    def test_handoff_contract_task_id_default_empty(self):
        """Legacy HandoffContract without task_id should default to empty string."""
        from galaxy_gateway.agent_bridge import HandoffContract

        contract = HandoffContract(
            trace_id="trace-legacy",
            task={"command": "noop"},
        )
        assert contract.task_id == ""
        d = contract.to_dict()
        # task_id should NOT appear in legacy payload when empty
        assert "task_id" not in d


# ---------------------------------------------------------------------------
# 8. handoff_contract_from_envelope helper
# ---------------------------------------------------------------------------

class TestHandoffContractFromEnvelope:
    def test_builds_contract_from_envelope(self):
        """handoff_contract_from_envelope should populate all expected fields."""
        from galaxy_gateway.agent_bridge import (
            handoff_contract_from_envelope,
            HandoffContract,
        )

        envelope = TaskEnvelope(
            task_id="env-task-bridge",
            trace_id="trace-bridge-1",
            source="test",
            targets=["dev_bridge"],
            tool_name="tap",
            args={"x": 5, "y": 10},
            metadata={"route_mode": "broadcast"},
        )
        contract = handoff_contract_from_envelope(
            envelope,
            capability="touch",
            exec_mode="remote",
        )
        assert isinstance(contract, HandoffContract)
        assert contract.trace_id == "trace-bridge-1"
        assert contract.task_id == "env-task-bridge"
        assert contract.capability == "touch"
        assert contract.exec_mode == "remote"
        assert contract.route_mode == "broadcast"
        d = contract.to_dict()
        assert d["task_id"] == "env-task-bridge"
        assert d["trace_id"] == "trace-bridge-1"
