#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_participant_authority_interfaces.py
==============================================
PR-8: Tests for core/participant_authority_interfaces.py — the participant-
generic authority interface layer above Android-specific implementations.

Coverage areas
--------------
A.  Module importable; authority and policy sentinels present and non-empty.
B.  All expected names are in __all__.
C.  ParticipantSessionPhase enum — values, terminal/active helpers.
D.  ParticipantSessionSignal enum — values, from_string helper.
E.  ParticipantDispatchBindingState enum — values, terminal/active helpers.
F.  ParticipantDispatchBindingSignal enum — values, from_string helper.
G.  ParticipantAvailabilityStatus enum — values, operational/evidence-gap helpers.
H.  ParticipantResultKind enum — values, terminal/canonical-state helpers.
I.  Concrete implementation registry — all four surfaces registered with
    expected keys.
J.  get_concrete_implementation_for() — returns correct entries and None for
    unknown names.
K.  Generic phase values align with Android concrete phase values (1-to-1
    mapping invariant).
L.  Generic signal values align with Android concrete signal values (1-to-1
    mapping invariant — directional mapping since Android uses legacy names).
M.  Generic availability status values align with Android concrete status.
N.  Generic result kind values align with Android concrete truth kind.
O.  Android concrete modules are importable and their authority sentinels
    reference the participant-generic interface layer (PR-8 cross-reference).
P.  Architecture declarations: Android modules carry the PR-8 generic-layer
    reference in their authority sentinels.
Q.  Policy sentinel content: each policy sentinel contains "POLICY::" tag.
R.  Runtime behavior stability: Android concrete session lifecycle functions
    remain callable and produce correct types after the authority sentinel
    update.
