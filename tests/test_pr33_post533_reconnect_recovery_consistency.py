"""tests/test_pr33_post533_reconnect_recovery_consistency.py
=============================================================
Tests for PR package 33 (post-533 dual-repo runtime unification master plan,
main repo side): Product-grade Reconnect and Recovery Consistency Hardening.

This test suite verifies that:

1. All PR-33 policy/authority sentinels are present in the orchestrator module.
2. The projection sentinel is importable and is not UNAVAILABLE.
3. ``core.runtime`` re-exports all PR-33 sentinel symbols.
4. ``AttachedSessionRegistryEntry`` tracks ``reconnect_count`` and
   ``last_reconnect_at`` and increments them correctly on reconnect.
5. ``reconnect_count`` is monotonically increasing; never decrements.
6. ``last_reconnect_at`` is None before any reconnect and set after.
7. ``runtime_session_id`` is preserved through reconnect (host-side truth).
8. ``to_dict`` / ``from_dict`` round-trip preserves reconnect fields.
9. ``clear_seq_context_for_reconnect()`` allows post-reconnect signals to be
   accepted rather than rejected as stale or out-of-order.
10. Signal-guard state for a context is cleared on reconnect but duplicate
    signal_id protection remains active.
11. ``get_active_execution_tracking_for_session()`` returns in-flight records
    after reconnect.
12. ``get_active_execution_tracking_for_session()`` returns None once a record
    reaches a terminal phase.
13. No new truth authority, duplicate recovery subsystem, or parallel
    reconciliation path is introduced.
14. Regression: existing registry / recovery-readiness / execution-tracker
    semantics are unchanged.

Coverage groups
---------------
A  — Orchestrator module: all PR-33 sentinels present and non-empty.
B  — Projection: PR-33 sentinel importable and not UNAVAILABLE.
C  — core.runtime re-exports all PR-33 sentinels.
D  — Registry: reconnect_count starts at 0 and increments on reconnect.
E  — Registry: reconnect_count is monotonically increasing across multiple reconnects.
F  — Registry: last_reconnect_at is None before reconnect and set after.
G  — Registry: runtime_session_id preserved through reconnect (host-side truth).
H  — Registry: to_dict / from_dict round-trip preserves reconnect_count and last_reconnect_at.
I  — Registry: non-reconnect transitions (detach, reattach) do not alter reconnect_count.
J  — Recovery readiness: clear_seq_context_for_reconnect allows post-reconnect accept.
K  — Recovery readiness: stale/out-of-order cleared by reconnect context clear.
L  — Recovery readiness: duplicate protection survives reconnect context clear.
M  — Recovery readiness: clear on absent context_key is a no-op (no error).
N  — Execution tracker: get_active_execution_tracking_for_session returns in-flight record.
O  — Execution tracker: returns None when latest record for session is terminal.
P  — Execution tracker: returns None when no record for session exists.
Q  — Execution tracker: ring-buffer not cleared on reconnect (records survive).
R  — No parallel authority: reconnect count lives on the existing entry, no new store.
S  — Sentinel strings contain expected PR-33 keywords.
T  — Regression: existing reconnect_session semantics unchanged.
"""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.runtime.source_dispatch_orchestrator import (
        RECONNECT_RECOVERY_CONSISTENCY_PR33_SENTINEL,
        RECONNECT_MUST_NOT_BREAK_HOST_SIDE_TRUTH_PR33_POLICY,
        REGISTRY_RECONNECT_EVENT_IS_OBSERVABLE_PR33_POLICY,
        EXECUTION_TRACKER_SURVIVES_RECONNECT_PR33_POLICY,
        RESULT_MERGE_CONSISTENT_THROUGH_RECOVERY_PR33_POLICY,
    )

    _ORCHESTRATOR_AVAILABLE = True
except ImportError:
    _ORCHESTRATOR_AVAILABLE = False

try:
    from core.routes.projection import RECONNECT_RECOVERY_CONSISTENCY_ALIGNED_PR33

    _PROJECTION_AVAILABLE = True
except ImportError:
    _PROJECTION_AVAILABLE = False

