#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr7_cross_device_substrate.py
==========================================
PR-7 — Unified Cross-Device Substrate tests

Validates that both remote execution styles share the same substrate root
(``CommandRouter.route_envelope``) and that mode metadata is preserved
consistently across the full dispatch chain.

Test classes:

  1. TestSubstrateRootUnification
       Both command_only and agent_runtime paths enter through route_envelope.
  2. TestAgentDispatchUsesRouteEnvelope
       dispatch_agent_remote calls route_envelope (not route_command) with
       remote_execution_mode=agent_runtime stamped in the envelope.
  3. TestDeployThenExecuteUsesRouteEnvelope
       _deploy_agent_then_execute calls route_envelope with agent_runtime.
  4. TestModeMetadataPropagation
       route_envelope propagates remote_execution_mode into the result dict
       for both modes.
  5. TestNATSBusRemoteExecutionModeField
       NATSBus._ensure_trace_fields propagates remote_execution_mode.
       publish_task_event accepts remote_execution_mode kwarg.
  6. TestGatewayNATSAdapterModePreservation
       GatewayNATSAdapter._handle_task_dispatch extracts remote_execution_mode
       from a TaskEnvelope and forwards it to _forward_to_device.
  7. TestOpenClawdAgentDispatchAlwaysAgentRuntime
       _dispatch_remote_agent's internal envelope always carries agent_runtime.
  8. TestBackwardCompatibility
       Callers that do not provide remote_execution_mode continue to work.

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import os
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# 1. TestSubstrateRootUnification
# ---------------------------------------------------------------------------


