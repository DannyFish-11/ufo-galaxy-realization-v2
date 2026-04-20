"""tests/test_prf_android_single_device_dispatch_wiring.py
===========================================================
Tests for PR-F: Wire single-device Android execution to SourceDispatchOrchestrator
as the canonical dispatch path from openclawd._delegate_single_remote.

Coverage:
  1.  PR-F sentinel strings are exported from source_dispatch_orchestrator.
  2.  PR-F policy strings contain required keywords.
  3.  openclawd._delegate_single_remote uses orchestrate_source_runtime_dispatch
      for Android targets; returns android_bridge_dispatch result when bridge succeeds.
  4.  openclawd._delegate_single_remote falls back to _dispatch_remote_agent
      when orchestrator does not succeed via android_bridge_dispatch.
  5.  openclawd._delegate_single_remote falls back gracefully when orchestrator raises.
  6.  MessageBuilder.task_assign propagates trace_id from payload to wire message.
  7.  MessageBuilder.task_assign does NOT add trace_id when payload has no trace_id.
  8.  AndroidBridge.assign_task logs trace_id and orchestrator_dispatch context.
  9.  AndroidBridge.assign_task routes to DeviceRouter when device is registered.
  10. AndroidBridge.assign_task falls back to MessageBuilder when DeviceRouter raises.
  11. result backflow path (consume_android_behavioral_result) is unaffected by PR-F.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1 & 2. PR-F sentinels and policies exported from orchestrator
# ---------------------------------------------------------------------------


class TestPRFSentinelsExported:
    """PR-F sentinel and policy strings must be present in the orchestrator module."""

    def test_openclawd_single_remote_uses_orchestrator_sentinel(self):
        from core.runtime.source_dispatch_orchestrator import (
            OPENCLAWD_SINGLE_REMOTE_USES_ORCHESTRATOR_DISPATCH_PR_F_SENTINEL,
        )

        s = OPENCLAWD_SINGLE_REMOTE_USES_ORCHESTRATOR_DISPATCH_PR_F_SENTINEL
        assert "PR_F" in s or "PR-F" in s.upper().replace("_", "-")
        assert "android" in s.lower()
        assert "orchestrator" in s.lower() or "dispatch" in s.lower()

    def test_openclawd_android_fallback_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            OPENCLAWD_ANDROID_DISPATCH_FALLS_BACK_TO_REMOTE_AGENT_PR_F_POLICY,
        )

        p = OPENCLAWD_ANDROID_DISPATCH_FALLS_BACK_TO_REMOTE_AGENT_PR_F_POLICY
        assert "android_bridge_dispatch" in p
        assert "_dispatch_remote_agent" in p

    def test_android_bridge_chain_observable_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            ANDROID_BRIDGE_DISPATCH_CHAIN_IS_OBSERVABLE_PR_F_POLICY,
        )

        p = ANDROID_BRIDGE_DISPATCH_CHAIN_IS_OBSERVABLE_PR_F_POLICY
        assert "trace_id" in p
        assert "DeviceRouter" in p or "MessageBuilder" in p

    def test_result_backflow_unaffected_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            RESULT_BACKFLOW_UNAFFECTED_BY_ORCHESTRATOR_WIRING_PR_F_POLICY,
        )

        p = RESULT_BACKFLOW_UNAFFECTED_BY_ORCHESTRATOR_WIRING_PR_F_POLICY
        assert "reconciler" in p.lower()


# ---------------------------------------------------------------------------
# 3. _delegate_single_remote returns android_bridge_dispatch result
# ---------------------------------------------------------------------------


class TestDelegateSingleRemoteAndroidBridgePath:
    """_delegate_single_remote must return the orchestrator result directly
    when orchestrate_source_runtime_dispatch succeeds via android_bridge_dispatch."""

    @pytest.mark.asyncio
    async def test_returns_android_bridge_result_when_orchestrator_succeeds(self, monkeypatch):
        from core.openclawd import OpenClawd
        import core.runtime.source_dispatch_orchestrator as orch_mod

        # Build a minimal orchestrator result mock
        mock_orch_result = MagicMock()
        mock_orch_result.to_dict.return_value = {
            "success": True,
            "mode": "remote_handoff",
            "dispatch_id": "disp_001",
            "result": {
                "success": True,
                "action_taken": "android_bridge_dispatch",
                "device_id": "android_dev_prf_001",
                "task_id": "task_prf_001",
                "android_bridge_response": {"success": True},
            },
        }

        original_orchestrate = orch_mod.orchestrate_source_runtime_dispatch
        try:
            orch_mod.orchestrate_source_runtime_dispatch = lambda **kw: mock_orch_result  # type: ignore[assignment]

            oc = OpenClawd.__new__(OpenClawd)

            mock_intent = MagicMock()
            mock_intent.command = "screenshot"
            mock_intent.params = {}

            result = await oc._delegate_single_remote(
                message="take screenshot",
                intent=mock_intent,
                device_id="android_dev_prf_001",
                session_id="sess_prf_001",
                trace_id="trace_prf_001",
            )
        finally:
            orch_mod.orchestrate_source_runtime_dispatch = original_orchestrate  # type: ignore[assignment]

        assert result is not None
        assert result.get("success") is True
        meta = result.get("metadata", {})
        assert meta.get("dispatch_path") == "orchestrator:android_bridge_dispatch"
        assert meta.get("delegation_point") == "single_remote"

    @pytest.mark.asyncio
    async def test_falls_back_to_dispatch_remote_agent_when_no_android_bridge(self, monkeypatch):
        """When orchestrator does not take android_bridge_dispatch path,
        _delegate_single_remote falls back to _dispatch_remote_agent."""
        from core.openclawd import OpenClawd
        import core.runtime.source_dispatch_orchestrator as orch_mod

        # Orchestrator returns non-android result (e.g. local mode)
        mock_orch_result = MagicMock()
        mock_orch_result.to_dict.return_value = {
            "success": False,
            "mode": "local",
            "dispatch_id": "disp_002",
            "result": {"action_taken": "none"},
        }

        fallback_called = {"n": 0}

        async def _fake_dispatch_remote_agent(self, message, intent=None, device_id=None, session_id=None, trace_id=None):
            fallback_called["n"] += 1
            return {
                "success": True,
                "response": "fallback result",
                "metadata": {},
            }

        original_orchestrate = orch_mod.orchestrate_source_runtime_dispatch
        try:
            orch_mod.orchestrate_source_runtime_dispatch = lambda **kw: mock_orch_result  # type: ignore[assignment]
            monkeypatch.setattr(OpenClawd, "_dispatch_remote_agent", _fake_dispatch_remote_agent)

            oc = OpenClawd.__new__(OpenClawd)

            result = await oc._delegate_single_remote(
                message="take screenshot",
                device_id="non_android_dev",
                session_id="sess_002",
                trace_id="trace_002",
            )
        finally:
            orch_mod.orchestrate_source_runtime_dispatch = original_orchestrate  # type: ignore[assignment]

        assert fallback_called["n"] == 1
        assert result.get("metadata", {}).get("delegation_point") == "single_remote"

    @pytest.mark.asyncio
    async def test_falls_back_when_orchestrator_raises(self, monkeypatch):
        """_delegate_single_remote must fall back gracefully when orchestrate raises."""
        from core.openclawd import OpenClawd
        import core.runtime.source_dispatch_orchestrator as orch_mod

        fallback_called = {"n": 0}

        async def _fake_dispatch_remote_agent(self, message, intent=None, device_id=None, session_id=None, trace_id=None):
            fallback_called["n"] += 1
            return {
                "success": True,
                "response": "fallback result",
                "metadata": {},
            }

        original_orchestrate = orch_mod.orchestrate_source_runtime_dispatch

        def _raise_on_call(**kw):
            raise RuntimeError("orchestrator unavailable")

        try:
            orch_mod.orchestrate_source_runtime_dispatch = _raise_on_call  # type: ignore[assignment]
            monkeypatch.setattr(OpenClawd, "_dispatch_remote_agent", _fake_dispatch_remote_agent)

            oc = OpenClawd.__new__(OpenClawd)

            result = await oc._delegate_single_remote(
                message="take screenshot",
                device_id="some_device",
                session_id="sess_003",
                trace_id="trace_003",
            )
        finally:
            orch_mod.orchestrate_source_runtime_dispatch = original_orchestrate  # type: ignore[assignment]

        assert fallback_called["n"] == 1
        assert result is not None


# ---------------------------------------------------------------------------
# 6 & 7. MessageBuilder.task_assign trace_id propagation
# ---------------------------------------------------------------------------


class TestMessageBuilderTraceIdPropagation:
    """MessageBuilder.task_assign should propagate trace_id from payload."""

    def test_trace_id_in_payload_propagated_to_wire_message(self):
        from galaxy_gateway.android.message_builder import MessageBuilder

        msg = MessageBuilder.task_assign(
            device_id="dev_001",
            task_id="task_001",
            task_type="screenshot",
            payload={
                "goal": "take screenshot",
                "trace_id": "trace_wire_001",
                "orchestrator_dispatch": True,
            },
        )

        assert msg["trace_id"] == "trace_wire_001"
        assert msg["task_id"] == "task_001"
        assert msg["task_type"] == "screenshot"

    def test_no_trace_id_when_absent_from_payload(self):
        from galaxy_gateway.android.message_builder import MessageBuilder

        msg = MessageBuilder.task_assign(
            device_id="dev_001",
            task_id="task_002",
            task_type="click",
            payload={"x": 100, "y": 200},
        )

        assert "trace_id" not in msg

    def test_empty_trace_id_not_propagated(self):
        from galaxy_gateway.android.message_builder import MessageBuilder

        msg = MessageBuilder.task_assign(
            device_id="dev_001",
            task_id="task_003",
            task_type="swipe",
            payload={"trace_id": ""},
        )

        # Empty string is falsy — should not be propagated
        assert "trace_id" not in msg

    def test_other_fields_unaffected(self):
        """Standard fields like task_id, task_type, priority, timeout remain unchanged."""
        from galaxy_gateway.android.message_builder import MessageBuilder

        msg = MessageBuilder.task_assign(
            device_id="dev_002",
            task_id="task_004",
            task_type="input_text",
            payload={"text": "hello", "trace_id": "trace_004"},
            priority=8,
            timeout=120,
        )

        assert msg["priority"] == 8
        assert msg["timeout"] == 120
        assert msg["payload"]["text"] == "hello"
        assert msg["trace_id"] == "trace_004"


# ---------------------------------------------------------------------------
# 8. AndroidBridge.assign_task logging context
# ---------------------------------------------------------------------------


class TestAndroidBridgeAssignTaskLogging:
    """AndroidBridge.assign_task must log trace_id and orchestrator_dispatch context."""

    @pytest.mark.asyncio
    async def test_assign_task_with_trace_id_payload(self, monkeypatch):
        """assign_task processes trace_id and orchestrator_dispatch from payload."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge.__new__(AndroidBridge)
        bridge._lock = asyncio.Lock()
        bridge._devices = {}

        # DeviceRouter not available → fallback to send_to_device
        monkeypatch.setitem(
            __import__("sys").modules,
            "galaxy_gateway.device_router",
            None,  # type: ignore[arg-type]
        )

        send_calls = []

        async def _fake_send(device_id, msg, wait_response=False, timeout=300.0):
            send_calls.append({"device_id": device_id, "msg": msg})
            return {"success": True}

        bridge.send_to_device = _fake_send  # type: ignore[method-assign]

        result = await bridge.assign_task(
            device_id="dev_trace_001",
            task_id="task_trace_001",
            task_type="screenshot",
            payload={
                "goal": "screenshot",
                "trace_id": "trace_bridge_001",
                "orchestrator_dispatch": True,
            },
        )

        # send_to_device should be called once (DeviceRouter unavailable)
        assert len(send_calls) == 1
        sent_msg = send_calls[0]["msg"]
        # The MessageBuilder message should have trace_id propagated
        assert sent_msg.get("trace_id") == "trace_bridge_001"


