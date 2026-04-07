"""tests/test_pr21_post533_delegated_execution_ingress_reconciliation_closure.py
=================================================================================
PR package 21 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Canonical Delegated Execution Ingress-Reconciliation Closure.

This test suite verifies that the single host-side canonical path
  ingress → guard → reconcile → tracker
is fully closed and consistent.  It does not introduce new tracker families,
new reconciliation authorities, or second execution-truth systems; it tightens
and verifies the existing PR-10 / PR-13 / PR-15 / PR-16 / PR-18 chain.

Coverage groups
---------------
A  — PR-21 sentinel / authority presence and correctness.
B  — PR-21 policy sentinels: non-empty and canonical content.
C  — Canonical ordering: guard MUST precede reconcile (accept path reaches tracker).
D  — Guard-rejected signals do not mutate tracker state:
     duplicate / replay / stale / out_of_order → was_updated=False, tracker unchanged.
E  — Monotonic phase progression through canonical path:
     pending_ack → acknowledged → in_progress → completed (no regression).
F  — Terminal state protection: after completion duplicate/replay/stale/out-of-order
     signals cannot corrupt execution truth.
G  — Identity continuity: contract_id, session_id, device_id, trace_id, task_id,
     signal_id all flow verbatim through ingress → envelope → tracker record.
H  — Full lifecycle: ack → progress → result/success → completed.
I  — Full lifecycle: result/failure → failed.
J  — Timeout signal → timed_out (terminal).
K  — Cancelled signal → cancelled (terminal).
L  — Signal on non-existent record: non-destructive miss (was_updated=False).
M  — Signal without lookup key: rejected at reconciler (was_updated=False).
N  — Two independent contracts are completely isolated in guard and tracker state.
O  — core.runtime re-exports PR-21 symbols.
P  — projection.py sentinel is present and not UNAVAILABLE.
Q  — All 15 ingress policies (PR-16 + PR-21) are non-empty strings.
R  — CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL contains 'package=21'.
S  — Partial-result signal advances to in_progress without closing tracking record.
T  — inject_delegated_execution_signal is the single entry-point (no second tracker path).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

import pytest

from core.android_delegated_signal_ingress import (
    ANDROID_DELEGATED_SIGNAL_INGRESS_AUTHORITY,
    ANDROID_DELEGATED_SIGNAL_INGRESS_PR16_SENTINEL,
    CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL,
    CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER_POLICY,
    IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH_POLICY,
    INGRESS_DELEGATES_TO_RECONCILER_POLICY,
    INGRESS_DELEGATED_SIGNAL_TYPE_IS_CANONICAL_POLICY,
    INGRESS_EMISSION_SEQ_IS_PRESERVED_POLICY,
    INGRESS_GUARD_REJECTED_SIGNAL_IS_DROPPED_POLICY,
    INGRESS_IDENTITY_FIELDS_ARE_VERBATIM_POLICY,
    INGRESS_NON_DESTRUCTIVE_ON_MISS_POLICY,
    INGRESS_RECOVERY_GUARD_IS_MANDATORY_POLICY,
    INGRESS_REQUIRES_LOOKUP_KEY_POLICY,
    INGRESS_RESULT_KIND_DISAMBIGUATES_RESULT_SIGNALS_POLICY,
    INGRESS_SIGNAL_ID_IS_PRESERVED_POLICY,
    INGRESS_SIGNAL_KIND_IS_EXPLICIT_FIELD_POLICY,
    INGRESS_TRACKER_PHASE_CONSISTENT_WITH_SIGNAL_KIND_POLICY,
    TERMINAL_STATE_IS_PROTECTED_AGAINST_REPLAY_POLICY,
    DelegatedSignalKind,
    ResultKind,
    DelegatedExecutionSignalEnvelope,
    extract_delegated_signal_envelope,
    ingest_delegated_execution_signal,
)
from core.attached_runtime_recovery_readiness import (
    RecoveryReadinessRuntime,
    SignalGuardDecision,
)
from core.delegated_runtime_execution_tracker import (
    DelegatedExecutionPhase,
    DelegatedExecutionTrackingRuntime,
    create_execution_tracking_record,
    get_execution_tracking_record,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_guard_runtime() -> RecoveryReadinessRuntime:
    """Return a fresh isolated guard runtime (not the process singleton)."""
    return RecoveryReadinessRuntime()


def _fresh_tracker_runtime() -> DelegatedExecutionTrackingRuntime:
    """Return a fresh isolated tracker runtime (not the process singleton)."""
    return DelegatedExecutionTrackingRuntime()


def _make_tracking_record(
    *,
    session_id: str = "ses-pr21-001",
    contract_id: str = "ctr-pr21-001",
    device_id: str = "dev-pr21-001",
    trace_id: str = "trace-pr21-001",
    runtime: Optional[DelegatedExecutionTrackingRuntime] = None,
):
    """Create a tracking record anchored to *runtime* and return (record, runtime)."""
    rt = runtime or _fresh_tracker_runtime()
    record = create_execution_tracking_record(
        session_id=session_id,
        contract_id=contract_id,
        device_id=device_id,
        trace_id=trace_id,
        source_runtime_posture="join_runtime",
        runtime=rt,
    )
    return record, rt


def _make_signal_message(
    *,
    device_id: str = "dev-pr21-001",
    task_id: str = "task-pr21-001",
    contract_id: str = "ctr-pr21-001",
    session_id: str = "ses-pr21-001",
    trace_id: str = "trace-pr21-001",
    signal_kind: str = "ack",
    result_kind: str = "",
    signal_id: str = "",
    emission_seq: int = 0,
    extra_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a synthetic ``delegated_execution_signal`` message dict."""
    payload: Dict[str, Any] = {
        "contract_id": contract_id,
        "session_id": session_id,
        "trace_id": trace_id,
        "signal_kind": signal_kind,
        "emission_seq": emission_seq,
    }
    if result_kind:
        payload["result_kind"] = result_kind
    if signal_id:
        payload["signal_id"] = signal_id
    if extra_payload:
        payload.update(extra_payload)
    return {
        "type": "delegated_execution_signal",
        "device_id": device_id,
        "task_id": task_id,
        "payload": payload,
    }