class TestSubstrateRootUnification:
    """Both command_only and agent_runtime dispatches enter through route_envelope."""

    def test_send_gateway_command_calls_route_envelope(self):
        """send_gateway_command (command_only path) calls route_envelope."""
        from core.schemas.remote_execution import RemoteExecutionMode

        captured: list = []

        async def fake_route_envelope(envelope):
            captured.append(envelope)
            return {"success": True, "response": "ok"}

        mock_cr = MagicMock()
        mock_cr.route_envelope = fake_route_envelope

        async def run():
            from core.openclawd import OpenClawd
            oc = OpenClawd.__new__(OpenClawd)
            oc._config = {}
            with patch("core.command_router.get_command_router", return_value=mock_cr):
                await oc.send_gateway_command(
                    device_id="dev_cmd",
                    command="screenshot",
                    payload={},
                )

        asyncio.get_running_loop().run_until_complete(run())
        assert len(captured) == 1
        assert captured[0].remote_execution_mode == RemoteExecutionMode.command_only

    def test_dispatch_agent_remote_calls_route_envelope(self):
        """dispatch_agent_remote (agent_runtime path) calls route_envelope,
        not route_command."""
        from core.command_router import CommandRouter
        from core.schemas.remote_execution import RemoteExecutionMode

        cr = CommandRouter.__new__(CommandRouter)
        captured_envelopes: list = []

        async def fake_route_envelope(envelope):
            captured_envelopes.append(envelope)
            return {
                "success": True,
                "result": "done",
                "latency_ms": 5.0,
                "remote_execution_mode": "agent_runtime",
            }

        cr.route_envelope = fake_route_envelope
        route_command_called = []
        cr.route_command = AsyncMock(side_effect=lambda *a, **kw: route_command_called.append(1))

        async def run():
            with patch("core.device_policy.requires_agent_deploy", return_value=False):
                mock_udm_module = MagicMock()
                mock_udm = MagicMock()
                mock_udm.get_device_type.return_value = "cloud"
                mock_udm_module.get_unified_device_manager.return_value = mock_udm
                with patch.dict(sys.modules, {"core.unified.device_manager": mock_udm_module}):
                    return await cr.dispatch_agent_remote(
                        device_id="cloud_001",
                        agent_id="agent_01",
                        agent_template="executor",
                        task="run task",
                        session_id="sess_01",
                        trace_id="trace_01",
                        task_id="task_01",
                    )

        asyncio.get_running_loop().run_until_complete(run())

        # route_envelope must have been called
        assert len(captured_envelopes) == 1, "route_envelope was not called"
        # route_command must NOT have been called
        assert len(route_command_called) == 0, "route_command should not be called from dispatch_agent_remote"
        # The envelope carries agent_runtime mode
        assert captured_envelopes[0].remote_execution_mode == RemoteExecutionMode.agent_runtime

    def test_both_modes_share_route_envelope_as_root(self):
        """Verify that calling route_envelope on a command_only or agent_runtime
        envelope both produce a result carrying remote_execution_mode."""
        from core.schemas.remote_execution import RemoteExecutionMode
        from core.schemas.task_envelope import TaskEnvelope

        route_envelope_call_args: list = []

        async def fake_execute_command(*args, **kwargs):
            return {"success": True, "result": None, "latency_ms": 1.0}

        from core.command_router import CommandRouter
        cr = CommandRouter.__new__(CommandRouter)
        cr._execute_command = fake_execute_command
        # Minimal attribute init to allow route_envelope to proceed
        cr._stats = {"total_dispatched": 0}

        for mode in (RemoteExecutionMode.command_only, RemoteExecutionMode.agent_runtime):
            env = TaskEnvelope(
                task_id=f"task_{uuid.uuid4().hex[:8]}",
                tool_name="ping",
                targets=["dev_test"],
                remote_execution_mode=mode,
            )

            async def run(envelope=env):
                # Patch heavy dependencies that route_envelope might call
                with patch("core.acl_enforcer.get_acl_enforcer") as mock_acl:
                    mock_acl.return_value.check.return_value = MagicMock(allowed=True)
                    with patch("core.task_memory.get_task_memory") as mock_mem:
                        mock_mem.return_value.get_recent_summaries.return_value = []
                        with patch("core.task_lifecycle.get_lifecycle_manager") as mock_lc:
                            mock_lc.return_value.mark_running.return_value = envelope
                            mock_lc.return_value.mark_done.return_value = None
                            mock_lc.return_value.mark_failed.return_value = None
                            cr._execute_command = AsyncMock(
                                return_value={"success": True, "result": None, "latency_ms": 1.0}
                            )
                            result = await cr.route_envelope(envelope)
                            return result

            result = asyncio.get_running_loop().run_until_complete(run())
            assert result.get("remote_execution_mode") == mode.value, (
                f"route_envelope did not propagate mode={mode.value} into result"
            )


# ---------------------------------------------------------------------------
# 2. TestAgentDispatchUsesRouteEnvelope
# ---------------------------------------------------------------------------