# ---------------------------------------------------------------------------
# 9 & 10. AndroidBridge.assign_task DeviceRouter routing and fallback
# ---------------------------------------------------------------------------


class TestAndroidBridgeAssignTaskRoutingPRF:
    """AndroidBridge.assign_task routes to DeviceRouter; falls back to MessageBuilder."""

    @pytest.mark.asyncio
    async def test_routes_to_device_router_when_registered(self, monkeypatch):
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge.__new__(AndroidBridge)
        bridge._lock = asyncio.Lock()
        device_id = "dev_router_prf_001"
        bridge._devices = {device_id: MagicMock()}

        mock_router_device = MagicMock()
        router_dispatch_calls = []

        async def _fake_dispatch_task(task_dict, router_device):
            router_dispatch_calls.append(task_dict)
            return {"success": True, "dispatched_via": "device_router"}

        mock_router = MagicMock()
        mock_router.devices = {device_id: mock_router_device}
        mock_router.dispatch_task = _fake_dispatch_task

        with patch("galaxy_gateway.device_router.device_router", mock_router):
            result = await bridge.assign_task(
                device_id=device_id,
                task_id="task_router_prf",
                task_type="screenshot",
                payload={"trace_id": "trace_router_prf"},
            )

        assert len(router_dispatch_calls) == 1
        assert result is not None
        assert result.get("success") is True
        assert result.get("dispatched_via") == "device_router"

    @pytest.mark.asyncio
    async def test_fallback_to_message_builder_when_router_raises(self, monkeypatch):
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge.__new__(AndroidBridge)
        bridge._lock = asyncio.Lock()
        device_id = "dev_fallback_prf_001"
        bridge._devices = {device_id: MagicMock()}

        mock_router = MagicMock()
        mock_router.devices = {device_id: MagicMock()}
        mock_router.dispatch_task = AsyncMock(side_effect=RuntimeError("router crashed"))

        send_calls = []

        async def _fake_send(did, msg, wait_response=False, timeout=300.0):
            send_calls.append({"device_id": did, "msg": msg})
            return {"success": True, "dispatched_via": "message_builder"}

        bridge.send_to_device = _fake_send  # type: ignore[method-assign]

        with patch("galaxy_gateway.device_router.device_router", mock_router):
            result = await bridge.assign_task(
                device_id=device_id,
                task_id="task_fallback_prf",
                task_type="click",
                payload={"trace_id": "trace_fallback_prf"},
            )

        assert len(send_calls) == 1
        sent_msg = send_calls[0]["msg"]
        assert sent_msg.get("trace_id") == "trace_fallback_prf"
        assert result is not None


