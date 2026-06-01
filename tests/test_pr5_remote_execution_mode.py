#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr5_remote_execution_mode.py
========================================
PR-5 — RemoteExecutionMode abstraction tests

Validates the canonical RemoteExecutionMode enum and its propagation
through the remote command and remote agent dispatch paths.

Test classes:

  1. TestRemoteExecutionModeEnum      — enum values, serialization
  2. TestTaskEnvelopeRemoteMode       — field on TaskEnvelope, backward compat
  3. TestOpenClawdRemoteCommandMode   — send_gateway_command carries command_only
  4. TestOpenClawdRemoteAgentMode     — _dispatch_remote_agent carries agent_runtime
  5. TestCommandRouterPreservesMode   — route_envelope propagates mode to result
  6. TestCommandRouterDispatchAgent   — dispatch_agent_remote carries agent_runtime
  7. TestBackwardCompatibility        — callers without mode continue to work

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# 1. TestRemoteExecutionModeEnum
# ---------------------------------------------------------------------------


class TestRemoteExecutionModeEnum:
    """Canonical enum values and serialization."""

    def test_enum_has_agent_runtime(self):
        from core.schemas.remote_execution import RemoteExecutionMode

        assert RemoteExecutionMode.agent_runtime == "agent_runtime"

    def test_enum_has_command_only(self):
        from core.schemas.remote_execution import RemoteExecutionMode

        assert RemoteExecutionMode.command_only == "command_only"

    def test_enum_is_string_subclass(self):
        from core.schemas.remote_execution import RemoteExecutionMode

        assert isinstance(RemoteExecutionMode.agent_runtime, str)
        assert isinstance(RemoteExecutionMode.command_only, str)

    def test_enum_values_are_stable_strings(self):
        from core.schemas.remote_execution import RemoteExecutionMode

        assert RemoteExecutionMode.agent_runtime.value == "agent_runtime"
        assert RemoteExecutionMode.command_only.value == "command_only"

    def test_enum_roundtrip(self):
        from core.schemas.remote_execution import RemoteExecutionMode

        assert RemoteExecutionMode("agent_runtime") is RemoteExecutionMode.agent_runtime
        assert RemoteExecutionMode("command_only") is RemoteExecutionMode.command_only

    def test_only_two_members(self):
        from core.schemas.remote_execution import RemoteExecutionMode

        members = list(RemoteExecutionMode)
        assert len(members) == 2


# ---------------------------------------------------------------------------
# 2. TestTaskEnvelopeRemoteMode
# ---------------------------------------------------------------------------


class TestTaskEnvelopeRemoteMode:
    """TaskEnvelope carries the optional remote_execution_mode field."""

    def test_default_is_none(self):
        from core.schemas.task_envelope import TaskEnvelope

        env = TaskEnvelope(tool_name="ping", targets=["dev1"])
        assert env.remote_execution_mode is None

    def test_can_set_agent_runtime(self):
        from core.schemas.remote_execution import RemoteExecutionMode
        from core.schemas.task_envelope import TaskEnvelope

        env = TaskEnvelope(
            tool_name="agent_execute",
            targets=["device_001"],
            remote_execution_mode=RemoteExecutionMode.agent_runtime,
        )
        assert env.remote_execution_mode == RemoteExecutionMode.agent_runtime

    def test_can_set_command_only(self):
        from core.schemas.remote_execution import RemoteExecutionMode
        from core.schemas.task_envelope import TaskEnvelope

        env = TaskEnvelope(
            tool_name="take_screenshot",
            targets=["device_001"],
            remote_execution_mode=RemoteExecutionMode.command_only,
        )
        assert env.remote_execution_mode == RemoteExecutionMode.command_only

    def test_serialized_value_is_string(self):
        from core.schemas.remote_execution import RemoteExecutionMode
        from core.schemas.task_envelope import TaskEnvelope

        env = TaskEnvelope(
            tool_name="agent_execute",
            targets=["device_001"],
            remote_execution_mode=RemoteExecutionMode.agent_runtime,
        )
        dumped = env.model_dump(mode="json")
        assert dumped["remote_execution_mode"] == "agent_runtime"

    def test_exclude_none_omits_missing_mode(self):
        from core.schemas.task_envelope import TaskEnvelope

        env = TaskEnvelope(tool_name="ping", targets=["dev1"])
        dumped = env.model_dump(mode="json", exclude_none=True)
        assert "remote_execution_mode" not in dumped

    def test_mode_accepted_as_plain_string(self):
        from core.schemas.task_envelope import TaskEnvelope

        env = TaskEnvelope(
            tool_name="cmd",
            targets=["dev"],
            remote_execution_mode="command_only",  # type: ignore[arg-type]
        )
        assert env.remote_execution_mode.value == "command_only"

    def test_model_copy_preserves_mode(self):
        from core.schemas.remote_execution import RemoteExecutionMode
        from core.schemas.task_envelope import TaskEnvelope

        env = TaskEnvelope(
            tool_name="t",
            targets=["d"],
            remote_execution_mode=RemoteExecutionMode.command_only,
        )
        copy = env.model_copy(update={"tool_name": "t2"})
        assert copy.remote_execution_mode == RemoteExecutionMode.command_only