class TestAgentDispatchUsesRouteEnvelope:
    """dispatch_agent_remote stamps agent_runtime in the envelope before route_envelope."""

    def test_envelope_has_agent_runtime_mode(self):
        """The envelope passed to route_envelope has remote_execution_mode=agent_runtime."""
        from core.command_router import CommandRouter
        from core.schemas.remote_execution import RemoteExecutionMode

        cr = CommandRouter.__new__(CommandRouter)
        captured: list = []

        async def capture_envelope(env):
            captured.append(env)
            return {"success": True, "result": "ok", "latency_ms": 2.0,
                    "remote_execution_mode": "agent_runtime"}

        cr.route_envelope = capture_envelope

        async def run():
            with patch("core.device_policy.requires_agent_deploy", return_value=False):
                mock_udm = MagicMock()
                mock_udm.get_unified_device_manager.return_value.get_device_type.return_value = "cloud"
                with patch.dict(sys.modules, {"core.unified.device_manager": mock_udm}):
                    await cr.dispatch_agent_remote(
                        device_id="dev_a",
                        agent_id="agt",
                        agent_template="exec",
                        task="go",
                        session_id="s",
                        trace_id="t",
                        task_id="tk",
                    )

        asyncio.get_running_loop().run_until_complete(run())
        assert captured, "route_envelope was not called"
        assert captured[0].remote_execution_mode == RemoteExecutionMode.agent_runtime

    def test_result_carries_agent_runtime(self):
        """The result from dispatch_agent_remote carries remote_execution_mode=agent_runtime."""
        from core.command_router import CommandRouter

        cr = CommandRouter.__new__(CommandRouter)

        async def fake_route_envelope(env):
            return {"success": True, "result": "ok", "latency_ms": 3.0,
                    "remote_execution_mode": "agent_runtime"}

        cr.route_envelope = fake_route_envelope

        async def run():
            with patch("core.device_policy.requires_agent_deploy", return_value=False):
                mock_udm = MagicMock()
                mock_udm.get_unified_device_manager.return_value.get_device_type.return_value = "cloud"
                with patch.dict(sys.modules, {"core.unified.device_manager": mock_udm}):
                    return await cr.dispatch_agent_remote(
                        device_id="dev_b",
                        agent_id="agt2",
                        agent_template="exec",
                        task="run",
                        session_id="s",
                        trace_id="t",
                        task_id="tk",
                    )

        result = asyncio.get_running_loop().run_until_complete(run())
        assert result.get("remote_execution_mode") == "agent_runtime"

    def test_envelope_tool_name_is_agent_execute(self):
        """The envelope constructed by dispatch_agent_remote uses agent_execute as tool_name."""
        from core.command_router import CommandRouter

        cr = CommandRouter.__new__(CommandRouter)
        captured: list = []

        async def capture(env):
            captured.append(env)
            return {"success": True, "result": "ok", "latency_ms": 1.0,
                    "remote_execution_mode": "agent_runtime"}

        cr.route_envelope = capture

        async def run():
            with patch("core.device_policy.requires_agent_deploy", return_value=False):
                mock_udm = MagicMock()
                mock_udm.get_unified_device_manager.return_value.get_device_type.return_value = "cloud"
                with patch.dict(sys.modules, {"core.unified.device_manager": mock_udm}):
                    await cr.dispatch_agent_remote(
                        device_id="dev_c",
                        agent_id="a",
                        agent_template="e",
                        task="t",
                        session_id="s",
                        trace_id="tr",
                        task_id="tid",
                    )

        asyncio.get_running_loop().run_until_complete(run())
        assert captured[0].tool_name == "agent_execute"

    def test_envelope_source_is_dispatch_agent_remote(self):
        """Envelope.source identifies the agent dispatch path."""
        from core.command_router import CommandRouter

        cr = CommandRouter.__new__(CommandRouter)
        captured: list = []

        async def capture(env):
            captured.append(env)
            return {"success": True, "result": "ok", "latency_ms": 1.0,
                    "remote_execution_mode": "agent_runtime"}

        cr.route_envelope = capture

        async def run():
            with patch("core.device_policy.requires_agent_deploy", return_value=False):
                mock_udm = MagicMock()
                mock_udm.get_unified_device_manager.return_value.get_device_type.return_value = "cloud"
                with patch.dict(sys.modules, {"core.unified.device_manager": mock_udm}):
                    await cr.dispatch_agent_remote(
                        device_id="dev_d",
                        agent_id="a",
                        agent_template="e",
                        task="t",
                        session_id="s",
                        trace_id="tr",
                        task_id="tid",
                    )

        asyncio.get_running_loop().run_until_complete(run())
        assert "dispatch_agent_remote" in (captured[0].source or "")


# ---------------------------------------------------------------------------
# 3. TestDeployThenExecuteUsesRouteEnvelope
# ---------------------------------------------------------------------------


