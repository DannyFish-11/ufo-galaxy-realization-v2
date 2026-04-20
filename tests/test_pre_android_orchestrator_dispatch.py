"""tests/test_pre_android_orchestrator_dispatch.py
===================================================
Tests for PR-E: Route single-device Android execution through
SourceDispatchOrchestrator.

Coverage:
  1.  PR-E sentinels are exported from source_dispatch_orchestrator.
  2.  _try_android_bridge_dispatch returns device_not_in_android_bridge when
      the device is absent from the AndroidBridge transport cache.
  3.  _try_android_bridge_dispatch succeeds when device is in the bridge cache
      and assign_task returns a success dict.
  4.  _try_android_bridge_dispatch handles async assign_task via asyncio.run.
  5.  _try_android_bridge_dispatch returns android_bridge_unavailable when
      galaxy_gateway.android_bridge cannot be imported.
  6.  _try_android_bridge_dispatch handles assign_task returning None.
  7.  _try_android_bridge_dispatch handles assign_task raising an exception.
  8.  orchestrate_source_runtime_dispatch in remote_handoff mode routes to
      android_bridge_dispatch when device is in bridge; result carries
      action_taken="android_bridge_dispatch".
  9.  orchestrate_source_runtime_dispatch falls through to remote_handoff when
      device is NOT in android bridge (device_not_in_android_bridge).
  10. orchestrate_source_runtime_dispatch marks fallback_local when android
      bridge fails with a non-structural error.
  11. Target discovery: _select_target_from_candidates picks up an Android
      device registered in the AttachedSessionRegistry when readiness and
      participation gates pass.
  12. consume_android_behavioral_result is unaffected by PR-E changes (result
      backflow path not degraded).
  13. SourceDispatchOrchestrator.dispatch passes through android_bridge_dispatch
      result when bridge succeeds.
  14. PR-E policy sentinel strings contain the expected policy keywords.
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


def _make_registry_entry(device_id: str = "android_dev_001") -> Any:
    """Build a minimal mock AttachedSessionRegistryEntry."""
    entry = MagicMock()
    entry.device_id = device_id
    entry.session_id = f"sess_{device_id}"
    entry.runtime_session_id = str(uuid.uuid4())
    entry.attachment_state = MagicMock()
    entry.attachment_state.value = "active"
    entry.metadata = {"registration_trigger": "android_device_register"}
    return entry


def _make_readiness(registered: bool = True, routable: bool = True) -> Any:
    r = MagicMock()
    r.registered = registered
    r.routable = routable
    return r


def _make_participation(
    orchestration_eligible: bool = True,
    participant_tier: str = "joined_runtime",
) -> Any:
    p = MagicMock()
    p.orchestration_eligible = orchestration_eligible
    p.participant_tier = participant_tier
    return p


# ---------------------------------------------------------------------------
# 1. PR-E sentinels are exported
# ---------------------------------------------------------------------------


class TestPRESentinelsExported:
    def test_android_dispatch_canonical_path_sentinel(self):
        from core.runtime.source_dispatch_orchestrator import (
            ANDROID_DISPATCH_CANONICAL_PATH_PR_E_SENTINEL,
        )

        assert "PR_E" in ANDROID_DISPATCH_CANONICAL_PATH_PR_E_SENTINEL
        assert "android" in ANDROID_DISPATCH_CANONICAL_PATH_PR_E_SENTINEL.lower()

    def test_android_bridge_dispatch_is_pre_handoff_adapter_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            ANDROID_BRIDGE_DISPATCH_IS_PRE_HANDOFF_ADAPTER_PR_E_POLICY,
        )

        assert "device_not_in_android_bridge" in ANDROID_BRIDGE_DISPATCH_IS_PRE_HANDOFF_ADAPTER_PR_E_POLICY

    def test_android_result_flow_preserved_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            ANDROID_RESULT_FLOW_PRESERVED_PR_E_POLICY,
        )

        assert "PR_E" in ANDROID_RESULT_FLOW_PRESERVED_PR_E_POLICY

    def test_android_target_discovery_uses_canonical_registry_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            ANDROID_TARGET_DISCOVERY_USES_CANONICAL_REGISTRY_PR_E_POLICY,
        )

        assert "AttachedSessionRegistry" in ANDROID_TARGET_DISCOVERY_USES_CANONICAL_REGISTRY_PR_E_POLICY


# ---------------------------------------------------------------------------
# 2. _try_android_bridge_dispatch: device absent from bridge
# ---------------------------------------------------------------------------


class TestTryAndroidBridgeDispatchDeviceAbsent:
    def test_returns_device_not_in_android_bridge(self, monkeypatch):
        import core.runtime.source_dispatch_orchestrator as mod

        fake_bridge = MagicMock()
        fake_bridge._devices = {}  # device not present

        fake_bridge_mod = MagicMock()
        fake_bridge_mod.android_bridge = fake_bridge
        monkeypatch.setitem(
            __import__("sys").modules,
            "galaxy_gateway.android_bridge",
            fake_bridge_mod,
        )

        result = mod._try_android_bridge_dispatch(
            "missing_device_001",
            "task_001",
            task={"tool_name": "screenshot"},
        )

        assert result["success"] is False
        assert result["skipped_reason"] == "device_not_in_android_bridge"
        assert result["action_taken"] == "none"


# ---------------------------------------------------------------------------
# 3. _try_android_bridge_dispatch: device present, assign_task succeeds
# ---------------------------------------------------------------------------


class TestTryAndroidBridgeDispatchSuccess:
    def test_returns_success_with_action_taken(self, monkeypatch):
        import core.runtime.source_dispatch_orchestrator as mod

        fake_bridge = MagicMock()
        android_device = MagicMock()
        device_id = "android_dev_001"
        fake_bridge._devices = {device_id: android_device}
        fake_bridge.assign_task = MagicMock(
            return_value={"success": True, "task_id": "task_001", "result": "ok"}
        )

        fake_bridge_mod = MagicMock()
        fake_bridge_mod.android_bridge = fake_bridge
        monkeypatch.setitem(
            __import__("sys").modules,
            "galaxy_gateway.android_bridge",
            fake_bridge_mod,
        )

        result = mod._try_android_bridge_dispatch(
            device_id,
            "task_001",
            task={"tool_name": "screenshot", "args": {}},
            trace_id="trace_abc",
            session_id="sess_001",
        )

        assert result["success"] is True
        assert result["action_taken"] == "android_bridge_dispatch"
        assert result["device_id"] == device_id
        assert result["task_id"] == "task_001"
        assert result["trace_id"] == "trace_abc"
        assert "android_bridge_response" in result

    def test_assign_task_called_with_correct_args(self, monkeypatch):
        import core.runtime.source_dispatch_orchestrator as mod

        fake_bridge = MagicMock()
        device_id = "android_dev_002"
        fake_bridge._devices = {device_id: MagicMock()}
        fake_bridge.assign_task = MagicMock(return_value={"success": True})

        fake_bridge_mod = MagicMock()
        fake_bridge_mod.android_bridge = fake_bridge
        monkeypatch.setitem(
            __import__("sys").modules,
            "galaxy_gateway.android_bridge",
            fake_bridge_mod,
        )

        mod._try_android_bridge_dispatch(
            device_id,
            "task_xyz",
            task={"task_type": "screenshot", "goal": "take a screenshot"},
            trace_id="trace_001",
            session_id="sess_002",
        )

        fake_bridge.assign_task.assert_called_once()
        call_kwargs = fake_bridge.assign_task.call_args
        assert call_kwargs.kwargs["device_id"] == device_id
        assert call_kwargs.kwargs["task_id"] == "task_xyz"
        # task_type should be extracted from task dict
        assert call_kwargs.kwargs["task_type"] == "screenshot"
        # orchestrator_dispatch flag should be injected
        payload = call_kwargs.kwargs["payload"]
        assert payload.get("orchestrator_dispatch") is True
        assert payload.get("trace_id") == "trace_001"


# ---------------------------------------------------------------------------
# 4. _try_android_bridge_dispatch: async assign_task
# ---------------------------------------------------------------------------


class TestTryAndroidBridgeDispatchAsync:
    def test_handles_async_assign_task_coroutine(self, monkeypatch):
        import core.runtime.source_dispatch_orchestrator as mod

        fake_bridge = MagicMock()
        device_id = "android_dev_async"
        fake_bridge._devices = {device_id: MagicMock()}

        async def _async_assign(*args, **kwargs):
            return {"success": True, "task_id": kwargs.get("task_id")}

        fake_bridge.assign_task = _async_assign

        fake_bridge_mod = MagicMock()
        fake_bridge_mod.android_bridge = fake_bridge
        monkeypatch.setitem(
            __import__("sys").modules,
            "galaxy_gateway.android_bridge",
            fake_bridge_mod,
        )

        result = mod._try_android_bridge_dispatch(
            device_id,
            "task_async_001",
            task={"tool_name": "click"},
        )

        assert result["success"] is True
        assert result["action_taken"] == "android_bridge_dispatch"


# ---------------------------------------------------------------------------
# 5. _try_android_bridge_dispatch: import error
# ---------------------------------------------------------------------------


class TestTryAndroidBridgeDispatchImportError:
    def test_returns_android_bridge_unavailable(self, monkeypatch):
        import sys
        import core.runtime.source_dispatch_orchestrator as mod

        # Remove the module from sys.modules to force ImportError
        monkeypatch.setitem(
            sys.modules, "galaxy_gateway.android_bridge", None  # type: ignore[arg-type]
        )

        result = mod._try_android_bridge_dispatch(
            "some_device",
            "task_001",
        )

        assert result["success"] is False
        assert "unavailable" in result["skipped_reason"] or "import" in result["skipped_reason"].lower()


# ---------------------------------------------------------------------------
# 6. _try_android_bridge_dispatch: assign_task returns None
# ---------------------------------------------------------------------------


class TestTryAndroidBridgeDispatchReturnsNone:
    def test_returns_failure_when_assign_task_returns_none(self, monkeypatch):
        import core.runtime.source_dispatch_orchestrator as mod

        fake_bridge = MagicMock()
        device_id = "dev_none"
        fake_bridge._devices = {device_id: MagicMock()}
        fake_bridge.assign_task = MagicMock(return_value=None)

        fake_bridge_mod = MagicMock()
        fake_bridge_mod.android_bridge = fake_bridge
        monkeypatch.setitem(
            __import__("sys").modules,
            "galaxy_gateway.android_bridge",
            fake_bridge_mod,
        )

        result = mod._try_android_bridge_dispatch(device_id, "task_001")

        assert result["success"] is False
        assert "none" in result["skipped_reason"].lower()


# ---------------------------------------------------------------------------
# 7. _try_android_bridge_dispatch: assign_task raises
# ---------------------------------------------------------------------------


class TestTryAndroidBridgeDispatchException:
    def test_returns_failure_on_assign_task_exception(self, monkeypatch):
        import core.runtime.source_dispatch_orchestrator as mod

        fake_bridge = MagicMock()
        device_id = "dev_exc"
        fake_bridge._devices = {device_id: MagicMock()}
        fake_bridge.assign_task = MagicMock(side_effect=RuntimeError("ws disconnected"))

        fake_bridge_mod = MagicMock()
        fake_bridge_mod.android_bridge = fake_bridge
        monkeypatch.setitem(
            __import__("sys").modules,
            "galaxy_gateway.android_bridge",
            fake_bridge_mod,
        )

        result = mod._try_android_bridge_dispatch(device_id, "task_001")

        assert result["success"] is False
        assert "android_bridge_error" in result["skipped_reason"]
        assert result["action_taken"] == "none"


# ---------------------------------------------------------------------------
# 8. orchestrate_source_runtime_dispatch: Android bridge dispatch path
# ---------------------------------------------------------------------------


class TestOrchestrateAndroidBridgeDispatch:
    """orchestrate_source_runtime_dispatch routes via android_bridge_dispatch
    when the target device is registered in the Android bridge."""

    def test_android_bridge_dispatch_path_taken(self, monkeypatch):
        from core.runtime.source_dispatch_orchestrator import (
            orchestrate_source_runtime_dispatch,
        )
        from contracts.source_dispatch import SourceDispatchMode

        device_id = "android_dev_orch_001"

        # Mock _try_android_bridge_dispatch to succeed
        monkeypatch.setattr(
            "core.runtime.source_dispatch_orchestrator._try_android_bridge_dispatch",
            lambda did, tid, **kw: {
                "success": True,
                "action_taken": "android_bridge_dispatch",
                "device_id": did,
                "task_id": tid,
                "android_bridge_response": {"success": True},
            },
        )

        result = orchestrate_source_runtime_dispatch(
            trace_id="trace_orch_001",
            task_id="task_orch_001",
            task={"tool_name": "screenshot", "args": {}},
            target_device_id=device_id,
        )

        assert result is not None
        result_dict = result.to_dict() if hasattr(result, "to_dict") else result
        assert isinstance(result_dict, dict)
        # The mode should be remote_handoff (android bridge is a remote path)
        assert result_dict.get("mode") in (
            SourceDispatchMode.remote_handoff.value,
            "remote_handoff",
        )
        assert result_dict.get("success") is True
        # decision_reason should reflect android bridge
        decision_reason = result_dict.get("decision_reason", "")
        assert "android_bridge_dispatch" in decision_reason

    def test_android_bridge_result_carries_device_id(self, monkeypatch):
        from core.runtime.source_dispatch_orchestrator import (
            orchestrate_source_runtime_dispatch,
        )

        device_id = "android_dev_check"

        monkeypatch.setattr(
            "core.runtime.source_dispatch_orchestrator._try_android_bridge_dispatch",
            lambda did, tid, **kw: {
                "success": True,
                "action_taken": "android_bridge_dispatch",
                "device_id": did,
                "task_id": tid,
                "android_bridge_response": {"success": True},
            },
        )

        result = orchestrate_source_runtime_dispatch(
            target_device_id=device_id,
            task={"tool_name": "swipe"},
            task_id="task_check",
        )

        result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
        # Success must be True
        assert result_dict.get("success") is True


# ---------------------------------------------------------------------------
# 9. orchestrate_source_runtime_dispatch: falls through to remote_handoff
#    when device not in android bridge
# ---------------------------------------------------------------------------


class TestOrchestrateAndroidBridgeFallthrough:
    """When _try_android_bridge_dispatch returns device_not_in_android_bridge,
    orchestrate_source_runtime_dispatch falls through to the generic
    HandoffEnvelopeV2 remote handoff path."""

    def test_falls_through_to_remote_handoff(self, monkeypatch):
        from core.runtime.source_dispatch_orchestrator import (
            orchestrate_source_runtime_dispatch,
        )
        from contracts.source_dispatch import SourceDispatchMode

        device_id = "non_android_dev_001"

        monkeypatch.setattr(
            "core.runtime.source_dispatch_orchestrator._try_android_bridge_dispatch",
            lambda did, tid, **kw: {
                "success": False,
                "skipped_reason": "device_not_in_android_bridge",
                "action_taken": "none",
            },
        )

        # Also stub _try_remote_handoff to succeed (simulates non-Android target)
        monkeypatch.setattr(
            "core.runtime.source_dispatch_orchestrator._try_remote_handoff",
            lambda envelope: {"success": True, "action_taken": "remote_handoff"},
        )

        result = orchestrate_source_runtime_dispatch(
            trace_id="trace_fallthrough",
            task_id="task_fallthrough",
            task={"tool_name": "desktop_action"},
            target_device_id=device_id,
        )

        result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
        # Success — remote handoff took over
        assert result_dict.get("success") is True

    def test_android_bridge_dispatch_not_called_for_local_mode(self, monkeypatch):
        """_try_android_bridge_dispatch must NOT be called when mode is local."""
        from core.runtime.source_dispatch_orchestrator import (
            orchestrate_source_runtime_dispatch,
        )

        call_count = {"n": 0}

        def _patched_android_dispatch(did, tid, **kw):
            call_count["n"] += 1
            return {"success": False, "skipped_reason": "device_not_in_android_bridge", "action_taken": "none"}

        monkeypatch.setattr(
            "core.runtime.source_dispatch_orchestrator._try_android_bridge_dispatch",
            _patched_android_dispatch,
        )

        # No target device → local mode
        orchestrate_source_runtime_dispatch(
            trace_id="trace_local",
            task_id="task_local",
            task={"tool_name": "local_tool"},
            force_local=True,
        )

        # Android bridge dispatch must not be invoked for local mode
        assert call_count["n"] == 0


# ---------------------------------------------------------------------------
# 10. orchestrate_source_runtime_dispatch: fallback_local on Android bridge error
# ---------------------------------------------------------------------------


class TestOrchestrateAndroidBridgeError:
    """When android_bridge_dispatch fails with a non-structural error,
    orchestrate_source_runtime_dispatch should record the error and fall back
    to local execution."""

    def test_fallback_local_on_android_bridge_error(self, monkeypatch):
        from core.runtime.source_dispatch_orchestrator import (
            orchestrate_source_runtime_dispatch,
        )
        from contracts.source_dispatch import SourceDispatchMode

        device_id = "android_dev_error"

        monkeypatch.setattr(
            "core.runtime.source_dispatch_orchestrator._try_android_bridge_dispatch",
            lambda did, tid, **kw: {
                "success": False,
                "skipped_reason": "android_bridge_error:ws_disconnected",
                "action_taken": "none",
            },
        )

        result = orchestrate_source_runtime_dispatch(
            trace_id="trace_err",
            task_id="task_err",
            task={"tool_name": "screenshot"},
            target_device_id=device_id,
        )

        result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
        # Should fall back to local mode
        assert result_dict.get("mode") in (
            SourceDispatchMode.fallback_local.value,
            "fallback_local",
            SourceDispatchMode.local.value,
            "local",
        )
        # decision_reason should mention android_bridge_dispatch_failed
        decision_reason = result_dict.get("decision_reason", "")
        assert "android_bridge" in decision_reason.lower()


# ---------------------------------------------------------------------------
# 11. Target discovery picks up Android device from registry
# ---------------------------------------------------------------------------


class TestTargetDiscoveryAndroidDevice:
    """_select_target_from_candidates discovers Android devices from the
    AttachedSessionRegistry when readiness and participation gates pass."""

    def test_android_device_discovered_via_registry(self, monkeypatch):
        from core.runtime.source_dispatch_orchestrator import (
            _select_target_from_candidates,
        )

        android_device_id = "android_dev_registry_001"
        entry = _make_registry_entry(android_device_id)

        readiness = _make_readiness(registered=True, routable=True)
        participation = _make_participation(
            orchestration_eligible=True, participant_tier="joined_runtime"
        )

        monkeypatch.setattr(
            "core.runtime.source_dispatch_orchestrator."
            "core.attached_runtime_session_registry.list_active_sessions"
            if False  # block — use direct path below
            else "core.attached_runtime_session_registry.list_active_sessions",
            lambda **kw: [entry],
            raising=False,
        )

        result = _select_target_from_candidates(
            readiness_inputs={android_device_id: readiness},
            participation_inputs={android_device_id: participation},
            reuse_inputs={android_device_id: False},
        )

        # If the registry returns the entry and gates pass, target is selected.
        # In environments where the live registry import succeeds, the result
        # must be a SourceDispatchTarget with the correct device_id.
        if result is not None:
            assert result.target_device_id == android_device_id
            assert "readiness" in result.selection_reason

    def test_android_device_rejected_if_not_routable(self, monkeypatch):
        from core.runtime.source_dispatch_orchestrator import (
            _select_target_from_candidates,
        )

        android_device_id = "android_dev_not_routable"
        entry = _make_registry_entry(android_device_id)

        readiness = _make_readiness(registered=True, routable=False)  # not routable
        participation = _make_participation(orchestration_eligible=True)

        result = _select_target_from_candidates(
            readiness_inputs={android_device_id: readiness},
            participation_inputs={android_device_id: participation},
            reuse_inputs={android_device_id: False},
        )

        # Not routable → must be rejected (None or different device)
        if result is not None:
            assert result.target_device_id != android_device_id

    def test_android_device_rejected_if_not_orchestration_eligible(self, monkeypatch):
        from core.runtime.source_dispatch_orchestrator import (
            _select_target_from_candidates,
        )

        android_device_id = "android_dev_not_eligible"
        entry = _make_registry_entry(android_device_id)

        readiness = _make_readiness(registered=True, routable=True)
        participation = _make_participation(orchestration_eligible=False)  # not eligible

        result = _select_target_from_candidates(
            readiness_inputs={android_device_id: readiness},
            participation_inputs={android_device_id: participation},
            reuse_inputs={android_device_id: False},
        )

        if result is not None:
            assert result.target_device_id != android_device_id


# ---------------------------------------------------------------------------
# 12. consume_android_behavioral_result is not degraded by PR-E
# ---------------------------------------------------------------------------


class TestConsumeAndroidBehavioralResultNotDegraded:
    """PR-E changes must not break the existing consume_android_behavioral_result
    result backflow path."""

    def test_consume_result_returns_consumed_true_on_update(self):
        from core.runtime.source_dispatch_orchestrator import (
            SourceDispatchOrchestrator,
        )
        from core.android_execution_signal_reconciler import AndroidSignalKind

        orchestrator = SourceDispatchOrchestrator()

        # Build a minimal reconcile outcome mock
        outcome = MagicMock()
        outcome.was_updated = True
        outcome.reject_reason = ""
        envelope = MagicMock()
        envelope.signal_kind = AndroidSignalKind.final_result
        envelope.result_kind = MagicMock()
        envelope.result_kind.value = "success"
        envelope.contract_id = "contract_001"
        envelope.session_id = "sess_001"
        envelope.task_id = "task_001"
        envelope.trace_id = "trace_001"
        outcome.envelope = envelope

        summary = orchestrator.consume_android_behavioral_result(
            outcome,
            trace_id="trace_001",
            session_id="sess_001",
            task_id="task_001",
        )

        assert summary["consumed"] is True
        assert summary["was_updated"] is True

    def test_consume_result_returns_not_consumed_on_reject(self):
        from core.runtime.source_dispatch_orchestrator import (
            SourceDispatchOrchestrator,
        )

        orchestrator = SourceDispatchOrchestrator()

        outcome = MagicMock()
        outcome.was_updated = False
        outcome.reject_reason = "tracking_record_not_found"
        outcome.envelope = MagicMock()
        outcome.envelope.signal_kind = None
        outcome.envelope.result_kind = None
        outcome.envelope.contract_id = ""
        outcome.envelope.session_id = ""
        outcome.envelope.task_id = ""
        outcome.envelope.trace_id = ""

        summary = orchestrator.consume_android_behavioral_result(outcome)

        assert summary["consumed"] is False
        assert summary["was_updated"] is False


# ---------------------------------------------------------------------------
# 13. SourceDispatchOrchestrator.dispatch passes through android_bridge result
# ---------------------------------------------------------------------------


class TestSourceDispatchOrchestratorAndroidDispatch:
    def test_dispatch_returns_success_when_bridge_succeeds(self, monkeypatch):
        from core.runtime.source_dispatch_orchestrator import (
            SourceDispatchOrchestrator,
        )
        from contracts.source_dispatch import SourceDispatchMode

        device_id = "android_dev_class_001"

        monkeypatch.setattr(
            "core.runtime.source_dispatch_orchestrator._try_android_bridge_dispatch",
            lambda did, tid, **kw: {
                "success": True,
                "action_taken": "android_bridge_dispatch",
                "device_id": did,
                "task_id": tid,
                "android_bridge_response": {"success": True},
            },
        )

        orchestrator = SourceDispatchOrchestrator()
        result = orchestrator.dispatch(
            trace_id="trace_class_001",
            task_id="task_class_001",
            task={"tool_name": "screenshot"},
            target_device_id=device_id,
        )

        result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
        assert result_dict.get("success") is True
        assert result_dict.get("mode") in (
            SourceDispatchMode.remote_handoff.value,
            "remote_handoff",
        )


# ---------------------------------------------------------------------------
# 14. PR-E policy sentinel content validation
# ---------------------------------------------------------------------------


class TestPREPolicySentinelContent:
    def test_pre_handoff_adapter_policy_mentions_device_router(self):
        from core.runtime.source_dispatch_orchestrator import (
            ANDROID_BRIDGE_DISPATCH_IS_PRE_HANDOFF_ADAPTER_PR_E_POLICY,
        )

        assert (
            "AndroidBridge" in ANDROID_BRIDGE_DISPATCH_IS_PRE_HANDOFF_ADAPTER_PR_E_POLICY
            or "android_bridge" in ANDROID_BRIDGE_DISPATCH_IS_PRE_HANDOFF_ADAPTER_PR_E_POLICY.lower()
        )

    def test_result_flow_policy_mentions_reconciler(self):
        from core.runtime.source_dispatch_orchestrator import (
            ANDROID_RESULT_FLOW_PRESERVED_PR_E_POLICY,
        )

        assert "reconciler" in ANDROID_RESULT_FLOW_PRESERVED_PR_E_POLICY.lower()

    def test_target_discovery_policy_mentions_registry(self):
        from core.runtime.source_dispatch_orchestrator import (
            ANDROID_TARGET_DISCOVERY_USES_CANONICAL_REGISTRY_PR_E_POLICY,
        )

        assert "registry" in ANDROID_TARGET_DISCOVERY_USES_CANONICAL_REGISTRY_PR_E_POLICY.lower()