# ---------------------------------------------------------------------------
# 3. TestOpenClawdRemoteCommandMode
# ---------------------------------------------------------------------------


class TestOpenClawdRemoteCommandMode:
    """send_gateway_command constructs a command_only envelope."""

    def _make_openclawd(self):
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)
        # Minimal attribute initialisation to avoid side effects
        oc._config = {}
        return oc

    def test_envelope_carries_command_only(self):
        """The TaskEnvelope constructed inside send_gateway_command has
        remote_execution_mode == command_only."""
        from core.schemas.remote_execution import RemoteExecutionMode

        captured: list = []

        async def fake_route_envelope(envelope):
            captured.append(envelope)
            return {"success": True, "response": "ok"}

        mock_cr = MagicMock()
        mock_cr.route_envelope = fake_route_envelope

        async def run():
            with patch(
                "core.command_router.get_command_router", return_value=mock_cr
            ):
                oc = self._make_openclawd()
                await oc.send_gateway_command(
                    device_id="dev_001",
                    command="take_screenshot",
                    payload={},
                )

        asyncio.get_running_loop().run_until_complete(run())

        assert len(captured) == 1
        env = captured[0]
        assert env.remote_execution_mode == RemoteExecutionMode.command_only


# ---------------------------------------------------------------------------
# 4. TestOpenClawdRemoteAgentMode
# ---------------------------------------------------------------------------