class TestDeployThenExecuteUsesRouteEnvelope:
    """_deploy_agent_then_execute stamps agent_runtime in the Step-2 envelope."""

    def _make_cr(self):
        from core.command_router import CommandRouter
        return CommandRouter.__new__(CommandRouter)

    def test_step2_envelope_has_agent_runtime(self):
        from core.schemas.remote_execution import RemoteExecutionMode
        cr = self._make_cr()
        captured: list = []

        async def capture(env):
            captured.append(env)
            return {"success": True, "result": "ok", "latency_ms": 2.0,
                    "remote_execution_mode": "agent_runtime"}

        cr.route_envelope = capture

        mock_cm = MagicMock()
        mock_cm.active_devices = {"android_01": True}
        mock_cm.send_to_device = AsyncMock(return_value=True)

        mock_shared = MagicMock()
        mock_shared.connection_manager = mock_cm

        async def run():
            with patch.dict(sys.modules, {"core.routes._shared": mock_shared}):
                with patch("core.agent_manifest.AgentManifest.create_device_control_agent") as mock_m:
                    m = MagicMock()
                    m.to_dict.return_value = {}
                    m.checksum.return_value = "chk"
                    m.manifest_id = "mid_001"
                    mock_m.return_value = m
                    return await cr._deploy_agent_then_execute(
                        device_id="android_01",
                        device_type="android",
                        agent_id="agt",
                        agent_template="exec",
                        task="run",
                        session_id="s",
                        trace_id="t",
                        task_id="tk",
                        context={},
                    )

        asyncio.get_running_loop().run_until_complete(run())
        assert captured, "route_envelope was not called in _deploy_agent_then_execute"
        assert captured[0].remote_execution_mode == RemoteExecutionMode.agent_runtime

    def test_step2_result_carries_agent_runtime(self):
        cr = self._make_cr()

        async def fake_route(env):
            return {"success": True, "result": "done", "latency_ms": 5.0,
                    "remote_execution_mode": "agent_runtime"}

        cr.route_envelope = fake_route

        mock_cm = MagicMock()
        mock_cm.active_devices = {"android_02": True}
        mock_cm.send_to_device = AsyncMock(return_value=True)

        mock_shared = MagicMock()
        mock_shared.connection_manager = mock_cm

        async def run():
            with patch.dict(sys.modules, {"core.routes._shared": mock_shared}):
                with patch("core.agent_manifest.AgentManifest.create_device_control_agent") as mock_m:
                    m = MagicMock()
                    m.to_dict.return_value = {}
                    m.checksum.return_value = "chk"
                    m.manifest_id = "mid_002"
                    mock_m.return_value = m
                    return await cr._deploy_agent_then_execute(
                        device_id="android_02",
                        device_type="android",
                        agent_id="agt2",
                        agent_template="exec",
                        task="go",
                        session_id="s",
                        trace_id="t",
                        task_id="tk",
                        context={},
                    )

        result = asyncio.get_running_loop().run_until_complete(run())
        assert result.get("remote_execution_mode") == "agent_runtime"


# ---------------------------------------------------------------------------
# 4. TestModeMetadataPropagation
# ---------------------------------------------------------------------------