try:
    from core.runtime import (
        RECONNECT_RECOVERY_CONSISTENCY_PR33_SENTINEL as _rt_sentinel,
        RECONNECT_MUST_NOT_BREAK_HOST_SIDE_TRUTH_PR33_POLICY as _rt_host_truth,
        REGISTRY_RECONNECT_EVENT_IS_OBSERVABLE_PR33_POLICY as _rt_observable,
        EXECUTION_TRACKER_SURVIVES_RECONNECT_PR33_POLICY as _rt_tracker,
        RESULT_MERGE_CONSISTENT_THROUGH_RECOVERY_PR33_POLICY as _rt_merge,
    )

    _RUNTIME_EXPORTS_AVAILABLE = True
except ImportError:
    _RUNTIME_EXPORTS_AVAILABLE = False

try:
    from core.attached_runtime_session_registry import (
        REGISTRY_RECONNECT_CONSISTENCY_PR33_SENTINEL,
        REGISTRY_RECONNECT_COUNT_IS_MONOTONIC_PR33_POLICY,
        REGISTRY_LAST_RECONNECT_AT_TRACKS_MOST_RECENT_RECONNECT_PR33_POLICY,
        AttachedSessionRegistry,
        AttachedSessionRegistryEntry,
        RegistryEntryState,
        RegistryTransition,
        InvalidationReason,
        register_session,
        reconnect_session,
        detach_session,
        reattach_session,
        invalidate_session,
    )

    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

try:
    from core.attached_runtime_recovery_readiness import (
        RECOVERY_READINESS_RECONNECT_CONSISTENCY_PR33_SENTINEL,
        RECOVERY_GUARD_CLEARS_SEQ_ON_RECONNECT_PR33_POLICY,
        RecoveryReadinessRuntime,
        build_idempotency_key,
        check_signal_guard,
        record_seen_signal,
        clear_seq_context_for_reconnect,
        SignalGuardDecision,
    )

    _RECOVERY_AVAILABLE = True
except ImportError:
    _RECOVERY_AVAILABLE = False

try:
    from core.delegated_runtime_execution_tracker import (
        EXECUTION_TRACKER_RECONNECT_CONSISTENCY_PR33_SENTINEL,
        TRACKER_ACTIVE_RECORDS_SURVIVE_RECONNECT_PR33_POLICY,
        DelegatedExecutionTrackingRuntime,
        DelegatedExecutionResult,
        DelegatedExecutionPhase,
        create_execution_tracking_record,
        apply_result,
        get_active_execution_tracking_for_session,
    )

    _TRACKER_AVAILABLE = True
except ImportError:
    _TRACKER_AVAILABLE = False

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_skip_orchestrator = pytest.mark.skipif(
    not _ORCHESTRATOR_AVAILABLE, reason="orchestrator module unavailable"
)
_skip_projection = pytest.mark.skipif(
    not _PROJECTION_AVAILABLE, reason="projection module unavailable (fastapi missing)"
)
_skip_runtime = pytest.mark.skipif(
    not _RUNTIME_EXPORTS_AVAILABLE, reason="core.runtime exports unavailable"
)
_skip_registry = pytest.mark.skipif(
    not _REGISTRY_AVAILABLE, reason="registry module unavailable"
)
_skip_recovery = pytest.mark.skipif(
    not _RECOVERY_AVAILABLE, reason="recovery readiness module unavailable"
)
_skip_tracker = pytest.mark.skipif(
    not _TRACKER_AVAILABLE, reason="execution tracker module unavailable"
)


def _make_registry() -> "AttachedSessionRegistry":
    return AttachedSessionRegistry()


def _fresh_tracker() -> "DelegatedExecutionTrackingRuntime":
    return DelegatedExecutionTrackingRuntime()


def _fresh_recovery() -> "RecoveryReadinessRuntime":
    return RecoveryReadinessRuntime()


# ===========================================================================
# A — Orchestrator sentinels
# ===========================================================================