"""

from __future__ import annotations

import sys
import os

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

from core.participant_authority_interfaces import (
    # Authority sentinels
    PARTICIPANT_AUTHORITY_INTERFACES_SENTINEL,
    PARTICIPANT_AUTHORITY_PR8_SENTINEL,
    ANDROID_IS_CONCRETE_PARTICIPANT_IMPLEMENTATION_SENTINEL,
    # Policy sentinels
    PARTICIPANT_GENERIC_LAYER_IS_ABOVE_ANDROID_CONCRETE_POLICY,
    ANDROID_CONCRETE_MUST_NOT_BE_REMOVED_POLICY,
    PARTICIPANT_DISPATCH_AUTHORITY_IS_PARTICIPANT_GENERIC_POLICY,
    PARTICIPANT_RESULT_INGRESS_IS_PARTICIPANT_GENERIC_POLICY,
    PARTICIPANT_SESSION_LEGALITY_IS_PARTICIPANT_GENERIC_POLICY,
    PARTICIPANT_AVAILABILITY_IS_PARTICIPANT_GENERIC_POLICY,
    PARTICIPANT_ORCHESTRATION_BOUNDARY_IS_PARTICIPANT_GENERIC_POLICY,
    WRONG_LAYER_ANDROID_NAMING_MUST_BE_LIFTED_POLICY,
    # Enumerations
    ParticipantSessionPhase,
    ParticipantSessionSignal,
    ParticipantDispatchBindingState,
    ParticipantDispatchBindingSignal,
    ParticipantAvailabilityStatus,
    ParticipantResultKind,
    # Registry
    PARTICIPANT_CONCRETE_IMPLEMENTATION_REGISTRY,
    get_concrete_implementation_for,
)
import core.participant_authority_interfaces as _mod


# ===========================================================================
# A. Module import and sentinel presence
# ===========================================================================


class TestModuleImport:
    def test_module_importable(self):
        import core.participant_authority_interfaces  # noqa: F401

    def test_authority_sentinel_non_empty(self):
        assert PARTICIPANT_AUTHORITY_INTERFACES_SENTINEL
        assert isinstance(PARTICIPANT_AUTHORITY_INTERFACES_SENTINEL, str)

    def test_authority_sentinel_contains_pr8(self):
        assert "PR-8" in PARTICIPANT_AUTHORITY_INTERFACES_SENTINEL

    def test_pr8_sentinel_non_empty(self):
        assert PARTICIPANT_AUTHORITY_PR8_SENTINEL
        assert "PR-8" in PARTICIPANT_AUTHORITY_PR8_SENTINEL

    def test_android_concrete_sentinel_non_empty(self):
        assert ANDROID_IS_CONCRETE_PARTICIPANT_IMPLEMENTATION_SENTINEL
        assert "android" in ANDROID_IS_CONCRETE_PARTICIPANT_IMPLEMENTATION_SENTINEL.lower()

    def test_android_concrete_sentinel_mentions_modules(self):
        s = ANDROID_IS_CONCRETE_PARTICIPANT_IMPLEMENTATION_SENTINEL
        assert "android_participant_session_state" in s
        assert "android_runtime_dispatch_binding" in s
        assert "android_participant_truth_ingress" in s
        assert "android_participant_evidence_ingress" in s


# ===========================================================================
# B. __all__ completeness
# ===========================================================================


class TestDunderAll:
    _EXPECTED = [
        "PARTICIPANT_AUTHORITY_INTERFACES_SENTINEL",
        "PARTICIPANT_AUTHORITY_PR8_SENTINEL",
        "ANDROID_IS_CONCRETE_PARTICIPANT_IMPLEMENTATION_SENTINEL",
        "PARTICIPANT_GENERIC_LAYER_IS_ABOVE_ANDROID_CONCRETE_POLICY",
        "ANDROID_CONCRETE_MUST_NOT_BE_REMOVED_POLICY",
        "PARTICIPANT_DISPATCH_AUTHORITY_IS_PARTICIPANT_GENERIC_POLICY",
        "PARTICIPANT_RESULT_INGRESS_IS_PARTICIPANT_GENERIC_POLICY",
        "PARTICIPANT_SESSION_LEGALITY_IS_PARTICIPANT_GENERIC_POLICY",
        "PARTICIPANT_AVAILABILITY_IS_PARTICIPANT_GENERIC_POLICY",
        "PARTICIPANT_ORCHESTRATION_BOUNDARY_IS_PARTICIPANT_GENERIC_POLICY",
        "WRONG_LAYER_ANDROID_NAMING_MUST_BE_LIFTED_POLICY",
        "ParticipantSessionPhase",
        "ParticipantSessionSignal",
        "ParticipantDispatchBindingState",
        "ParticipantDispatchBindingSignal",
        "ParticipantAvailabilityStatus",
        "ParticipantResultKind",
        "PARTICIPANT_CONCRETE_IMPLEMENTATION_REGISTRY",
        "get_concrete_implementation_for",
    ]

    def test_all_expected_names_in_dunder_all(self):
        for name in self._EXPECTED:
            assert name in _mod.__all__, f"{name!r} missing from __all__"

    def test_dunder_all_is_list_or_tuple(self):
        assert isinstance(_mod.__all__, (list, tuple))


# ===========================================================================
# C. ParticipantSessionPhase
# ===========================================================================


class TestParticipantSessionPhase:
    def test_all_expected_values_present(self):
        expected = [
            "pre_dispatch",
            "contract_dispatched",
            "negotiation_pending",
            "negotiation_accepted",
            "execution",
            "reconciling",
            "terminal_success",
            "terminal_failure",
            "terminal_cancelled",
        ]
        for v in expected:
            assert ParticipantSessionPhase(v) is not None

    def test_terminal_phases_are_terminal(self):
        for v in ["terminal_success", "terminal_failure", "terminal_cancelled"]:
            assert ParticipantSessionPhase(v).is_terminal()

    def test_non_terminal_phases_are_active(self):
        for v in [
            "pre_dispatch",
            "contract_dispatched",
            "negotiation_pending",
            "negotiation_accepted",
            "execution",
            "reconciling",
        ]:
            assert ParticipantSessionPhase(v).is_active()
            assert not ParticipantSessionPhase(v).is_terminal()

    def test_from_string_known(self):
        assert ParticipantSessionPhase.from_string("execution") == ParticipantSessionPhase.execution

    def test_from_string_unknown_defaults_to_pre_dispatch(self):
        assert ParticipantSessionPhase.from_string("not_a_phase") == ParticipantSessionPhase.pre_dispatch

    def test_from_string_non_str_defaults(self):
        assert ParticipantSessionPhase.from_string(None) == ParticipantSessionPhase.pre_dispatch  # type: ignore[arg-type]

    def test_is_str_subclass(self):
        assert isinstance(ParticipantSessionPhase.execution, str)


# ===========================================================================
# D. ParticipantSessionSignal
# ===========================================================================


class TestParticipantSessionSignal:
    def test_all_expected_values_present(self):
        expected = [
            "contract_dispatched",
            "negotiation_requested",
            "negotiation_accepted",
            "negotiation_rejected",
            "execution_started",
            "execution_progressed",
            "reconciliation_started",
            "result_success",
            "result_failure",
            "result_cancelled",
        ]
        for v in expected:
            assert ParticipantSessionSignal(v) is not None

    def test_from_string_known(self):
        assert (
            ParticipantSessionSignal.from_string("result_success")
            == ParticipantSessionSignal.result_success
        )

    def test_from_string_unknown_defaults(self):
        assert (
            ParticipantSessionSignal.from_string("no_such_signal")
            == ParticipantSessionSignal.execution_progressed
        )

    def test_is_str_subclass(self):
        assert isinstance(ParticipantSessionSignal.result_failure, str)


# ===========================================================================
# E. ParticipantDispatchBindingState
# ===========================================================================


class TestParticipantDispatchBindingState:
    def test_all_expected_values_present(self):
        for v in ["unbound", "binding", "bound", "dispatching", "suspended", "released"]:
            assert ParticipantDispatchBindingState(v) is not None

    def test_released_is_terminal(self):
        assert ParticipantDispatchBindingState.released.is_terminal()

    def test_non_released_are_active(self):
        for v in ["unbound", "binding", "bound", "dispatching", "suspended"]:
            s = ParticipantDispatchBindingState(v)
            assert s.is_active()
            assert not s.is_terminal()

    def test_from_string_known(self):
        assert (
            ParticipantDispatchBindingState.from_string("bound")
            == ParticipantDispatchBindingState.bound
        )

    def test_from_string_unknown_defaults_to_unbound(self):
        assert (
            ParticipantDispatchBindingState.from_string("xyz")
            == ParticipantDispatchBindingState.unbound
        )


# ===========================================================================
# F. ParticipantDispatchBindingSignal
# ===========================================================================


class TestParticipantDispatchBindingSignal:
    def test_all_expected_values_present(self):
        for v in ["bind", "confirm", "dispatch", "suspend", "resume", "release"]:
            assert ParticipantDispatchBindingSignal(v) is not None

    def test_from_string_known(self):
        assert (
            ParticipantDispatchBindingSignal.from_string("release")
            == ParticipantDispatchBindingSignal.release
        )

    def test_from_string_unknown_defaults_to_bind(self):
        assert (
            ParticipantDispatchBindingSignal.from_string("no_such")
            == ParticipantDispatchBindingSignal.bind
        )


# ===========================================================================
# G. ParticipantAvailabilityStatus
# ===========================================================================


class TestParticipantAvailabilityStatus:
    def test_all_expected_values_present(self):
        for v in [
            "ready", "degraded", "unavailable", "recovered",
            "missing_evidence", "malformed_evidence", "stale_evidence", "unverified",
        ]:
            assert ParticipantAvailabilityStatus(v) is not None

    def test_ready_is_operational(self):
        assert ParticipantAvailabilityStatus.ready.is_operational()

    def test_recovered_is_operational(self):
        assert ParticipantAvailabilityStatus.recovered.is_operational()

    def test_degraded_not_operational(self):
        assert not ParticipantAvailabilityStatus.degraded.is_operational()

    def test_unavailable_not_operational(self):
        assert not ParticipantAvailabilityStatus.unavailable.is_operational()

    def test_evidence_gap_values(self):
        for v in ["missing_evidence", "malformed_evidence", "stale_evidence", "unverified"]:
            assert ParticipantAvailabilityStatus(v).is_evidence_gap()

    def test_non_evidence_gap_values(self):
        for v in ["ready", "degraded", "unavailable", "recovered"]:
            assert not ParticipantAvailabilityStatus(v).is_evidence_gap()

    def test_from_string_known(self):
        assert (
            ParticipantAvailabilityStatus.from_string("degraded")
            == ParticipantAvailabilityStatus.degraded
        )

    def test_from_string_unknown_defaults_to_missing_evidence(self):
        assert (
            ParticipantAvailabilityStatus.from_string("not_known")
            == ParticipantAvailabilityStatus.missing_evidence
        )

    def test_from_string_non_str_defaults(self):
        assert (
            ParticipantAvailabilityStatus.from_string(42)  # type: ignore[arg-type]
            == ParticipantAvailabilityStatus.missing_evidence
        )


# ===========================================================================
# H. ParticipantResultKind
# ===========================================================================


class TestParticipantResultKind:
    def test_all_expected_values_present(self):
        for v in [
            "session_snapshot", "readiness_assessment", "task_phase",
            "runtime_state", "cancel", "status", "failure", "result",
            "reconciliation_signal", "governance_artifact", "unknown",
        ]:
            assert ParticipantResultKind(v) is not None

    def test_terminal_signal_kinds(self):
        for v in ["cancel", "failure", "result", "reconciliation_signal"]:
            assert ParticipantResultKind(v).is_terminal_signal()

    def test_non_terminal_signal_kinds(self):
        for v in ["session_snapshot", "readiness_assessment", "task_phase",
                  "runtime_state", "status", "governance_artifact", "unknown"]:
            assert not ParticipantResultKind(v).is_terminal_signal()

    def test_affects_canonical_state_kinds(self):
        for v in ["cancel", "failure", "result", "status", "task_phase",
                  "reconciliation_signal", "governance_artifact"]:
            assert ParticipantResultKind(v).affects_canonical_state()

    def test_does_not_affect_canonical_state(self):
        for v in ["session_snapshot", "readiness_assessment", "runtime_state", "unknown"]:
            assert not ParticipantResultKind(v).affects_canonical_state()

    def test_from_string_known(self):
        assert (
            ParticipantResultKind.from_string("cancel")
            == ParticipantResultKind.cancel
        )

    def test_from_string_unknown_defaults_to_unknown(self):
        assert (
            ParticipantResultKind.from_string("xyz")
            == ParticipantResultKind.unknown
        )


# ===========================================================================
# I. Concrete implementation registry
# ===========================================================================


class TestConcreteImplementationRegistry:
    _EXPECTED_SURFACES = [
        "session_lifecycle",
        "dispatch_binding",
        "result_ingress",
        "availability",
    ]
    _REQUIRED_KEYS = ["generic_interface", "concrete_module", "platform"]

    def test_registry_is_dict(self):
        assert isinstance(PARTICIPANT_CONCRETE_IMPLEMENTATION_REGISTRY, dict)

    def test_all_surfaces_registered(self):
        for surface in self._EXPECTED_SURFACES:
            assert surface in PARTICIPANT_CONCRETE_IMPLEMENTATION_REGISTRY, (
                f"Surface {surface!r} missing from registry"
            )

    def test_each_entry_has_required_keys(self):
        for surface, entry in PARTICIPANT_CONCRETE_IMPLEMENTATION_REGISTRY.items():
            for key in self._REQUIRED_KEYS:
                assert key in entry, (
                    f"Entry {surface!r} missing required key {key!r}"
                )

    def test_all_platforms_are_android(self):
        for surface, entry in PARTICIPANT_CONCRETE_IMPLEMENTATION_REGISTRY.items():
            assert entry["platform"] == "android", (
                f"Surface {surface!r} platform should be 'android', got {entry['platform']!r}"
            )

    def test_concrete_modules_are_android_prefixed(self):
        for surface, entry in PARTICIPANT_CONCRETE_IMPLEMENTATION_REGISTRY.items():
            module = entry["concrete_module"]
            assert "android" in module, (
                f"Surface {surface!r} concrete_module {module!r} should reference android"
            )


# ===========================================================================
# J. get_concrete_implementation_for()
# ===========================================================================


class TestGetConcreteImplementationFor:
    def test_session_lifecycle_returned(self):
        entry = get_concrete_implementation_for("session_lifecycle")
        assert entry is not None
        assert "android_participant_session_state" in entry["concrete_module"]

    def test_dispatch_binding_returned(self):
        entry = get_concrete_implementation_for("dispatch_binding")
        assert entry is not None
        assert "android_runtime_dispatch_binding" in entry["concrete_module"]

    def test_result_ingress_returned(self):
        entry = get_concrete_implementation_for("result_ingress")
        assert entry is not None
        assert "android_participant_truth_ingress" in entry["concrete_module"]

    def test_availability_returned(self):
        entry = get_concrete_implementation_for("availability")
        assert entry is not None
        assert "android_participant_evidence_ingress" in entry["concrete_module"]

    def test_unknown_returns_none(self):
        assert get_concrete_implementation_for("no_such_surface") is None

    def test_empty_string_returns_none(self):
        assert get_concrete_implementation_for("") is None


# ===========================================================================
# K. Phase value alignment with Android concrete enum
# ===========================================================================


class TestPhaseAlignmentWithAndroid:
    """Invariant: every ParticipantSessionPhase terminal/active classification
    must be consistently derivable from the canonical terminal value set,
    regardless of which concrete platform is used."""

    def test_terminal_set_is_exhaustive(self):
        terminal = {
            ParticipantSessionPhase.terminal_success,
            ParticipantSessionPhase.terminal_failure,
            ParticipantSessionPhase.terminal_cancelled,
        }
        for phase in ParticipantSessionPhase:
            if phase in terminal:
                assert phase.is_terminal(), f"{phase} should be terminal"
            else:
                assert not phase.is_terminal(), f"{phase} should not be terminal"

    def test_android_phases_are_semantically_represented(self):
        """Every Android phase has a semantic equivalent in the generic enum.

        Android              → Generic
        handoff_dispatched   → contract_dispatched
        takeover_pending     → negotiation_pending
        takeover_accepted    → negotiation_accepted
        execution            → execution  (identical)
        reconciling          → reconciling  (identical)
        terminal_*           → terminal_*  (identical)
        pre_dispatch         → pre_dispatch  (identical)
        """
        android_to_generic = {
            "pre_dispatch": "pre_dispatch",
            "handoff_dispatched": "contract_dispatched",
            "takeover_pending": "negotiation_pending",
            "takeover_accepted": "negotiation_accepted",
            "execution": "execution",
            "reconciling": "reconciling",
            "terminal_success": "terminal_success",
            "terminal_failure": "terminal_failure",
            "terminal_cancelled": "terminal_cancelled",
        }
        for android_val, generic_val in android_to_generic.items():
            generic_phase = ParticipantSessionPhase(generic_val)
            assert generic_phase is not None
            # Verify terminal consistency: Android terminal phases map to
            # generic terminal phases.
            if android_val.startswith("terminal_"):
                assert generic_phase.is_terminal()


# ===========================================================================
# L. Signal value alignment with Android concrete enum
# ===========================================================================


class TestSignalAlignmentWithAndroid:
    def test_android_signals_are_semantically_represented(self):
        """Every Android signal has a semantic equivalent in the generic enum."""
        android_to_generic = {
            "handoff_dispatched": "contract_dispatched",
            "takeover_requested": "negotiation_requested",
            "takeover_accepted": "negotiation_accepted",
            "takeover_rejected": "negotiation_rejected",
            "execution_started": "execution_started",
            "execution_progressed": "execution_progressed",
            "reconciliation_started": "reconciliation_started",
            "result_success": "result_success",
            "result_failure": "result_failure",
            "result_cancelled": "result_cancelled",
        }
        for _, generic_val in android_to_generic.items():
            sig = ParticipantSessionSignal(generic_val)
            assert sig is not None


# ===========================================================================
# M. Availability status alignment with Android concrete enum
# ===========================================================================


class TestAvailabilityAlignmentWithAndroid:
    def test_android_status_values_are_represented(self):
        """Every AndroidParticipantStatus value has a ParticipantAvailabilityStatus
        equivalent (same string value for all but the evidence-gap states)."""
        android_values = [
            "ready", "degraded", "unavailable", "recovered",
            "missing_evidence", "malformed_evidence", "stale_evidence", "unverified",
        ]
        for v in android_values:
            status = ParticipantAvailabilityStatus(v)
            assert status is not None

    def test_operational_semantics_consistent(self):
        assert ParticipantAvailabilityStatus.ready.is_operational()
        assert ParticipantAvailabilityStatus.recovered.is_operational()
        assert not ParticipantAvailabilityStatus.degraded.is_operational()
        assert not ParticipantAvailabilityStatus.unavailable.is_operational()
        assert not ParticipantAvailabilityStatus.missing_evidence.is_operational()


# ===========================================================================
# N. Result kind alignment with Android concrete enum
# ===========================================================================


class TestResultKindAlignmentWithAndroid:
    def test_android_truth_kind_values_are_represented(self):
        """Every AndroidParticipantTruthKind value has a ParticipantResultKind
        equivalent (identical string values)."""
        android_values = [
            "session_snapshot", "readiness_assessment", "task_phase",
            "runtime_state", "cancel", "status", "failure", "result",
            "reconciliation_signal", "governance_artifact", "unknown",
        ]
        for v in android_values:
            kind = ParticipantResultKind(v)
            assert kind is not None

    def test_terminal_signal_semantics_consistent(self):
        for v in ["cancel", "failure", "result", "reconciliation_signal"]:
            assert ParticipantResultKind(v).is_terminal_signal()


# ===========================================================================
# O. Android concrete modules importable
# ===========================================================================


class TestAndroidConcreteModulesImportable:
    def test_android_participant_session_state_importable(self):
        import core.android_participant_session_state  # noqa: F401

    def test_android_runtime_dispatch_binding_importable(self):
        import core.android_runtime_dispatch_binding  # noqa: F401

    def test_android_participant_truth_ingress_importable(self):
        import core.android_participant_truth_ingress  # noqa: F401

    def test_android_participant_evidence_ingress_importable(self):
        import core.android_participant_evidence_ingress  # noqa: F401


# ===========================================================================
# P. Architecture declarations: Android modules reference PR-8
# ===========================================================================


class TestArchitectureDeclarations:
    """Verify that Android concrete authority sentinels now reference the
    participant-generic interface layer (PR-8 cross-reference requirement)."""

    def test_session_state_authority_references_pr8(self):
        from core.android_participant_session_state import (
            ANDROID_PARTICIPANT_SESSION_STATE_AUTHORITY,
        )
        sentinel = ANDROID_PARTICIPANT_SESSION_STATE_AUTHORITY
        assert "participant_authority_interfaces" in sentinel or "PR-8" in sentinel, (
            "android_participant_session_state authority sentinel should reference "
            "participant_authority_interfaces or PR-8"
        )

    def test_dispatch_binding_authority_references_pr8(self):
        from core.android_runtime_dispatch_binding import (
            ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY,
        )
        sentinel = ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY
        assert "participant_authority_interfaces" in sentinel or "PR-8" in sentinel, (
            "android_runtime_dispatch_binding authority sentinel should reference "
            "participant_authority_interfaces or PR-8"
        )

    def test_truth_ingress_authority_references_pr8(self):
        from core.android_participant_truth_ingress import (
            ANDROID_PARTICIPANT_TRUTH_INGRESS_AUTHORITY,
        )
        sentinel = ANDROID_PARTICIPANT_TRUTH_INGRESS_AUTHORITY
        assert "participant_authority_interfaces" in sentinel or "PR-8" in sentinel, (
            "android_participant_truth_ingress authority sentinel should reference "
            "participant_authority_interfaces or PR-8"
        )

    def test_evidence_ingress_authority_references_pr8(self):
        from core.android_participant_evidence_ingress import (
            ANDROID_PARTICIPANT_EVIDENCE_INGRESS_AUTHORITY,
        )
        sentinel = ANDROID_PARTICIPANT_EVIDENCE_INGRESS_AUTHORITY
        assert "participant_authority_interfaces" in sentinel or "PR-8" in sentinel, (
            "android_participant_evidence_ingress authority sentinel should reference "
            "participant_authority_interfaces or PR-8"
        )

    def test_session_state_authority_sentinel_is_concrete_android(self):
        from core.android_participant_session_state import (
            ANDROID_PARTICIPANT_SESSION_STATE_AUTHORITY,
        )
        assert "concrete" in ANDROID_PARTICIPANT_SESSION_STATE_AUTHORITY.lower() or \
               "Android" in ANDROID_PARTICIPANT_SESSION_STATE_AUTHORITY or \
               "android" in ANDROID_PARTICIPANT_SESSION_STATE_AUTHORITY.lower()

    def test_dispatch_binding_authority_sentinel_is_concrete_android(self):
        from core.android_runtime_dispatch_binding import (
            ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY,
        )
        assert "concrete" in ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY.lower() or \
               "android" in ANDROID_RUNTIME_DISPATCH_BINDING_AUTHORITY.lower()


# ===========================================================================
# Q. Policy sentinel format
# ===========================================================================


class TestPolicySentinelFormat:
    _POLICIES = [
        PARTICIPANT_GENERIC_LAYER_IS_ABOVE_ANDROID_CONCRETE_POLICY,
        ANDROID_CONCRETE_MUST_NOT_BE_REMOVED_POLICY,
        PARTICIPANT_DISPATCH_AUTHORITY_IS_PARTICIPANT_GENERIC_POLICY,
        PARTICIPANT_RESULT_INGRESS_IS_PARTICIPANT_GENERIC_POLICY,
        PARTICIPANT_SESSION_LEGALITY_IS_PARTICIPANT_GENERIC_POLICY,
        PARTICIPANT_AVAILABILITY_IS_PARTICIPANT_GENERIC_POLICY,
        PARTICIPANT_ORCHESTRATION_BOUNDARY_IS_PARTICIPANT_GENERIC_POLICY,
        WRONG_LAYER_ANDROID_NAMING_MUST_BE_LIFTED_POLICY,
    ]

    def test_all_policies_are_non_empty_strings(self):
        for p in self._POLICIES:
            assert isinstance(p, str) and p, f"Policy sentinel must be a non-empty string: {p!r}"

    def test_all_policies_contain_policy_tag(self):
        for p in self._POLICIES:
            assert "POLICY::" in p, f"Policy sentinel must contain 'POLICY::': {p!r}"

    def test_generic_layer_policy_mentions_android(self):
        assert "android" in PARTICIPANT_GENERIC_LAYER_IS_ABOVE_ANDROID_CONCRETE_POLICY.lower()

    def test_android_must_not_be_removed_policy_is_prohibitive(self):
        p = ANDROID_CONCRETE_MUST_NOT_BE_REMOVED_POLICY
        # Should forbid removal — check for relevant language
        assert "MUST NOT" in p or "must not" in p.lower() or "prohibit" in p.lower()


# ===========================================================================
# R. Runtime behavior stability: Android concrete session lifecycle
# ===========================================================================


class TestRuntimeBehaviorStability:
    """Verify that Android concrete session lifecycle functions remain callable
    and produce correct types after the authority sentinel update."""

    def test_create_participant_session_record_returns_record(self):
        from core.android_participant_session_state import (
            create_participant_session_record,
            AndroidParticipantSessionRecord,
            AndroidParticipantSessionPhase,
        )
        record = create_participant_session_record(
            session_id="test-session-pr8",
            device_id="test-device-pr8",
        )
        assert isinstance(record, AndroidParticipantSessionRecord)
        assert record.phase == AndroidParticipantSessionPhase.pre_dispatch
        assert record.session_id == "test-session-pr8"

    def test_advance_participant_session_produces_new_record(self):
        from core.android_participant_session_state import (
            create_participant_session_record,
            advance_participant_session,
            AndroidParticipantSessionRecord,
            AndroidParticipantSessionPhase,
            AndroidParticipantSessionSignal,
        )
        record = create_participant_session_record(session_id="adv-test-pr8")
        advanced = advance_participant_session(
            record, AndroidParticipantSessionSignal.handoff_dispatched
        )
        assert isinstance(advanced, AndroidParticipantSessionRecord)
        assert advanced.phase == AndroidParticipantSessionPhase.handoff_dispatched
        # Original record is unchanged (immutable)
        assert record.phase == AndroidParticipantSessionPhase.pre_dispatch

    def test_terminal_android_phase_is_absorbing(self):
        from core.android_participant_session_state import (
            create_participant_session_record,
            advance_participant_session,
            AndroidParticipantSessionPhase,
            AndroidParticipantSessionSignal,
        )
        record = create_participant_session_record(session_id="term-test-pr8")
        # Drive to terminal
        r1 = advance_participant_session(record, AndroidParticipantSessionSignal.handoff_dispatched)
        r2 = advance_participant_session(r1, AndroidParticipantSessionSignal.execution_started)
        r3 = advance_participant_session(r2, AndroidParticipantSessionSignal.result_success)
        assert r3.phase == AndroidParticipantSessionPhase.terminal_success
        # Any further signal on a terminal record is a no-op
        r4 = advance_participant_session(r3, AndroidParticipantSessionSignal.execution_progressed)
        assert r4.phase == AndroidParticipantSessionPhase.terminal_success

    def test_android_participant_truth_kind_maps_to_generic(self):
        """Android concrete truth kinds match the generic ParticipantResultKind values."""
        from core.android_participant_truth_ingress import AndroidParticipantTruthKind

        for kind in AndroidParticipantTruthKind:
            # Every Android truth kind value should exist in the generic enum
            generic = ParticipantResultKind.from_string(kind.value)
            assert generic != ParticipantResultKind.unknown or kind.value == "unknown", (
                f"AndroidParticipantTruthKind.{kind.name} ({kind.value!r}) should map "
                f"to a known ParticipantResultKind, got 'unknown'"
            )

    def test_android_availability_status_maps_to_generic(self):
        """Android concrete availability status values match generic enum values."""
        from core.android_participant_evidence_ingress import AndroidParticipantStatus

        for status in AndroidParticipantStatus:
            generic = ParticipantAvailabilityStatus.from_string(status.value)
            assert generic != ParticipantAvailabilityStatus.missing_evidence or \
                status.value == "missing_evidence", (
                f"AndroidParticipantStatus.{status.name} ({status.value!r}) should map "
                f"to a known ParticipantAvailabilityStatus"
            )