class TestModeMetadataPropagation:
    """route_envelope propagates remote_execution_mode into the result."""

    def test_agent_runtime_propagated(self):
        from core.schemas.remote_execution import RemoteExecutionMode
        from core.schemas.task_envelope import TaskEnvelope
        from core.command_router import CommandRouter

        cr = CommandRouter.__new__(CommandRouter)

        env = TaskEnvelope(
            task_id="t1",
            tool_name="agent_execute",
            targets=["dev1"],
            remote_execution_mode=RemoteExecutionMode.agent_runtime,
        )

        async def run():
            with patch("core.acl_enforcer.get_acl_enforcer") as mock_acl:
                mock_acl.return_value.check.return_value = MagicMock(allowed=True)
                with patch("core.task_memory.get_task_memory") as mock_mem:
                    mock_mem.return_value.get_recent_summaries.return_value = []
                    with patch("core.task_lifecycle.get_lifecycle_manager") as mock_lc:
                        mock_lc.return_value.mark_running.return_value = env
                        mock_lc.return_value.mark_done.return_value = None
                        cr._execute_command = AsyncMock(
                            return_value={"success": True, "result": None, "latency_ms": 1.0}
                        )
                        return await cr.route_envelope(env)

        result = asyncio.get_running_loop().run_until_complete(run())
        assert result.get("remote_execution_mode") == "agent_runtime"

    def test_command_only_propagated(self):
        from core.schemas.remote_execution import RemoteExecutionMode
        from core.schemas.task_envelope import TaskEnvelope
        from core.command_router import CommandRouter

        cr = CommandRouter.__new__(CommandRouter)

        env = TaskEnvelope(
            task_id="t2",
            tool_name="screenshot",
            targets=["dev2"],
            remote_execution_mode=RemoteExecutionMode.command_only,
        )

        async def run():
            with patch("core.acl_enforcer.get_acl_enforcer") as mock_acl:
                mock_acl.return_value.check.return_value = MagicMock(allowed=True)
                with patch("core.task_memory.get_task_memory") as mock_mem:
                    mock_mem.return_value.get_recent_summaries.return_value = []
                    with patch("core.task_lifecycle.get_lifecycle_manager") as mock_lc:
                        mock_lc.return_value.mark_running.return_value = env
                        mock_lc.return_value.mark_done.return_value = None
                        cr._execute_command = AsyncMock(
                            return_value={"success": True, "result": None, "latency_ms": 1.0}
                        )
                        return await cr.route_envelope(env)

        result = asyncio.get_running_loop().run_until_complete(run())
        assert result.get("remote_execution_mode") == "command_only"

    def test_no_mode_not_propagated(self):
        """When envelope has no mode, result does not gain a spurious mode key."""
        from core.schemas.task_envelope import TaskEnvelope
        from core.command_router import CommandRouter

        cr = CommandRouter.__new__(CommandRouter)

        env = TaskEnvelope(task_id="t3", tool_name="ping", targets=["dev3"])
        assert env.remote_execution_mode is None

        async def run():
            with patch("core.acl_enforcer.get_acl_enforcer") as mock_acl:
                mock_acl.return_value.check.return_value = MagicMock(allowed=True)
                with patch("core.task_memory.get_task_memory") as mock_mem:
                    mock_mem.return_value.get_recent_summaries.return_value = []
                    with patch("core.task_lifecycle.get_lifecycle_manager") as mock_lc:
                        mock_lc.return_value.mark_running.return_value = env
                        mock_lc.return_value.mark_done.return_value = None
                        cr._execute_command = AsyncMock(
                            return_value={"success": True, "result": None, "latency_ms": 1.0}
                        )
                        return await cr.route_envelope(env)

        result = asyncio.get_running_loop().run_until_complete(run())
        # Mode must not be injected when envelope had none
        assert "remote_execution_mode" not in result or result.get("remote_execution_mode") is None


# ---------------------------------------------------------------------------
# 5. TestNATSBusRemoteExecutionModeField
# ---------------------------------------------------------------------------