@_skip_orchestrator
class TestOrchestratorSentinels:
    def test_AA1_sentinel_present_and_non_empty(self):
        assert RECONNECT_RECOVERY_CONSISTENCY_PR33_SENTINEL
        assert len(RECONNECT_RECOVERY_CONSISTENCY_PR33_SENTINEL) > 10

    def test_AA2_host_truth_policy_present(self):
        assert RECONNECT_MUST_NOT_BREAK_HOST_SIDE_TRUTH_PR33_POLICY
        assert len(RECONNECT_MUST_NOT_BREAK_HOST_SIDE_TRUTH_PR33_POLICY) > 10

    def test_AA3_observable_policy_present(self):
        assert REGISTRY_RECONNECT_EVENT_IS_OBSERVABLE_PR33_POLICY
        assert len(REGISTRY_RECONNECT_EVENT_IS_OBSERVABLE_PR33_POLICY) > 10

    def test_AA4_tracker_policy_present(self):
        assert EXECUTION_TRACKER_SURVIVES_RECONNECT_PR33_POLICY
        assert len(EXECUTION_TRACKER_SURVIVES_RECONNECT_PR33_POLICY) > 10

    def test_AA5_merge_policy_present(self):
        assert RESULT_MERGE_CONSISTENT_THROUGH_RECOVERY_PR33_POLICY
        assert len(RESULT_MERGE_CONSISTENT_THROUGH_RECOVERY_PR33_POLICY) > 10

    def test_AA6_all_five_sentinels_are_distinct(self):
        sentinels = [
            RECONNECT_RECOVERY_CONSISTENCY_PR33_SENTINEL,
            RECONNECT_MUST_NOT_BREAK_HOST_SIDE_TRUTH_PR33_POLICY,
            REGISTRY_RECONNECT_EVENT_IS_OBSERVABLE_PR33_POLICY,
            EXECUTION_TRACKER_SURVIVES_RECONNECT_PR33_POLICY,
            RESULT_MERGE_CONSISTENT_THROUGH_RECOVERY_PR33_POLICY,
        ]
        assert len(set(sentinels)) == 5


# ===========================================================================
# B — Projection sentinel
# ===========================================================================


@_skip_projection
class TestProjectionSentinel:
    def test_AB1_sentinel_importable(self):
        assert RECONNECT_RECOVERY_CONSISTENCY_ALIGNED_PR33

    def test_AB2_sentinel_not_unavailable(self):
        assert "UNAVAILABLE" not in RECONNECT_RECOVERY_CONSISTENCY_ALIGNED_PR33

    def test_AB3_sentinel_contains_pr33(self):
        assert any(kw in RECONNECT_RECOVERY_CONSISTENCY_ALIGNED_PR33 for kw in ("PR33", "PR-33", "package=33"))


# ===========================================================================
# C — core.runtime re-exports
# ===========================================================================


@_skip_runtime
class TestRuntimeExports:
    def test_AC1_sentinel_reexported(self):
        assert _rt_sentinel
        assert "PR33" in _rt_sentinel or "package=33" in _rt_sentinel

    def test_AC2_host_truth_policy_reexported(self):
        assert _rt_host_truth
        assert "PR33" in _rt_host_truth

    def test_AC3_observable_policy_reexported(self):
        assert _rt_observable
        assert "PR33" in _rt_observable

    def test_AC4_tracker_policy_reexported(self):
        assert _rt_tracker
        assert "PR33" in _rt_tracker

    def test_AC5_merge_policy_reexported(self):
        assert _rt_merge
        assert "PR33" in _rt_merge


# ===========================================================================
# D — Registry: reconnect_count increments on reconnect
# ===========================================================================