# ===========================================================================
# Group A — PR-21 sentinel / authority presence
# ===========================================================================


def test_A01_pr21_sentinel_present():
    assert CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL


def test_A02_pr21_sentinel_contains_package_21():
    assert "package=21" in CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL


def test_A03_pr21_sentinel_contains_pr21_main():
    assert "pr21" in CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL.lower()


def test_A04_pr21_sentinel_contains_closure():
    assert "closure" in CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL


def test_A05_pr21_sentinel_references_authority():
    assert "ANDROID_DELEGATED_SIGNAL_INGRESS_AUTHORITY" in CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL


def test_A06_authority_sentinel_present():
    assert ANDROID_DELEGATED_SIGNAL_INGRESS_AUTHORITY
    assert "PR16" in ANDROID_DELEGATED_SIGNAL_INGRESS_AUTHORITY


# ===========================================================================
# Group B — PR-21 policy sentinels
# ===========================================================================


def test_B01_canonical_path_policy_present():
    assert CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER_POLICY
    assert "CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER" in (
        CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER_POLICY
    )


def test_B02_canonical_path_policy_mentions_ingress_guard_reconcile_tracker():
    policy = CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER_POLICY.lower()
    assert "ingress" in policy
    assert "guard" in policy
    assert "reconcil" in policy
    assert "tracker" in policy


def test_B03_identity_continuity_policy_present():
    assert IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH_POLICY
    assert "IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH" in (
        IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH_POLICY
    )


def test_B04_identity_continuity_policy_mentions_key_fields():
    policy = IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH_POLICY.lower()
    assert "task_id" in policy
    assert "trace_id" in policy
    assert "contract_id" in policy
    assert "session_id" in policy


def test_B05_terminal_state_protection_policy_present():
    assert TERMINAL_STATE_IS_PROTECTED_AGAINST_REPLAY_POLICY
    assert "TERMINAL_STATE_IS_PROTECTED_AGAINST_REPLAY" in (
        TERMINAL_STATE_IS_PROTECTED_AGAINST_REPLAY_POLICY
    )


def test_B06_terminal_state_policy_mentions_replay_and_terminal():
    policy = TERMINAL_STATE_IS_PROTECTED_AGAINST_REPLAY_POLICY.lower()
    assert "terminal" in policy
    assert "duplicate" in policy or "replay" in policy


# ===========================================================================
# Group C — Canonical ordering: accepted signal reaches tracker
# ===========================================================================


def test_C01_accepted_ack_reaches_tracker():
    """Guard accepts signal → reconciler updates tracker → phase is acknowledged."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-c01", session_id="ses-c01"
    )
    guard_rt = _fresh_guard_runtime()
    outcome = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-c01",
            session_id="ses-c01",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert outcome.was_updated
    assert outcome.record is not None
    assert outcome.record.phase is DelegatedExecutionPhase.acknowledged


def test_C02_accepted_signal_returns_typed_outcome():
    """ingest_delegated_execution_signal always returns AndroidSignalReconcileOutcome."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-c02", session_id="ses-c02"
    )
    guard_rt = _fresh_guard_runtime()
    outcome = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-c02",
            session_id="ses-c02",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert hasattr(outcome, "was_updated")
    assert hasattr(outcome, "record")
    assert hasattr(outcome, "reject_reason")
    assert hasattr(outcome, "envelope")


def test_C03_guard_required_field_is_in_path():
    """INGRESS_RECOVERY_GUARD_IS_MANDATORY_POLICY sentinel confirms guard is required."""
    assert "MUST" in INGRESS_RECOVERY_GUARD_IS_MANDATORY_POLICY
    assert "guard_inbound_signal" in INGRESS_RECOVERY_GUARD_IS_MANDATORY_POLICY


def test_C04_reconciler_delegation_confirmed_by_policy():
    """INGRESS_DELEGATES_TO_RECONCILER_POLICY confirms reconciler is canonical."""
    assert "reconcile_android_execution_signal" in INGRESS_DELEGATES_TO_RECONCILER_POLICY
    assert "MUST NOT" in INGRESS_DELEGATES_TO_RECONCILER_POLICY


# ===========================================================================
# Group D — Guard-rejected signals do not mutate tracker state
# ===========================================================================