class TestOpenClawdRemoteAgentMode:
    """_dispatch_remote_agent constructs an agent_runtime envelope and returns
    remote_execution_mode in its metadata."""

    def test_return_metadata_carries_agent_runtime(self):
        """When CommandRouter.dispatch_agent_remote succeeds, the returned
        metadata dict from _dispatch_remote_agent must include
        remote_execution_mode='agent_runtime'."""

        mock_cr = MagicMock()
        mock_cr.dispatch_agent_remote = AsyncMock(
            return_value={
                "success": True,
                "result": {"response": "done"},
                "latency_ms": 10.0,
            }
        )

        async def run():
            from core.openclawd import OpenClawd

            oc = OpenClawd.__new__(OpenClawd)
            oc._config = {}

            with patch(
                "core.command_router.get_command_router", return_value=mock_cr
            ):
                result = await oc._dispatch_remote_agent(
                    message="run task",
                    device_id="dev_002",
                    session_id="sess_abc",
                    trace_id="trace_xyz",
                )
            return result

        result = asyncio.get_running_loop().run_until_complete(run())

        assert result.get("metadata", {}).get("remote_execution_mode") == "agent_runtime"

    def test_envelope_carries_agent_runtime(self):
        """The TaskEnvelope constructed inside _dispatch_remote_agent must
        carry remote_execution_mode == agent_runtime."""
        from core.schemas.remote_execution import RemoteExecutionMode

        captured_envelopes: list = []

        class CapturingTaskEnvelope:
            """Wrapper to capture envelope kwargs."""

            def __init__(self, **kwargs):
                captured_envelopes.append(kwargs)

        mock_cr = MagicMock()
        mock_cr.dispatch_agent_remote = AsyncMock(
            return_value={
                "success": True,
                "result": {"response": "ok"},
                "latency_ms": 5.0,
            }
        )

        async def run():
            from core.openclawd import OpenClawd

            oc = OpenClawd.__new__(OpenClawd)
            oc._config = {}

            with patch(
                "core.command_router.get_command_router", return_value=mock_cr
            ), patch(
                "core.schemas.task_envelope.TaskEnvelope",
                side_effect=CapturingTaskEnvelope,
            ):
                await oc._dispatch_remote_agent(
                    message="do something",
                    device_id="dev_003",
                )

        asyncio.get_running_loop().run_until_complete(run())

        assert len(captured_envelopes) >= 1
        modes = [
            e.get("remote_execution_mode")
            for e in captured_envelopes
            if "remote_execution_mode" in e
        ]
        assert any(m == RemoteExecutionMode.agent_runtime for m in modes), (
            f"Expected agent_runtime in captured envelope kwargs, got: {captured_envelopes}"
        )


# ---------------------------------------------------------------------------
# 5. TestCommandRouterPreservesMode
# ---------------------------------------------------------------------------


class TestCommandRouterPreservesMode:
    """route_envelope propagates remote_execution_mode into the result dict."""

    def _build_router(self):
        from core.command_router import CommandRouter

        cr = CommandRouter.__new__(CommandRouter)
        cr._circuit_breakers = {}
        cr._audit_handlers = []
        cr._history = []
        return cr

    def test_agent_runtime_appears_in_result(self):
        from core.schemas.remote_execution import RemoteExecutionMode
        from core.schemas.task_envelope import TaskEnvelope

        env = TaskEnvelope(
            task_id="task_001",
            trace_id="trace_001",
            source="test",
            targets=["dev_001"],
            tool_name="agent_execute",
            remote_execution_mode=RemoteExecutionMode.agent_runtime,
        )

        fake_result: Dict[str, Any] = {
            "success": True,
            "result": "ok",
            "request_id": "req_001",
            "task_id": "task_001",
            "command_id": "task_001",
            "device_id": "dev_001",
            "command": "agent_execute",
            "via": "command_router",
            "latency_ms": 5.0,
        }

        async def run():
            cr = self._build_router()
            with patch.object(cr, "_execute_command", AsyncMock(return_value=fake_result)):
                # Bypass optional lifecycle / acl / memory hooks
                with patch("core.acl_enforcer.get_acl_enforcer", side_effect=ImportError):
                    with patch("core.task_memory.get_task_memory", side_effect=ImportError):
                        with patch(
                            "core.task_lifecycle.get_lifecycle_manager",
                            side_effect=ImportError,
                        ):
                            return await cr.route_envelope(env)

        result = asyncio.get_running_loop().run_until_complete(run())
        assert result.get("remote_execution_mode") == "agent_runtime"

    def test_command_only_appears_in_result(self):
        from core.schemas.remote_execution import RemoteExecutionMode
        from core.schemas.task_envelope import TaskEnvelope

        env = TaskEnvelope(
            task_id="task_002",
            trace_id="trace_002",
            source="test",
            targets=["dev_001"],
            tool_name="take_screenshot",
            remote_execution_mode=RemoteExecutionMode.command_only,
        )

        fake_result: Dict[str, Any] = {
            "success": True,
            "result": "screenshot.png",
            "request_id": "req_002",
            "task_id": "task_002",
            "command_id": "task_002",
            "device_id": "dev_001",
            "command": "take_screenshot",
            "via": "command_router",
            "latency_ms": 3.0,
        }

        async def run():
            cr = self._build_router()
            with patch.object(cr, "_execute_command", AsyncMock(return_value=fake_result)):
                with patch("core.acl_enforcer.get_acl_enforcer", side_effect=ImportError):
                    with patch("core.task_memory.get_task_memory", side_effect=ImportError):
                        with patch(
                            "core.task_lifecycle.get_lifecycle_manager",
                            side_effect=ImportError,
                        ):
                            return await cr.route_envelope(env)

        result = asyncio.get_running_loop().run_until_complete(run())
        assert result.get("remote_execution_mode") == "command_only"

    def test_none_mode_not_added_to_result(self):
        from core.schemas.task_envelope import TaskEnvelope

        env = TaskEnvelope(
            task_id="task_003",
            trace_id="trace_003",
            source="test",
            targets=["dev_001"],
            tool_name="ping",
        )
        # remote_execution_mode defaults to None

        fake_result: Dict[str, Any] = {
            "success": True,
            "result": "pong",
            "request_id": "req_003",
            "task_id": "task_003",
            "command_id": "task_003",
            "device_id": "dev_001",
            "command": "ping",
            "via": "command_router",
            "latency_ms": 1.0,
        }

        async def run():
            cr = self._build_router()
            with patch.object(cr, "_execute_command", AsyncMock(return_value=fake_result)):
                with patch("core.acl_enforcer.get_acl_enforcer", side_effect=ImportError):
                    with patch("core.task_memory.get_task_memory", side_effect=ImportError):
                        with patch(
                            "core.task_lifecycle.get_lifecycle_manager",
                            side_effect=ImportError,
                        ):
                            return await cr.route_envelope(env)

        result = asyncio.get_running_loop().run_until_complete(run())
        # When mode is None, route_envelope must NOT inject the key
        assert "remote_execution_mode" not in result