class TestNATSBusRemoteExecutionModeField:
    """NATSBus._ensure_trace_fields and publish_task_event propagate mode."""

    def test_ensure_trace_fields_adds_mode(self):
        from core.nats_bus import NATSBus
        bus = NATSBus.__new__(NATSBus)
        result = bus._ensure_trace_fields(
            {"action": "dispatch"},
            trace_id="trace_abc",
            runtime_session_id="sess_001",
            remote_execution_mode="agent_runtime",
        )
        assert result["remote_execution_mode"] == "agent_runtime"
        assert result["trace_id"] == "trace_abc"
        assert result["runtime_session_id"] == "sess_001"

    def test_ensure_trace_fields_command_only(self):
        from core.nats_bus import NATSBus
        bus = NATSBus.__new__(NATSBus)
        result = bus._ensure_trace_fields(
            {},
            remote_execution_mode="command_only",
        )
        assert result["remote_execution_mode"] == "command_only"

    def test_ensure_trace_fields_no_override(self):
        """Existing remote_execution_mode in data is not overridden."""
        from core.nats_bus import NATSBus
        bus = NATSBus.__new__(NATSBus)
        result = bus._ensure_trace_fields(
            {"remote_execution_mode": "agent_runtime"},
            remote_execution_mode="command_only",  # should not override
        )
        assert result["remote_execution_mode"] == "agent_runtime"

    def test_ensure_trace_fields_empty_mode_not_added(self):
        """When remote_execution_mode is empty string, it is not added."""
        from core.nats_bus import NATSBus
        bus = NATSBus.__new__(NATSBus)
        result = bus._ensure_trace_fields({}, remote_execution_mode="")
        assert "remote_execution_mode" not in result

    def test_publish_task_event_passes_mode(self):
        """publish_task_event accepts remote_execution_mode kwarg and calls _ensure_trace_fields."""
        from core.nats_bus import NATSBus

        bus = NATSBus.__new__(NATSBus)
        captured_calls: list = []

        def mock_ensure(data, trace_id="", runtime_session_id="", remote_execution_mode=""):
            captured_calls.append({
                "data": data,
                "trace_id": trace_id,
                "remote_execution_mode": remote_execution_mode,
            })
            return {**data, "remote_execution_mode": remote_execution_mode, "_nats_schema": ""}

        bus._ensure_trace_fields = mock_ensure

        async def run():
            with patch.object(bus, "_publish", AsyncMock(return_value={"success": True})):
                await bus.publish_task_event(
                    "dispatch.device_01",
                    {"task_id": "t1"},
                    trace_id="tr_abc",
                    remote_execution_mode="agent_runtime",
                )

        asyncio.get_running_loop().run_until_complete(run())
        assert len(captured_calls) == 1
        assert captured_calls[0]["remote_execution_mode"] == "agent_runtime"


# ---------------------------------------------------------------------------
# 6. TestGatewayNATSAdapterModePreservation
# ---------------------------------------------------------------------------


class TestGatewayNATSAdapterModePreservation:
    """GatewayNATSAdapter extracts and forwards remote_execution_mode."""

    def _make_adapter(self):
        from galaxy_gateway.gateway_nats_adapter import GatewayNATSAdapter
        adapter = GatewayNATSAdapter.__new__(GatewayNATSAdapter)
        adapter._pending = {}
        adapter._stats = {
            "dispatched": 0, "succeeded": 0, "failed": 0,
            "timed_out": 0, "dlq": 0,
        }
        adapter._task_timeout = 30.0
        adapter._max_retries = 0
        adapter._dlq_subject = "galaxy.tasks.deadletter"
        adapter._device_manager = None
        adapter._websocket_manager = None
        return adapter

    def test_handles_task_envelope_with_agent_runtime(self):
        """A TaskEnvelope NATS message with agent_runtime passes mode to _forward_to_device."""
        adapter = self._make_adapter()
        forwarded_mode: list = []

        async def fake_forward(task_id, target, task_type, payload, *, remote_execution_mode=""):
            forwarded_mode.append(remote_execution_mode)
            return {"success": True, "result": None}

        adapter._forward_to_device = fake_forward
        adapter._publish_result = AsyncMock()

        nats_data = {
            "_nats_schema": "TaskEnvelope",
            "task_id": "t_agent",
            "trace_id": "tr_001",
            "targets": ["dev_001"],
            "tool_name": "agent_execute",
            "args": {},
            "metadata": {},
            "remote_execution_mode": "agent_runtime",
        }

        async def run():
            with patch("galaxy_gateway.gateway_nats_adapter._publish_event", AsyncMock()):
                with patch("galaxy_gateway.gateway_nats_adapter._publish_m2_event_safe"):
                    await adapter._handle_task_dispatch(nats_data)

        asyncio.get_running_loop().run_until_complete(run())
        assert forwarded_mode, "_forward_to_device was not called"
        assert forwarded_mode[0] == "agent_runtime", (
            f"Expected agent_runtime, got {forwarded_mode[0]!r}"
        )

    def test_handles_task_envelope_with_command_only(self):
        """A TaskEnvelope NATS message with command_only passes mode to _forward_to_device."""
        adapter = self._make_adapter()
        forwarded_mode: list = []

        async def fake_forward(task_id, target, task_type, payload, *, remote_execution_mode=""):
            forwarded_mode.append(remote_execution_mode)
            return {"success": True, "result": None}

        adapter._forward_to_device = fake_forward
        adapter._publish_result = AsyncMock()

        nats_data = {
            "_nats_schema": "TaskEnvelope",
            "task_id": "t_cmd",
            "trace_id": "tr_002",
            "targets": ["dev_002"],
            "tool_name": "screenshot",
            "args": {},
            "metadata": {},
            "remote_execution_mode": "command_only",
        }

        async def run():
            with patch("galaxy_gateway.gateway_nats_adapter._publish_event", AsyncMock()):
                with patch("galaxy_gateway.gateway_nats_adapter._publish_m2_event_safe"):
                    await adapter._handle_task_dispatch(nats_data)

        asyncio.get_running_loop().run_until_complete(run())
        assert forwarded_mode, "_forward_to_device was not called"
        assert forwarded_mode[0] == "command_only"

    def test_handles_legacy_dispatch_without_mode(self):
        """Legacy TaskDispatch without remote_execution_mode passes empty string."""
        adapter = self._make_adapter()
        forwarded_mode: list = []

        async def fake_forward(task_id, target, task_type, payload, *, remote_execution_mode=""):
            forwarded_mode.append(remote_execution_mode)
            return {"success": True, "result": None}

        adapter._forward_to_device = fake_forward
        adapter._publish_result = AsyncMock()

        legacy_data = {
            "task_id": "t_legacy",
            "target_device_id": "dev_003",
            "task_type": "command",
            "payload": {},
        }

        async def run():
            with patch("galaxy_gateway.gateway_nats_adapter._publish_event", AsyncMock()):
                with patch("galaxy_gateway.gateway_nats_adapter._publish_m2_event_safe"):
                    await adapter._handle_task_dispatch(legacy_data)

        asyncio.get_running_loop().run_until_complete(run())
        assert len(forwarded_mode) > 0, "_forward_to_device was not called"
        # Legacy dispatch has no mode — should pass empty string (not crash)
        assert forwarded_mode[0] == ""


