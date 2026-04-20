"""tests/test_prf_android_single_device_dispatch.py
====================================================
Tests for the PR-F wiring: single-device Android execution routed through
SourceDispatchOrchestrator as the canonical dispatch brain.

Coverage:
  1.  New sentinel constants are exported from source_dispatch_orchestrator.
  2.  openclawd._delegate_single_remote uses orchestrator dispatch (not just plan).
  3.  When orchestrator succeeds with android_bridge_dispatch, result is returned
      directly without falling through to _dispatch_remote_agent.
  4.  Orchestrator dispatch metadata is attached to the response metadata.
  5.  When orchestrator does not handle Android (device not in bridge), falls
      through to _dispatch_remote_agent unchanged.
  6.  When orchestrator dispatch raises, falls through to _dispatch_remote_agent.
  7.  MessageBuilder.task_assign propagates trace_id as a top-level AIP field.
  8.  MessageBuilder.task_assign without trace_id remains backward compatible.
  9.  AndroidBridge.assign_task extracts trace_id from payload and surfaces it
      in the MessageBuilder call.
  10. AndroidBridge.assign_task logs trace_id when orchestrator_dispatch is set.
  11. dispatch_via=orchestrator:android_bridge in metadata when bridge handles it.
  12. _dispatch_remote_agent is NOT called when orchestrator handles Android.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orch_result(
    success: bool = True,
    action_taken: str = "android_bridge_dispatch",
    mode: str = "remote_handoff",
    dispatch_id: str = "dispatch_001",
    decision_reason: str = "android_bridge_dispatch:success",
    android_bridge_response: Optional[Dict[str, Any]] = None,
) -> Any:
    """Build a minimal mock SourceDispatchResult."""
    result_dict = {
        "dispatch_id": dispatch_id,
        "mode": mode,
        "success": success,
        "decision_reason": decision_reason,
        "result": {
            "action_taken": action_taken,
            "success": success,
            "android_bridge_response": android_bridge_response or {"success": True},
            "device_id": "android_dev_001",
            "task_id": "task_001",
        },
    }
    mock_result = MagicMock()
    mock_result.success = success
    mock_result.mode = mode
    mock_result.dispatch_id = dispatch_id
    mock_result.decision_reason = decision_reason
    mock_result.result = result_dict["result"]
    mock_result.to_dict = lambda: result_dict
    return mock_result


# ---------------------------------------------------------------------------
# 1. Sentinel constants exported
# ---------------------------------------------------------------------------


class TestSentinelConstantsExported:
    def test_openclawd_single_remote_uses_orchestrator_dispatch_sentinel(self):
        from core.runtime.source_dispatch_orchestrator import (
            OPENCLAWD_SINGLE_REMOTE_USES_ORCHESTRATOR_DISPATCH_SENTINEL,
        )

        assert "android_bridge_dispatch" in OPENCLAWD_SINGLE_REMOTE_USES_ORCHESTRATOR_DISPATCH_SENTINEL
        assert "orchestrator" in OPENCLAWD_SINGLE_REMOTE_USES_ORCHESTRATOR_DISPATCH_SENTINEL.lower()

    def test_openclawd_single_remote_orchestrator_dispatch_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            OPENCLAWD_SINGLE_REMOTE_ORCHESTRATOR_DISPATCH_POLICY,
        )

        assert "android_bridge_dispatch" in OPENCLAWD_SINGLE_REMOTE_ORCHESTRATOR_DISPATCH_POLICY
        assert "_dispatch_remote_agent" in OPENCLAWD_SINGLE_REMOTE_ORCHESTRATOR_DISPATCH_POLICY

    def test_android_bridge_dispatch_chain_is_canonical_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            ANDROID_BRIDGE_DISPATCH_CHAIN_IS_CANONICAL_POLICY,
        )

        assert "assign_task" in ANDROID_BRIDGE_DISPATCH_CHAIN_IS_CANONICAL_POLICY
        assert "trace_id" in ANDROID_BRIDGE_DISPATCH_CHAIN_IS_CANONICAL_POLICY.lower()


# ---------------------------------------------------------------------------
# 2 & 3. _delegate_single_remote uses orchestrator dispatch, returns directly
# ---------------------------------------------------------------------------


class TestDelegateSingleRemoteUsesOrchestratorDispatch:
    """_delegate_single_remote must use _orch.dispatch() and return the result
    directly when action_taken == "android_bridge_dispatch"."""

    @pytest.mark.asyncio
    async def test_returns_orchestrator_result_when_android_bridge_handles(
        self, monkeypatch
    ):
        """When orchestrator dispatch succeeds with android_bridge_dispatch,
        _delegate_single_remote returns without calling _dispatch_remote_agent."""
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)
        remote_agent_call_count = {"n": 0}

        async def _fake_dispatch_remote_agent(**kw):
            remote_agent_call_count["n"] += 1
            return {"success": True, "response": "remote_agent_result"}

        oc._dispatch_remote_agent = _fake_dispatch_remote_agent  # type: ignore[attr-defined]

        mock_result = _make_orch_result(
            success=True,
            action_taken="android_bridge_dispatch",
        )

        mock_orch = MagicMock()
        mock_orch.dispatch = MagicMock(return_value=mock_result)

        mock_sdo_cls = MagicMock(return_value=mock_orch)

        monkeypatch.setattr(
            "core.openclawd.SourceDispatchOrchestrator",
            mock_sdo_cls,
            raising=False,
        )

        # Patch the import inside _delegate_single_remote
        import sys

        fake_sdo_mod = MagicMock()
        fake_sdo_mod.SourceDispatchOrchestrator = mock_sdo_cls
        monkeypatch.setitem(
            sys.modules,
            "core.runtime.source_dispatch_orchestrator",
            fake_sdo_mod,
        )

        result = await oc._delegate_single_remote(  # type: ignore[attr-defined]
            message="take a screenshot",
            device_id="android_dev_001",
            session_id="sess_001",
            trace_id="trace_001",
        )

        # Must succeed and indicate android bridge path
        assert result["success"] is True
        assert result["metadata"]["delegation_point"] == "single_remote"
        assert result["metadata"]["dispatch_via"] == "orchestrator:android_bridge"
        # _dispatch_remote_agent must NOT have been called
        assert remote_agent_call_count["n"] == 0

    @pytest.mark.asyncio
    async def test_falls_through_when_orchestrator_does_not_handle_android(
        self, monkeypatch
    ):
        """When orchestrator dispatch does not produce android_bridge_dispatch
        (e.g., device not in bridge), _dispatch_remote_agent is called."""
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)
        remote_agent_call_count = {"n": 0}

        async def _fake_dispatch_remote_agent(**kw):
            remote_agent_call_count["n"] += 1
            return {"success": True, "response": "remote_agent_result"}

        oc._dispatch_remote_agent = _fake_dispatch_remote_agent  # type: ignore[attr-defined]

        # Orchestrator returns "not android" scenario
        mock_result = _make_orch_result(
            success=False,
            action_taken="none",
            mode="fallback_local",
            decision_reason="device_not_in_android_bridge",
        )

        import sys

        mock_sdo_cls = MagicMock()
        mock_sdo_cls.return_value.dispatch.return_value = mock_result
        fake_sdo_mod = MagicMock()
        fake_sdo_mod.SourceDispatchOrchestrator = mock_sdo_cls
        monkeypatch.setitem(
            sys.modules,
            "core.runtime.source_dispatch_orchestrator",
            fake_sdo_mod,
        )

        result = await oc._delegate_single_remote(  # type: ignore[attr-defined]
            message="run task",
            device_id="non_android_dev",
            session_id="sess_002",
            trace_id="trace_002",
        )

        # Must call _dispatch_remote_agent as fallback
        assert remote_agent_call_count["n"] == 1
        assert result["metadata"]["delegation_point"] == "single_remote"

    @pytest.mark.asyncio
    async def test_falls_through_when_orchestrator_raises(self, monkeypatch):
        """When the orchestrator import raises, _dispatch_remote_agent is called."""
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)
        remote_agent_call_count = {"n": 0}

        async def _fake_dispatch_remote_agent(**kw):
            remote_agent_call_count["n"] += 1
            return {"success": True, "response": "remote_agent_result"}

        oc._dispatch_remote_agent = _fake_dispatch_remote_agent  # type: ignore[attr-defined]

        import sys

        # Remove the module to force ImportError
        monkeypatch.setitem(
            sys.modules,
            "core.runtime.source_dispatch_orchestrator",
            None,  # type: ignore[arg-type]
        )

        result = await oc._delegate_single_remote(  # type: ignore[attr-defined]
            message="do something",
            device_id="some_device",
        )

        assert remote_agent_call_count["n"] == 1
        assert result["metadata"]["delegation_point"] == "single_remote"


# ---------------------------------------------------------------------------
# 4. Orchestrator metadata attached to response
# ---------------------------------------------------------------------------


class TestOrchestratorMetadataAttached:
    @pytest.mark.asyncio
    async def test_orchestrator_metadata_in_response_on_android_bridge(
        self, monkeypatch
    ):
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)

        mock_result = _make_orch_result(
            success=True,
            action_taken="android_bridge_dispatch",
            dispatch_id="dp_meta_001",
            mode="remote_handoff",
        )

        import sys

        mock_sdo_cls = MagicMock()
        mock_sdo_cls.return_value.dispatch.return_value = mock_result
        fake_sdo_mod = MagicMock()
        fake_sdo_mod.SourceDispatchOrchestrator = mock_sdo_cls
        monkeypatch.setitem(
            sys.modules, "core.runtime.source_dispatch_orchestrator", fake_sdo_mod
        )

        result = await oc._delegate_single_remote(  # type: ignore[attr-defined]
            message="test",
            device_id="android_dev_meta",
            trace_id="trace_meta",
        )

        meta = result.get("metadata", {})
        assert meta.get("orchestrator_dispatch_id") == "dp_meta_001"
        assert meta.get("orchestrator_mode") == "remote_handoff"
        assert meta.get("orchestrator_action_taken") == "android_bridge_dispatch"

    @pytest.mark.asyncio
    async def test_orchestrator_metadata_in_response_on_fallthrough(
        self, monkeypatch
    ):
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)

        async def _fake_remote_agent(**kw):
            return {"success": True, "response": "ok"}

        oc._dispatch_remote_agent = _fake_remote_agent  # type: ignore[attr-defined]

        mock_result = _make_orch_result(
            success=False,
            action_taken="none",
            dispatch_id="dp_fall_001",
            mode="local",
        )

        import sys

        mock_sdo_cls = MagicMock()
        mock_sdo_cls.return_value.dispatch.return_value = mock_result
        fake_sdo_mod = MagicMock()
        fake_sdo_mod.SourceDispatchOrchestrator = mock_sdo_cls
        monkeypatch.setitem(
            sys.modules, "core.runtime.source_dispatch_orchestrator", fake_sdo_mod
        )

        result = await oc._delegate_single_remote(  # type: ignore[attr-defined]
            message="test",
            device_id="non_android",
        )

        meta = result.get("metadata", {})
        assert meta.get("orchestrator_dispatch_id") == "dp_fall_001"
        assert meta.get("orchestrator_action_taken") == "none"


# ---------------------------------------------------------------------------
# 7 & 8. MessageBuilder.task_assign trace_id support
# ---------------------------------------------------------------------------


class TestMessageBuilderTaskAssignTraceId:
    def test_task_assign_with_trace_id_adds_top_level_field(self):
        from galaxy_gateway.android.message_builder import MessageBuilder

        msg = MessageBuilder.task_assign(
            device_id="dev_001",
            task_id="task_001",
            task_type="screenshot",
            payload={"goal": "take screenshot"},
            trace_id="trace_abc",
        )

        assert msg["trace_id"] == "trace_abc"
        assert msg["task_id"] == "task_001"
        assert msg["task_type"] == "screenshot"
        assert msg["payload"] == {"goal": "take screenshot"}

    def test_task_assign_without_trace_id_backward_compatible(self):
        from galaxy_gateway.android.message_builder import MessageBuilder

        msg = MessageBuilder.task_assign(
            device_id="dev_002",
            task_id="task_002",
            task_type="click",
            payload={"x": 100, "y": 200},
        )

        # No trace_id field — backward compatible
        assert "trace_id" not in msg
        assert msg["task_id"] == "task_002"
        assert msg["task_type"] == "click"

    def test_task_assign_trace_id_none_does_not_add_field(self):
        from galaxy_gateway.android.message_builder import MessageBuilder

        msg = MessageBuilder.task_assign(
            device_id="dev_003",
            task_id="task_003",
            task_type="swipe",
            payload={},
            trace_id=None,
        )

        assert "trace_id" not in msg

    def test_task_assign_with_trace_id_does_not_affect_payload(self):
        from galaxy_gateway.android.message_builder import MessageBuilder

        payload = {"orchestrator_dispatch": True, "trace_id": "nested_trace"}
        msg = MessageBuilder.task_assign(
            device_id="dev_004",
            task_id="task_004",
            task_type="generic",
            payload=payload,
            trace_id="top_trace",
        )

        # Top-level trace_id is the explicit param, not the nested one
        assert msg["trace_id"] == "top_trace"
        # Payload is unchanged
        assert msg["payload"]["trace_id"] == "nested_trace"


# ---------------------------------------------------------------------------
# 9. AndroidBridge.assign_task surfaces trace_id from payload
# ---------------------------------------------------------------------------


class TestAndroidBridgeAssignTaskTraceId:
    @pytest.mark.asyncio
    async def test_assign_task_extracts_trace_id_from_payload_to_message_builder(
        self, monkeypatch
    ):
        """AndroidBridge.assign_task extracts trace_id from payload and passes
        it to MessageBuilder.task_assign as a keyword argument."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.android.message_builder import MessageBuilder

        bridge = AndroidBridge.__new__(AndroidBridge)
        bridge._devices = {"dev_trace": MagicMock()}
        bridge._lock = asyncio.Lock()

        captured_task_assign_kwargs = {}

        original_task_assign = MessageBuilder.task_assign

        @classmethod  # type: ignore[misc]
        def _capture_task_assign(
            cls,
            device_id,
            task_id,
            task_type,
            payload,
            priority=5,
            timeout=300,
            trace_id=None,
        ):
            captured_task_assign_kwargs.update(
                {
                    "device_id": device_id,
                    "task_id": task_id,
                    "trace_id": trace_id,
                }
            )
            return original_task_assign.__func__(
                cls, device_id, task_id, task_type, payload, priority, timeout, trace_id
            )

        # Force DeviceRouter lookup to fail so we use the fallback send_to_device path
        import sys

        fake_dr_mod = MagicMock()
        fake_dr_mod.device_router.devices.get = MagicMock(return_value=None)
        monkeypatch.setitem(
            sys.modules, "galaxy_gateway.device_router", fake_dr_mod
        )

        # Patch MessageBuilder.task_assign to capture kwargs
        monkeypatch.setattr(
            "galaxy_gateway.android.message_builder.MessageBuilder.task_assign",
            _capture_task_assign,
        )

        # Patch send_to_device to avoid actual network calls
        async def _fake_send(dev_id, msg, **kw):
            return {"success": True}

        bridge.send_to_device = _fake_send  # type: ignore[method-assign]

        payload = {
            "trace_id": "trace_from_payload",
            "orchestrator_dispatch": True,
        }
        await bridge.assign_task(
            device_id="dev_trace",
            task_id="task_trace",
            task_type="screenshot",
            payload=payload,
        )

        assert captured_task_assign_kwargs.get("trace_id") == "trace_from_payload"

    @pytest.mark.asyncio
    async def test_assign_task_no_trace_id_in_payload_passes_none(
        self, monkeypatch
    ):
        """When payload has no trace_id, MessageBuilder.task_assign is called
        with trace_id=None."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.android.message_builder import MessageBuilder

        bridge = AndroidBridge.__new__(AndroidBridge)
        bridge._devices = {"dev_no_trace": MagicMock()}
        bridge._lock = asyncio.Lock()

        captured_trace_id = {"value": "SENTINEL"}

        original_task_assign = MessageBuilder.task_assign

        @classmethod  # type: ignore[misc]
        def _capture(cls, dev_id, task_id, task_type, payload, priority=5, timeout=300, trace_id=None):
            captured_trace_id["value"] = trace_id
            return original_task_assign.__func__(
                cls, dev_id, task_id, task_type, payload, priority, timeout, trace_id
            )

        import sys

        fake_dr_mod = MagicMock()
        fake_dr_mod.device_router.devices.get = MagicMock(return_value=None)
        monkeypatch.setitem(sys.modules, "galaxy_gateway.device_router", fake_dr_mod)
        monkeypatch.setattr(
            "galaxy_gateway.android.message_builder.MessageBuilder.task_assign",
            _capture,
        )

        async def _fake_send(dev_id, msg, **kw):
            return {"success": True}

        bridge.send_to_device = _fake_send  # type: ignore[method-assign]

        await bridge.assign_task(
            device_id="dev_no_trace",
            task_id="task_no_trace",
            task_type="click",
            payload={"x": 10, "y": 20},
        )

        assert captured_trace_id["value"] is None


# ---------------------------------------------------------------------------
# 11. dispatch_via field correct
# ---------------------------------------------------------------------------


class TestDispatchViaField:
    @pytest.mark.asyncio
    async def test_dispatch_via_is_orchestrator_android_bridge(self, monkeypatch):
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)

        mock_result = _make_orch_result(
            success=True,
            action_taken="android_bridge_dispatch",
        )

        import sys

        mock_sdo_cls = MagicMock()
        mock_sdo_cls.return_value.dispatch.return_value = mock_result
        fake_sdo_mod = MagicMock()
        fake_sdo_mod.SourceDispatchOrchestrator = mock_sdo_cls
        monkeypatch.setitem(
            sys.modules, "core.runtime.source_dispatch_orchestrator", fake_sdo_mod
        )

        result = await oc._delegate_single_remote(  # type: ignore[attr-defined]
            message="screenshot",
            device_id="android_dev_dispatch",
        )

        assert result["metadata"]["dispatch_via"] == "orchestrator:android_bridge"

    @pytest.mark.asyncio
    async def test_dispatch_via_not_set_when_fallthrough(self, monkeypatch):
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)

        async def _fake_remote(**kw):
            return {"success": True, "response": "ok"}

        oc._dispatch_remote_agent = _fake_remote  # type: ignore[attr-defined]

        mock_result = _make_orch_result(success=False, action_taken="none")

        import sys

        mock_sdo_cls = MagicMock()
        mock_sdo_cls.return_value.dispatch.return_value = mock_result
        fake_sdo_mod = MagicMock()
        fake_sdo_mod.SourceDispatchOrchestrator = mock_sdo_cls
        monkeypatch.setitem(
            sys.modules, "core.runtime.source_dispatch_orchestrator", fake_sdo_mod
        )

        result = await oc._delegate_single_remote(  # type: ignore[attr-defined]
            message="run",
            device_id="non_android",
        )

        # dispatch_via should not be set when we fell through
        assert result["metadata"].get("dispatch_via") != "orchestrator:android_bridge"


# ---------------------------------------------------------------------------
# 12. _dispatch_remote_agent not called when bridge handles it
# ---------------------------------------------------------------------------


class TestRemoteAgentNotCalledForAndroid:
    @pytest.mark.asyncio
    async def test_dispatch_remote_agent_not_invoked_for_android(self, monkeypatch):
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)

        was_called = {"remote_agent": False}

        async def _fake_remote_agent(**kw):
            was_called["remote_agent"] = True
            return {"success": True, "response": "remote"}

        oc._dispatch_remote_agent = _fake_remote_agent  # type: ignore[attr-defined]

        mock_result = _make_orch_result(
            success=True,
            action_taken="android_bridge_dispatch",
        )

        import sys

        mock_sdo_cls = MagicMock()
        mock_sdo_cls.return_value.dispatch.return_value = mock_result
        fake_sdo_mod = MagicMock()
        fake_sdo_mod.SourceDispatchOrchestrator = mock_sdo_cls
        monkeypatch.setitem(
            sys.modules, "core.runtime.source_dispatch_orchestrator", fake_sdo_mod
        )

        result = await oc._delegate_single_remote(  # type: ignore[attr-defined]
            message="android task",
            device_id="android_main",
            trace_id="trace_no_remote",
        )

        assert result["success"] is True
        assert was_called["remote_agent"] is False, (
            "_dispatch_remote_agent should NOT be called when "
            "orchestrator handles Android dispatch"
        )
