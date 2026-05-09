"""tests/test_android_mode_switch_integration.py
=================================================
Integration tests for Android local ↔ cross-device mode switch.

These tests verify that:

1. ``evaluate_android_mode_readiness()`` returns correct verdicts under all
   gate combinations.
2. ``apply_mode_switch_to_registry()`` correctly updates the session registry
   entry for both local→cross_device and cross_device→local transitions.
3. ``record_mode_switch_in_session()`` records mode transition history and
   updates posture atomically.
4. Session continuity is preserved across mode switches: ``runtime_session_id``
   does NOT change, only ``posture`` and ``metadata`` are updated.
5. Dispatch eligibility and takeover eligibility correctly reflect the mode
   state after a switch.

Coverage groups
---------------
A.  Module imports — authority sentinels, enums, dataclasses, functions
    all importable from ``core.android_mode_gate_policy``.
B.  ``AndroidDeviceMode`` enum — all values, from_string().
C.  ``GateEvalResult`` — construction, to_dict().
D.  ``AndroidModeState`` — construction, to_dict(), to_json().
E.  ``AndroidModeReadinessVerdict`` — construction, to_dict(), to_json().
F.  ``evaluate_android_mode_readiness()`` — all gates pass → cross_device_ready.
G.  ``evaluate_android_mode_readiness()`` — V2 switch OFF → not ready.
H.  ``evaluate_android_mode_readiness()`` — no active session → not ready.
I.  ``evaluate_android_mode_readiness()`` — control_only posture → not ready.
J.  ``evaluate_android_mode_readiness()`` — Android cross_device gate OFF → not ready.
K.  ``evaluate_android_mode_readiness()`` — local_loop_ready=False → not takeover eligible.
L.  ``evaluate_android_mode_readiness()`` — graceful degradation on missing snapshot.
M.  local → cross_device mode switch via ``apply_mode_switch_to_registry()``:
    posture promoted to join_runtime.
N.  cross_device → local mode switch via ``apply_mode_switch_to_registry()``:
    posture demoted to control_only.
O.  Session continuity: runtime_session_id unchanged across mode switch.
P.  Mode switch history recorded in session metadata.
Q.  ``record_mode_switch_in_session()`` — records history and updates posture.
R.  ``record_mode_switch_in_session()`` — preserves existing posture when
    new_posture is None.
S.  ``record_mode_switch_in_session()`` — returns None for unknown device.
T.  ``build_mode_state_for_device()`` — correctly assembles state from registry.
U.  ``build_cross_device_readiness_panel_dict()`` — returns expected summary keys.
V.  Dispatch eligibility after local→cross_device switch.
W.  Takeover eligibility after cross_device→local switch (must be blocked).
X.  Mode switch with session_id cross-check: mismatched id skips update.
Y.  ``REGISTRY_MODE_SWITCH_METADATA_POLICY`` sentinel importable from
    ``core.attached_runtime_session_registry``.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from core.attached_runtime_session_registry import (
    REGISTRY_MODE_SWITCH_METADATA_POLICY,
    get_session_registry,
    lookup_session_by_device,
    record_mode_switch_in_session,
    register_session,
    reset_session_registry,
    update_session_posture,
)
from core.android_mode_gate_policy import (
    ANDROID_MODE_GATE_POLICY_AUTHORITY,
    ANDROID_MODE_GATE_POLICY_PR_SENTINEL,
    CANONICAL_ANDROID_EXECUTION_GATE_POLICY,
    CROSS_DEVICE_READINESS_GATE_POLICY,
    MODE_SWITCH_SESSION_CONSISTENCY_POLICY,
    UNIFIED_GATE_POLICY_SENTINELS,
    AndroidCanonicalExecutionGateDecision,
    AndroidDeviceMode,
    AndroidModeReadinessVerdict,
    AndroidModeState,
    GateEvalResult,
    apply_mode_switch_to_registry,
    build_cross_device_readiness_panel_dict,
    build_mode_state_for_device,
    evaluate_android_mode_readiness,
    resolve_android_execution_gate_decision,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_snapshot(
    *,
    local_loop_ready: bool = True,
    model_ready: bool = True,
    accessibility_ready: bool = True,
    cross_device_enabled: bool = True,
    goal_execution_enabled: bool = True,
    parallel_execution_enabled: bool = True,
    absorbed_at: Optional[float] = None,
) -> MagicMock:
    snap = MagicMock()
    snap.absorbed_at = absorbed_at or time.time()
    snap.local_loop_ready = local_loop_ready
    snap.model_ready = model_ready
    snap.accessibility_ready = accessibility_ready
    snap.local_loop_config = {
        "crossDeviceEnabled": cross_device_enabled,
        "goalExecutionEnabled": goal_execution_enabled,
        "parallelExecutionEnabled": parallel_execution_enabled,
    }
    snap.llama_cpp_available = True
    snap.ncnn_available = False
    snap.pending_first_download = False
    snap.degraded_reasons = []
    return snap


# ---------------------------------------------------------------------------
# A. Module imports — authority sentinels, enums, dataclasses, functions
# ---------------------------------------------------------------------------


class TestModuleImports:

    def test_A1_authority_sentinel_present(self):
        assert ANDROID_MODE_GATE_POLICY_AUTHORITY
        assert "ANDROID_MODE_GATE_POLICY_V1" in ANDROID_MODE_GATE_POLICY_AUTHORITY

    def test_A2_unified_gate_policy_sentinel(self):
        assert UNIFIED_GATE_POLICY_SENTINELS
        assert "evaluate_android_mode_readiness" in UNIFIED_GATE_POLICY_SENTINELS

    def test_A3_mode_switch_session_policy_sentinel(self):
        assert MODE_SWITCH_SESSION_CONSISTENCY_POLICY
        assert "apply_mode_switch_to_registry" in MODE_SWITCH_SESSION_CONSISTENCY_POLICY

    def test_A4_cross_device_readiness_gate_policy_sentinel(self):
        assert CROSS_DEVICE_READINESS_GATE_POLICY

    def test_A5_pr_sentinel(self):
        assert ANDROID_MODE_GATE_POLICY_PR_SENTINEL

    def test_A6_registry_mode_switch_sentinel(self):
        assert REGISTRY_MODE_SWITCH_METADATA_POLICY
        assert "record_mode_switch_in_session" in REGISTRY_MODE_SWITCH_METADATA_POLICY

    def test_A6b_canonical_execution_gate_policy(self):
        assert "allow/deny/defer" in CANONICAL_ANDROID_EXECUTION_GATE_POLICY
        assert "resolve_android_execution_gate_decision" in CANONICAL_ANDROID_EXECUTION_GATE_POLICY

    def test_A7_evaluate_android_mode_readiness_callable(self):
        assert callable(evaluate_android_mode_readiness)

    def test_A8_apply_mode_switch_to_registry_callable(self):
        assert callable(apply_mode_switch_to_registry)

    def test_A9_build_mode_state_for_device_callable(self):
        assert callable(build_mode_state_for_device)

    def test_A10_build_cross_device_readiness_panel_dict_callable(self):
        assert callable(build_cross_device_readiness_panel_dict)


# ---------------------------------------------------------------------------
# B. AndroidDeviceMode enum
# ---------------------------------------------------------------------------


class TestAndroidDeviceModeEnum:

    def test_B1_local_value(self):
        assert AndroidDeviceMode.local.value == "local"

    def test_B2_cross_device_value(self):
        assert AndroidDeviceMode.cross_device.value == "cross_device"

    def test_B3_transitioning_value(self):
        assert AndroidDeviceMode.transitioning.value == "transitioning"

    def test_B4_unknown_value(self):
        assert AndroidDeviceMode.unknown.value == "unknown"

    def test_B5_from_string_local(self):
        assert AndroidDeviceMode.from_string("local") == AndroidDeviceMode.local

    def test_B6_from_string_cross_device(self):
        assert AndroidDeviceMode.from_string("cross_device") == AndroidDeviceMode.cross_device

    def test_B7_from_string_unknown_fallback(self):
        assert AndroidDeviceMode.from_string("something_else") == AndroidDeviceMode.unknown


# ---------------------------------------------------------------------------
# C. GateEvalResult
# ---------------------------------------------------------------------------


class TestGateEvalResult:

    def test_C1_construction(self):
        g = GateEvalResult(gate_name="test_gate", passed=True)
        assert g.gate_name == "test_gate"
        assert g.passed is True

    def test_C2_to_dict_contains_required_keys(self):
        g = GateEvalResult(gate_name="v2_cross_device_switch", passed=False, reason="OFF", source="env")
        d = g.to_dict()
        assert d["gate_name"] == "v2_cross_device_switch"
        assert d["passed"] is False
        assert d["reason"] == "OFF"
        assert d["source"] == "env"

    def test_C3_failed_gate_has_reason(self):
        g = GateEvalResult(gate_name="session_active", passed=False, reason="no session")
        assert "no session" in g.reason


# ---------------------------------------------------------------------------
# D. AndroidModeState
# ---------------------------------------------------------------------------


class TestAndroidModeState:

    def test_D1_construction_defaults(self):
        s = AndroidModeState(device_id="dev_x")
        assert s.device_id == "dev_x"
        assert s.mode == AndroidDeviceMode.unknown
        assert s.cross_device_enabled is False
        assert s.session_active is False

    def test_D2_to_dict_contains_required_keys(self):
        s = AndroidModeState(device_id="dev_y", mode=AndroidDeviceMode.local)
        d = s.to_dict()
        required = [
            "device_id", "mode", "cross_device_enabled", "goal_execution_enabled",
            "parallel_execution_enabled", "session_active", "session_posture",
            "session_id", "local_loop_ready", "model_ready", "accessibility_ready",
            "snapshot_age_s", "assembled_at", "_authority",
        ]
        for key in required:
            assert key in d, f"Missing key: {key}"

    def test_D3_to_json_is_valid_json(self):
        import json
        s = AndroidModeState(device_id="dev_z", mode=AndroidDeviceMode.cross_device)
        j = s.to_json()
        parsed = json.loads(j)
        assert parsed["device_id"] == "dev_z"
        assert parsed["mode"] == "cross_device"


# ---------------------------------------------------------------------------
# E. AndroidModeReadinessVerdict
# ---------------------------------------------------------------------------


class TestAndroidModeReadinessVerdict:

    def test_E1_construction_defaults(self):
        v = AndroidModeReadinessVerdict(device_id="dev_a")
        assert v.device_id == "dev_a"
        assert v.is_cross_device_ready is False
        assert v.is_dispatch_eligible is False
        assert v.is_takeover_eligible is False
        assert v.gate_results == []
        assert v.blocking_gates == []

    def test_E2_to_dict_contains_required_keys(self):
        v = AndroidModeReadinessVerdict(device_id="dev_b")
        d = v.to_dict()
        required = [
            "device_id", "mode", "is_cross_device_ready", "is_dispatch_eligible",
            "is_takeover_eligible", "gate_results", "blocking_gates",
            "evaluated_at", "_authority",
        ]
        for key in required:
            assert key in d, f"Missing key: {key}"

    def test_E3_to_json_is_valid_json(self):
        import json
        v = AndroidModeReadinessVerdict(device_id="dev_c")
        j = v.to_json()
        parsed = json.loads(j)
        assert parsed["device_id"] == "dev_c"


# ---------------------------------------------------------------------------
# E2. Canonical execution gate decision
# ---------------------------------------------------------------------------


class TestAndroidCanonicalExecutionGateDecision:

    def test_E2_1_dataclass_to_dict(self):
        d = AndroidCanonicalExecutionGateDecision(decision="allow", reasons=("ok",)).to_dict()
        assert d["decision"] == "allow"
        assert d["reasons"] == ["ok"]
        assert d["_policy"] == CANONICAL_ANDROID_EXECUTION_GATE_POLICY

    def test_E2_2_policy_not_eligible_denies(self):
        decision = resolve_android_execution_gate_decision(
            policy_eligible=False,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=True,
            fallback_tier="center_delegated",
            model_ready=True,
        )
        assert decision.decision == "deny"
        assert "policy_ineligible" in decision.reasons

    def test_E2_3_busy_state_defers_when_other_signals_ready(self):
        decision = resolve_android_execution_gate_decision(
            policy_eligible=True,
            readiness_ready=True,
            execution_busy=True,
            local_inference_available=True,
            fallback_tier=None,
            model_ready=True,
        )
        assert decision.decision == "defer"
        assert "execution_busy" in decision.reasons

    def test_E2_4_fallback_restores_capability_and_allows(self):
        decision = resolve_android_execution_gate_decision(
            policy_eligible=True,
            readiness_ready=True,
            execution_busy=False,
            local_inference_available=False,
            fallback_tier="center_delegated",
            model_ready=False,
        )
        assert decision.decision == "allow"
        assert decision.capability_ready is True
        assert any(r.startswith("fallback_tier:") for r in decision.reasons)


# ---------------------------------------------------------------------------
# F. evaluate_android_mode_readiness — all gates pass → cross_device_ready
# ---------------------------------------------------------------------------


class TestEvaluateReadinessAllGatesPass:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_F1_all_gates_pass_is_cross_device_ready(self):
        register_session("dev_full", posture="join_runtime")
        snap = _make_snapshot()
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict = evaluate_android_mode_readiness("dev_full")

        assert verdict.is_cross_device_ready is True
        assert verdict.blocking_gates == []

    def test_F2_mode_inferred_as_cross_device(self):
        register_session("dev_mode", posture="join_runtime")
        snap = _make_snapshot()
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict = evaluate_android_mode_readiness("dev_mode")

        assert verdict.mode == AndroidDeviceMode.cross_device

    def test_F3_is_dispatch_eligible_when_all_pass(self):
        register_session("dev_disp", posture="join_runtime")
        snap = _make_snapshot()
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict = evaluate_android_mode_readiness("dev_disp")

        assert verdict.is_dispatch_eligible is True

    def test_F4_is_takeover_eligible_when_local_loop_ready(self):
        register_session("dev_takeover", posture="join_runtime")
        snap = _make_snapshot(local_loop_ready=True)
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict = evaluate_android_mode_readiness("dev_takeover")

        assert verdict.is_takeover_eligible is True


# ---------------------------------------------------------------------------
# G. evaluate_android_mode_readiness — V2 switch OFF → not ready
# ---------------------------------------------------------------------------


class TestEvaluateReadinessV2SwitchOff:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_G1_v2_switch_off_blocks_cross_device_ready(self):
        register_session("dev_off", posture="join_runtime")
        snap = _make_snapshot()
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=False
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict = evaluate_android_mode_readiness("dev_off")

        assert verdict.is_cross_device_ready is False
        assert "v2_cross_device_switch" in verdict.blocking_gates

    def test_G2_v2_switch_off_blocks_dispatch_eligible(self):
        register_session("dev_off2", posture="join_runtime")
        snap = _make_snapshot()
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=False
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict = evaluate_android_mode_readiness("dev_off2")

        assert verdict.is_dispatch_eligible is False

    def test_G3_gate_results_include_v2_switch(self):
        register_session("dev_off3", posture="join_runtime")
        snap = _make_snapshot()
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=False
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict = evaluate_android_mode_readiness("dev_off3")

        gate_names = [g.gate_name for g in verdict.gate_results]
        assert "v2_cross_device_switch" in gate_names


# ---------------------------------------------------------------------------
# H. evaluate_android_mode_readiness — no active session → not ready
# ---------------------------------------------------------------------------


class TestEvaluateReadinessNoSession:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_H1_no_session_blocks_cross_device_ready(self):
        # No register_session call
        snap = _make_snapshot()
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict = evaluate_android_mode_readiness("dev_nosession")

        assert verdict.is_cross_device_ready is False
        assert "session_active" in verdict.blocking_gates

    def test_H2_mode_inferred_as_unknown_when_no_session(self):
        snap = _make_snapshot()
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict = evaluate_android_mode_readiness("dev_nosession2")

        assert verdict.mode == AndroidDeviceMode.unknown


# ---------------------------------------------------------------------------
# I. evaluate_android_mode_readiness — control_only posture → not ready
# ---------------------------------------------------------------------------


class TestEvaluateReadinessControlOnlyPosture:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_I1_control_only_posture_blocks_cross_device(self):
        register_session("dev_co", posture="control_only")
        snap = _make_snapshot()
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict = evaluate_android_mode_readiness("dev_co")

        assert verdict.is_cross_device_ready is False
        assert "session_posture_join_runtime" in verdict.blocking_gates

    def test_I2_mode_inferred_as_local_when_control_only(self):
        register_session("dev_co2", posture="control_only")
        snap = _make_snapshot()
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict = evaluate_android_mode_readiness("dev_co2")

        # Session is active but posture is not join_runtime → local mode
        assert verdict.mode == AndroidDeviceMode.local


# ---------------------------------------------------------------------------
# J. evaluate_android_mode_readiness — Android cross_device gate OFF → not ready
# ---------------------------------------------------------------------------


class TestEvaluateReadinessAndroidGateOff:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_J1_android_gate_off_blocks_cross_device(self):
        register_session("dev_agoff", posture="join_runtime")
        snap = _make_snapshot(cross_device_enabled=False)
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict = evaluate_android_mode_readiness("dev_agoff")

        assert verdict.is_cross_device_ready is False
        assert "android_cross_device_enabled" in verdict.blocking_gates

    def test_J2_goal_execution_gate_off_blocks_dispatch_eligible(self):
        register_session("dev_geoff", posture="join_runtime")
        snap = _make_snapshot(goal_execution_enabled=False)
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict = evaluate_android_mode_readiness("dev_geoff", require_goal_execution=True)

        assert verdict.is_dispatch_eligible is False
        assert "android_goal_execution_enabled" in verdict.blocking_gates

    def test_J3_parallel_gate_off_not_blocking_when_not_required(self):
        register_session("dev_paroff", posture="join_runtime")
        snap = _make_snapshot(parallel_execution_enabled=False)
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict = evaluate_android_mode_readiness(
                "dev_paroff", require_parallel_execution=False
            )

        # parallel is not required, so its gate should not be blocking
        assert "android_parallel_execution_enabled" not in verdict.blocking_gates


# ---------------------------------------------------------------------------
# K. evaluate_android_mode_readiness — local_loop_ready=False → not takeover eligible
# ---------------------------------------------------------------------------


class TestEvaluateReadinessLocalLoopNotReady:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_K1_local_loop_not_ready_blocks_takeover(self):
        register_session("dev_lloff", posture="join_runtime")
        snap = _make_snapshot(local_loop_ready=False)
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict = evaluate_android_mode_readiness("dev_lloff", require_local_loop_ready=True)

        assert verdict.is_takeover_eligible is False
        assert "device_local_loop_ready" in verdict.blocking_gates

    def test_K2_dispatch_may_still_be_eligible_when_local_loop_not_required(self):
        register_session("dev_lloff2", posture="join_runtime")
        snap = _make_snapshot(local_loop_ready=False)
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict = evaluate_android_mode_readiness(
                "dev_lloff2", require_local_loop_ready=False
            )

        # When local_loop is not required, the takeover gate may not be explicitly
        # blocked by it; but is_dispatch_eligible should reflect the other gates.
        assert verdict.is_dispatch_eligible is True


# ---------------------------------------------------------------------------
# L. evaluate_android_mode_readiness — graceful degradation on missing snapshot
# ---------------------------------------------------------------------------


class TestEvaluateReadinessGracefulDegradation:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_L1_no_snapshot_returns_verdict_not_cross_device_ready(self):
        register_session("dev_nosnap", posture="join_runtime")
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=None
        ):
            verdict = evaluate_android_mode_readiness("dev_nosnap")

        assert verdict.is_cross_device_ready is False

    def test_L2_missing_store_returns_verdict_not_cross_device_ready(self):
        register_session("dev_nostore", posture="join_runtime")
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot",
            side_effect=ImportError("store unavailable"),
        ):
            verdict = evaluate_android_mode_readiness("dev_nostore")

        assert verdict.is_cross_device_ready is False
        # Must never raise
        assert verdict is not None

    def test_L3_entirely_missing_cross_device_switch_returns_not_ready(self):
        register_session("dev_noswitch", posture="join_runtime")
        snap = _make_snapshot()
        with patch(
            "core.android_mode_gate_policy._check_v2_cross_device_switch",
            side_effect=Exception("switch module unavailable"),
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict = evaluate_android_mode_readiness("dev_noswitch")

        # The outer exception handler must return a safe "not ready" verdict.
        assert verdict.is_cross_device_ready is False


# ---------------------------------------------------------------------------
# M. local → cross_device mode switch via apply_mode_switch_to_registry
# ---------------------------------------------------------------------------


class TestModeSwitchLocalToCrossDevice:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_M1_posture_promoted_to_join_runtime(self):
        register_session("dev_switch_lc", posture="control_only")
        updated = apply_mode_switch_to_registry(
            "dev_switch_lc",
            AndroidDeviceMode.local,
            AndroidDeviceMode.cross_device,
        )
        assert updated is not None
        assert updated.posture == "join_runtime"

    def test_M2_entry_remains_active(self):
        register_session("dev_switch_lc2", posture="control_only")
        updated = apply_mode_switch_to_registry(
            "dev_switch_lc2",
            AndroidDeviceMode.local,
            AndroidDeviceMode.cross_device,
        )
        assert updated is not None
        assert updated.is_active()

    def test_M3_mode_recorded_in_metadata(self):
        register_session("dev_switch_lc3", posture="control_only")
        updated = apply_mode_switch_to_registry(
            "dev_switch_lc3",
            AndroidDeviceMode.local,
            AndroidDeviceMode.cross_device,
        )
        assert updated is not None
        assert updated.metadata.get("current_mode") == "cross_device"

    def test_M4_mode_switch_history_has_one_entry(self):
        register_session("dev_switch_lc4", posture="control_only")
        updated = apply_mode_switch_to_registry(
            "dev_switch_lc4",
            AndroidDeviceMode.local,
            AndroidDeviceMode.cross_device,
        )
        assert updated is not None
        history = updated.metadata.get("mode_switch_history", [])
        assert len(history) >= 1
        assert history[-1]["from_mode"] == "local"
        assert history[-1]["to_mode"] == "cross_device"


# ---------------------------------------------------------------------------
# N. cross_device → local mode switch via apply_mode_switch_to_registry
# ---------------------------------------------------------------------------


class TestModeSwitchCrossDeviceToLocal:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_N1_posture_demoted_to_control_only(self):
        register_session("dev_switch_cl", posture="join_runtime")
        updated = apply_mode_switch_to_registry(
            "dev_switch_cl",
            AndroidDeviceMode.cross_device,
            AndroidDeviceMode.local,
        )
        assert updated is not None
        assert updated.posture == "control_only"

    def test_N2_entry_remains_active(self):
        register_session("dev_switch_cl2", posture="join_runtime")
        updated = apply_mode_switch_to_registry(
            "dev_switch_cl2",
            AndroidDeviceMode.cross_device,
            AndroidDeviceMode.local,
        )
        assert updated is not None
        assert updated.is_active()

    def test_N3_mode_recorded_in_metadata(self):
        register_session("dev_switch_cl3", posture="join_runtime")
        updated = apply_mode_switch_to_registry(
            "dev_switch_cl3",
            AndroidDeviceMode.cross_device,
            AndroidDeviceMode.local,
        )
        assert updated is not None
        assert updated.metadata.get("current_mode") == "local"


# ---------------------------------------------------------------------------
# O. Session continuity: runtime_session_id unchanged across mode switch
# ---------------------------------------------------------------------------


class TestSessionContinuityAcrossModeSwitch:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_O1_runtime_session_id_preserved_on_local_to_cross_device(self):
        entry = register_session("dev_cont1", posture="control_only")
        original_rsid = entry.runtime_session_id

        updated = apply_mode_switch_to_registry(
            "dev_cont1",
            AndroidDeviceMode.local,
            AndroidDeviceMode.cross_device,
        )
        assert updated is not None
        assert updated.runtime_session_id == original_rsid

    def test_O2_runtime_session_id_preserved_on_cross_device_to_local(self):
        entry = register_session("dev_cont2", posture="join_runtime")
        original_rsid = entry.runtime_session_id

        updated = apply_mode_switch_to_registry(
            "dev_cont2",
            AndroidDeviceMode.cross_device,
            AndroidDeviceMode.local,
        )
        assert updated is not None
        assert updated.runtime_session_id == original_rsid

    def test_O3_device_id_preserved_on_mode_switch(self):
        register_session("dev_cont3", posture="control_only")
        updated = apply_mode_switch_to_registry(
            "dev_cont3",
            AndroidDeviceMode.local,
            AndroidDeviceMode.cross_device,
        )
        assert updated is not None
        assert updated.device_id == "dev_cont3"

    def test_O4_entry_id_preserved_on_mode_switch(self):
        entry = register_session("dev_cont4", posture="control_only")
        original_entry_id = entry.entry_id

        updated = apply_mode_switch_to_registry(
            "dev_cont4",
            AndroidDeviceMode.local,
            AndroidDeviceMode.cross_device,
        )
        assert updated is not None
        assert updated.entry_id == original_entry_id


# ---------------------------------------------------------------------------
# P. Mode switch history recorded in session metadata
# ---------------------------------------------------------------------------


class TestModeSwitchHistoryInMetadata:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_P1_two_switches_produce_two_history_entries(self):
        register_session("dev_hist", posture="control_only")
        apply_mode_switch_to_registry(
            "dev_hist", AndroidDeviceMode.local, AndroidDeviceMode.cross_device
        )
        updated = apply_mode_switch_to_registry(
            "dev_hist", AndroidDeviceMode.cross_device, AndroidDeviceMode.local
        )
        assert updated is not None
        history = updated.metadata.get("mode_switch_history", [])
        assert len(history) == 2
        assert history[0]["from_mode"] == "local"
        assert history[1]["from_mode"] == "cross_device"

    def test_P2_history_capped_at_10(self):
        entry = register_session("dev_histcap", posture="join_runtime")
        # Apply 12 switches alternating
        for i in range(12):
            fm = AndroidDeviceMode.cross_device if i % 2 == 0 else AndroidDeviceMode.local
            tm = AndroidDeviceMode.local if i % 2 == 0 else AndroidDeviceMode.cross_device
            apply_mode_switch_to_registry("dev_histcap", fm, tm)

        final = lookup_session_by_device("dev_histcap")
        assert final is not None
        history = final.metadata.get("mode_switch_history", [])
        assert len(history) <= 10

    def test_P3_switch_record_contains_switched_at_timestamp(self):
        register_session("dev_histts", posture="control_only")
        before = time.time()
        updated = apply_mode_switch_to_registry(
            "dev_histts", AndroidDeviceMode.local, AndroidDeviceMode.cross_device
        )
        after = time.time()
        assert updated is not None
        history = updated.metadata.get("mode_switch_history", [])
        assert history
        ts = history[-1]["switched_at"]
        assert before <= ts <= after


# ---------------------------------------------------------------------------
# Q. record_mode_switch_in_session — records history and updates posture
# ---------------------------------------------------------------------------


class TestRecordModeSwitchInSession:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_Q1_records_history_and_updates_posture(self):
        register_session("dev_rms", posture="control_only")
        updated = record_mode_switch_in_session(
            "dev_rms", "local", "cross_device", new_posture="join_runtime"
        )
        assert updated is not None
        assert updated.posture == "join_runtime"
        history = updated.metadata.get("mode_switch_history", [])
        assert len(history) == 1
        assert history[0]["from_mode"] == "local"
        assert history[0]["to_mode"] == "cross_device"

    def test_Q2_current_mode_in_metadata(self):
        register_session("dev_rms2", posture="join_runtime")
        updated = record_mode_switch_in_session(
            "dev_rms2", "cross_device", "local", new_posture="control_only"
        )
        assert updated is not None
        assert updated.metadata.get("current_mode") == "local"

    def test_Q3_entry_remains_active(self):
        register_session("dev_rms3", posture="join_runtime")
        updated = record_mode_switch_in_session(
            "dev_rms3", "cross_device", "local", new_posture="control_only"
        )
        assert updated is not None
        assert updated.is_active()


# ---------------------------------------------------------------------------
# R. record_mode_switch_in_session — preserves existing posture when new_posture is None
# ---------------------------------------------------------------------------


class TestRecordModeSwitchPreservesPosture:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_R1_posture_unchanged_when_new_posture_is_none(self):
        register_session("dev_rp", posture="join_runtime")
        updated = record_mode_switch_in_session(
            "dev_rp", "local", "cross_device", new_posture=None
        )
        assert updated is not None
        assert updated.posture == "join_runtime"

    def test_R2_unknown_new_posture_normalised_to_control_only(self):
        register_session("dev_rp2", posture="join_runtime")
        updated = record_mode_switch_in_session(
            "dev_rp2", "local", "cross_device", new_posture="observe_only"
        )
        assert updated is not None
        assert updated.posture == "control_only"


# ---------------------------------------------------------------------------
# S. record_mode_switch_in_session — returns None for unknown device
# ---------------------------------------------------------------------------


class TestRecordModeSwitchUnknownDevice:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_S1_returns_none_for_unknown_device(self):
        result = record_mode_switch_in_session(
            "dev_nobody", "local", "cross_device", new_posture="join_runtime"
        )
        assert result is None


# ---------------------------------------------------------------------------
# T. build_mode_state_for_device — assembles state from registry
# ---------------------------------------------------------------------------


class TestBuildModeStateForDevice:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_T1_active_session_reflected_in_mode_state(self):
        register_session("dev_bms", posture="join_runtime")
        snap = _make_snapshot(cross_device_enabled=True)
        with patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            state = build_mode_state_for_device("dev_bms")

        assert state.session_active is True
        assert state.session_posture == "join_runtime"

    def test_T2_no_session_reflected_in_mode_state(self):
        # No register call
        snap = _make_snapshot()
        with patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            state = build_mode_state_for_device("dev_bms_none")

        assert state.session_active is False
        assert state.mode == AndroidDeviceMode.unknown

    def test_T3_cross_device_enabled_flag_reflected(self):
        register_session("dev_bms3", posture="join_runtime")
        snap = _make_snapshot(cross_device_enabled=True)
        with patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            state = build_mode_state_for_device("dev_bms3")

        assert state.cross_device_enabled is True

    def test_T4_mode_inferred_as_cross_device_when_cross_device_enabled_and_active_session(self):
        register_session("dev_bms4", posture="join_runtime")
        snap = _make_snapshot(cross_device_enabled=True)
        with patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            state = build_mode_state_for_device("dev_bms4")

        assert state.mode == AndroidDeviceMode.cross_device

    def test_T5_mode_inferred_as_local_when_cross_device_disabled_but_active_session(self):
        register_session("dev_bms5", posture="join_runtime")
        snap = _make_snapshot(cross_device_enabled=False)
        with patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            state = build_mode_state_for_device("dev_bms5")

        assert state.mode == AndroidDeviceMode.local


# ---------------------------------------------------------------------------
# U. build_cross_device_readiness_panel_dict — summary dict keys
# ---------------------------------------------------------------------------


class TestBuildCrossDeviceReadinessPanelDict:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_U1_returns_dict_with_required_keys(self):
        result = build_cross_device_readiness_panel_dict([])
        required = [
            "devices", "cross_device_ready_count", "dispatch_eligible_count",
            "takeover_eligible_count", "total_devices", "_source",
        ]
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_U2_empty_device_list_returns_zero_counts(self):
        result = build_cross_device_readiness_panel_dict([])
        assert result["total_devices"] == 0
        assert result["cross_device_ready_count"] == 0

    def test_U3_per_device_dicts_include_mode_and_readiness(self):
        register_session("dev_panel", posture="join_runtime")
        snap = _make_snapshot()
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            result = build_cross_device_readiness_panel_dict(["dev_panel"])

        assert result["total_devices"] == 1
        assert len(result["devices"]) == 1
        device_dict = result["devices"][0]
        assert "mode" in device_dict
        assert "is_cross_device_ready" in device_dict

    def test_U4_source_annotation_present(self):
        result = build_cross_device_readiness_panel_dict([])
        assert "_source" in result
        assert "ANDROID_MODE_GATE_POLICY_V1" in result["_source"]


# ---------------------------------------------------------------------------
# V. Dispatch eligibility after local→cross_device switch
# ---------------------------------------------------------------------------


class TestDispatchEligibilityAfterModeSwitch:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_V1_dispatch_not_eligible_before_mode_switch(self):
        # Start as local (control_only posture)
        register_session("dev_disp_v", posture="control_only")
        snap = _make_snapshot()
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict_before = evaluate_android_mode_readiness("dev_disp_v")

        assert verdict_before.is_dispatch_eligible is False

    def test_V2_dispatch_eligible_after_local_to_cross_device_switch(self):
        # Start as local (control_only posture)
        register_session("dev_disp_v2", posture="control_only")

        # Perform mode switch
        apply_mode_switch_to_registry(
            "dev_disp_v2",
            AndroidDeviceMode.local,
            AndroidDeviceMode.cross_device,
        )

        snap = _make_snapshot()
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict_after = evaluate_android_mode_readiness("dev_disp_v2")

        assert verdict_after.is_dispatch_eligible is True


# ---------------------------------------------------------------------------
# W. Takeover eligibility after cross_device→local switch (must be blocked)
# ---------------------------------------------------------------------------


class TestTakeoverEligibilityAfterModeSwitch:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_W1_takeover_eligible_before_cross_device_to_local_switch(self):
        register_session("dev_tko", posture="join_runtime")
        snap = _make_snapshot(local_loop_ready=True)
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict_before = evaluate_android_mode_readiness("dev_tko")

        assert verdict_before.is_takeover_eligible is True

    def test_W2_takeover_not_eligible_after_cross_device_to_local_switch(self):
        register_session("dev_tko2", posture="join_runtime")

        # Switch to local mode → posture becomes control_only
        apply_mode_switch_to_registry(
            "dev_tko2",
            AndroidDeviceMode.cross_device,
            AndroidDeviceMode.local,
        )

        snap = _make_snapshot(local_loop_ready=True)
        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled", return_value=True
        ), patch(
            "core.android_device_state_store.get_device_state_snapshot", return_value=snap
        ):
            verdict_after = evaluate_android_mode_readiness("dev_tko2")

        assert verdict_after.is_takeover_eligible is False
        # The posture gate should now block it
        assert "session_posture_join_runtime" in verdict_after.blocking_gates


# ---------------------------------------------------------------------------
# X. Mode switch with session_id cross-check
# ---------------------------------------------------------------------------


class TestModeSwitchSessionIdCrossCheck:

    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_X1_matching_session_id_allows_update(self):
        entry = register_session("dev_xcheck", session_id="sess_match", posture="control_only")
        updated = apply_mode_switch_to_registry(
            "dev_xcheck",
            AndroidDeviceMode.local,
            AndroidDeviceMode.cross_device,
            session_id="sess_match",
        )
        assert updated is not None
        assert updated.posture == "join_runtime"

    def test_X2_mismatched_session_id_skips_update(self):
        register_session("dev_xcheck2", session_id="sess_real", posture="control_only")
        updated = apply_mode_switch_to_registry(
            "dev_xcheck2",
            AndroidDeviceMode.local,
            AndroidDeviceMode.cross_device,
            session_id="sess_wrong",
        )
        assert updated is None
        # Verify original posture preserved
        entry = lookup_session_by_device("dev_xcheck2")
        assert entry is not None
        assert entry.posture == "control_only"

    def test_X3_empty_session_id_skips_cross_check(self):
        register_session("dev_xcheck3", session_id="sess_any", posture="control_only")
        updated = apply_mode_switch_to_registry(
            "dev_xcheck3",
            AndroidDeviceMode.local,
            AndroidDeviceMode.cross_device,
            session_id="",
        )
        assert updated is not None
        assert updated.posture == "join_runtime"


# ---------------------------------------------------------------------------
# Y. REGISTRY_MODE_SWITCH_METADATA_POLICY sentinel importable
# ---------------------------------------------------------------------------


class TestRegistryModeSwitchSentinelImportable:

    def test_Y1_sentinel_is_non_empty_string(self):
        assert isinstance(REGISTRY_MODE_SWITCH_METADATA_POLICY, str)
        assert len(REGISTRY_MODE_SWITCH_METADATA_POLICY) > 0

    def test_Y2_sentinel_contains_function_name(self):
        assert "record_mode_switch_in_session" in REGISTRY_MODE_SWITCH_METADATA_POLICY