# ---------------------------------------------------------------------------
# 6. TestCommandRouterDispatchAgent
# ---------------------------------------------------------------------------


class TestCommandRouterDispatchAgent:
    """dispatch_agent_remote result carries remote_execution_mode='agent_runtime'."""

    def test_dispatch_agent_result_carries_agent_runtime(self):
        from core.command_router import CommandRouter
        import sys

        cr = CommandRouter.__new__(CommandRouter)

        fake_route_result: Dict[str, Any] = {
            "success": True,
            "result": "completed",
            "latency_ms": 20.0,
            "via": "command_router",
        }

        # Create minimal mocks for the heavy dependencies imported inside dispatch_agent_remote
        mock_udm_module = MagicMock()
        mock_udm = MagicMock()
        mock_udm.get_device_type.return_value = "cloud"
        mock_udm_module.get_unified_device_manager.return_value = mock_udm

        async def run():
            with patch.object(cr, "route_envelope", AsyncMock(return_value=fake_route_result)):
                with patch("core.device_policy.requires_agent_deploy", return_value=False):
                    with patch.dict(
                        sys.modules,
                        {"core.unified.device_manager": mock_udm_module},
                    ):
                        return await cr.dispatch_agent_remote(
                            device_id="cloud_001",
                            agent_id="agent_abc",
                            agent_template="executor",
                            task="do something",
                            session_id="sess_001",
                            trace_id="trace_001",
                            task_id="task_001",
                        )

        result = asyncio.get_running_loop().run_until_complete(run())
        assert result.get("remote_execution_mode") == "agent_runtime"

    def test_deploy_then_execute_result_carries_agent_runtime(self):
        """Physical device pre-deploy path also carries agent_runtime."""
        from core.command_router import CommandRouter
        import sys

        cr = CommandRouter.__new__(CommandRouter)

        fake_route_result: Dict[str, Any] = {
            "success": True,
            "result": "executed",
            "latency_ms": 30.0,
            "via": "command_router",
        }

        mock_udm_module = MagicMock()
        mock_udm = MagicMock()
        mock_udm.get_device_type.return_value = "android"
        mock_udm_module.get_unified_device_manager.return_value = mock_udm

        mock_cm = MagicMock()
        mock_cm.active_devices = {"android_001": True}
        mock_cm.send_to_device = AsyncMock(return_value=True)

        mock_shared_module = MagicMock()
        mock_shared_module.connection_manager = mock_cm

        async def run():
            with patch.object(cr, "route_envelope", AsyncMock(return_value=fake_route_result)):
                with patch("core.device_policy.requires_agent_deploy", return_value=True):
                    with patch.dict(
                        sys.modules,
                        {
                            "core.unified.device_manager": mock_udm_module,
                            "core.routes._shared": mock_shared_module,
                        },
                    ):
                        with patch(
                            "core.agent_manifest.AgentManifest.create_device_control_agent"
                        ) as mock_manifest:
                            manifest_obj = MagicMock()
                            manifest_obj.to_dict.return_value = {}
                            manifest_obj.checksum.return_value = "abc123"
                            manifest_obj.manifest_id = "manifest_001"
                            mock_manifest.return_value = manifest_obj
                            return await cr.dispatch_agent_remote(
                                device_id="android_001",
                                agent_id="agent_xyz",
                                agent_template="executor",
                                task="run app",
                                session_id="sess_002",
                                trace_id="trace_002",
                                task_id="task_002",
                            )

        result = asyncio.get_running_loop().run_until_complete(run())
        assert result.get("remote_execution_mode") == "agent_runtime"