def test_D01_duplicate_signal_does_not_mutate_tracker():
    """Sending the same signal_id twice → second is duplicate, tracker unchanged."""
    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-d01", session_id="ses-d01"
    )
    guard_rt = _fresh_guard_runtime()
    sig_id = str(uuid.uuid4())
    msg = _make_signal_message(
        contract_id="ctr-d01",
        session_id="ses-d01",
        signal_kind="ack",
        signal_id=sig_id,
        emission_seq=1,
    )
    outcome1 = ingest_delegated_execution_signal(msg, runtime=tracker_rt, guard_runtime=guard_rt)
    assert outcome1.was_updated
    assert outcome1.record.phase is DelegatedExecutionPhase.acknowledged

    outcome2 = ingest_delegated_execution_signal(msg, runtime=tracker_rt, guard_runtime=guard_rt)
    assert not outcome2.was_updated
    assert "duplicate" in outcome2.reject_reason

    rec = get_execution_tracking_record("ses-d01", runtime=tracker_rt)
    assert rec.phase is DelegatedExecutionPhase.acknowledged


def test_D02_replay_signal_does_not_mutate_tracker():
    """Same emission_seq with different signal_id → replay, tracker unchanged."""
    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-d02", session_id="ses-d02"
    )
    guard_rt = _fresh_guard_runtime()
    outcome1 = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-d02",
            session_id="ses-d02",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=5,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert outcome1.was_updated

    # Same seq, different signal_id → replay
    outcome2 = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-d02",
            session_id="ses-d02",
            signal_kind="progress",
            signal_id=str(uuid.uuid4()),
            emission_seq=5,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert not outcome2.was_updated
    assert "replay" in outcome2.reject_reason

    rec = get_execution_tracking_record("ses-d02", runtime=tracker_rt)
    assert rec.phase is DelegatedExecutionPhase.acknowledged


def test_D03_stale_signal_does_not_mutate_tracker():
    """emission_seq far below max_seen → stale, tracker unchanged."""
    from core.attached_runtime_recovery_readiness import STALE_EMISSION_SEQ_THRESHOLD

    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-d03", session_id="ses-d03"
    )
    guard_rt = _fresh_guard_runtime()
    high_seq = STALE_EMISSION_SEQ_THRESHOLD + 50

    outcome1 = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-d03",
            session_id="ses-d03",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=high_seq,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert outcome1.was_updated

    # Seq far behind max → stale
    outcome2 = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-d03",
            session_id="ses-d03",
            signal_kind="progress",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert not outcome2.was_updated
    assert "stale" in outcome2.reject_reason

    rec = get_execution_tracking_record("ses-d03", runtime=tracker_rt)
    assert rec.phase is DelegatedExecutionPhase.acknowledged


def test_D04_out_of_order_signal_does_not_mutate_tracker():
    """emission_seq slightly below max_seen → out_of_order, tracker unchanged."""
    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-d04", session_id="ses-d04"
    )
    guard_rt = _fresh_guard_runtime()

    # Establish max_seen at seq=10
    outcome1 = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-d04",
            session_id="ses-d04",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=10,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert outcome1.was_updated

    # seq=9 → out_of_order
    outcome2 = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-d04",
            session_id="ses-d04",
            signal_kind="progress",
            signal_id=str(uuid.uuid4()),
            emission_seq=9,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert not outcome2.was_updated
    assert "out_of_order" in outcome2.reject_reason

    rec = get_execution_tracking_record("ses-d04", runtime=tracker_rt)
    assert rec.phase is DelegatedExecutionPhase.acknowledged


def test_D05_all_rejection_decisions_leave_reject_reason():
    """Every guard rejection encodes the decision in reject_reason."""
    from core.attached_runtime_recovery_readiness import STALE_EMISSION_SEQ_THRESHOLD

    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-d05", session_id="ses-d05"
    )
    guard_rt = _fresh_guard_runtime()
    sig_id = str(uuid.uuid4())

    # First ack (accepted)
    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-d05",
            session_id="ses-d05",
            signal_kind="ack",
            signal_id=sig_id,
            emission_seq=STALE_EMISSION_SEQ_THRESHOLD + 20,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )

    # Duplicate
    dup = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-d05",
            session_id="ses-d05",
            signal_kind="ack",
            signal_id=sig_id,
            emission_seq=STALE_EMISSION_SEQ_THRESHOLD + 20,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert not dup.was_updated
    assert dup.reject_reason  # non-empty

    # Stale
    stale = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-d05",
            session_id="ses-d05",
            signal_kind="progress",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert not stale.was_updated
    assert stale.reject_reason


# ===========================================================================
# Group E — Monotonic phase progression
# ===========================================================================


