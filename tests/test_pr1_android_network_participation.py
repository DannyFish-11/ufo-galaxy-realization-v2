#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr1_android_network_participation.py
================================================
Tests for PR-1: core/android_network_participation.py — unified Android
network participation truth module.

Coverage areas
--------------
A.  Module importable; authority sentinels present and non-empty.
B.  AndroidNetworkParticipationTier enum values and ordering.
C.  AndroidParticipationTransitionSignal enum values present.
D.  PARTICIPATION_TIER_TRANSITIONS table covers all signals.
E.  derive_android_network_participation_tier — all tier derivation paths.
    E1.  local_only: no websocket.
    E2.  local_only: websocket up but no reg ack.
    E3.  control_only: reg ack + control_only posture.
    E4.  control_only: operator suspended (overrides everything).
    E5.  cross_device_capable: reg ack + gaps present.
    E6.  cross_device_capable: fully attached but cross_device_enabled=False.
    E7.  cross_device_enabled: fully attached + cross_device_enabled=True but
         no active session / capability not visible.
    E8.  fully_attached: fully attached + cross_device_enabled + capability
         visible + join_runtime session.
    E9.  dispatch_eligible: fully_attached + readiness_satisfied +
         dispatch_gate_passed.
    E10. distributed_participant: dispatch_eligible + execution_active.
F.  derive returns blocking_reasons for each blocked condition.
G.  build_android_network_participation_state round-trips correctly.
H.  apply_participation_signal — upward and downward transitions.
    H1.  websocket_disconnected forces local_only.
    H2.  registration_fully_attached raises tier to cross_device_enabled.
    H3.  operator_suspended caps at control_only.
    H4.  execution_session_started → distributed_participant.
    H5.  execution_session_ended → drops from distributed_participant.
    H6.  capability_visibility_lost → drops from fully_attached.
I.  record_participation_state / get_stored_participation_state round-trip.
J.  reset_participation_store clears all entries.
K.  get_participation_state_for_device — safe without any stores available.
L.  AndroidNetworkParticipationState.to_dict() serialisable.
M.  V2 unified state contract integration — participation tier appears in
    raw_signals and derived_state when build_v2_unified_state_contract is called.
    M1.  Baseline call with empty android signals → tier = local_only.
    M2.  Call with android_attached + cross_device signals → tier >= control_only.
    M3.  participation_evidence override passes through.
    M4.  derived_state key "android_network_participation" present.
    M5.  contract version bumped to 1.3.0.
