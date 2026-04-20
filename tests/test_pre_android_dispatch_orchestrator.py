"""tests/test_pre_android_dispatch_orchestrator.py
====================================================
Tests for PR-E: Route single-device Android execution through
SourceDispatchOrchestrator.

Coverage:
  1.  PR-E sentinel constants are present in source_dispatch_orchestrator.
  2.  PR-E sentinel constant is present in android_bridge.
  3.  _is_android_dispatch_target returns True when device is in AndroidBridge.
  4.  _is_android_dispatch_target returns False when device is not in AndroidBridge.
  5.  _is_android_dispatch_target returns False for empty/None device_id.
  6.  _is_android_dispatch_target degrades gracefully when AndroidBridge unavailable.
  7.  _try_android_dispatch dispatches via AndroidBridge and returns success dict.
  8.  _try_android_dispatch returns success=False when bridge unavailable.
  9.  _try_android_dispatch returns success=False when assign_task returns None.
  10. _try_android_dispatch passes trace_id and session_id to payload.
  11. orchestrate_source_runtime_dispatch routes to Android bridge for Android target.
  12. orchestrate_source_runtime_dispatch falls back to remote_handoff when android
      dispatch fails.
  13. orchestrate_source_runtime_dispatch falls back to local when target is not Android.
  14. SourceDispatchOrchestrator.dispatch works end-to-end with Android target.
  15. Existing result contract is preserved for Android dispatch path.
  16. Android dispatch decision_reason identifies android path.
  17. Lifecycle/reconciler compatibility: reconcile_inbound_message not affected.
  18. _try_android_dispatch handles non-dict bridge response.
  19. _try_android_dispatch uses task_type from task dict when present.
  20. _is_android_dispatch_target returns False when bridge has no _devices attribute.
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


def _make_android_bridge(device_ids=("dev_android_01",)):
    """Return a mock AndroidBridge with _devices populated."""
    bridge = MagicMock()
    bridge._devices = {did: MagicMock() for did in device_ids}
    bridge.assign_task = AsyncMock(
        return_value={"success": True, "action_taken": "android_dispatch"}
    )
    return bridge


def _make_readiness(registered=True, routable=True):
    r = MagicMock()
    r.registered = registered
    r.routable = routable
    return r


def _make_participation(orchestration_eligible=True, participant_tier="active_participant"):
    p = MagicMock()
    p.orchestration_eligible = orchestration_eligible
    p.participant_tier = participant_tier
    return p


# ---------------------------------------------------------------------------
# 1–2. Sentinel constants
# ---------------------------------------------------------------------------


class TestSentinelConstants:
    def test_pre_sentinel_in_orchestrator(self):
        """PR-E sentinel is exported from source_dispatch_orchestrator."""
        from core.runtime.source_dispatch_orchestrator import (
            ANDROID_SINGLE_DEVICE_DISPATCH_CANONICAL_PATH_PRE_SENTINEL,
        )

        assert "ANDROID_SINGLE_DEVICE_DISPATCH_CANONICAL_PATH_PRE" in (
            ANDROID_SINGLE_DEVICE_DISPATCH_CANONICAL_PATH_PRE_SENTINEL
        )

    def test_pre_policy_dispatch_routes_through_bridge(self):
        from core.runtime.source_dispatch_orchestrator import (
            ANDROID_DISPATCH_ROUTES_THROUGH_ANDROID_BRIDGE_PRE_POLICY,
        )

        assert "POLICY" in ANDROID_DISPATCH_ROUTES_THROUGH_ANDROID_BRIDGE_PRE_POLICY
        assert "AndroidBridge" in ANDROID_DISPATCH_ROUTES_THROUGH_ANDROID_BRIDGE_PRE_POLICY

    def test_pre_policy_target_selection_uses_registry(self):
        from core.runtime.source_dispatch_orchestrator import (
            ANDROID_TARGET_SELECTION_USES_CANONICAL_REGISTRY_PRE_POLICY,
        )

        assert "AttachedSessionRegistry" in (
            ANDROID_TARGET_SELECTION_USES_CANONICAL_REGISTRY_PRE_POLICY
        )

    def test_pre_policy_result_flows_to_reconciler(self):
        from core.runtime.source_dispatch_orchestrator import (
            ANDROID_DISPATCH_RESULT_FLOWS_TO_CANONICAL_RECONCILER_PRE_POLICY,
        )

        assert "reconcile_inbound_message" in (
            ANDROID_DISPATCH_RESULT_FLOWS_TO_CANONICAL_RECONCILER_PRE_POLICY
        )

    def test_pre_sentinel_in_android_bridge(self):
        """PR-E sentinel is exported from android_bridge."""
        from galaxy_gateway.android_bridge import (
            ANDROID_BRIDGE_IS_ORCHESTRATOR_DISPATCH_TARGET_PRE,
        )

        assert "ANDROID_BRIDGE_IS_ORCHESTRATOR_DISPATCH_TARGET_PRE" in (
            ANDROID_BRIDGE_IS_ORCHESTRATOR_DISPATCH_TARGET_PRE
        )


# ---------------------------------------------------------------------------
# 3–6. _is_android_dispatch_target
# ---------------------------------------------------------------------------


class TestIsAndroidDispatchTarget:
    def test_returns_true_when_device_in_bridge(self):
        """_is_android_dispatch_target returns True for device in AndroidBridge."""
        from core.runtime.source_dispatch_orchestrator import _is_android_dispatch_target

        bridge = _make_android_bridge(("dev_a",))
        with patch(
            "galaxy_gateway.android_bridge.android_bridge",
            bridge,
        ):
            result = _is_android_dispatch_target("dev_a")
        assert result is True

    def test_returns_false_when_device_not_in_bridge(self):
        """_is_android_dispatch_target returns False for unknown device."""
        from core.runtime.source_dispatch_orchestrator import _is_android_dispatch_target

        bridge = _make_android_bridge(("dev_known",))
        with patch(
            "galaxy_gateway.android_bridge.android_bridge",
            bridge,
        ):
            result = _is_android_dispatch_target("dev_unknown")
        assert result is False

    def test_returns_false_for_empty_string(self):
        """_is_android_dispatch_target returns False for empty device_id."""
        from core.runtime.source_dispatch_orchestrator import _is_android_dispatch_target

        assert _is_android_dispatch_target("") is False

    def test_degrades_gracefully_on_import_error(self):
        """_is_android_dispatch_target returns False when AndroidBridge import fails."""
        from core.runtime.source_dispatch_orchestrator import _is_android_dispatch_target

        with patch.dict("sys.modules", {"galaxy_gateway.android_bridge": None}):
            # Graceful degradation contract: must return False (not raise)
            try:
                result = _is_android_dispatch_target("dev_x")
                assert result is False
            except Exception as exc:
                pytest.fail(
                    f"_is_android_dispatch_target raised instead of returning False: {exc}"
                )

    def test_returns_false_when_bridge_has_no_devices(self):
        """_is_android_dispatch_target returns False when bridge has no _devices attr."""
        from core.runtime.source_dispatch_orchestrator import _is_android_dispatch_target

        bridge = MagicMock(spec=[])  # spec=[] means no attributes
        with patch(
            "galaxy_gateway.android_bridge.android_bridge",
            bridge,
        ):
            result = _is_android_dispatch_target("dev_x")
        assert result is False


# ---------------------------------------------------------------------------
# 7–10. _try_android_dispatch
# ---------------------------------------------------------------------------


class TestTryAndroidDispatch:
    def test_dispatches_via_bridge_returns_success(self):
        """_try_android_dispatch calls assign_task and returns success."""
        from core.runtime.source_dispatch_orchestrator import _try_android_dispatch

        bridge = _make_android_bridge(("dev_android_01",))
        # assign_task returns a success dict (synchronous mock)
        bridge.assign_task = MagicMock(
            return_value={"success": True, "action_taken": "android_dispatch"}
        )

        with patch("galaxy_gateway.android_bridge.android_bridge", bridge):
            result = _try_android_dispatch(
                "dev_android_01",
                {"tool_name": "screenshot", "args": {}},
                trace_id="trace_001",
                task_id="task_001",
                session_id="sess_001",
            )

        assert result.get("success") is True
        assert result.get("action_taken") == "android_dispatch"
        assert result.get("target_device_id") == "dev_android_01"

    def test_returns_failure_when_bridge_unavailable(self):
        """_try_android_dispatch returns success=False when AndroidBridge is unavailable."""
        from core.runtime.source_dispatch_orchestrator import _try_android_dispatch

        with patch("galaxy_gateway.android_bridge.android_bridge", None):
            result = _try_android_dispatch(
                "dev_x",
                {"tool_name": "click"},
            )

        assert result.get("success") is False
        assert "skipped_reason" in result

    def test_returns_failure_when_assign_task_returns_none(self):
        """_try_android_dispatch returns success=False when assign_task returns None."""
        from core.runtime.source_dispatch_orchestrator import _try_android_dispatch

        bridge = _make_android_bridge(("dev_y",))
        bridge.assign_task = MagicMock(return_value=None)

        with patch("galaxy_gateway.android_bridge.android_bridge", bridge):
            result = _try_android_dispatch("dev_y", {"tool_name": "tap"})

        assert result.get("success") is False
        assert "none" in result.get("skipped_reason", "").lower()

    def test_includes_trace_id_in_payload(self):
        """_try_android_dispatch passes trace_id into payload."""
        from core.runtime.source_dispatch_orchestrator import _try_android_dispatch

        captured_payload: Dict[str, Any] = {}

        def fake_assign(device_id, task_id, task_type, payload, *args, **kwargs):
            captured_payload.update(payload)
            return {"success": True, "action_taken": "android_dispatch"}

        bridge = _make_android_bridge(("dev_z",))
        bridge.assign_task = MagicMock(side_effect=fake_assign)

        with patch("galaxy_gateway.android_bridge.android_bridge", bridge):
            _try_android_dispatch(
                "dev_z",
                {"tool_name": "input", "args": {}},
                trace_id="trace_abc",
                task_id="task_abc",
                session_id="sess_abc",
            )

        assert captured_payload.get("trace_id") == "trace_abc"
        assert captured_payload.get("session_id") == "sess_abc"

    def test_uses_task_type_from_task_dict(self):
        """_try_android_dispatch uses task_type from task dict when present."""
        from core.runtime.source_dispatch_orchestrator import _try_android_dispatch

        captured: Dict[str, str] = {}

        def fake_assign(device_id, task_id, task_type, payload, *args, **kwargs):
            captured["task_type"] = task_type
            return {"success": True}

        bridge = _make_android_bridge(("dev_t",))
        bridge.assign_task = MagicMock(side_effect=fake_assign)

        with patch("galaxy_gateway.android_bridge.android_bridge", bridge):
            _try_android_dispatch(
                "dev_t",
                {"task_type": "goal_execution", "goal": "take screenshot"},
            )

        assert captured.get("task_type") == "goal_execution"

    def test_handles_non_dict_bridge_response(self):
        """_try_android_dispatch wraps a non-dict bridge response in a success dict."""
        from core.runtime.source_dispatch_orchestrator import _try_android_dispatch

        bridge = _make_android_bridge(("dev_nd",))
        bridge.assign_task = MagicMock(return_value="ok_string_response")

        with patch("galaxy_gateway.android_bridge.android_bridge", bridge):
            result = _try_android_dispatch("dev_nd", {"tool_name": "ping"})

        assert result.get("success") is True
        assert "bridge_response" in result


# ---------------------------------------------------------------------------
# 11–16. orchestrate_source_runtime_dispatch with Android target
# ---------------------------------------------------------------------------


def _make_registry_entry(device_id: str):
    """Build a minimal mock AttachedSessionRegistryEntry."""
    entry = MagicMock()
    entry.device_id = device_id
    entry.session_id = f"sess_{device_id}"
    entry.runtime_session_id = str(uuid.uuid4())
    entry.is_active = MagicMock(return_value=True)
    return entry


class TestOrchestrateWithAndroidTarget:
    def _setup_android_target(self, device_id: str):
        """Return patch objects that simulate an Android dispatch target."""
        bridge = _make_android_bridge((device_id,))
        bridge.assign_task = MagicMock(
            return_value={"success": True, "action_taken": "android_dispatch"}
        )
        return bridge

    def test_routes_to_android_bridge_for_android_target(self):
        """orchestrate_source_runtime_dispatch routes to android bridge for Android target."""
        from contracts.source_dispatch import SourceDispatchMode
        from core.runtime.source_dispatch_orchestrator import (
            orchestrate_source_runtime_dispatch,
        )

        device_id = "dev_android_dispatch_01"
        bridge = self._setup_android_target(device_id)

        with patch(
            "core.runtime.source_dispatch_orchestrator._is_android_dispatch_target",
            return_value=True,
        ), patch(
            "core.runtime.source_dispatch_orchestrator._try_android_dispatch",
            return_value={"success": True, "action_taken": "android_dispatch"},
        ) as mock_android_dispatch:
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace_android",
                task_id="task_android_01",
                task={"tool_name": "screenshot"},
                target_device_id=device_id,
            )

        assert result is not None
        assert result.mode in (
            SourceDispatchMode.remote_handoff,
            SourceDispatchMode.fallback_local,
            SourceDispatchMode.local,
        )
        mock_android_dispatch.assert_called()

    def test_android_dispatch_success_sets_success_true(self):
        """When android_dispatch succeeds, orchestrator result has success=True."""
        from contracts.source_dispatch import SourceDispatchMode
        from core.runtime.source_dispatch_orchestrator import (
            orchestrate_source_runtime_dispatch,
        )

        device_id = "dev_android_dispatch_02"

        with patch(
            "core.runtime.source_dispatch_orchestrator._is_android_dispatch_target",
            return_value=True,
        ), patch(
            "core.runtime.source_dispatch_orchestrator._try_android_dispatch",
            return_value={"success": True, "action_taken": "android_dispatch"},
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace_android_02",
                task_id="task_android_02",
                task={"tool_name": "screenshot"},
                target_device_id=device_id,
            )

        assert result.success is True
        assert result.mode == SourceDispatchMode.remote_handoff

    def test_decision_reason_identifies_android_path(self):
        """When android_dispatch succeeds, decision_reason contains 'android_dispatch'."""
        from core.runtime.source_dispatch_orchestrator import (
            orchestrate_source_runtime_dispatch,
        )

        device_id = "dev_android_reason"

        with patch(
            "core.runtime.source_dispatch_orchestrator._is_android_dispatch_target",
            return_value=True,
        ), patch(
            "core.runtime.source_dispatch_orchestrator._try_android_dispatch",
            return_value={"success": True, "action_taken": "android_dispatch"},
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace_reason",
                task_id="task_reason",
                task={"tool_name": "click"},
                target_device_id=device_id,
            )

        assert "android" in (result.decision_reason or "").lower()

    def test_falls_back_to_remote_handoff_when_android_dispatch_fails(self):
        """When android_dispatch fails, orchestrator falls back to remote_handoff."""
        from contracts.source_dispatch import SourceDispatchMode
        from core.runtime.source_dispatch_orchestrator import (
            orchestrate_source_runtime_dispatch,
        )

        device_id = "dev_android_fallback"

        with patch(
            "core.runtime.source_dispatch_orchestrator._is_android_dispatch_target",
            return_value=True,
        ), patch(
            "core.runtime.source_dispatch_orchestrator._try_android_dispatch",
            return_value={
                "success": False,
                "skipped_reason": "android_bridge_unavailable",
            },
        ), patch(
            "core.runtime.source_dispatch_orchestrator._try_remote_handoff",
            return_value={"success": False, "skipped_reason": "no_bridge"},
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace_fallback",
                task_id="task_fallback",
                task={"tool_name": "screenshot"},
                target_device_id=device_id,
            )

        # After android dispatch + remote_handoff both fail, falls back to local
        assert result.mode in (
            SourceDispatchMode.fallback_local,
            SourceDispatchMode.local,
        )

    def test_non_android_target_uses_remote_handoff_not_android(self):
        """Non-Android target does not call _try_android_dispatch."""
        from core.runtime.source_dispatch_orchestrator import (
            orchestrate_source_runtime_dispatch,
        )

        with patch(
            "core.runtime.source_dispatch_orchestrator._is_android_dispatch_target",
            return_value=False,
        ), patch(
            "core.runtime.source_dispatch_orchestrator._try_android_dispatch",
        ) as mock_android, patch(
            "core.runtime.source_dispatch_orchestrator._try_remote_handoff",
            return_value={"success": False, "skipped_reason": "no_bridge"},
        ):
            orchestrate_source_runtime_dispatch(
                trace_id="trace_non_android",
                task_id="task_non_android",
                task={"tool_name": "screenshot"},
                target_device_id="dev_desktop_01",
            )

        mock_android.assert_not_called()


# ---------------------------------------------------------------------------
# 14. SourceDispatchOrchestrator.dispatch works end-to-end
# ---------------------------------------------------------------------------


class TestSourceDispatchOrchestratorWithAndroid:
    def test_dispatch_returns_result_for_android_target(self):
        """SourceDispatchOrchestrator.dispatch returns a SourceDispatchResult for Android."""
        from core.runtime.source_dispatch_orchestrator import SourceDispatchOrchestrator

        orchestrator = SourceDispatchOrchestrator()

        with patch(
            "core.runtime.source_dispatch_orchestrator._is_android_dispatch_target",
            return_value=True,
        ), patch(
            "core.runtime.source_dispatch_orchestrator._try_android_dispatch",
            return_value={"success": True, "action_taken": "android_dispatch"},
        ):
            result = orchestrator.dispatch(
                trace_id="trace_handler",
                task_id="task_handler",
                task={"tool_name": "screenshot"},
                target_device_id="dev_android_handler",
            )

        assert result is not None
        assert result.result_id is not None
        assert isinstance(result.to_dict(), dict)


# ---------------------------------------------------------------------------
# 15. Result contract is preserved for Android dispatch path
# ---------------------------------------------------------------------------


class TestResultContractAndroidPath:
    def test_result_has_all_required_fields(self):
        """Android dispatch result carries all required SourceDispatchResult fields."""
        from core.runtime.source_dispatch_orchestrator import (
            orchestrate_source_runtime_dispatch,
        )

        with patch(
            "core.runtime.source_dispatch_orchestrator._is_android_dispatch_target",
            return_value=True,
        ), patch(
            "core.runtime.source_dispatch_orchestrator._try_android_dispatch",
            return_value={"success": True, "action_taken": "android_dispatch"},
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace_contract",
                task_id="task_contract",
                task={"tool_name": "screenshot"},
                target_device_id="dev_android_contract",
            )

        d = result.to_dict()
        for field in ("result_id", "dispatch_id", "mode", "success", "errors"):
            assert field in d, f"Missing required field: {field}"

    def test_result_to_dict_is_json_serialisable(self):
        """Android dispatch result.to_dict() is JSON-serialisable."""
        import json

        from core.runtime.source_dispatch_orchestrator import (
            orchestrate_source_runtime_dispatch,
        )

        with patch(
            "core.runtime.source_dispatch_orchestrator._is_android_dispatch_target",
            return_value=True,
        ), patch(
            "core.runtime.source_dispatch_orchestrator._try_android_dispatch",
            return_value={"success": True, "action_taken": "android_dispatch"},
        ):
            result = orchestrate_source_runtime_dispatch(
                trace_id="trace_json",
                task_id="task_json",
                task={"tool_name": "screenshot"},
                target_device_id="dev_android_json",
            )

        try:
            json.dumps(result.to_dict())
        except (TypeError, ValueError) as exc:
            pytest.fail(f"result.to_dict() is not JSON-serialisable: {exc}")


# ---------------------------------------------------------------------------
# 17. Lifecycle/reconciler compatibility
# ---------------------------------------------------------------------------


class TestLifecycleReconcilerCompatibility:
    def test_reconcile_inbound_message_still_importable(self):
        """reconcile_inbound_message is still importable and callable after PR-E."""
        from core.android_execution_signal_reconciler import reconcile_inbound_message

        assert callable(reconcile_inbound_message)

    def test_reconcile_inbound_message_handles_task_result_message(self):
        """reconcile_inbound_message processes task_result messages after PR-E."""
        from core.android_execution_signal_reconciler import reconcile_inbound_message

        msg = {
            "type": "task_result",
            "device_id": "dev_reconcile",
            "task_id": "task_reconcile",
            "status": "completed",
            "payload": {"session_id": "sess_r", "trace_id": "trace_r"},
        }
        # Should not raise; returns an AndroidSignalReconcileOutcome
        outcome = reconcile_inbound_message(msg)
        # Outcome may report was_updated=False (no matching tracker) but must not raise
        assert outcome is not None

    def test_task_lifecycle_handler_still_importable(self):
        """task_lifecycle handler is still importable after PR-E."""
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_result

        assert callable(handle_task_result)

    def test_goal_execution_handler_still_importable(self):
        """goal_execution handler is still importable after PR-E."""
        from galaxy_gateway.android.handlers.goal_execution import (
            handle_goal_execution_result,
        )

        assert callable(handle_goal_execution_result)