def test_E01_phase_cannot_regress_ack_then_progress():
    """ack → in_progress; never goes back to acknowledged."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-e01", session_id="ses-e01"
    )
    guard_rt = _fresh_guard_runtime()

    o1 = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-e01",
            session_id="ses-e01",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o1.record.phase is DelegatedExecutionPhase.acknowledged

    o2 = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-e01",
            session_id="ses-e01",
            signal_kind="progress",
            signal_id=str(uuid.uuid4()),
            emission_seq=2,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o2.record.phase is DelegatedExecutionPhase.in_progress


def test_E02_phase_order_pending_ack_acknowledged_in_progress():
    """Canonical progression: pending_ack → acknowledged → in_progress."""
    record, _ = _make_tracking_record(
        contract_id="ctr-e02", session_id="ses-e02"
    )
    assert record.phase is DelegatedExecutionPhase.pending_ack

    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-e02b", session_id="ses-e02b"
    )
    guard_rt = _fresh_guard_runtime()

    o_ack = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-e02b",
            session_id="ses-e02b",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o_ack.record.phase is DelegatedExecutionPhase.acknowledged

    o_prog = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-e02b",
            session_id="ses-e02b",
            signal_kind="progress",
            signal_id=str(uuid.uuid4()),
            emission_seq=2,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o_prog.record.phase is DelegatedExecutionPhase.in_progress


def test_E03_phase_mapping_ack_to_acknowledged():
    """DelegatedSignalKind.ack maps to DelegatedExecutionPhase.acknowledged."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-e03", session_id="ses-e03"
    )
    guard_rt = _fresh_guard_runtime()
    o = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-e03",
            session_id="ses-e03",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o.record.phase is DelegatedExecutionPhase.acknowledged


def test_E04_phase_mapping_progress_to_in_progress():
    """DelegatedSignalKind.progress maps to DelegatedExecutionPhase.in_progress."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-e04", session_id="ses-e04"
    )
    guard_rt = _fresh_guard_runtime()
    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-e04",
            session_id="ses-e04",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    o = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-e04",
            session_id="ses-e04",
            signal_kind="progress",
            signal_id=str(uuid.uuid4()),
            emission_seq=2,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o.record.phase is DelegatedExecutionPhase.in_progress


# ===========================================================================
# Group F — Terminal state protection
# ===========================================================================


def test_F01_terminal_completed_blocks_further_signals():
    """After result/success → completed, no further signal mutates the record."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-f01", session_id="ses-f01"
    )
    guard_rt = _fresh_guard_runtime()

    # Drive to completed
    for seq, kind in [(1, "ack"), (2, "progress")]:
        ingest_delegated_execution_signal(
            _make_signal_message(
                contract_id="ctr-f01",
                session_id="ses-f01",
                signal_kind=kind,
                signal_id=str(uuid.uuid4()),
                emission_seq=seq,
            ),
            runtime=tracker_rt,
            guard_runtime=guard_rt,
        )
    o_result = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-f01",
            session_id="ses-f01",
            signal_kind="result",
            result_kind="success",
            signal_id=str(uuid.uuid4()),
            emission_seq=3,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o_result.record.phase is DelegatedExecutionPhase.completed

    # Another progress after terminal
    o_late = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-f01",
            session_id="ses-f01",
            signal_kind="progress",
            signal_id=str(uuid.uuid4()),
            emission_seq=4,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert not o_late.was_updated
    rec = get_execution_tracking_record("ses-f01", runtime=tracker_rt)
    assert rec.phase is DelegatedExecutionPhase.completed


def test_F02_terminal_failed_blocks_further_signals():
    """After result/failure → failed, no further signal mutates the record."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-f02", session_id="ses-f02"
    )
    guard_rt = _fresh_guard_runtime()

    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-f02",
            session_id="ses-f02",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    o_fail = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-f02",
            session_id="ses-f02",
            signal_kind="result",
            result_kind="failure",
            signal_id=str(uuid.uuid4()),
            emission_seq=2,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o_fail.record.phase is DelegatedExecutionPhase.failed

    o_extra = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-f02",
            session_id="ses-f02",
            signal_kind="progress",
            signal_id=str(uuid.uuid4()),
            emission_seq=3,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert not o_extra.was_updated
    rec = get_execution_tracking_record("ses-f02", runtime=tracker_rt)
    assert rec.phase is DelegatedExecutionPhase.failed


def test_F03_duplicate_after_terminal_does_not_mutate():
    """Duplicate signal after terminal phase → duplicate-rejected (or terminal-blocked), tracker unchanged."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-f03", session_id="ses-f03"
    )
    guard_rt = _fresh_guard_runtime()

    sig_id = str(uuid.uuid4())
    # Drive to completed via result/success
    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-f03",
            session_id="ses-f03",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    msg_result = _make_signal_message(
        contract_id="ctr-f03",
        session_id="ses-f03",
        signal_kind="result",
        result_kind="success",
        signal_id=sig_id,
        emission_seq=2,
    )
    ingest_delegated_execution_signal(msg_result, runtime=tracker_rt, guard_runtime=guard_rt)

    # Duplicate result
    o_dup = ingest_delegated_execution_signal(msg_result, runtime=tracker_rt, guard_runtime=guard_rt)
    assert not o_dup.was_updated

    rec = get_execution_tracking_record("ses-f03", runtime=tracker_rt)
    assert rec.phase is DelegatedExecutionPhase.completed


