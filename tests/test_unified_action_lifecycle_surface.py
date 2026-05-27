"""tests/test_unified_action_lifecycle_surface.py
==================================================
PR-UAS behavioral tests: Unified Action Lifecycle Surface.

These tests prove that the unified surface changes real runtime
result/composition, not just field names.  Each test group covers a
specific requirement from the PR spec:

Group A — Android result surface integration
  Verify that Android execution result is a first-class object in the
  unified surface (not a secondary V2 post-interpretation value).

Group B — Blocker / confirmation surface convergence
  Verify that blocker and confirmation_needed are canonical surface fields,
  not scattered handler-local state.

Group C — Action lifecycle composition difference
  Verify that the unified surface changes the default response / result
  payload composition (DesktopPresenceRuntime.handle_request returns
  action_lifecycle_surface in its output).

Group D — Cross-repo lifecycle mapping
  Verify that Android acceptance / handoff / reconciliation events map to
  the canonical lifecycle phase names defined in CROSS_REPO_LIFECYCLE_MAP.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.unified_action_lifecycle_surface import (
    CROSS_REPO_LIFECYCLE_MAP,
    ActionLifecyclePhase,
    ActionOrigin,
    ClosureState,
    UnifiedActionLifecycleSurface,
    apply_blocker,
    apply_confirmation,
    build_from_dispatch,
    build_from_handoff_response,
    build_from_normalizer_outcome,
    close_surface,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_handoff_outcome(
    response_kind: str = "result",
    was_correlated: bool = True,
    callback_invoked: bool = True,
    handoff_id: str = "hid-001",
    task_id: str = "task-001",
    device_id: str = "dev-001",
    session_id: str = "sess-001",
    payload: Optional[Dict] = None,
    is_terminal: bool = True,
):
    """Create a mock HandoffV2ResponseOutcome-like object."""
    env = MagicMock()
    env.response_kind = MagicMock()
    env.response_kind.value = response_kind
    env.handoff_id = handoff_id
    env.task_id = task_id
    env.device_id = device_id
    env.session_id = session_id
    env.payload = payload or {"output": "android_execution_completed"}
    env.is_terminal = is_terminal
    env.trace_id = ""

    outcome = MagicMock()
    outcome.envelope = env
    outcome.was_correlated = was_correlated
    outcome.callback_invoked = callback_invoked
    return outcome


def _make_mock_normalizer_outcome(
    message_type: str = "task_result",
    was_normalized: bool = True,
    was_deduplicated: bool = False,
    committed_identity: str = "contract-001",
    with_handoff_response: bool = False,
):
    """Create a mock AndroidResultNormalizerOutcome-like object."""
    outcome = MagicMock()
    outcome.message_type = message_type
    outcome.was_normalized = was_normalized
    outcome.was_deduplicated = was_deduplicated
    outcome.committed_terminal_identity = committed_identity
    outcome.source_message_id = "msg-001"
    outcome.handoff_response_outcome = None
    outcome.participant_truth_outcome = MagicMock() if message_type in {"task_result", "goal_execution_result"} else None
    outcome.signal_reconcile_outcome = None

    if with_handoff_response and was_normalized:
        hr_outcome = _make_mock_handoff_outcome(
            response_kind="result",
            handoff_id="hid-normalizer",
        )
        outcome.handoff_response_outcome = hr_outcome

    return outcome


# ---------------------------------------------------------------------------
# Group A: Android result surface integration
# ---------------------------------------------------------------------------


class TestAndroidResultSurfaceIntegration:
    """Group A: Android execution result is first-class in unified surface."""

    def test_A01_handoff_result_populates_android_result_field(self):
        """android_result is a named top-level field set from Android handoff result."""
        outcome = _make_mock_handoff_outcome(response_kind="result")
        surface = build_from_handoff_response(outcome)

        assert surface.android_result is not None, (
            "android_result must be set when handoff result arrives"
        )
        assert surface.android_result_authority == "android_device", (
            "authority must name Android device, not V2"
        )
        assert surface.is_android_result_first_class(), (
            "is_android_result_first_class() must return True"
        )

    def test_A02_android_result_dict_includes_response_kind(self):
        """android_result dict contains response_kind, handoff_id, task_id, device_id."""
        outcome = _make_mock_handoff_outcome(
            response_kind="result",
            handoff_id="hid-A02",
            task_id="task-A02",
            device_id="dev-A02",
        )
        surface = build_from_handoff_response(outcome)

        r = surface.android_result
        assert r is not None
        assert r["response_kind"] == "result"
        assert r["handoff_id"] == "hid-A02"
        assert r["task_id"] == "task-A02"
        assert r["device_id"] == "dev-A02"

    def test_A03_android_failure_also_first_class(self):
        """Failure result is also a first-class android_result (not only success)."""
        outcome = _make_mock_handoff_outcome(response_kind="failure")
        surface = build_from_handoff_response(outcome)

        assert surface.android_result is not None
        assert surface.android_result_authority == "android_device"
        assert surface.android_result["response_kind"] == "failure"

    def test_A04_handoff_ack_does_not_set_android_result(self):
        """ACK is acceptance-only — android_result stays None until terminal."""
        outcome = _make_mock_handoff_outcome(
            response_kind="ack", is_terminal=False, callback_invoked=False
        )
        surface = build_from_handoff_response(outcome)

        assert surface.android_result is None
        assert surface.android_result_authority == ""
        assert surface.accepted is True
        assert surface.acceptance_tag == "android_handoff_ack"
        assert surface.phase == ActionLifecyclePhase.accepted

    def test_A05_uncorrelated_outcome_has_no_android_result(self):
        """Uncorrelated outcome does not produce a first-class android result."""
        outcome = _make_mock_handoff_outcome(
            response_kind="result", was_correlated=False
        )
        surface = build_from_handoff_response(outcome)

        assert surface.android_result is None
        assert not surface.is_android_result_first_class()

    def test_A06_normalizer_task_result_surfaces_android_result(self):
        """task_result via normalizer populates android_result as first-class object."""
        outcome = _make_mock_normalizer_outcome(message_type="task_result")
        surface = build_from_normalizer_outcome(outcome, device_id="dev-normalizer")

        assert surface.android_result is not None
        assert surface.android_result_authority == "android_device"
        assert surface.android_result["message_type"] == "task_result"

    def test_A07_normalizer_handoff_result_delegates_to_handoff_surface(self):
        """normalizer with handoff_response_outcome surfaces android_result from it."""
        outcome = _make_mock_normalizer_outcome(
            message_type="handoff_result", with_handoff_response=True
        )
        surface = build_from_normalizer_outcome(outcome)

        assert surface.android_result is not None
        assert surface.android_result_authority == "android_device"

    def test_A08_to_dict_exposes_android_result_at_top_level(self):
        """to_dict() returns android_result and android_result_authority as top-level keys."""
        outcome = _make_mock_handoff_outcome(response_kind="result")
        surface = build_from_handoff_response(outcome)
        d = surface.to_dict()

        assert "android_result" in d
        assert "android_result_authority" in d
        assert d["android_result_authority"] == "android_device"
        assert isinstance(d["android_result"], dict)


# ---------------------------------------------------------------------------
# Group B: Blocker / confirmation surface convergence
# ---------------------------------------------------------------------------


class TestBlockerConfirmationSurfaceConvergence:
    """Group B: blocker and confirmation_needed are canonical surface fields."""

    def test_B01_apply_blocker_sets_phase_and_surface_field(self):
        """apply_blocker() converges blocker into canonical surface and changes phase."""
        surface = build_from_dispatch(task_id="task-B01")
        # Sanity: surface starts as dispatched with no blocker
        assert surface.phase == ActionLifecyclePhase.dispatched
        assert not surface.has_blocker()

        apply_blocker(
            surface,
            blocker={"reason": "missing_permission", "kind": "authorization"},
            blocker_reason="missing_permission",
            blocker_kind="authorization",
        )

        assert surface.has_blocker()
        assert surface.phase == ActionLifecyclePhase.blocked
        assert surface.blocker_reason == "missing_permission"
        assert surface.blocker_kind == "authorization"
        assert surface.blocker is not None

    def test_B02_blocker_in_to_dict(self):
        """Blocker data appears at canonical positions in to_dict() output."""
        surface = build_from_dispatch(task_id="task-B02")
        apply_blocker(
            surface,
            blocker={"reason": "device_unavailable"},
            blocker_kind="device_blocker",
        )
        d = surface.to_dict()

        assert d["phase"] == "blocked"
        assert d["blocker"] == {"reason": "device_unavailable"}
        assert d["blocker_kind"] == "device_blocker"

    def test_B03_apply_confirmation_sets_phase_and_flag(self):
        """apply_confirmation() sets confirmation_needed=True and changes phase."""
        surface = build_from_dispatch(task_id="task-B03")
        apply_confirmation(
            surface,
            confirmation_context={"reason": "destructive_action", "target": "prod"},
        )

        assert surface.confirmation_needed is True
        assert surface.phase == ActionLifecyclePhase.confirmation_needed
        assert surface.confirmation_context is not None
        assert surface.confirmation_context["reason"] == "destructive_action"

    def test_B04_confirmation_in_to_dict(self):
        """confirmation_needed appears at canonical position in to_dict()."""
        surface = build_from_dispatch(task_id="task-B04")
        apply_confirmation(surface, reason="needs_user_approval")
        d = surface.to_dict()

        assert d["phase"] == "confirmation_needed"
        assert d["confirmation_needed"] is True
        assert d["confirmation_context"]["reason"] == "needs_user_approval"

    def test_B05_close_surface_sets_closure_state(self):
        """close_surface() converges closure state into the canonical surface."""
        surface = build_from_dispatch(task_id="task-B05")
        assert not surface.is_closed()

        close_surface(surface, reason="android_handoff_result")

        assert surface.is_closed()
        assert surface.closure_state == ClosureState.closed
        assert surface.closure_reason == "android_handoff_result"
        assert surface.phase == ActionLifecyclePhase.closed

    def test_B06_handoff_result_auto_closes_surface(self):
        """build_from_handoff_response with terminal result auto-sets closed state."""
        outcome = _make_mock_handoff_outcome(response_kind="result", is_terminal=True)
        surface = build_from_handoff_response(outcome)

        assert surface.is_closed()
        assert surface.closure_state == ClosureState.closed

    def test_B07_handoff_ack_sets_handoff_pending_not_closed(self):
        """ACK advances closure to handoff_pending, not yet closed."""
        outcome = _make_mock_handoff_outcome(
            response_kind="ack", is_terminal=False, callback_invoked=False
        )
        surface = build_from_handoff_response(outcome)

        assert surface.closure_state == ClosureState.handoff_pending
        assert not surface.is_closed()

    def test_B08_blocker_survives_to_dict_round_trip(self):
        """Blocker dict in to_dict() matches the original blocker payload."""
        blocker_payload = {"reason": "quota_exceeded", "kind": "rate_limit", "retry_after": 30}
        surface = build_from_dispatch()
        apply_blocker(surface, blocker=blocker_payload)
        d = surface.to_dict()

        assert d["blocker"] == blocker_payload


# ---------------------------------------------------------------------------
# Group C: Action lifecycle composition difference
# ---------------------------------------------------------------------------


class TestActionLifecycleCompositionDifference:
    """Group C: unified surface changes default response / result payload."""

    def _make_runtime(self):
        """Construct a minimal DesktopPresenceRuntime for composition tests."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        return DesktopPresenceRuntime()

    def test_C01_handle_request_result_contains_action_lifecycle_surface(self):
        """handle_request() returns action_lifecycle_surface in canonical result."""
        runtime = self._make_runtime()
        result = asyncio.run(
            runtime.handle_request("test C01", source="chat")
        )

        assert "action_lifecycle_surface" in result, (
            "action_lifecycle_surface must be present in default handle_request() result"
        )

    def test_C02_action_lifecycle_surface_has_required_keys(self):
        """action_lifecycle_surface dict contains all mandatory canonical keys."""
        runtime = self._make_runtime()
        result = asyncio.run(
            runtime.handle_request("test C02", source="chat")
        )

        surface_dict = result["action_lifecycle_surface"]
        mandatory_keys = {
            "action_id",
            "phase",
            "origin",
            "android_result",
            "android_result_authority",
            "blocker",
            "blocker_reason",
            "confirmation_needed",
            "closure_state",
            "cross_repo_lifecycle_map",
            "surface_version",
        }
        missing = mandatory_keys - set(surface_dict.keys())
        assert not missing, f"action_lifecycle_surface missing keys: {missing}"

    def test_C03_android_carrier_sets_android_origin(self):
        """Android carrier (android_goal_execution) sets origin=android_device in surface."""
        runtime = self._make_runtime()

        # Patch _dispatch to return a minimal android execution result
        async def _fake_dispatch(*args, **kwargs):
            return {
                "response": "ok",
                "execution_result": {"output": "android_result_payload", "success": True},
            }

        with patch.object(runtime, "_dispatch", side_effect=_fake_dispatch):
            result = asyncio.run(
                runtime.handle_request(
                    "test C03",
                    source="android_goal_execution",
                    device_id="dev-C03",
                )
            )

        surface_dict = result["action_lifecycle_surface"]
        assert surface_dict["origin"] == "android_device", (
            "android_goal_execution carrier must produce android_device origin"
        )
        # Android result should be first-class when execution_result is present
        assert surface_dict["android_result"] is not None, (
            "android_result must be populated for android_goal_execution with result"
        )
        assert surface_dict["android_result_authority"] == "android_device"

    def test_C04_non_android_carrier_sets_v2_center_origin(self):
        """Desktop carrier (chat) sets origin=v2_center in surface."""
        runtime = self._make_runtime()
        result = asyncio.run(
            runtime.handle_request("test C04", source="chat")
        )

        surface_dict = result["action_lifecycle_surface"]
        assert surface_dict["origin"] == "v2_center", (
            "chat carrier must produce v2_center origin"
        )

    def test_C05_surface_session_id_matches_result_session_id(self):
        """action_lifecycle_surface.session_id matches result.conversation_session_id."""
        runtime = self._make_runtime()
        result = asyncio.run(
            runtime.handle_request("test C05", source="chat")
        )

        surface_session = result["action_lifecycle_surface"]["session_id"]
        result_session = result.get("conversation_session_id", "")
        assert surface_session == result_session, (
            "surface session_id must match result conversation_session_id"
        )

    def test_C06_surface_action_id_matches_runtime_session_id(self):
        """action_lifecycle_surface.action_id is the runtime_session_id (correlation)."""
        runtime = self._make_runtime()
        result = asyncio.run(
            runtime.handle_request("test C06", source="chat")
        )

        surface_action_id = result["action_lifecycle_surface"]["action_id"]
        runtime_session_id = result.get("runtime_session_id", "")
        assert surface_action_id == runtime_session_id, (
            "surface action_id must equal runtime_session_id for stable correlation"
        )

    def test_C07_blocker_in_execution_result_surfaces_in_action_lifecycle(self):
        """When execution_result carries a blocker, action_lifecycle_surface reflects blocked phase."""
        runtime = self._make_runtime()

        async def _fake_dispatch_blocker(*args, **kwargs):
            return {
                "response": "blocked",
                "execution_result": {"blocker": "device_offline", "success": False},
            }

        with patch.object(runtime, "_dispatch", side_effect=_fake_dispatch_blocker):
            result = asyncio.run(
                runtime.handle_request("test C07", source="chat")
            )

        surface_dict = result["action_lifecycle_surface"]
        assert surface_dict["phase"] == "blocked", (
            "phase must be 'blocked' when execution_result has a blocker"
        )
        assert surface_dict["blocker"] is not None

    def test_C08_confirmation_in_execution_result_surfaces_in_action_lifecycle(self):
        """confirmation_needed in execution_result surfaces in action_lifecycle_surface."""
        runtime = self._make_runtime()

        async def _fake_dispatch_confirm(*args, **kwargs):
            return {
                "response": "confirm",
                "execution_result": {"confirmation_needed": True},
            }

        with patch.object(runtime, "_dispatch", side_effect=_fake_dispatch_confirm):
            result = asyncio.run(
                runtime.handle_request("test C08", source="chat")
            )

        surface_dict = result["action_lifecycle_surface"]
        assert surface_dict["confirmation_needed"] is True
        assert surface_dict["phase"] == "confirmation_needed"