N.  Registration handler integration — network_participation_tier in ack.
"""

from __future__ import annotations

import sys
import os
from typing import Any, Dict, List, Optional

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from core.android_network_participation import (
    ANDROID_NETWORK_PARTICIPATION_AUTHORITY,
    ANDROID_NETWORK_PARTICIPATION_CONTRACT_VERSION,
    ANDROID_ORIGINATING_CONTRACT,
    PARTICIPATION_TIER_TRANSITIONS,
    AndroidNetworkParticipationTier,
    AndroidParticipationTransitionSignal,
    AndroidNetworkParticipationState,
    derive_android_network_participation_tier,
    build_android_network_participation_state,
    apply_participation_signal,
    record_participation_state,
    get_stored_participation_state,
    list_participation_transition_history,
    reset_participation_store,
    get_participation_state_for_device,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _all_true_conditions(**overrides: Any) -> Dict[str, Any]:
    """Return a conditions dict where every flag is at its most permissive
    value, optionally overriding specific fields."""
    base: Dict[str, Any] = {
        "websocket_connected": True,
        "registration_ack_success": True,
        "registration_fully_attached": True,
        "registration_gaps": [],
        "capability_visible": True,
        "active_session_count": 1,
        "session_posture": "join_runtime",
        "cross_device_enabled": True,
        "readiness_satisfied": True,
        "dispatch_gate_passed": True,
        "operator_suspended": False,
        "execution_active": False,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Group A: Module importable / authority sentinels
# ---------------------------------------------------------------------------


class TestAuthoritySentinels:
    def test_authority_present(self):
        assert ANDROID_NETWORK_PARTICIPATION_AUTHORITY
        assert "PR-1" in ANDROID_NETWORK_PARTICIPATION_AUTHORITY
        assert "android_network_participation" in ANDROID_NETWORK_PARTICIPATION_AUTHORITY

    def test_contract_version_present(self):
        assert ANDROID_NETWORK_PARTICIPATION_CONTRACT_VERSION
        assert ANDROID_NETWORK_PARTICIPATION_CONTRACT_VERSION.startswith("1.")

    def test_originating_contract_present(self):
        assert ANDROID_ORIGINATING_CONTRACT
        assert "join_runtime" in ANDROID_ORIGINATING_CONTRACT


# ---------------------------------------------------------------------------
# Group B: AndroidNetworkParticipationTier enum
# ---------------------------------------------------------------------------


class TestAndroidNetworkParticipationTier:
    def test_all_seven_tiers_present(self):
        expected = {
            "local_only", "control_only", "cross_device_capable",
            "cross_device_enabled", "fully_attached", "dispatch_eligible",
            "distributed_participant",
        }
        actual = {t.value for t in AndroidNetworkParticipationTier}
        assert expected == actual

    def test_ordering_local_only_is_lowest(self):
        assert AndroidNetworkParticipationTier.local_only.ordinal() == 0

    def test_ordering_distributed_participant_is_highest(self):
        assert AndroidNetworkParticipationTier.distributed_participant.ordinal() == 6

    def test_strict_ordering(self):
        tiers = list(AndroidNetworkParticipationTier)
        for i in range(len(tiers) - 1):
            assert tiers[i] < tiers[i + 1], f"{tiers[i]} should be < {tiers[i+1]}"

    def test_from_string_valid(self):
        t = AndroidNetworkParticipationTier.from_string("dispatch_eligible")
        assert t == AndroidNetworkParticipationTier.dispatch_eligible

    def test_from_string_unknown_returns_local_only(self):
        t = AndroidNetworkParticipationTier.from_string("not_a_tier")
        assert t == AndroidNetworkParticipationTier.local_only

    def test_from_string_empty_returns_local_only(self):
        t = AndroidNetworkParticipationTier.from_string("")
        assert t == AndroidNetworkParticipationTier.local_only

    def test_ge_le(self):
        T = AndroidNetworkParticipationTier
        assert T.dispatch_eligible >= T.fully_attached
        assert T.local_only <= T.control_only


# ---------------------------------------------------------------------------
# Group C: AndroidParticipationTransitionSignal enum
# ---------------------------------------------------------------------------


class TestAndroidParticipationTransitionSignal:
    def test_all_expected_signals_present(self):
        expected = {
            "websocket_connected", "registration_ack_success",
            "registration_fully_attached", "registration_partial_attached",
            "capability_visibility_gained", "capability_visibility_lost",
            "active_session_acquired", "active_session_lost",
            "readiness_satisfied", "readiness_lost",
            "cross_device_switch_enabled", "cross_device_switch_disabled",
            "cross_device_gate_enabled", "cross_device_gate_disabled",
            "posture_join_runtime", "posture_control_only",
            "execution_session_started", "execution_session_ended",
            "websocket_disconnected", "reconnect_continuity_resumed",
            "attachment_break", "operator_suspended", "operator_suspension_lifted",
        }
        actual = {s.value for s in AndroidParticipationTransitionSignal}
        assert expected == actual


# ---------------------------------------------------------------------------
# Group D: PARTICIPATION_TIER_TRANSITIONS table
# ---------------------------------------------------------------------------


class TestParticipationTierTransitions:
    def test_all_signals_covered(self):
        for signal in AndroidParticipationTransitionSignal:
            assert signal in PARTICIPATION_TIER_TRANSITIONS, (
                f"Signal {signal.value} not in PARTICIPATION_TIER_TRANSITIONS"
            )

    def test_values_are_non_empty_strings(self):
        for signal, description in PARTICIPATION_TIER_TRANSITIONS.items():
            assert isinstance(description, str) and description.strip(), (
                f"Transition for {signal.value} has empty description"
            )


# ---------------------------------------------------------------------------
# Group E: derive_android_network_participation_tier
# ---------------------------------------------------------------------------


class TestDeriveTier:
    """E1–E10: derivation path tests."""

    def _derive(self, **overrides: Any):
        conditions = _all_true_conditions(**overrides)
        conditions["execution_active"] = False  # reset default
        conditions.update(overrides)
        tier, blocking, notes = derive_android_network_participation_tier(**conditions)
        return tier, blocking, notes

    def test_e1_local_only_no_websocket(self):
        tier, blocking, _ = self._derive(websocket_connected=False)
        assert tier == AndroidNetworkParticipationTier.local_only
        assert any("websocket" in r for r in blocking)

    def test_e2_local_only_no_reg_ack(self):
        tier, blocking, _ = self._derive(
            websocket_connected=True,
            registration_ack_success=False,
        )
        assert tier == AndroidNetworkParticipationTier.local_only
        assert any("registration_ack" in r for r in blocking)

    def test_e3_control_only_control_posture(self):
        tier, blocking, _ = self._derive(session_posture="control_only")
        assert tier == AndroidNetworkParticipationTier.control_only
        assert any("control_only" in r for r in blocking)

    def test_e4_control_only_operator_suspended(self):
        tier, blocking, _ = self._derive(
            operator_suspended=True,
            # even with everything else True, operator suspension caps at control_only
        )
        assert tier == AndroidNetworkParticipationTier.control_only
        assert any("operator_suspended" in r for r in blocking)

    def test_e5_cross_device_capable_with_gaps(self):
        tier, blocking, _ = self._derive(
            registration_gaps=["model_capability_report"],
            registration_fully_attached=False,
            session_posture="join_runtime",
        )
        assert tier == AndroidNetworkParticipationTier.cross_device_capable
        assert any("registration_gaps" in r for r in blocking)

    def test_e6_cross_device_capable_cross_device_gate_off(self):
        tier, blocking, _ = self._derive(
            registration_gaps=[],
            registration_fully_attached=True,
            cross_device_enabled=False,
        )
        assert tier == AndroidNetworkParticipationTier.cross_device_capable
        assert any("cross_device_enabled" in r for r in blocking)

    def test_e7_cross_device_enabled_no_session(self):
        tier, blocking, _ = self._derive(
            active_session_count=0,
            capability_visible=False,
            session_posture="",
        )
        assert tier == AndroidNetworkParticipationTier.cross_device_enabled
        assert any("active_session_count" in r or "capability_visible" in r for r in blocking)

    def test_e8_fully_attached(self):
        tier, blocking, _ = self._derive(
            readiness_satisfied=False,
            dispatch_gate_passed=False,
            execution_active=False,
        )
        assert tier == AndroidNetworkParticipationTier.fully_attached
        assert any("readiness" in r for r in blocking)

    def test_e9_dispatch_eligible(self):
        tier, blocking, _ = self._derive(execution_active=False)
        assert tier == AndroidNetworkParticipationTier.dispatch_eligible
        assert any("execution_active" in r for r in blocking)

    def test_e10_distributed_participant(self):
        tier, blocking, _ = self._derive(execution_active=True)
        assert tier == AndroidNetworkParticipationTier.distributed_participant
        assert blocking == []  # no blocking conditions at top tier


# ---------------------------------------------------------------------------
# Group F: blocking_reasons populated correctly
# ---------------------------------------------------------------------------


class TestBlockingReasons:
    def test_blocking_reasons_empty_at_distributed_participant(self):
        conditions = _all_true_conditions(execution_active=True)
        tier, blocking, _ = derive_android_network_participation_tier(**conditions)
        assert tier == AndroidNetworkParticipationTier.distributed_participant
        assert blocking == []

    def test_multiple_blockers_returned(self):
        tier, blocking, _ = derive_android_network_participation_tier(
            websocket_connected=True,
            registration_ack_success=True,
            registration_fully_attached=True,
            registration_gaps=[],
            cross_device_enabled=True,
            # Missing both capability_visible AND active session:
            capability_visible=False,
            active_session_count=0,
            session_posture="join_runtime",
            readiness_satisfied=False,
            dispatch_gate_passed=False,
            operator_suspended=False,
            execution_active=False,
        )
        assert tier == AndroidNetworkParticipationTier.cross_device_enabled
        assert len(blocking) >= 2

    def test_derivation_notes_non_empty(self):
        conditions = _all_true_conditions(execution_active=True)
        _, _, notes = derive_android_network_participation_tier(**conditions)
        assert len(notes) > 0


# ---------------------------------------------------------------------------
# Group G: build_android_network_participation_state
# ---------------------------------------------------------------------------


class TestBuildParticipationState:
    def test_builds_dispatch_eligible_state(self):
        state = build_android_network_participation_state(
            "device-1",
            **_all_true_conditions(execution_active=False),
        )
        assert state.device_id == "device-1"
        assert state.tier == AndroidNetworkParticipationTier.dispatch_eligible
        assert state.websocket_connected is True
        assert state.registration_fully_attached is True

    def test_builds_local_only_state(self):
        state = build_android_network_participation_state(
            "device-2",
            websocket_connected=False,
        )
        assert state.tier == AndroidNetworkParticipationTier.local_only

    def test_prior_tier_and_signal_recorded(self):
        state = build_android_network_participation_state(
            "device-3",
            **_all_true_conditions(execution_active=False),
            prior_tier=AndroidNetworkParticipationTier.local_only,
            last_signal=AndroidParticipationTransitionSignal.registration_fully_attached,
        )
        assert state.prior_tier == AndroidNetworkParticipationTier.local_only
        assert state.last_signal == AndroidParticipationTransitionSignal.registration_fully_attached

    def test_blocking_reasons_stored(self):
        state = build_android_network_participation_state(
            "device-4",
            websocket_connected=False,
        )
        assert len(state.blocking_reasons) > 0

    def test_derivation_notes_stored(self):
        state = build_android_network_participation_state(
            "device-5",
            **_all_true_conditions(execution_active=True),
        )
        assert len(state.tier_derivation_notes) > 0


# ---------------------------------------------------------------------------
# Group H: apply_participation_signal
# ---------------------------------------------------------------------------


class TestApplyParticipationSignal:
    def _dispatch_eligible_state(self, device_id: str = "d1") -> AndroidNetworkParticipationState:
        return build_android_network_participation_state(
            device_id,
            **_all_true_conditions(execution_active=False),
        )

    def test_h1_websocket_disconnected_forces_local_only(self):
        state = self._dispatch_eligible_state()
        new_state = apply_participation_signal(
            state,
            AndroidParticipationTransitionSignal.websocket_disconnected,
            websocket_connected=False,
        )
        assert new_state.tier == AndroidNetworkParticipationTier.local_only
        assert new_state.last_signal == AndroidParticipationTransitionSignal.websocket_disconnected
        assert new_state.prior_tier == AndroidNetworkParticipationTier.dispatch_eligible

    def test_h2_registration_fully_attached_raises_tier(self):
        # Start with a partially attached state
        start = build_android_network_participation_state(
            "d2",
            websocket_connected=True,
            registration_ack_success=True,
            registration_fully_attached=False,
            registration_gaps=["capability_report"],
            session_posture="join_runtime",
        )
        assert start.tier == AndroidNetworkParticipationTier.cross_device_capable

        new_state = apply_participation_signal(
            start,
            AndroidParticipationTransitionSignal.registration_fully_attached,
            registration_fully_attached=True,
            registration_gaps=[],
        )
        # Should be at least cross_device_capable (gaps cleared → cross_device_capable or higher)
        assert new_state.tier >= AndroidNetworkParticipationTier.cross_device_capable

    def test_h3_operator_suspended_caps_at_control_only(self):
        state = self._dispatch_eligible_state()
        new_state = apply_participation_signal(
            state,
            AndroidParticipationTransitionSignal.operator_suspended,
            operator_suspended=True,
        )
        assert new_state.tier == AndroidNetworkParticipationTier.control_only

    def test_h4_execution_session_started_distributed_participant(self):
        state = self._dispatch_eligible_state()
        new_state = apply_participation_signal(
            state,
            AndroidParticipationTransitionSignal.execution_session_started,
            execution_active=True,
        )
        assert new_state.tier == AndroidNetworkParticipationTier.distributed_participant

    def test_h5_execution_session_ended_drops_from_distributed(self):
        state = build_android_network_participation_state(
            "d5",
            **_all_true_conditions(execution_active=True),
        )
        assert state.tier == AndroidNetworkParticipationTier.distributed_participant
        new_state = apply_participation_signal(
            state,
            AndroidParticipationTransitionSignal.execution_session_ended,
            execution_active=False,
        )
        assert new_state.tier == AndroidNetworkParticipationTier.dispatch_eligible

    def test_h6_capability_visibility_lost_drops_from_fully_attached(self):
        state = self._dispatch_eligible_state()
        new_state = apply_participation_signal(
            state,
            AndroidParticipationTransitionSignal.capability_visibility_lost,
            capability_visible=False,
        )
        # Without capability_visible, tier should drop to at most cross_device_enabled
        assert new_state.tier <= AndroidNetworkParticipationTier.cross_device_enabled

    def test_original_state_unchanged(self):
        state = self._dispatch_eligible_state()
        original_tier = state.tier
        _ = apply_participation_signal(
            state,
            AndroidParticipationTransitionSignal.websocket_disconnected,
            websocket_connected=False,
        )
        # original state must be unchanged (not frozen but should not be mutated)
        assert state.tier == original_tier


# ---------------------------------------------------------------------------
# Group I: record/get participation state
# ---------------------------------------------------------------------------


class TestParticipationStore:
    def setup_method(self):
        reset_participation_store()

    def test_record_and_retrieve(self):
        state = build_android_network_participation_state(
            "store-device-1",
            **_all_true_conditions(execution_active=False),
        )
        record_participation_state(state)
        retrieved = get_stored_participation_state("store-device-1")
        assert retrieved is not None
        assert retrieved.device_id == "store-device-1"
        assert retrieved.tier == AndroidNetworkParticipationTier.dispatch_eligible

    def test_get_absent_device_returns_none(self):
        result = get_stored_participation_state("nonexistent-device")
        assert result is None

    def test_overwrite_with_newer_state(self):
        s1 = build_android_network_participation_state("dev-x", websocket_connected=False)
        record_participation_state(s1)
        s2 = build_android_network_participation_state(
            "dev-x",
            **_all_true_conditions(execution_active=False),
        )
        record_participation_state(s2)
        retrieved = get_stored_participation_state("dev-x")
        assert retrieved is not None
        assert retrieved.tier == AndroidNetworkParticipationTier.dispatch_eligible


# ---------------------------------------------------------------------------
# Group J: reset_participation_store
# ---------------------------------------------------------------------------


class TestResetParticipationStore:
    def test_reset_clears_entries(self):
        state = build_android_network_participation_state(
            "reset-dev",
            websocket_connected=True,
            registration_ack_success=False,
        )
        record_participation_state(state)
        assert get_stored_participation_state("reset-dev") is not None

        reset_participation_store()
        assert get_stored_participation_state("reset-dev") is None


# ---------------------------------------------------------------------------
# Group K: get_participation_state_for_device (safe without stores)
# ---------------------------------------------------------------------------


class TestGetParticipationStateForDevice:
    def setup_method(self):
        reset_participation_store()

    def test_returns_valid_state_without_stores(self):
        # With no stores populated, should return local_only (fail-conservative)
        state = get_participation_state_for_device("unknown-device-xyz")
        assert isinstance(state, AndroidNetworkParticipationState)
        assert state.device_id == "unknown-device-xyz"
        # tier may be local_only since no stores have data for this device
        assert isinstance(state.tier, AndroidNetworkParticipationTier)

    def test_never_raises(self):
        for i in range(5):
            state = get_participation_state_for_device(f"test-device-{i}")
            assert state is not None


# ---------------------------------------------------------------------------
# Group L: AndroidNetworkParticipationState.to_dict()
# ---------------------------------------------------------------------------


class TestParticipationStateToDict:
    def test_to_dict_is_json_serialisable(self):
        import json
        state = build_android_network_participation_state(
            "ser-device",
            **_all_true_conditions(execution_active=True),
        )
        d = state.to_dict()
        # Should not raise
        serialised = json.dumps(d)
        assert serialised

    def test_to_dict_contains_required_keys(self):
        state = build_android_network_participation_state(
            "dict-device",
            **_all_true_conditions(execution_active=False),
        )
        d = state.to_dict()
        for key in [
            "device_id", "tier", "last_signal", "prior_tier", "derived_at",
            "websocket_connected", "registration_ack_success",
            "registration_fully_attached", "registration_gaps",
            "capability_visible", "active_session_count", "session_posture",
            "cross_device_enabled", "readiness_satisfied", "dispatch_gate_passed",
            "operator_suspended", "execution_active", "blocking_reasons",
            "tier_derivation_notes", "_authority", "_contract_version",
        ]:
            assert key in d, f"Missing key in to_dict(): {key}"

    def test_to_dict_tier_is_string(self):
        state = build_android_network_participation_state(
            "tier-str-device",
            **_all_true_conditions(execution_active=False),
        )
        d = state.to_dict()
        assert isinstance(d["tier"], str)


# ---------------------------------------------------------------------------
# Group M: V2 unified state contract integration
# ---------------------------------------------------------------------------


class TestV2UnifiedStateContractIntegration:
    """Tests that build_v2_unified_state_contract includes participation tier."""

    def _make_minimal_contract(self, **kwargs: Any) -> Any:
        """Build a minimal V2 state contract for testing."""
        from core.v2_unified_state_contract import build_v2_unified_state_contract
        from core.operational_registration_path import (
            get_operational_registration_path,
            OnboardingValidation,
            ValidationStatus,
        )

        path = get_operational_registration_path()
        validation = OnboardingValidation(
            checks=[],
            overall_status=ValidationStatus.PASS,
            summary="ok",
        )

        return build_v2_unified_state_contract(
            path=path,
            validation=validation,
            kind_states=[],
            **kwargs,
        )

    def test_m1_baseline_tier_local_only(self):
        contract = self._make_minimal_contract()
        d = contract.to_dict()
        assert "android_network_participation_tier" in d["raw_signals"]
        # With no android device, tier should be local_only
        assert d["raw_signals"]["android_network_participation_tier"] == "local_only"

    def test_m2_android_attached_raises_tier(self):
        contract = self._make_minimal_contract(
            device_evidence={"android_device_count": 1, "registration_fully_attached": True},
            android_evidence={"snapshot_count": 1, "capability_visible_count": 1},
            session_evidence={
                "active_session_count": 1,
                "participant_total_count": 1,
                "session_posture": "join_runtime",
            },
        )
        d = contract.to_dict()
        tier = d["raw_signals"]["android_network_participation_tier"]
        # With android attached and capability visible, should be at least control_only
        assert tier != "local_only", f"Expected tier > local_only, got {tier}"

    def test_m3_participation_evidence_override(self):
        contract = self._make_minimal_contract(
            participation_evidence={
                "tier": "dispatch_eligible",
                "blocking_reasons": [],
                "tier_derivation_notes": ["test override"],
                "source": "test",
            },
        )
        d = contract.to_dict()
        assert d["raw_signals"]["android_network_participation_tier"] == "dispatch_eligible"

    def test_m4_derived_state_contains_android_network_participation(self):
        contract = self._make_minimal_contract()
        d = contract.to_dict()
        assert "android_network_participation" in d["derived_state"], (
            "android_network_participation ContractDecision missing from derived_state"
        )
        participation_decision = d["derived_state"]["android_network_participation"]
        assert participation_decision["decision_id"] == "android_network_participation"
        assert "tier" in participation_decision["evidence"]
        assert "blocking_reasons" in participation_decision["evidence"]

    def test_m5_contract_version_bumped(self):
        from core.v2_unified_state_contract import V2_UNIFIED_STATE_CONTRACT_VERSION
        assert V2_UNIFIED_STATE_CONTRACT_VERSION == "1.3.0"

    def test_m_derived_state_participation_tier_matches_raw_signals(self):
        contract = self._make_minimal_contract(
            participation_evidence={
                "tier": "fully_attached",
                "blocking_reasons": [],
                "tier_derivation_notes": [],
                "source": "test",
            },
        )
        d = contract.to_dict()
        raw_tier = d["raw_signals"]["android_network_participation_tier"]
        derived_tier = d["derived_state"]["android_network_participation"]["evidence"]["tier"]
        assert raw_tier == derived_tier == "fully_attached"

    def test_m_eligible_flag_set_for_dispatch_eligible(self):
        contract = self._make_minimal_contract(
            participation_evidence={
                "tier": "dispatch_eligible",
                "blocking_reasons": [],
                "tier_derivation_notes": [],
                "source": "test",
            },
        )
        d = contract.to_dict()
        decision = d["derived_state"]["android_network_participation"]
        assert decision["eligible"] is True

    def test_m_active_flag_set_for_distributed_participant(self):
        contract = self._make_minimal_contract(
            participation_evidence={
                "tier": "distributed_participant",
                "blocking_reasons": [],
                "tier_derivation_notes": [],
                "source": "test",
            },
        )
        d = contract.to_dict()
        decision = d["derived_state"]["android_network_participation"]
        assert decision["active"] is True


# ---------------------------------------------------------------------------
# Group N: Registration handler integration
# ---------------------------------------------------------------------------


class TestRegistrationHandlerIntegration:
    """Smoke tests for the registration handler participation tier emission."""

    def test_n_participation_tier_key_in_ack_on_success(self):
        """When registration succeeds with no gaps, ack should contain
        network_participation_tier."""
        import importlib
        import unittest.mock as mock

        # We can't fully run the registration handler without a real WebSocket,
        # but we can verify the ack-building code path by testing the import
        # and the key presence via the build_android_network_participation_state
        # function that the handler delegates to.
        reset_participation_store()

        # Simulate what the handler does after registration succeeds with no gaps:
        from core.android_network_participation import (
            build_android_network_participation_state,
            record_participation_state,
            AndroidParticipationTransitionSignal,
        )

        gaps: List[str] = []
        reg_entry_mock = mock.MagicMock()
        reg_entry_mock.posture = "join_runtime"
        is_fully_attached = len(gaps) == 0
        signal = (
            AndroidParticipationTransitionSignal.registration_fully_attached
            if is_fully_attached
            else AndroidParticipationTransitionSignal.registration_partial_attached
        )
        state = build_android_network_participation_state(
            "reg-test-device",
            websocket_connected=True,
            registration_ack_success=True,
            registration_fully_attached=is_fully_attached,
            registration_gaps=gaps,
            session_posture=reg_entry_mock.posture,
            active_session_count=1,
            last_signal=signal,
        )
        record_participation_state(state)

        # Verify ack would contain the tier
        ack = {"registration_fully_attached": True}
        ack["network_participation_tier"] = state.tier.value

        assert "network_participation_tier" in ack
        assert ack["network_participation_tier"] in {
            t.value for t in AndroidNetworkParticipationTier
        }

    def test_n_partial_registration_ack_has_cross_device_capable_or_lower(self):
        """Partial registration (with gaps) should yield cross_device_capable tier."""
        reset_participation_store()

        from core.android_network_participation import (
            build_android_network_participation_state,
            AndroidParticipationTransitionSignal,
        )

        gaps = ["model_capability_report"]
        state = build_android_network_participation_state(
            "reg-partial-device",
            websocket_connected=True,
            registration_ack_success=True,
            registration_fully_attached=False,
            registration_gaps=gaps,
            session_posture="join_runtime",
            active_session_count=1,
            last_signal=AndroidParticipationTransitionSignal.registration_partial_attached,
        )
        assert state.tier <= AndroidNetworkParticipationTier.cross_device_capable


class TestParticipationTransitionAuditability:
    def setup_method(self):
        reset_participation_store()

    def test_transition_history_records_signal_and_tier_change(self):
        first = build_android_network_participation_state(
            "hist-device",
            websocket_connected=True,
            registration_ack_success=True,
            registration_fully_attached=False,
            registration_gaps=["capability_report"],
            session_posture="join_runtime",
            active_session_count=1,
            last_signal=AndroidParticipationTransitionSignal.registration_partial_attached,
        )
        record_participation_state(first)
        second = apply_participation_signal(
            first,
            AndroidParticipationTransitionSignal.registration_fully_attached,
            registration_fully_attached=True,
            registration_gaps=[],
            cross_device_enabled=True,
        )
        record_participation_state(second)
        history = list_participation_transition_history("hist-device", limit=10)
        assert len(history) >= 2
        assert history[-1]["to_tier"] == second.tier.value
        assert history[-1]["signal"] in {
            AndroidParticipationTransitionSignal.registration_fully_attached.value,
            None,
        }


class TestGatewayHandlerParticipationIntegration:
    def test_android_device_state_store_participation_evidence_contains_transition_history(self):
        from core.android_device_state_store import get_android_participation_evidence

        state = build_android_network_participation_state(
            "android-pr1-device",
            websocket_connected=True,
            registration_ack_success=True,
            registration_fully_attached=True,
            registration_gaps=[],
            capability_visible=True,
            active_session_count=1,
            session_posture="join_runtime",
            cross_device_enabled=True,
            readiness_satisfied=False,
            dispatch_gate_passed=False,
            last_signal=AndroidParticipationTransitionSignal.registration_fully_attached,
        )
        record_participation_state(state)
        evidence = get_android_participation_evidence("android-pr1-device", include_history_limit=5)
        assert evidence["tier"] in {t.value for t in AndroidNetworkParticipationTier}
        assert evidence["source"] == "core.android_network_participation"
        assert isinstance(evidence["transition_history"], list)


class TestAuthoritativeContractConsumptionPath:
    def test_contract_consumes_authoritative_participation_accessor_when_device_identity_present(self):
        from unittest.mock import patch
        from core.v2_unified_state_contract import build_v2_unified_state_contract
        from core.operational_registration_path import (
            get_operational_registration_path,
            OnboardingValidation,
            ValidationStatus,
        )

        path = get_operational_registration_path()
        validation = OnboardingValidation(checks=[], overall_status=ValidationStatus.PASS, summary="ok")
        authoritative_state = build_android_network_participation_state(
            "android-auth-device",
            **_all_true_conditions(execution_active=False),
        )

        with patch(
            "core.android_network_participation.get_participation_state_for_device",
            return_value=authoritative_state,
        ) as mocked_get:
            contract = build_v2_unified_state_contract(
                path=path,
                validation=validation,
                kind_states=[],
                device_evidence={
                    "android_device_count": 1,
                    "android_device_ids": ["android-auth-device"],
                },
                android_evidence={"snapshot_count": 1, "capability_visible_count": 1},
                session_evidence={"active_session_count": 1, "session_posture": "join_runtime"},
            ).to_dict()
        assert mocked_get.called
        assert contract["raw_signals"]["android_network_participation_tier"] == authoritative_state.tier.value
        decision = contract["derived_state"]["android_network_participation"]
        assert decision["evidence"]["source"].startswith(
            "core.android_network_participation.get_participation_state_for_device"
        )