# ---------------------------------------------------------------------------
# 7. TestBackwardCompatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Callers that do not set remote_execution_mode continue to work."""

    def test_task_envelope_without_mode_is_valid(self):
        from core.schemas.task_envelope import TaskEnvelope

        env = TaskEnvelope(tool_name="run", targets=["dev1"])
        assert env.remote_execution_mode is None
        # Serialization should not include the field when None (exclude_none)
        d = env.model_dump(mode="json", exclude_none=True)
        assert "remote_execution_mode" not in d

    def test_envelope_from_command_request_has_no_mode(self):
        from core.schemas.task_envelope import envelope_from_command_request

        env = envelope_from_command_request(
            command="ping",
            targets=["dev1"],
            params={},
        )
        assert env.remote_execution_mode is None

    def test_envelope_from_relay_request_has_no_mode(self):
        from core.schemas.task_envelope import envelope_from_relay_request

        env = envelope_from_relay_request(
            source_device="host",
            target_device="phone",
            payload_type="command",
            payload={"cmd": "wake"},
        )
        assert env.remote_execution_mode is None

    def test_envelope_from_mcp_call_has_no_mode(self):
        from core.schemas.task_envelope import envelope_from_mcp_call

        env = envelope_from_mcp_call(
            server_name="filesystem",
            tool_name="read_file",
            arguments={"path": "/tmp/x"},
        )
        assert env.remote_execution_mode is None

    def test_route_command_compat_shim_has_no_mode(self):
        """route_command (compat shim) builds an envelope without mode."""
        from core.schemas.task_envelope import TaskEnvelope

        captured: list = []

        async def run():
            from core.command_router import CommandRouter

            cr = CommandRouter.__new__(CommandRouter)

            async def fake_route_envelope(env):
                captured.append(env)
                return {"success": True, "result": "ok", "latency_ms": 1.0}

            with patch.object(cr, "route_envelope", side_effect=fake_route_envelope):
                await cr.route_command(
                    device_id="dev_001",
                    command="ping",
                    payload={},
                    command_id="cmd_001",
                    task_id="task_001",
                )

        asyncio.get_running_loop().run_until_complete(run())
        assert len(captured) == 1
        assert captured[0].remote_execution_mode is None