# ---------------------------------------------------------------------------
# Group D: Cross-repo lifecycle mapping
# ---------------------------------------------------------------------------


class TestCrossRepoLifecycleMapping:
    """Group D: Android gateway events map to canonical lifecycle phases."""

    def test_D01_cross_repo_lifecycle_map_covers_key_android_events(self):
        """CROSS_REPO_LIFECYCLE_MAP includes all critical Android gateway events."""
        required_events = {
            "handoff_ack",
            "handoff_result",
            "handoff_failure",
            "delegated_execution_signal",
            "reconciliation_signal",
            "acceptance_report",
        }
        missing = required_events - set(CROSS_REPO_LIFECYCLE_MAP.keys())
        assert not missing, (
            f"CROSS_REPO_LIFECYCLE_MAP missing Android events: {missing}"
        )

    def test_D02_handoff_ack_maps_to_accepted(self):
        """handoff_ack → accepted in canonical lifecycle map."""
        assert CROSS_REPO_LIFECYCLE_MAP["handoff_ack"] == "accepted"

    def test_D03_handoff_result_maps_to_result_received(self):
        """handoff_result → result_received in canonical lifecycle map."""
        assert CROSS_REPO_LIFECYCLE_MAP["handoff_result"] == "result_received"

    def test_D04_reconciliation_signal_maps_to_closed(self):
        """reconciliation_signal → closed in canonical lifecycle map."""
        assert CROSS_REPO_LIFECYCLE_MAP["reconciliation_signal"] == "closed"

    def test_D05_acceptance_report_maps_to_accepted(self):
        """acceptance_report → accepted in canonical lifecycle map."""
        assert CROSS_REPO_LIFECYCLE_MAP["acceptance_report"] == "accepted"

    def test_D06_handoff_response_surface_carries_lifecycle_map(self):
        """Surface built from handoff response carries the canonical lifecycle map."""
        outcome = _make_mock_handoff_outcome(response_kind="result")
        surface = build_from_handoff_response(outcome)

        assert "handoff_ack" in surface.cross_repo_lifecycle_map
        assert "handoff_result" in surface.cross_repo_lifecycle_map
        assert surface.cross_repo_lifecycle_map["handoff_ack"] == "accepted"
        assert surface.cross_repo_lifecycle_map["handoff_result"] == "result_received"

    def test_D07_last_android_event_recorded_on_surface(self):
        """Surface records which Android event last drove its phase."""
        outcome = _make_mock_handoff_outcome(response_kind="result")
        surface = build_from_handoff_response(outcome)

        assert surface.last_android_event == "handoff_result"

    def test_D08_ack_surface_last_event_is_handoff_ack(self):
        """ACK surface records handoff_ack as last Android event."""
        outcome = _make_mock_handoff_outcome(
            response_kind="ack", is_terminal=False, callback_invoked=False
        )
        surface = build_from_handoff_response(outcome)

        assert surface.last_android_event == "handoff_ack"

    def test_D09_normalizer_outcome_surface_carries_lifecycle_map(self):
        """Surface built from normalizer outcome also carries cross-repo map."""
        outcome = _make_mock_normalizer_outcome(message_type="task_result")
        surface = build_from_normalizer_outcome(outcome)

        assert "handoff_ack" in surface.cross_repo_lifecycle_map
        assert "reconciliation_signal" in surface.cross_repo_lifecycle_map

    def test_D10_dispatch_surface_has_correct_phase_and_map(self):
        """Dispatch surface starts at dispatched phase with full lifecycle map."""
        surface = build_from_dispatch(
            action_id="act-D10",
            task_id="task-D10",
            device_id="dev-D10",
            origin=ActionOrigin.cross_repo,
        )

        assert surface.phase == ActionLifecyclePhase.dispatched
        assert surface.origin == ActionOrigin.cross_repo
        assert "handoff_dispatch" in surface.cross_repo_lifecycle_map
        assert surface.cross_repo_lifecycle_map["handoff_dispatch"] == "dispatched"

    def test_D11_handoff_v2_result_handler_returns_action_lifecycle_surface(self):
        """handle_handoff_v2_result() ACK includes action_lifecycle_surface field."""

        async def _run():
            from galaxy_gateway.android.handlers.handoff_v2_result import (
                handle_handoff_v2_result,
            )

            # Build a minimal correlated outcome that will trigger surface build
            _outcome = _make_mock_handoff_outcome(
                response_kind="result",
                was_correlated=True,
                handoff_id="hid-D11",
                task_id="task-D11",
                device_id="dev-D11",
            )

            # Patch the ingress so it returns our mock outcome
            # Also patch schema gate so it allows the message through
            _gate_allow = MagicMock()
            _gate_allow.action = "allow"

            with patch(
                "galaxy_gateway.android.handlers.handoff_v2_result._ingest_handoff_response",
                return_value=_outcome,
            ), patch(
                "contracts.cross_repo_schema_version_gate.evaluate_android_uplink_schema_gate",
                return_value=_gate_allow,
            ):
                msg = {
                    "version": "3.0",
                    "type": "handoff_result",
                    "device_id": "dev-D11",
                    "message_id": "msg-D11",
                    "handoff_id": "hid-D11",
                    "task_id": "task-D11",
                    "payload": {"output": "done"},
                }
                bridge = MagicMock()
                ws = MagicMock()
                ack = await handle_handoff_v2_result(bridge, ws, msg)

            return ack

        ack = asyncio.run(_run())
        # The ACK must have the surface attached
        assert "action_lifecycle_surface" in ack, (
            "handle_handoff_v2_result() ACK must include action_lifecycle_surface"
        )
        surface_dict = ack["action_lifecycle_surface"]
        assert surface_dict["android_result"] is not None
        assert surface_dict["android_result_authority"] == "android_device"


