"""tests/test_prf_android_canonical_dispatch.py
================================================
Tests for PR-F: Stabilise single-device Android execution through the
canonical SourceDispatchOrchestrator path.

Coverage:
  1.  PR-F sentinel strings are exported from source_dispatch_orchestrator.
  2.  MessageBuilder.task_assign_from_orchestrator_dispatch stamps
      orchestrator_dispatch=True at message level.
  3.  MessageBuilder.task_assign_from_orchestrator_dispatch stamps
      trace_id / session_id at message level.
  4.  MessageBuilder.task_assign_from_orchestrator_dispatch falls back
      gracefully when trace_id / session_id are None.
  5.  task_assign_from_orchestrator_dispatch includes canonical TASK_ASSIGN
      fields (task_id, task_type, payload, priority, timeout).
  6.  AndroidBridge.assign_task uses task_assign_from_orchestrator_dispatch
      in the fallback path when orchestrator_dispatch=True is in payload.
  7.  AndroidBridge.assign_task uses plain task_assign in the fallback path
      when orchestrator_dispatch is absent from payload.
  8.  _delegate_single_remote routes to Android bridge via orchestrator
      when orchestrator succeeds with android_bridge_dispatch.
  9.  _delegate_single_remote falls through to _dispatch_remote_agent when
      orchestrator does not return android_bridge_dispatch (non-Android target).
  10. _delegate_single_remote falls through to _dispatch_remote_agent when
      orchestrator raises an exception (robustness guard).
  11. _delegate_single_remote result carries delegation_point="single_remote"
      even when orchestrator dispatch succeeds.
  12. consume_android_behavioral_result is not degraded by PR-F changes
      (lifecycle/result backflow unaffected).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. PR-F sentinel strings are exported
# ---------------------------------------------------------------------------


class TestPRFSentinelsExported:
    def test_single_remote_delegates_through_orchestrator_sentinel(self):
        from core.runtime.source_dispatch_orchestrator import (
            SINGLE_REMOTE_DELEGATES_THROUGH_ORCHESTRATOR_PR_F_SENTINEL,
        )

        assert "PR_F" in SINGLE_REMOTE_DELEGATES_THROUGH_ORCHESTRATOR_PR_F_SENTINEL
        assert "single_remote" in SINGLE_REMOTE_DELEGATES_THROUGH_ORCHESTRATOR_PR_F_SENTINEL.lower()

    def test_single_remote_android_bridge_canonical_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            SINGLE_REMOTE_ANDROID_BRIDGE_IS_CANONICAL_DISPATCH_PR_F_POLICY,
        )

        assert "android_bridge_dispatch" in SINGLE_REMOTE_ANDROID_BRIDGE_IS_CANONICAL_DISPATCH_PR_F_POLICY
        assert "PR-F" in SINGLE_REMOTE_ANDROID_BRIDGE_IS_CANONICAL_DISPATCH_PR_F_POLICY

    def test_orchestrator_dispatch_message_builder_contract_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            ORCHESTRATOR_DISPATCH_MESSAGE_BUILDER_CONTRACT_PR_F_POLICY,
        )

        assert "task_assign_from_orchestrator_dispatch" in ORCHESTRATOR_DISPATCH_MESSAGE_BUILDER_CONTRACT_PR_F_POLICY
        assert "PR-F" in ORCHESTRATOR_DISPATCH_MESSAGE_BUILDER_CONTRACT_PR_F_POLICY

    def test_android_result_lifecycle_not_degraded_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            ANDROID_RESULT_LIFECYCLE_NOT_DEGRADED_PR_F_POLICY,
        )

        assert "PR-F" in ANDROID_RESULT_LIFECYCLE_NOT_DEGRADED_PR_F_POLICY
        assert "consume_android_behavioral_result" in ANDROID_RESULT_LIFECYCLE_NOT_DEGRADED_PR_F_POLICY


# ---------------------------------------------------------------------------
# 2-5. MessageBuilder.task_assign_from_orchestrator_dispatch
# ---------------------------------------------------------------------------


class TestMessageBuilderOrchestratorDispatch:
    """task_assign_from_orchestrator_dispatch stamps orchestrator context."""

    def test_orchestrator_dispatch_flag_at_top_level(self):
        from galaxy_gateway.android.message_builder import MessageBuilder

        msg = MessageBuilder.task_assign_from_orchestrator_dispatch(
            device_id="dev_001",
            task_id="task_001",
            task_type="screenshot",
            payload={"quality": 80},
        )

        assert msg["orchestrator_dispatch"] is True

    def test_trace_id_at_top_level(self):
        from galaxy_gateway.android.message_builder import MessageBuilder

        msg = MessageBuilder.task_assign_from_orchestrator_dispatch(
            device_id="dev_001",
            task_id="task_001",
            task_type="screenshot",
            payload={},
            trace_id="trace_abc",
        )

        assert msg["trace_id"] == "trace_abc"

    def test_session_id_at_top_level(self):
        from galaxy_gateway.android.message_builder import MessageBuilder

        msg = MessageBuilder.task_assign_from_orchestrator_dispatch(
            device_id="dev_001",
            task_id="task_001",
            task_type="screenshot",
            payload={},
            session_id="sess_xyz",
        )

        assert msg["session_id"] == "sess_xyz"

    def test_none_trace_and_session_not_added(self):
        from galaxy_gateway.android.message_builder import MessageBuilder

        msg = MessageBuilder.task_assign_from_orchestrator_dispatch(
            device_id="dev_001",
            task_id="task_001",
            task_type="screenshot",
            payload={},
        )

        assert "trace_id" not in msg
        assert "session_id" not in msg
        assert msg["orchestrator_dispatch"] is True

    def test_canonical_task_assign_fields_present(self):
        from galaxy_gateway.android.message_builder import MessageBuilder

        payload = {"goal": "take screenshot"}
        msg = MessageBuilder.task_assign_from_orchestrator_dispatch(
            device_id="dev_001",
            task_id="task_001",
            task_type="screenshot",
            payload=payload,
            priority=3,
            timeout=60,
        )

        assert msg["task_id"] == "task_001"
        assert msg["task_type"] == "screenshot"
        assert msg["payload"] == payload
        assert msg["priority"] == 3
        assert msg["timeout"] == 60
        assert msg["device_id"] == "dev_001"

    def test_type_is_task_assign(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        from galaxy_gateway.protocol.aip_v3 import MessageType

        msg = MessageBuilder.task_assign_from_orchestrator_dispatch(
            device_id="dev_001",
            task_id="task_001",
            task_type="click",
            payload={},
        )

        assert msg["type"] == MessageType.TASK_ASSIGN.value


# ---------------------------------------------------------------------------
# 6-7. AndroidBridge.assign_task uses correct MessageBuilder in fallback path
# ---------------------------------------------------------------------------


class TestAndroidBridgeAssignTaskOrchestratorBuilder:
    """assign_task uses task_assign_from_orchestrator_dispatch in fallback
    when orchestrator_dispatch=True; uses plain task_assign otherwise."""

    @pytest.mark.asyncio
    async def test_fallback_uses_orchestrator_builder_when_flag_set(self):
        """When DeviceRouter is absent and orchestrator_dispatch=True, the
        fallback should call task_assign_from_orchestrator_dispatch."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = "dev_orch_fallback"
        # Put device in transport cache but NOT in DeviceRouter
        mock_dev = MagicMock()
        mock_dev.device_id = device_id
        mock_dev.connected = True
        bridge._devices[device_id] = mock_dev

        sent_messages: list = []

        async def _fake_send(did, msg, **kw):
            sent_messages.append(msg)
            return {"success": True}

        bridge.send_to_device = _fake_send

        # DeviceRouter has no entry for this device
        mock_router = MagicMock()
        mock_router.devices = {}

        with patch("galaxy_gateway.device_router.device_router", mock_router):
            await bridge.assign_task(
                device_id,
                "task_fb_001",
                "screenshot",
                {"quality": 80, "orchestrator_dispatch": True, "trace_id": "t1"},
            )

        assert len(sent_messages) == 1
        msg = sent_messages[0]
        # PR-F: orchestrator context should be at message top level
        assert msg.get("orchestrator_dispatch") is True
        assert msg.get("trace_id") == "t1"

    @pytest.mark.asyncio
    async def test_fallback_uses_plain_builder_when_flag_absent(self):
        """When DeviceRouter is absent and orchestrator_dispatch NOT in payload,
        the fallback uses plain task_assign (no top-level orchestrator fields)."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = "dev_plain_fallback"
        mock_dev = MagicMock()
        mock_dev.device_id = device_id
        mock_dev.connected = True
        bridge._devices[device_id] = mock_dev

        sent_messages: list = []

        async def _fake_send(did, msg, **kw):
            sent_messages.append(msg)
            return {"success": True}

        bridge.send_to_device = _fake_send

        mock_router = MagicMock()
        mock_router.devices = {}

        with patch("galaxy_gateway.device_router.device_router", mock_router):
            await bridge.assign_task(
                device_id,
                "task_plain_001",
                "click",
                {"x": 100, "y": 200},
            )

        assert len(sent_messages) == 1
        msg = sent_messages[0]
        # Plain builder does NOT add orchestrator_dispatch at top level
        assert "orchestrator_dispatch" not in msg


# ---------------------------------------------------------------------------
# 8. _delegate_single_remote routes through orchestrator for Android targets
# ---------------------------------------------------------------------------


class TestDelegateSingleRemoteAndroidOrchestrator:
    """_delegate_single_remote should route Android targets through the
    SourceDispatchOrchestrator canonical path (PR-F)."""

    @pytest.mark.asyncio
    async def test_android_bridge_dispatch_path_taken(self, monkeypatch):
        """When orchestrator succeeds with android_bridge_dispatch, the result
        should be returned directly without calling _dispatch_remote_agent."""
        from contracts.source_dispatch import SourceDispatchMode

        device_id = "android_single_001"
        _dispatch_remote_agent_called = []

        # Build a mock orchestrator result
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.mode = SourceDispatchMode.remote_handoff
        mock_result.to_dict = lambda: {
            "dispatch_id": "disp_001",
            "mode": "remote_handoff",
            "success": True,
            "decision_reason": "android_bridge_dispatch:success",
            "result": {
                "action_taken": "android_bridge_dispatch",
                "device_id": device_id,
            },
        }

        monkeypatch.setattr(
            "core.runtime.source_dispatch_orchestrator.orchestrate_source_runtime_dispatch",
            lambda **kw: mock_result,
        )

        # Import OpenClawd lazily to avoid heavy bootstrap
        try:
            from core.openclawd import OpenClawd
        except Exception:
            pytest.skip("OpenClawd import failed — skipping integration test")

        openclawd = OpenClawd.__new__(OpenClawd)

        async def _fake_dispatch_remote_agent(**kw):
            _dispatch_remote_agent_called.append(True)
            return {"success": True, "response": "remote_agent_dispatched"}

        openclawd._dispatch_remote_agent = _fake_dispatch_remote_agent

        intent = MagicMock()
        intent.command = "screenshot"
        intent.params = {"quality": 80}

        result = await openclawd._delegate_single_remote(
            message="take a screenshot",
            intent=intent,
            device_id=device_id,
            session_id="sess_001",
            trace_id="trace_001",
        )

        # _dispatch_remote_agent must NOT have been called
        assert not _dispatch_remote_agent_called, (
            "_dispatch_remote_agent should not be called when orchestrator "
            "handles Android bridge dispatch"
        )
        assert result["success"] is True
        assert result["metadata"]["delegation_point"] == "single_remote"
        assert result["metadata"]["dispatch_mode"] == "android_bridge"

    @pytest.mark.asyncio
    async def test_falls_through_to_dispatch_remote_agent_for_non_android(self, monkeypatch):
        """When orchestrator returns a non-android_bridge_dispatch result
        (e.g. non-Android target), _dispatch_remote_agent should be called."""
        from contracts.source_dispatch import SourceDispatchMode

        device_id = "desktop_device_001"

        # Orchestrator returns success=False (device not in android bridge)
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.mode = SourceDispatchMode.remote_handoff
        mock_result.to_dict = lambda: {
            "dispatch_id": "disp_002",
            "mode": "remote_handoff",
            "success": False,
            "decision_reason": "remote_handoff:no_target_or_envelope:fallback_local",
            "result": {},
        }

        monkeypatch.setattr(
            "core.runtime.source_dispatch_orchestrator.orchestrate_source_runtime_dispatch",
            lambda **kw: mock_result,
        )

        try:
            from core.openclawd import OpenClawd
        except Exception:
            pytest.skip("OpenClawd import failed — skipping integration test")

        openclawd = OpenClawd.__new__(OpenClawd)

        _dispatch_remote_agent_called = []

        async def _fake_dispatch_remote_agent(**kw):
            _dispatch_remote_agent_called.append(True)
            return {"success": True, "response": "remote_agent_dispatched"}

        openclawd._dispatch_remote_agent = _fake_dispatch_remote_agent

        intent = MagicMock()
        intent.command = "agent_task"
        intent.params = {}

        result = await openclawd._delegate_single_remote(
            message="do something",
            intent=intent,
            device_id=device_id,
            session_id="sess_002",
            trace_id="trace_002",
        )

        # _dispatch_remote_agent MUST have been called as fallback
        assert _dispatch_remote_agent_called, (
            "_dispatch_remote_agent should be called when orchestrator "
            "does not handle Android bridge dispatch"
        )
        assert result["metadata"]["delegation_point"] == "single_remote"

    @pytest.mark.asyncio
    async def test_falls_through_when_orchestrator_raises(self, monkeypatch):
        """When orchestrate_source_runtime_dispatch raises, _dispatch_remote_agent
        is called as a safe fallback (no silent failure)."""
        monkeypatch.setattr(
            "core.runtime.source_dispatch_orchestrator.orchestrate_source_runtime_dispatch",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("orchestrator_error")),
        )

        try:
            from core.openclawd import OpenClawd
        except Exception:
            pytest.skip("OpenClawd import failed — skipping integration test")

        openclawd = OpenClawd.__new__(OpenClawd)

        _dispatch_remote_agent_called = []

        async def _fake_dispatch_remote_agent(**kw):
            _dispatch_remote_agent_called.append(True)
            return {"success": True, "response": "remote_agent_dispatched"}

        openclawd._dispatch_remote_agent = _fake_dispatch_remote_agent

        intent = MagicMock()
        intent.command = "screenshot"
        intent.params = {}

        result = await openclawd._delegate_single_remote(
            message="take screenshot",
            intent=intent,
            device_id="android_exc_001",
            session_id=None,
            trace_id="trace_exc",
        )

        # Must fall through to _dispatch_remote_agent when orchestrator raises
        assert _dispatch_remote_agent_called
        assert result["metadata"]["delegation_point"] == "single_remote"


# ---------------------------------------------------------------------------
# 11. delegation_point is always present in result
# ---------------------------------------------------------------------------


class TestDelegateSingleRemoteDelegationPointAlwaysSet:
    @pytest.mark.asyncio
    async def test_delegation_point_in_android_bridge_result(self, monkeypatch):
        """delegation_point='single_remote' must be present even when
        orchestrator handles the dispatch via Android bridge."""
        from contracts.source_dispatch import SourceDispatchMode

        device_id = "android_dp_001"

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.mode = SourceDispatchMode.remote_handoff
        mock_result.to_dict = lambda: {
            "dispatch_id": "disp_dp_001",
            "mode": "remote_handoff",
            "success": True,
            "decision_reason": "android_bridge_dispatch:success",
            "result": {
                "action_taken": "android_bridge_dispatch",
                "device_id": device_id,
            },
        }

        monkeypatch.setattr(
            "core.runtime.source_dispatch_orchestrator.orchestrate_source_runtime_dispatch",
            lambda **kw: mock_result,
        )

        try:
            from core.openclawd import OpenClawd
        except Exception:
            pytest.skip("OpenClawd import failed — skipping integration test")

        openclawd = OpenClawd.__new__(OpenClawd)
        openclawd._dispatch_remote_agent = AsyncMock(
            return_value={"success": True, "response": "fallback"}
        )

        intent = MagicMock()
        intent.command = "screenshot"
        intent.params = {}

        result = await openclawd._delegate_single_remote(
            message="snap",
            intent=intent,
            device_id=device_id,
            session_id=None,
            trace_id=None,
        )

        assert result["metadata"]["delegation_point"] == "single_remote"


# ---------------------------------------------------------------------------
# 12. consume_android_behavioral_result not degraded
# ---------------------------------------------------------------------------


class TestConsumeAndroidBehavioralResultNotDegraded:
    """PR-F must not degrade consume_android_behavioral_result (result
    backflow path is independent of outbound dispatch routing)."""

    def test_consume_android_behavioral_result_still_callable(self):
        from core.runtime.source_dispatch_orchestrator import SourceDispatchOrchestrator

        orch = SourceDispatchOrchestrator()
        # Build a minimal mock reconcile outcome
        mock_outcome = MagicMock()
        mock_outcome.signal_kind = "goal_execution_result"
        mock_outcome.result_kind = "success"
        mock_outcome.contract_id = str(uuid.uuid4())
        mock_outcome.session_id = "sess_bfr_001"
        mock_outcome.task_id = "task_bfr_001"
        mock_outcome.was_updated = True

        result = orch.consume_android_behavioral_result(
            mock_outcome,
            trace_id="trace_bfr",
            session_id="sess_bfr_001",
            task_id="task_bfr_001",
        )

        assert isinstance(result, dict)
        # Must return a structured dict with at least a 'consumed' key
        assert "consumed" in result