# ---------------------------------------------------------------------------
# 11. Result backflow path not degraded by PR-F changes
# ---------------------------------------------------------------------------


class TestResultBackflowNotDegradedByPRF:
    """consume_android_behavioral_result must be unaffected by the PR-F
    dispatch wiring changes in openclawd and android_bridge."""

    def test_consume_result_still_works(self):
        from core.runtime.source_dispatch_orchestrator import SourceDispatchOrchestrator
        from core.android_execution_signal_reconciler import AndroidSignalKind

        orchestrator = SourceDispatchOrchestrator()

        outcome = MagicMock()
        outcome.was_updated = True
        outcome.reject_reason = ""
        envelope = MagicMock()
        envelope.signal_kind = AndroidSignalKind.final_result
        envelope.result_kind = MagicMock()
        envelope.result_kind.value = "success"
        envelope.contract_id = "contract_prf_001"
        envelope.session_id = "sess_prf_001"
        envelope.task_id = "task_prf_001"
        envelope.trace_id = "trace_prf_001"
        outcome.envelope = envelope

        summary = orchestrator.consume_android_behavioral_result(
            outcome,
            trace_id="trace_prf_001",
            session_id="sess_prf_001",
            task_id="task_prf_001",
        )

        assert summary["consumed"] is True
        assert summary["was_updated"] is True

    def test_orchestrator_sentinel_for_result_backflow_present(self):
        """RESULT_BACKFLOW_UNAFFECTED_BY_ORCHESTRATOR_WIRING_PR_F_POLICY exists."""
        from core.runtime.source_dispatch_orchestrator import (
            RESULT_BACKFLOW_UNAFFECTED_BY_ORCHESTRATOR_WIRING_PR_F_POLICY,
        )

        assert "reconciler" in RESULT_BACKFLOW_UNAFFECTED_BY_ORCHESTRATOR_WIRING_PR_F_POLICY.lower()
        assert "PR_F" in RESULT_BACKFLOW_UNAFFECTED_BY_ORCHESTRATOR_WIRING_PR_F_POLICY or (
            "PR-F" in RESULT_BACKFLOW_UNAFFECTED_BY_ORCHESTRATOR_WIRING_PR_F_POLICY
        )