@_skip_registry
class TestRegistryReconnectCount:
    def test_AD1_reconnect_count_zero_after_register(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        assert e.reconnect_count == 0

    def test_AD2_reconnect_count_increments_on_reconnect(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e2 = detach_session(e, registry=r)
        e3 = reconnect_session(e2, registry=r)
        assert e3.reconnect_count == 1

    def test_AD3_reconnect_count_two_after_two_reconnects(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e = detach_session(e, registry=r)
        e = reconnect_session(e, registry=r)
        e = detach_session(e, registry=r)
        e = reconnect_session(e, registry=r)
        assert e.reconnect_count == 2

    def test_AD4_reconnect_count_not_reset_by_reattach(self):
        r = _make_registry()
        e = register_session("dev1", registry=r)
        e = detach_session(e, registry=r)
        e = reconnect_session(e, registry=r)
        assert e.reconnect_count == 1
        e = detach_session(e, registry=r)
        e2 = reattach_session(e, registry=r)
        # reattach does not increment reconnect_count
        assert e2.reconnect_count == 1


# ===========================================================================
# E — Registry: reconnect_count monotonically increasing
# ===========================================================================


@_skip_registry
class TestRegistryReconnectCountMonotonic:
    def test_AE1_count_never_decreases(self):
        r = _make_registry()
        e = register_session("dev2", registry=r)
        counts = [e.reconnect_count]
        for _ in range(5):
            e = detach_session(e, registry=r)
            e = reconnect_session(e, registry=r)
            counts.append(e.reconnect_count)
        for i in range(1, len(counts)):
            assert counts[i] > counts[i - 1]

    def test_AE2_count_after_five_reconnects_is_five(self):
        r = _make_registry()
        e = register_session("dev3", registry=r)
        for _ in range(5):
            e = detach_session(e, registry=r)
            e = reconnect_session(e, registry=r)
        assert e.reconnect_count == 5


# ===========================================================================
# F — Registry: last_reconnect_at
# ===========================================================================


@_skip_registry
class TestRegistryLastReconnectAt:
    def test_AF1_last_reconnect_at_none_after_register(self):
        r = _make_registry()
        e = register_session("dev4", registry=r)
        assert e.last_reconnect_at is None

    def test_AF2_last_reconnect_at_set_after_first_reconnect(self):
        r = _make_registry()
        e = register_session("dev5", registry=r)
        e = detach_session(e, registry=r)
        e = reconnect_session(e, registry=r)
        assert e.last_reconnect_at is not None
        assert isinstance(e.last_reconnect_at, float)
        assert e.last_reconnect_at > 0

    def test_AF3_last_reconnect_at_advances_on_second_reconnect(self):
        import time as _time
        r = _make_registry()
        e = register_session("dev6", registry=r)
        e = detach_session(e, registry=r)
        e = reconnect_session(e, registry=r)
        t1 = e.last_reconnect_at
        _time.sleep(0.01)
        e = detach_session(e, registry=r)
        e = reconnect_session(e, registry=r)
        t2 = e.last_reconnect_at
        assert t2 >= t1

    def test_AF4_last_reconnect_at_none_on_detach(self):
        r = _make_registry()
        e = register_session("dev7", registry=r)
        # last_reconnect_at is None before any reconnect; detach should not set it
        e = detach_session(e, registry=r)
        assert e.last_reconnect_at is None


# ===========================================================================
# G — Registry: host-side truth (runtime_session_id preserved)
# ===========================================================================


@_skip_registry
class TestRegistryHostSideTruth:
    def test_AG1_runtime_session_id_preserved_through_reconnect(self):
        r = _make_registry()
        e = register_session("dev8", registry=r)
        original_rsid = e.runtime_session_id
        e = detach_session(e, registry=r)
        e = reconnect_session(e, registry=r)
        assert e.runtime_session_id == original_rsid

    def test_AG2_runtime_session_id_preserved_across_multiple_reconnects(self):
        r = _make_registry()
        e = register_session("dev9", registry=r)
        original_rsid = e.runtime_session_id
        for _ in range(3):
            e = detach_session(e, registry=r)
            e = reconnect_session(e, registry=r)
        assert e.runtime_session_id == original_rsid

    def test_AG3_session_active_after_reconnect(self):
        r = _make_registry()
        e = register_session("dev10", registry=r)
        e = detach_session(e, registry=r)
        assert e.attachment_state == RegistryEntryState.detached
        e = reconnect_session(e, registry=r)
        assert e.attachment_state == RegistryEntryState.active

    def test_AG4_short_disconnect_reconnect_does_not_break_lookup(self):
        r = _make_registry()
        e = register_session("dev11", registry=r)
        e = detach_session(e, registry=r)
        e = reconnect_session(e, registry=r)
        # After reconnect the session should be findable as active
        found = r.get_active_for_device("dev11")
        assert found is not None
        assert found.runtime_session_id == e.runtime_session_id


# ===========================================================================
# H — Registry: to_dict / from_dict round-trip
# ===========================================================================


@_skip_registry
class TestRegistryRoundTrip:
    def test_AH1_to_dict_includes_reconnect_count(self):
        r = _make_registry()
        e = register_session("dev12", registry=r)
        e = detach_session(e, registry=r)
        e = reconnect_session(e, registry=r)
        d = e.to_dict()
        assert "reconnect_count" in d
        assert d["reconnect_count"] == 1

    def test_AH2_to_dict_includes_last_reconnect_at(self):
        r = _make_registry()
        e = register_session("dev13", registry=r)
        e = detach_session(e, registry=r)
        e = reconnect_session(e, registry=r)
        d = e.to_dict()
        assert "last_reconnect_at" in d
        assert d["last_reconnect_at"] is not None

    def test_AH3_from_dict_restores_reconnect_count(self):
        r = _make_registry()
        e = register_session("dev14", registry=r)
        e = detach_session(e, registry=r)
        e = reconnect_session(e, registry=r)
        d = e.to_dict()
        e2 = AttachedSessionRegistryEntry.from_dict(d)
        assert e2.reconnect_count == 1

    def test_AH4_from_dict_restores_last_reconnect_at(self):
        r = _make_registry()
        e = register_session("dev15", registry=r)
        e = detach_session(e, registry=r)
        e = reconnect_session(e, registry=r)
        d = e.to_dict()
        e2 = AttachedSessionRegistryEntry.from_dict(d)
        assert e2.last_reconnect_at == e.last_reconnect_at

    def test_AH5_from_dict_zero_reconnect_count_when_absent(self):
        """Backward compat: dicts without reconnect_count deserialise to 0."""
        r = _make_registry()
        e = register_session("dev16", registry=r)
        d = e.to_dict()
        d.pop("reconnect_count", None)
        d.pop("last_reconnect_at", None)
        e2 = AttachedSessionRegistryEntry.from_dict(d)
        assert e2.reconnect_count == 0
        assert e2.last_reconnect_at is None


# ===========================================================================
# I — Registry: non-reconnect transitions don't alter reconnect_count
# ===========================================================================


@_skip_registry
class TestRegistryNonReconnectTransitions:
    def test_AI1_detach_does_not_alter_reconnect_count(self):
        r = _make_registry()
        e = register_session("dev17", registry=r)
        e = detach_session(e, registry=r)
        assert e.reconnect_count == 0

    def test_AI2_invalidate_does_not_alter_reconnect_count(self):
        r = _make_registry()
        e = register_session("dev18", registry=r)
        e = invalidate_session(e, registry=r)
        assert e.reconnect_count == 0

    def test_AI3_reattach_preserves_reconnect_count(self):
        r = _make_registry()
        e = register_session("dev19", registry=r)
        e = detach_session(e, registry=r)
        e = reconnect_session(e, registry=r)
        assert e.reconnect_count == 1
        e = detach_session(e, registry=r)
        e = reattach_session(e, registry=r)
        # reattach is different from reconnect and must not increment count
        assert e.reconnect_count == 1


# ===========================================================================
# J — Recovery readiness: clear_seq_context_for_reconnect allows accept
# ===========================================================================


@_skip_recovery
class TestRecoveryReconnectContextClear:
    def test_AJ1_post_reconnect_signal_accepted_after_clear(self):
        rt = _fresh_recovery()
        key = build_idempotency_key("sig1", "contract1", "session1")
        record_seen_signal(key, 20, runtime=rt)
        # Without clear: seq=15 (20 - 15 = 5 <= STALE_THRESHOLD=10) is out_of_order
        key2 = build_idempotency_key("sig2", "contract1", "session1")
        d = check_signal_guard(key2, 15, runtime=rt)
        assert d == SignalGuardDecision.out_of_order
        # After reconnect clear: same seq should be accepted
        clear_seq_context_for_reconnect(key.context_key, runtime=rt)
        d2 = check_signal_guard(key2, 15, runtime=rt)
        assert d2 == SignalGuardDecision.accept

    def test_AJ2_stale_signal_accepted_after_reconnect_clear(self):
        rt = _fresh_recovery()
        key = build_idempotency_key("sig_a", "cA", "sA")
        record_seen_signal(key, 100, runtime=rt)
        # stale: 100 - 10 threshold → seq < 90
        key2 = build_idempotency_key("sig_b", "cA", "sA")
        d = check_signal_guard(key2, 5, runtime=rt)
        assert d == SignalGuardDecision.stale
        clear_seq_context_for_reconnect(key.context_key, runtime=rt)
        d2 = check_signal_guard(key2, 5, runtime=rt)
        assert d2 == SignalGuardDecision.accept

    def test_AJ3_new_signal_after_clear_is_accepted(self):
        rt = _fresh_recovery()
        key = build_idempotency_key("sig_x", "cX", "sX")
        record_seen_signal(key, 50, runtime=rt)
        clear_seq_context_for_reconnect(key.context_key, runtime=rt)
        # Fresh start: seq=1 should be accepted
        key_post = build_idempotency_key("sig_post", "cX", "sX")
        d = check_signal_guard(key_post, 1, runtime=rt)
        assert d == SignalGuardDecision.accept


# ===========================================================================
# K — Recovery readiness: stale/out-of-order cleared
# ===========================================================================


@_skip_recovery
class TestRecoveryClearEffectiveness:
    def test_AK1_seq_index_cleared_after_reconnect(self):
        rt = _fresh_recovery()
        key = build_idempotency_key("sig1", "c1", "s1")
        record_seen_signal(key, 30, runtime=rt)
        assert rt.get_max_seq(key.context_key) == 30
        clear_seq_context_for_reconnect(key.context_key, runtime=rt)
        assert rt.get_max_seq(key.context_key) == -1  # cleared

    def test_AK2_second_context_unaffected_by_clear(self):
        rt = _fresh_recovery()
        key1 = build_idempotency_key("sig1", "c1", "s1")
        key2 = build_idempotency_key("sig2", "c2", "s2")
        record_seen_signal(key1, 30, runtime=rt)
        record_seen_signal(key2, 15, runtime=rt)
        clear_seq_context_for_reconnect(key1.context_key, runtime=rt)
        # key1 cleared, key2 unaffected
        assert rt.get_max_seq(key1.context_key) == -1
        assert rt.get_max_seq(key2.context_key) == 15


# ===========================================================================
# L — Recovery readiness: duplicate protection survives reconnect context clear
# ===========================================================================


@_skip_recovery
class TestRecoveryDuplicateProtectionSurvivesReconnect:
    def test_AL1_duplicate_signal_still_rejected_after_clear(self):
        rt = _fresh_recovery()
        key = build_idempotency_key("dup_sig", "contract_d", "session_d")
        record_seen_signal(key, 5, runtime=rt)
        clear_seq_context_for_reconnect(key.context_key, runtime=rt)
        # Same signal_id must still be rejected as duplicate
        d = check_signal_guard(key, 1, runtime=rt)
        assert d == SignalGuardDecision.duplicate

    def test_AL2_new_signal_id_after_clear_is_accepted(self):
        rt = _fresh_recovery()
        key_old = build_idempotency_key("old_sig", "contract_e", "session_e")
        record_seen_signal(key_old, 5, runtime=rt)
        clear_seq_context_for_reconnect(key_old.context_key, runtime=rt)
        key_new = build_idempotency_key("new_sig", "contract_e", "session_e")
        d = check_signal_guard(key_new, 1, runtime=rt)
        assert d == SignalGuardDecision.accept


# ===========================================================================
# M — Recovery readiness: clear on absent context_key is a no-op
# ===========================================================================


@_skip_recovery
class TestRecoveryClearAbsentContext:
    def test_AM1_clear_absent_context_no_error(self):
        rt = _fresh_recovery()
        # Should not raise
        clear_seq_context_for_reconnect("nonexistent_context", runtime=rt)

    def test_AM2_clear_empty_string_no_error(self):
        rt = _fresh_recovery()
        clear_seq_context_for_reconnect("", runtime=rt)


# ===========================================================================
# N — Execution tracker: get_active_execution_tracking_for_session
# ===========================================================================


@_skip_tracker
class TestExecutionTrackerActiveForSession:
    def test_AN1_returns_in_flight_record(self):
        rt = _fresh_tracker()
        create_execution_tracking_record(session_id="s1", contract_id="c1", runtime=rt)
        active = get_active_execution_tracking_for_session("s1", runtime=rt)
        assert active is not None
        assert active.phase == DelegatedExecutionPhase.pending_ack

    def test_AN2_returns_in_flight_record_after_ack(self):
        from core.delegated_runtime_execution_tracker import (
            apply_acknowledgment_signal,
            AcknowledgmentSignal,
        )
        rt = _fresh_tracker()
        rec = create_execution_tracking_record(session_id="s2", contract_id="c2", runtime=rt)
        apply_acknowledgment_signal(rec, AcknowledgmentSignal.ack, runtime=rt)
        active = get_active_execution_tracking_for_session("s2", runtime=rt)
        assert active is not None
        assert active.phase == DelegatedExecutionPhase.acknowledged


# ===========================================================================
# O — Execution tracker: returns None when latest is terminal
# ===========================================================================


@_skip_tracker
class TestExecutionTrackerReturnsNoneWhenTerminal:
    def test_AO1_none_after_completed(self):
        rt = _fresh_tracker()
        rec = create_execution_tracking_record(session_id="s3", contract_id="c3", runtime=rt)
        apply_result(rec, DelegatedExecutionResult(success=True), runtime=rt)
        assert get_active_execution_tracking_for_session("s3", runtime=rt) is None

    def test_AO2_none_after_failed(self):
        rt = _fresh_tracker()
        rec = create_execution_tracking_record(session_id="s4", contract_id="c4", runtime=rt)
        apply_result(rec, DelegatedExecutionResult(success=False), runtime=rt)
        assert get_active_execution_tracking_for_session("s4", runtime=rt) is None


# ===========================================================================
# P — Execution tracker: returns None when no record exists
# ===========================================================================


@_skip_tracker
class TestExecutionTrackerNoRecord:
    def test_AP1_returns_none_for_unknown_session(self):
        rt = _fresh_tracker()
        assert get_active_execution_tracking_for_session("ghost_session", runtime=rt) is None

    def test_AP2_returns_none_for_empty_session_id(self):
        rt = _fresh_tracker()
        assert get_active_execution_tracking_for_session("", runtime=rt) is None


# ===========================================================================
# Q — Execution tracker: ring-buffer survives reconnect
# ===========================================================================


@_skip_tracker
@_skip_registry
class TestExecutionTrackerSurvivesReconnect:
    def test_AQ1_in_flight_record_survives_registry_reconnect(self):
        """Registry reconnect does not clear the execution tracker ring-buffer."""
        reg = _make_registry()
        tr = _fresh_tracker()
        e = register_session("devR", registry=reg)
        create_execution_tracking_record(
            session_id=e.session_id or "session_r",
            contract_id="contract_r",
            runtime=tr,
        )
        # Simulate disconnect + reconnect
        e = detach_session(e, registry=reg)
        e = reconnect_session(e, registry=reg)
        # Tracker ring-buffer is unaffected by registry transition
        active = get_active_execution_tracking_for_session(
            e.session_id or "session_r", runtime=tr
        )
        assert active is not None

    def test_AQ2_reconnect_count_observable_from_registry_after_reconnect(self):
        reg = _make_registry()
        tr = _fresh_tracker()
        e = register_session("devR2", registry=reg)
        create_execution_tracking_record(
            session_id=e.session_id or "session_r2",
            contract_id="contract_r2",
            runtime=tr,
        )
        e = detach_session(e, registry=reg)
        e = reconnect_session(e, registry=reg)
        assert e.reconnect_count == 1


# ===========================================================================
# R — No parallel authority: reconnect_count lives on existing entry
# ===========================================================================


@_skip_registry
class TestNoParallelAuthority:
    def test_AR1_no_separate_reconnect_event_store(self):
        """reconnect_count is a field on AttachedSessionRegistryEntry; no new store."""
        r = _make_registry()
        e = register_session("devNPA", registry=r)
        assert hasattr(e, "reconnect_count")
        assert hasattr(e, "last_reconnect_at")
        # The existing registry is the only source — no separate module
        assert not hasattr(r, "reconnect_event_log")
        assert not hasattr(r, "reconnect_registry")

    def test_AR2_no_alternate_recovery_runtime(self):
        """clear_seq_context_for_reconnect operates on the existing RecoveryReadinessRuntime."""
        if not _RECOVERY_AVAILABLE:
            pytest.skip("recovery module unavailable")
        rt = _fresh_recovery()
        key = build_idempotency_key("sid", "cid", "ses")
        record_seen_signal(key, 10, runtime=rt)
        # Function operates on the same runtime — no second runtime created
        clear_seq_context_for_reconnect(key.context_key, runtime=rt)
        assert rt.get_max_seq(key.context_key) == -1


# ===========================================================================
# S — Sentinel string content
# ===========================================================================


@_skip_orchestrator
class TestSentinelContent:
    def test_AS1_main_sentinel_contains_pr33(self):
        assert "33" in RECONNECT_RECOVERY_CONSISTENCY_PR33_SENTINEL

    def test_AS2_host_truth_policy_mentions_reconnect(self):
        assert "reconnect" in RECONNECT_MUST_NOT_BREAK_HOST_SIDE_TRUTH_PR33_POLICY.lower()

    def test_AS3_observable_policy_mentions_reconnect_count(self):
        assert "reconnect_count" in REGISTRY_RECONNECT_EVENT_IS_OBSERVABLE_PR33_POLICY

    def test_AS4_tracker_policy_mentions_session(self):
        assert "session" in EXECUTION_TRACKER_SURVIVES_RECONNECT_PR33_POLICY.lower()

    def test_AS5_merge_policy_mentions_clear_seq(self):
        assert "clear_seq_context_for_reconnect" in RESULT_MERGE_CONSISTENT_THROUGH_RECOVERY_PR33_POLICY


# ===========================================================================
# T — Regression: existing semantics unchanged
# ===========================================================================


@_skip_registry
class TestRegressionRegistrySemantics:
    def test_AT1_register_session_creates_active_entry(self):
        r = _make_registry()
        e = register_session("devREG", registry=r)
        assert e.attachment_state == RegistryEntryState.active

    def test_AT2_reconnect_session_restores_active(self):
        r = _make_registry()
        e = register_session("devREG2", registry=r)
        e = detach_session(e, registry=r)
        e = reconnect_session(e, registry=r)
        assert e.attachment_state == RegistryEntryState.active

    def test_AT3_detach_produces_recoverable_state(self):
        r = _make_registry()
        e = register_session("devREG3", registry=r)
        e = detach_session(e, registry=r)
        assert e.attachment_state == RegistryEntryState.detached
        assert e.is_recoverable()

    def test_AT4_invalidate_produces_terminal_state(self):
        r = _make_registry()
        e = register_session("devREG4", registry=r)
        e = invalidate_session(e, registry=r)
        assert e.is_terminal()


@_skip_recovery
class TestRegressionRecoverySemantics:
    def test_AT5_guard_accepts_new_signal(self):
        rt = _fresh_recovery()
        key = build_idempotency_key("fresh_sig", "c_fresh", "s_fresh")
        d = check_signal_guard(key, 1, runtime=rt)
        assert d == SignalGuardDecision.accept

    def test_AT6_duplicate_signal_id_rejected(self):
        rt = _fresh_recovery()
        key = build_idempotency_key("dup", "c1", "s1")
        record_seen_signal(key, 1, runtime=rt)
        d = check_signal_guard(key, 2, runtime=rt)
        assert d == SignalGuardDecision.duplicate


@_skip_tracker
class TestRegressionTrackerSemantics:
    def test_AT7_create_record_starts_pending_ack(self):
        rt = _fresh_tracker()
        rec = create_execution_tracking_record(session_id="sr1", contract_id="cr1", runtime=rt)
        assert rec.phase == DelegatedExecutionPhase.pending_ack

    def test_AT8_apply_result_advances_to_completed(self):
        rt = _fresh_tracker()
        rec = create_execution_tracking_record(session_id="sr2", contract_id="cr2", runtime=rt)
        rec2 = apply_result(rec, DelegatedExecutionResult(success=True), runtime=rt)
        assert rec2.phase == DelegatedExecutionPhase.completed

    def test_AT9_apply_result_idempotent_on_terminal(self):
        rt = _fresh_tracker()
        rec = create_execution_tracking_record(session_id="sr3", contract_id="cr3", runtime=rt)
        rec2 = apply_result(rec, DelegatedExecutionResult(success=True), runtime=rt)
        rec3 = apply_result(rec2, DelegatedExecutionResult(success=False), runtime=rt)
        assert rec3.phase == DelegatedExecutionPhase.completed