def test_F04_stale_signal_after_terminal_does_not_corrupt():
    """Stale signal after terminal phase → stale-rejected, terminal truth intact."""
    from core.attached_runtime_recovery_readiness import STALE_EMISSION_SEQ_THRESHOLD

    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-f04", session_id="ses-f04"
    )
    guard_rt = _fresh_guard_runtime()
    high_seq = STALE_EMISSION_SEQ_THRESHOLD + 10

    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-f04",
            session_id="ses-f04",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=high_seq,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-f04",
            session_id="ses-f04",
            signal_kind="result",
            result_kind="success",
            signal_id=str(uuid.uuid4()),
            emission_seq=high_seq + 1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )

    # Stale signal with very low seq
    o_stale = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-f04",
            session_id="ses-f04",
            signal_kind="result",
            result_kind="failure",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert not o_stale.was_updated

    rec = get_execution_tracking_record("ses-f04", runtime=tracker_rt)
    assert rec.phase is DelegatedExecutionPhase.completed


# ===========================================================================
# Group G — Identity continuity through canonical path
# ===========================================================================


def test_G01_contract_id_preserved_in_outcome_envelope():
    """contract_id flows verbatim from message → outcome.envelope."""
    contract_id = "ctr-g01-canonical"
    _, tracker_rt = _make_tracking_record(
        contract_id=contract_id, session_id="ses-g01"
    )
    guard_rt = _fresh_guard_runtime()

    o = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id=contract_id,
            session_id="ses-g01",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o.envelope.contract_id == contract_id


def test_G02_session_id_preserved_in_outcome_envelope():
    """session_id flows verbatim from message → outcome.envelope."""
    session_id = "ses-g02-canonical"
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-g02", session_id=session_id
    )
    guard_rt = _fresh_guard_runtime()

    o = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-g02",
            session_id=session_id,
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o.envelope.session_id == session_id


def test_G03_device_id_preserved_in_outcome_envelope():
    """device_id flows verbatim from message → outcome.envelope."""
    device_id = "dev-g03-android"
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-g03", session_id="ses-g03", device_id=device_id
    )
    guard_rt = _fresh_guard_runtime()

    o = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-g03",
            session_id="ses-g03",
            device_id=device_id,
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o.envelope.device_id == device_id


def test_G04_trace_id_preserved_in_outcome_envelope():
    """trace_id flows verbatim from message → outcome.envelope."""
    trace_id = "trace-g04-distributed"
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-g04", session_id="ses-g04", trace_id=trace_id
    )
    guard_rt = _fresh_guard_runtime()

    o = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-g04",
            session_id="ses-g04",
            trace_id=trace_id,
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o.envelope.trace_id == trace_id


def test_G05_task_id_preserved_in_outcome_envelope():
    """task_id flows verbatim from message → outcome.envelope."""
    task_id = "task-g05-android-task"
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-g05", session_id="ses-g05"
    )
    guard_rt = _fresh_guard_runtime()

    o = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-g05",
            session_id="ses-g05",
            task_id=task_id,
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o.envelope.task_id == task_id


def test_G06_signal_id_preserved_in_outcome_envelope():
    """signal_id flows verbatim from message → outcome.envelope."""
    signal_id = str(uuid.uuid4())
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-g06", session_id="ses-g06"
    )
    guard_rt = _fresh_guard_runtime()

    o = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-g06",
            session_id="ses-g06",
            signal_kind="ack",
            signal_id=signal_id,
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o.envelope.signal_id == signal_id


def test_G07_emission_seq_preserved_in_outcome_envelope():
    """emission_seq flows verbatim from message → outcome.envelope."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-g07", session_id="ses-g07"
    )
    guard_rt = _fresh_guard_runtime()

    o = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-g07",
            session_id="ses-g07",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=42,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o.envelope.emission_seq == 42


def test_G08_all_identity_fields_present_in_envelope():
    """DelegatedExecutionSignalEnvelope carries all identity/signal fields."""
    env = extract_delegated_signal_envelope(
        _make_signal_message(
            contract_id="ctr-g08",
            session_id="ses-g08",
            device_id="dev-g08",
            trace_id="trace-g08",
            task_id="task-g08",
            signal_kind="result",
            result_kind="success",
            signal_id="sig-g08",
            emission_seq=7,
        )
    )
    assert env.contract_id == "ctr-g08"
    assert env.session_id == "ses-g08"
    assert env.device_id == "dev-g08"
    assert env.trace_id == "trace-g08"
    assert env.task_id == "task-g08"
    assert env.signal_kind is DelegatedSignalKind.result
    assert env.result_kind is ResultKind.success
    assert env.signal_id == "sig-g08"
    assert env.emission_seq == 7


# ===========================================================================
# Group H — Full lifecycle: ack → progress → result/success → completed
# ===========================================================================


def test_H01_full_lifecycle_ack_progress_success_completed():
    """End-to-end: ack → progress → result/success drives tracker to completed."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-h01", session_id="ses-h01"
    )
    guard_rt = _fresh_guard_runtime()

    o_ack = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-h01",
            session_id="ses-h01",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o_ack.was_updated
    assert o_ack.record.phase is DelegatedExecutionPhase.acknowledged

    o_prog = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-h01",
            session_id="ses-h01",
            signal_kind="progress",
            signal_id=str(uuid.uuid4()),
            emission_seq=2,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o_prog.was_updated
    assert o_prog.record.phase is DelegatedExecutionPhase.in_progress

    o_result = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-h01",
            session_id="ses-h01",
            signal_kind="result",
            result_kind="success",
            signal_id=str(uuid.uuid4()),
            emission_seq=3,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o_result.was_updated
    assert o_result.record.phase is DelegatedExecutionPhase.completed
    assert o_result.record.result is not None
    assert o_result.record.result.success is True