# ---------------------------------------------------------------------------
# Standalone surface unit tests
# ---------------------------------------------------------------------------


class TestUnifiedSurfaceUnit:
    """Miscellaneous unit tests for the surface dataclass."""

    def test_U01_default_surface_is_open_and_unknown(self):
        surface = UnifiedActionLifecycleSurface()
        assert surface.phase == ActionLifecyclePhase.unknown
        assert surface.closure_state == ClosureState.open
        assert not surface.is_closed()
        assert not surface.has_blocker()
        assert not surface.is_android_result_first_class()

    def test_U02_to_dict_round_trip_preserves_phase(self):
        surface = build_from_dispatch(task_id="u02")
        d = surface.to_dict()
        assert d["phase"] == "dispatched"
        assert d["closure_state"] == "open"
        assert d["surface_version"] == "1.0"
        assert d["surface_origin_module"] == "core.unified_action_lifecycle_surface"

    def test_U03_sentinel_string_is_stable(self):
        from core.unified_action_lifecycle_surface import (
            UNIFIED_ACTION_LIFECYCLE_SURFACE_SENTINEL,
        )
        assert "pr-uas" in UNIFIED_ACTION_LIFECYCLE_SURFACE_SENTINEL
        assert "dual-repo" in UNIFIED_ACTION_LIFECYCLE_SURFACE_SENTINEL

    def test_U04_action_id_is_uuid_by_default(self):
        surface = UnifiedActionLifecycleSurface()
        # Should be parseable as UUID
        parsed = uuid.UUID(surface.action_id)
        assert str(parsed) == surface.action_id

    def test_U05_build_from_dispatch_sets_v2_center_origin_by_default(self):
        surface = build_from_dispatch(task_id="u05")
        assert surface.origin == ActionOrigin.v2_center