# ---------------------------------------------------------------------------
# 7. TestOpenClawdAgentDispatchAlwaysAgentRuntime
# ---------------------------------------------------------------------------


class TestOpenClawdAgentDispatchAlwaysAgentRuntime:
    """_dispatch_remote_agent always stamps agent_runtime in its internal envelope."""

    def test_internal_envelope_always_agent_runtime(self):
        """Even when PR-6 resolver would return command_only for unknown device,
        _dispatch_remote_agent's internal envelope must carry agent_runtime."""
        from core.schemas.remote_execution import RemoteExecutionMode

        captured_envelopes: list = []

        original_te_init = None

        class CapturingTE:
            def __init__(self, **kwargs):
                captured_envelopes.append(dict(kwargs))

        mock_cr = MagicMock()
        mock_cr.dispatch_agent_remote = AsyncMock(
            return_value={
                "success": True,
                "result": {"response": "done"},
                "latency_ms": 5.0,
                "remote_execution_mode": "agent_runtime",
            }
        )

        async def run():
            from core.openclawd import OpenClawd
            oc = OpenClawd.__new__(OpenClawd)
            oc._config = {}

            # Patch TaskEnvelope to capture constructor calls
            with patch("core.schemas.task_envelope.TaskEnvelope", CapturingTE):
                with patch("core.command_router.get_command_router", return_value=mock_cr):
                    result = await oc._dispatch_remote_agent(
                        message="run task",
                        device_id="unknown_device_xyz",
                        session_id="sess",
                        trace_id="trace",
                    )
            return result

        asyncio.get_running_loop().run_until_complete(run())

        # Find the internal _remote_envelope (from openclawd._dispatch_remote_agent)
        agent_envelopes = [
            e for e in captured_envelopes
            if e.get("source") == "openclawd._dispatch_remote_agent"
        ]
        assert agent_envelopes, "Internal envelope from _dispatch_remote_agent not found"
        env_mode = agent_envelopes[0].get("remote_execution_mode")
        assert env_mode == RemoteExecutionMode.agent_runtime, (
            f"Expected agent_runtime in internal envelope, got {env_mode!r}"
        )

    def test_metadata_remote_execution_mode_is_agent_runtime(self):
        """The returned metadata.remote_execution_mode is agent_runtime even when
        dispatch_agent_remote mock does not return remote_execution_mode."""
        mock_cr = MagicMock()
        mock_cr.dispatch_agent_remote = AsyncMock(
            return_value={
                "success": True,
                "result": {"response": "done"},
                "latency_ms": 5.0,
                # deliberately no remote_execution_mode in result
            }
        )

        async def run():
            from core.openclawd import OpenClawd
            oc = OpenClawd.__new__(OpenClawd)
            oc._config = {}
            with patch("core.command_router.get_command_router", return_value=mock_cr):
                return await oc._dispatch_remote_agent(
                    message="run task",
                    device_id="thin_device",
                    session_id="sess",
                    trace_id="trace",
                )

        result = asyncio.get_running_loop().run_until_complete(run())
        assert result.get("metadata", {}).get("remote_execution_mode") == "agent_runtime"