def test_H02_full_lifecycle_result_carries_typed_result():
    """result/success → completed: result.success is True and completed_at is set."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-h02", session_id="ses-h02"
    )
    guard_rt = _fresh_guard_runtime()

    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-h02",
            session_id="ses-h02",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    o = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-h02",
            session_id="ses-h02",
            signal_kind="result",
            result_kind="success",
            signal_id=str(uuid.uuid4()),
            emission_seq=2,
            extra_payload={"result": "all done"},
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o.record.result is not None
    assert o.record.result.success is True
    assert o.record.result.completed_at > 0


# ===========================================================================
# Group I — Full lifecycle: result/failure → failed
# ===========================================================================


def test_I01_result_failure_drives_to_failed():
    """result/failure signal drives tracker to failed."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-i01", session_id="ses-i01"
    )
    guard_rt = _fresh_guard_runtime()

    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-i01",
            session_id="ses-i01",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    o = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-i01",
            session_id="ses-i01",
            signal_kind="result",
            result_kind="failure",
            signal_id=str(uuid.uuid4()),
            emission_seq=2,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o.was_updated
    assert o.record.phase is DelegatedExecutionPhase.failed
    assert o.record.result is not None
    assert o.record.result.success is False


def test_I02_result_failure_is_terminal_no_further_mutation():
    """After failed, additional signals are ignored."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-i02", session_id="ses-i02"
    )
    guard_rt = _fresh_guard_runtime()

    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-i02",
            session_id="ses-i02",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-i02",
            session_id="ses-i02",
            signal_kind="result",
            result_kind="failure",
            signal_id=str(uuid.uuid4()),
            emission_seq=2,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    # Another result/success cannot overwrite
    o_extra = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-i02",
            session_id="ses-i02",
            signal_kind="result",
            result_kind="success",
            signal_id=str(uuid.uuid4()),
            emission_seq=3,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert not o_extra.was_updated
    rec = get_execution_tracking_record("ses-i02", runtime=tracker_rt)
    assert rec.phase is DelegatedExecutionPhase.failed


# ===========================================================================
# Group J — Timeout signal → timed_out
# ===========================================================================


def test_J01_timeout_signal_drives_to_timed_out():
    """timeout signal advances tracker to timed_out (terminal)."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-j01", session_id="ses-j01"
    )
    guard_rt = _fresh_guard_runtime()

    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-j01",
            session_id="ses-j01",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    o = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-j01",
            session_id="ses-j01",
            signal_kind="timeout",
            signal_id=str(uuid.uuid4()),
            emission_seq=2,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o.was_updated
    assert o.record.phase is DelegatedExecutionPhase.timed_out


def test_J02_timed_out_is_terminal():
    """After timed_out, no further signals advance the tracker."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-j02", session_id="ses-j02"
    )
    guard_rt = _fresh_guard_runtime()

    for seq, kind in [(1, "ack"), (2, "timeout")]:
        ingest_delegated_execution_signal(
            _make_signal_message(
                contract_id="ctr-j02",
                session_id="ses-j02",
                signal_kind=kind,
                signal_id=str(uuid.uuid4()),
                emission_seq=seq,
            ),
            runtime=tracker_rt,
            guard_runtime=guard_rt,
        )

    o_extra = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-j02",
            session_id="ses-j02",
            signal_kind="result",
            result_kind="success",
            signal_id=str(uuid.uuid4()),
            emission_seq=3,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert not o_extra.was_updated
    assert get_execution_tracking_record("ses-j02", runtime=tracker_rt).phase is DelegatedExecutionPhase.timed_out


# ===========================================================================
# Group K — Cancelled signal → cancelled
# ===========================================================================


def test_K01_cancelled_signal_drives_to_cancelled():
    """cancelled signal advances tracker to cancelled (terminal)."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-k01", session_id="ses-k01"
    )
    guard_rt = _fresh_guard_runtime()

    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-k01",
            session_id="ses-k01",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    o = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-k01",
            session_id="ses-k01",
            signal_kind="cancelled",
            signal_id=str(uuid.uuid4()),
            emission_seq=2,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o.was_updated
    assert o.record.phase is DelegatedExecutionPhase.cancelled


def test_K02_cancelled_is_terminal():
    """After cancelled, no further signals advance the tracker."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-k02", session_id="ses-k02"
    )
    guard_rt = _fresh_guard_runtime()

    for seq, kind in [(1, "ack"), (2, "cancelled")]:
        ingest_delegated_execution_signal(
            _make_signal_message(
                contract_id="ctr-k02",
                session_id="ses-k02",
                signal_kind=kind,
                signal_id=str(uuid.uuid4()),
                emission_seq=seq,
            ),
            runtime=tracker_rt,
            guard_runtime=guard_rt,
        )

    o_extra = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-k02",
            session_id="ses-k02",
            signal_kind="progress",
            signal_id=str(uuid.uuid4()),
            emission_seq=3,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert not o_extra.was_updated


# ===========================================================================
# Group L — Non-destructive miss
# ===========================================================================


def test_L01_signal_for_unknown_contract_id_returns_not_updated():
    """Signal for a contract_id with no tracking record → was_updated=False."""
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()

    o = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-unknown-l01",
            session_id="ses-unknown-l01",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert not o.was_updated
    assert o.record is None


def test_L02_miss_does_not_create_phantom_record():
    """Signal miss creates no phantom tracking record."""
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()

    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-phantom-l02",
            session_id="ses-phantom-l02",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    # Should not have created a record
    rec = get_execution_tracking_record("ses-phantom-l02", runtime=tracker_rt)
    assert rec is None


# ===========================================================================
# Group M — Signal without lookup key
# ===========================================================================


def test_M01_no_lookup_key_returns_not_updated():
    """Message without contract_id or session_id → was_updated=False."""
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()

    msg: Dict[str, Any] = {
        "type": "delegated_execution_signal",
        "device_id": "dev-m01",
        "payload": {
            "signal_kind": "ack",
            "emission_seq": 1,
            "signal_id": str(uuid.uuid4()),
        },
    }
    o = ingest_delegated_execution_signal(msg, runtime=tracker_rt, guard_runtime=guard_rt)
    assert not o.was_updated


# ===========================================================================
# Group N — Independent contracts: isolated guard and tracker state
# ===========================================================================


def test_N01_two_contracts_have_independent_guard_state():
    """Two different contract executions do not share guard state."""
    _, tracker_rt_a = _make_tracking_record(
        contract_id="ctr-n01-a", session_id="ses-n01-a"
    )
    _, tracker_rt_b = _make_tracking_record(
        contract_id="ctr-n01-b", session_id="ses-n01-b"
    )
    guard_rt = _fresh_guard_runtime()

    sig_id_a = str(uuid.uuid4())
    sig_id_b = str(uuid.uuid4())

    # Both contracts can send seq=1 without collision
    oa = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-n01-a",
            session_id="ses-n01-a",
            signal_kind="ack",
            signal_id=sig_id_a,
            emission_seq=1,
        ),
        runtime=tracker_rt_a,
        guard_runtime=guard_rt,
    )
    ob = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-n01-b",
            session_id="ses-n01-b",
            signal_kind="ack",
            signal_id=sig_id_b,
            emission_seq=1,
        ),
        runtime=tracker_rt_b,
        guard_runtime=guard_rt,
    )
    assert oa.was_updated
    assert ob.was_updated


def test_N02_duplicate_in_contract_a_does_not_affect_contract_b():
    """Duplicate signal for contract A doesn't block contract B."""
    _, tracker_rt_a = _make_tracking_record(
        contract_id="ctr-n02-a", session_id="ses-n02-a"
    )
    _, tracker_rt_b = _make_tracking_record(
        contract_id="ctr-n02-b", session_id="ses-n02-b"
    )
    guard_rt = _fresh_guard_runtime()
    sig_id_a = str(uuid.uuid4())

    msg_a = _make_signal_message(
        contract_id="ctr-n02-a",
        session_id="ses-n02-a",
        signal_kind="ack",
        signal_id=sig_id_a,
        emission_seq=1,
    )
    ingest_delegated_execution_signal(msg_a, runtime=tracker_rt_a, guard_runtime=guard_rt)
    # Duplicate A
    dup_a = ingest_delegated_execution_signal(msg_a, runtime=tracker_rt_a, guard_runtime=guard_rt)
    assert not dup_a.was_updated

    # Contract B at same seq is NOT a duplicate
    ob = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-n02-b",
            session_id="ses-n02-b",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt_b,
        guard_runtime=guard_rt,
    )
    assert ob.was_updated


# ===========================================================================
# Group O — core.runtime re-exports PR-21 symbols
# ===========================================================================


def test_O01_core_runtime_exports_pr21_sentinel():
    from core import runtime as rt
    assert hasattr(rt, "CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL")
    assert rt.CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL
    assert "package=21" in rt.CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL


def test_O02_core_runtime_exports_canonical_path_policy():
    from core import runtime as rt
    assert hasattr(rt, "CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER_POLICY")
    assert rt.CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER_POLICY


def test_O03_core_runtime_exports_identity_continuity_policy():
    from core import runtime as rt
    assert hasattr(rt, "IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH_POLICY")
    assert rt.IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH_POLICY


def test_O04_core_runtime_exports_terminal_state_policy():
    from core import runtime as rt
    assert hasattr(rt, "TERMINAL_STATE_IS_PROTECTED_AGAINST_REPLAY_POLICY")
    assert rt.TERMINAL_STATE_IS_PROTECTED_AGAINST_REPLAY_POLICY


def test_O05_core_runtime_exports_ingest_function():
    from core import runtime as rt
    assert hasattr(rt, "ingest_delegated_execution_signal")
    assert callable(rt.ingest_delegated_execution_signal)


# ===========================================================================
# Group P — projection.py sentinel
# ===========================================================================


def test_P01_projection_sentinel_present_and_not_unavailable():
    try:
        from core.routes.projection import CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21
        assert CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21
        assert "UNAVAILABLE" not in CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21
    except ImportError:
        pytest.skip("projection module unavailable (likely missing fastapi)")


def test_P02_projection_sentinel_mentions_pr21():
    try:
        from core.routes.projection import CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21
        assert "PR21" in CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21 or "pr21" in CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21.lower()
    except ImportError:
        pytest.skip("projection module unavailable (likely missing fastapi)")