# ---------------------------------------------------------------------------
# 8. TestBackwardCompatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Existing callers that do not set remote_execution_mode continue to work."""

    def test_route_envelope_without_mode_succeeds(self):
        """A TaskEnvelope without remote_execution_mode routes successfully."""
        from core.schemas.task_envelope import TaskEnvelope
        from core.command_router import CommandRouter

        cr = CommandRouter.__new__(CommandRouter)
        env = TaskEnvelope(task_id="t_compat", tool_name="ping", targets=["dev1"])

        async def run():
            with patch("core.acl_enforcer.get_acl_enforcer") as mock_acl:
                mock_acl.return_value.check.return_value = MagicMock(allowed=True)
                with patch("core.task_memory.get_task_memory") as mock_mem:
                    mock_mem.return_value.get_recent_summaries.return_value = []
                    with patch("core.task_lifecycle.get_lifecycle_manager") as mock_lc:
                        mock_lc.return_value.mark_running.return_value = env
                        mock_lc.return_value.mark_done.return_value = None
                        cr._execute_command = AsyncMock(
                            return_value={"success": True, "result": None, "latency_ms": 1.0}
                        )
                        return await cr.route_envelope(env)

        result = asyncio.get_running_loop().run_until_complete(run())
        assert result["success"] is True

    def test_route_command_compat_shim_still_works(self):
        """route_command (compat shim) still delegates to route_envelope correctly."""
        from core.command_router import CommandRouter

        cr = CommandRouter.__new__(CommandRouter)
        route_envelope_called: list = []

        async def capture(env):
            route_envelope_called.append(env)
            return {"success": True, "result": None, "latency_ms": 1.0}

        cr.route_envelope = capture

        async def run():
            return await cr.route_command(
                device_id="dev_shim",
                command="ping",
                payload={},
                command_id="cmd_001",
                task_id="task_001",
            )

        result = asyncio.get_running_loop().run_until_complete(run())
        assert len(route_envelope_called) == 1, "route_command did not call route_envelope"
        assert result["success"] is True

    def test_nats_bus_publish_task_event_without_mode_works(self):
        """publish_task_event without remote_execution_mode kwarg still publishes."""
        from core.nats_bus import NATSBus

        bus = NATSBus.__new__(NATSBus)
        published: list = []

        async def fake_publish(subject, data):
            published.append({"subject": subject, "data": data})
            return {"success": True}

        bus._publish = fake_publish

        async def run():
            await bus.publish_task_event(
                "dispatch.device_01",
                {"task_id": "t_compat"},
                trace_id="tr_compat",
            )

        asyncio.get_running_loop().run_until_complete(run())
        assert published, "publish was not called"
        assert "galaxy.task." in published[0]["subject"]