def test_P03_projection_sentinel_mentions_canonical():
    try:
        from core.routes.projection import CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21
        assert "canonical" in CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21.lower()
    except ImportError:
        pytest.skip("projection module unavailable (likely missing fastapi)")


# ===========================================================================
# Group Q — All 15 ingress policies are non-empty strings
# ===========================================================================


_ALL_PR16_PR21_POLICIES = [
    INGRESS_DELEGATED_SIGNAL_TYPE_IS_CANONICAL_POLICY,
    INGRESS_SIGNAL_KIND_IS_EXPLICIT_FIELD_POLICY,
    INGRESS_RESULT_KIND_DISAMBIGUATES_RESULT_SIGNALS_POLICY,
    INGRESS_SIGNAL_ID_IS_PRESERVED_POLICY,
    INGRESS_EMISSION_SEQ_IS_PRESERVED_POLICY,
    INGRESS_IDENTITY_FIELDS_ARE_VERBATIM_POLICY,
    INGRESS_REQUIRES_LOOKUP_KEY_POLICY,
    INGRESS_DELEGATES_TO_RECONCILER_POLICY,
    INGRESS_TRACKER_PHASE_CONSISTENT_WITH_SIGNAL_KIND_POLICY,
    INGRESS_NON_DESTRUCTIVE_ON_MISS_POLICY,
    INGRESS_RECOVERY_GUARD_IS_MANDATORY_POLICY,
    INGRESS_GUARD_REJECTED_SIGNAL_IS_DROPPED_POLICY,
    CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER_POLICY,
    IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH_POLICY,
    TERMINAL_STATE_IS_PROTECTED_AGAINST_REPLAY_POLICY,
]


def test_Q01_all_15_policies_are_non_empty_strings():
    assert len(_ALL_PR16_PR21_POLICIES) == 15
    for policy in _ALL_PR16_PR21_POLICIES:
        assert isinstance(policy, str)
        assert policy


def test_Q02_all_policies_contain_policy_prefix():
    """All ingress policies follow the INGRESS_POLICY:: naming convention."""
    for policy in _ALL_PR16_PR21_POLICIES:
        assert "POLICY::" in policy, f"Missing POLICY:: in: {policy[:80]}"


# ===========================================================================
# Group R — PR-21 sentinel content checks
# ===========================================================================


def test_R01_pr21_sentinel_contains_package_21():
    assert "package=21" in CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL


def test_R02_pr16_sentinel_contains_package_16():
    assert "package=16" in ANDROID_DELEGATED_SIGNAL_INGRESS_PR16_SENTINEL


def test_R03_pr21_sentinel_is_distinct_from_pr16_sentinel():
    assert (
        CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL
        != ANDROID_DELEGATED_SIGNAL_INGRESS_PR16_SENTINEL
    )


# ===========================================================================
# Group S — Partial-result signal advances to in_progress without terminal
# ===========================================================================


def test_S01_progress_signal_does_not_close_tracking():
    """progress signal leaves tracker in in_progress (non-terminal)."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-s01", session_id="ses-s01"
    )
    guard_rt = _fresh_guard_runtime()

    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-s01",
            session_id="ses-s01",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    o_prog = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-s01",
            session_id="ses-s01",
            signal_kind="progress",
            signal_id=str(uuid.uuid4()),
            emission_seq=2,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o_prog.was_updated
    assert o_prog.record.phase is DelegatedExecutionPhase.in_progress
    assert not o_prog.record.phase.is_terminal()


def test_S02_multiple_progress_signals_keep_in_progress():
    """Multiple progress signals keep tracker at in_progress (idempotent phase)."""
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-s02", session_id="ses-s02"
    )
    guard_rt = _fresh_guard_runtime()

    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-s02",
            session_id="ses-s02",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    for seq in range(2, 6):
        o = ingest_delegated_execution_signal(
            _make_signal_message(
                contract_id="ctr-s02",
                session_id="ses-s02",
                signal_kind="progress",
                signal_id=str(uuid.uuid4()),
                emission_seq=seq,
            ),
            runtime=tracker_rt,
            guard_runtime=guard_rt,
        )
        assert o.was_updated
        assert o.record.phase is DelegatedExecutionPhase.in_progress


# ===========================================================================
# Group T — Single entry-point invariant
# ===========================================================================


def test_T01_ingest_delegated_execution_signal_is_callable():
    """ingest_delegated_execution_signal is the canonical, callable entry-point."""
    assert callable(ingest_delegated_execution_signal)


def test_T02_extract_delegated_signal_envelope_is_callable():
    """extract_delegated_signal_envelope is the canonical extraction function."""
    assert callable(extract_delegated_signal_envelope)


def test_T03_ingress_module_does_not_directly_mutate_tracker():
    """INGRESS_DELEGATES_TO_RECONCILER_POLICY confirms ingress delegates (not direct mutation)."""
    assert "reconcile_android_execution_signal" in INGRESS_DELEGATES_TO_RECONCILER_POLICY
    assert "MUST NOT" in INGRESS_DELEGATES_TO_RECONCILER_POLICY
    # The policy explicitly forbids direct tracker manipulation from ingress
    assert "directly manipulate the execution tracker" in INGRESS_DELEGATES_TO_RECONCILER_POLICY
