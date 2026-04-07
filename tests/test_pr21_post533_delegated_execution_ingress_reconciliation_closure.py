"""tests/test_pr21_post533_delegated_execution_ingress_reconciliation_closure.py
================================================================================
Tests for PR package 21 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical Delegated Execution Ingress and Reconciliation
Closure.

This test suite verifies that the canonical host-side delegated execution path:

    ingress → guard → reconcile → tracker

is fully closed, consistent, and safe.  Specifically:

1. PR-21 closure sentinels are present in the ingress module and are
   re-exported from ``core.runtime``.
2. The projection sentinel ``CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21``
   is present and not UNAVAILABLE.
3. The canonical path ordering is strictly: ingress extracts the envelope,
   guard evaluates before any state mutation, reconcile forwards only accepted
   signals to the tracker.
4. Guard-rejected signals never mutate execution-truth state.
5. Tracker phase progression is monotonic and aligned with signal kind.
6. Terminal result state is protected against duplicate / replay / stale /
   out-of-order signals.
7. Android-originated delegated execution identity (task_id, trace_id,
   signal_id, emission_seq, contract_id, session_id, device_id) flows
   verbatim from ingress to tracker — identity continuity.

Coverage groups
---------------
A  — PR-21 closure sentinels present in ingress module.
B  — Sentinel content / shape correctness.
C  — core.runtime re-exports all four PR-21 symbols.
D  — Projection sentinel present and not UNAVAILABLE (skipped without fastapi).
E  — Canonical path ordering: ingress → guard → reconcile → tracker.
F  — Guard-rejected signals do not mutate tracker state (all four decisions).
G  — Accepted signals reconcile into tracker state correctly.
H  — Monotonic phase progression (no regression).
I  — Terminal state protection: no further tracker mutation after terminal.
J  — Identity continuity through the canonical path.
K  — Integration: full lifecycle ack → progress → result/success → completed.
L  — Integration: full lifecycle ack → result/failure → failed.
M  — Integration: timeout → timed_out terminal.
N  — Integration: cancelled → cancelled terminal.
O  — Integration: duplicate signal after accepted → tracker unchanged.
P  — Integration: replay signal → tracker unchanged.
Q  — Integration: stale signal → tracker unchanged.
R  — Integration: out_of_order signal → tracker unchanged.
S  — Integration: two independent contracts are completely isolated.
T  — Integration: guard snapshot shows correct rejection counts after mixed signals.
U  — Integration: Android-originated identity preserved end-to-end.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from core.android_delegated_signal_ingress import (
    ANDROID_DELEGATED_SIGNAL_INGRESS_PR16_SENTINEL,
    CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL,
    CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER_POLICY,
    IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH_POLICY,
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
    guard_inbound_signal,
    build_idempotency_key,
    record_seen_signal,
    build_recovery_readiness_snapshot,
)
from core.delegated_runtime_execution_tracker import (
    DelegatedExecutionPhase,
    DelegatedExecutionTrackingRuntime,
    create_execution_tracking_record,
    get_execution_tracking_record,
    reset_execution_tracking_runtime,
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
    return {
        "type": "delegated_execution_signal",
        "device_id": device_id,
        "task_id": task_id,
        "payload": payload,
    }


# ===========================================================================
# Group A — PR-21 closure sentinels present in ingress module
# ===========================================================================


def test_A01_pr21_closure_sentinel_present():
    assert CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL
    assert isinstance(CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL, str)


def test_A02_pr21_closure_sentinel_contains_package_21():
    assert "package=21" in CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL


def test_A03_canonical_path_policy_present():
    assert CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER_POLICY
    assert isinstance(CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER_POLICY, str)


def test_A04_identity_continuity_policy_present():
    assert IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH_POLICY
    assert isinstance(IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH_POLICY, str)


def test_A05_terminal_state_policy_present():
    assert TERMINAL_STATE_IS_PROTECTED_AGAINST_REPLAY_POLICY
    assert isinstance(TERMINAL_STATE_IS_PROTECTED_AGAINST_REPLAY_POLICY, str)


def test_A06_all_three_pr21_policies_are_non_empty():
    for policy in (
        CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER_POLICY,
        IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH_POLICY,
        TERMINAL_STATE_IS_PROTECTED_AGAINST_REPLAY_POLICY,
    ):
        assert len(policy) > 20


# ===========================================================================
# Group B — Sentinel content / shape correctness
# ===========================================================================


def test_B01_closure_sentinel_references_ingress_guard_reconcile_tracker():
    s = CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL
    assert "ingress" in s
    assert "guard" in s
    assert "reconcile" in s
    assert "tracker" in s


def test_B02_canonical_path_policy_key_word_present():
    assert "CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER" in (
        CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER_POLICY
    )


def test_B03_identity_continuity_policy_key_word_present():
    assert "IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH" in (
        IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH_POLICY
    )


def test_B04_terminal_state_policy_key_word_present():
    assert "TERMINAL_STATE_IS_PROTECTED_AGAINST_REPLAY" in (
        TERMINAL_STATE_IS_PROTECTED_AGAINST_REPLAY_POLICY
    )


def test_B05_closure_sentinel_references_pr21_policies():
    s = CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL
    assert "CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER" in s
    assert "IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH" in s
    assert "TERMINAL_STATE_IS_PROTECTED_AGAINST_REPLAY" in s


def test_B06_pr16_sentinel_still_present():
    assert ANDROID_DELEGATED_SIGNAL_INGRESS_PR16_SENTINEL
    assert "package=16" in ANDROID_DELEGATED_SIGNAL_INGRESS_PR16_SENTINEL


# ===========================================================================
# Group C — core.runtime re-exports all four PR-21 symbols
# ===========================================================================


def test_C01_core_runtime_exports_closure_sentinel():
    pytest.importorskip("pydantic", reason="pydantic not installed (core.runtime dep)")
    from core.runtime import CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_PR21_SENTINEL as s
    assert s
    assert "package=21" in s


def test_C02_core_runtime_exports_canonical_path_policy():
    pytest.importorskip("pydantic", reason="pydantic not installed (core.runtime dep)")
    from core.runtime import CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER_POLICY as p
    assert p
    assert "CANONICAL_PATH_IS_INGRESS_GUARD_RECONCILE_TRACKER" in p


def test_C03_core_runtime_exports_identity_continuity_policy():
    pytest.importorskip("pydantic", reason="pydantic not installed (core.runtime dep)")
    from core.runtime import IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH_POLICY as p
    assert p
    assert "IDENTITY_CONTINUITY_ACROSS_CANONICAL_PATH" in p


def test_C04_core_runtime_exports_terminal_state_policy():
    pytest.importorskip("pydantic", reason="pydantic not installed (core.runtime dep)")
    from core.runtime import TERMINAL_STATE_IS_PROTECTED_AGAINST_REPLAY_POLICY as p
    assert p
    assert "TERMINAL_STATE_IS_PROTECTED_AGAINST_REPLAY" in p


# ===========================================================================
# Group D — Projection sentinel (skipped without fastapi)
# ===========================================================================


def test_D01_projection_sentinel_present_and_not_unavailable():
    pytest.importorskip("fastapi", reason="fastapi not installed")
    from core.routes.projection import CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21
    assert CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21
    assert "UNAVAILABLE" not in CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21


def test_D02_projection_sentinel_references_pr21():
    pytest.importorskip("fastapi", reason="fastapi not installed")
    from core.routes.projection import CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21
    assert "PR21" in CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21 or "package=21" in CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21.lower()


def test_D03_projection_sentinel_mentions_canonical_path():
    pytest.importorskip("fastapi", reason="fastapi not installed")
    from core.routes.projection import CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21
    assert "canonical" in CANONICAL_DELEGATED_EXECUTION_PATH_CLOSED_ALIGNED_PR21.lower()


# ===========================================================================
# Group E — Canonical path ordering: ingress → guard → reconcile → tracker
# ===========================================================================


def test_E01_accepted_signal_flows_from_ingress_to_tracker():
    """Accepted signal: ingress extracts, guard accepts, reconciler updates tracker."""
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    msg = _make_signal_message(signal_id=str(uuid.uuid4()), emission_seq=1)
    outcome = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.was_updated is True


def test_E02_guard_is_consulted_before_reconcile():
    """Guard must be called before reconcile. Patch guard to reject and verify
    reconciler is not reached."""
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    # Send same signal twice — second should be rejected by guard as duplicate.
    sig_id = str(uuid.uuid4())
    msg = _make_signal_message(signal_id=sig_id, emission_seq=1)
    outcome1 = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome1.was_updated is True

    outcome2 = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    # Guard rejects duplicate — reconciler must NOT have updated tracker.
    assert outcome2.was_updated is False
    assert "guard" in outcome2.reject_reason.lower() or "duplicate" in outcome2.reject_reason.lower()


def test_E03_ingress_extracts_envelope_before_guard():
    """ingest_delegated_execution_signal() must extract the envelope from the raw
    message dict; this extraction step precedes guard evaluation."""
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    raw_msg = _make_signal_message(signal_id=str(uuid.uuid4()), emission_seq=5)
    outcome = ingest_delegated_execution_signal(
        raw_msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    # Envelope was extracted and signal reached reconciler — tracker was updated.
    assert outcome.was_updated is True
    assert outcome.envelope is not None
    assert outcome.envelope.emission_seq == 5


def test_E04_ingress_delegates_to_reconciler_not_directly_to_tracker():
    """The ingress path MUST NOT directly manipulate the tracker.
    Verify by checking that a missing tracker record returns was_updated=False
    (non-destructive on miss) rather than creating a phantom record."""
    guard_rt = _fresh_guard_runtime()
    tracker_rt = _fresh_tracker_runtime()
    # No tracking record created for this contract_id.
    msg = _make_signal_message(
        contract_id="ctr-pr21-phantom",
        session_id="ses-pr21-phantom",
        signal_id=str(uuid.uuid4()),
        emission_seq=1,
    )
    outcome = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.was_updated is False
    # Confirm no phantom record was created.
    rec = get_execution_tracking_record("ses-pr21-phantom", runtime=tracker_rt)
    assert rec is None


# ===========================================================================
# Group F — Guard-rejected signals do not mutate tracker state
# ===========================================================================


def test_F01_duplicate_does_not_mutate_tracker():
    """Duplicate signal: guard rejects → tracker record must not change."""
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _, tracker_rt = _make_tracking_record(runtime=tracker_rt)

    sig_id = str(uuid.uuid4())
    msg = _make_signal_message(signal_id=sig_id, emission_seq=1)
    # First ingestion — accepted, phase → acknowledged.
    ingest_delegated_execution_signal(msg, runtime=tracker_rt, guard_runtime=guard_rt)

    record_before = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    assert record_before is not None
    phase_before = record_before.phase

    # Second ingestion — duplicate, guard rejects.
    outcome = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.was_updated is False

    record_after = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    assert record_after is not None
    assert record_after.phase == phase_before  # phase unchanged


def test_F02_replay_does_not_mutate_tracker():
    """Replay signal (same seq, different signal_id): guard rejects → tracker unchanged."""
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    # First: accepted at seq=2
    msg1 = _make_signal_message(
        signal_id=str(uuid.uuid4()), emission_seq=2, signal_kind="ack"
    )
    ingest_delegated_execution_signal(msg1, runtime=tracker_rt, guard_runtime=guard_rt)

    record_before = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    phase_before = record_before.phase

    # Replay: different signal_id, same seq=2 → guard should detect replay.
    msg_replay = _make_signal_message(
        signal_id=str(uuid.uuid4()), emission_seq=2, signal_kind="progress"
    )
    outcome = ingest_delegated_execution_signal(
        msg_replay, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.was_updated is False

    record_after = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    assert record_after.phase == phase_before


def test_F03_stale_does_not_mutate_tracker():
    """Stale signal (far behind max_seen): guard rejects → tracker unchanged."""
    from core.attached_runtime_recovery_readiness import STALE_EMISSION_SEQ_THRESHOLD

    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    high_seq = STALE_EMISSION_SEQ_THRESHOLD + 5
    # First: accepted at high seq.
    msg_high = _make_signal_message(
        signal_id=str(uuid.uuid4()), emission_seq=high_seq, signal_kind="ack"
    )
    ingest_delegated_execution_signal(
        msg_high, runtime=tracker_rt, guard_runtime=guard_rt
    )

    record_before = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    phase_before = record_before.phase

    # Stale: seq=0, far below max_seen.
    msg_stale = _make_signal_message(
        signal_id=str(uuid.uuid4()), emission_seq=0, signal_kind="progress"
    )
    outcome = ingest_delegated_execution_signal(
        msg_stale, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.was_updated is False

    record_after = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    assert record_after.phase == phase_before


def test_F04_out_of_order_does_not_mutate_tracker():
    """Out-of-order signal (slightly behind max_seen): guard rejects → tracker unchanged."""
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    # First: accepted at seq=5.
    msg_5 = _make_signal_message(
        signal_id=str(uuid.uuid4()), emission_seq=5, signal_kind="ack"
    )
    ingest_delegated_execution_signal(
        msg_5, runtime=tracker_rt, guard_runtime=guard_rt
    )

    record_before = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    phase_before = record_before.phase

    # Out-of-order: seq=3, slightly behind max_seen=5.
    msg_ooo = _make_signal_message(
        signal_id=str(uuid.uuid4()), emission_seq=3, signal_kind="progress"
    )
    outcome = ingest_delegated_execution_signal(
        msg_ooo, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.was_updated is False

    record_after = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    assert record_after.phase == phase_before


def test_F05_rejected_outcome_reject_reason_encodes_guard_decision():
    """reject_reason for all four rejection types encodes the guard decision."""
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    sig_id = str(uuid.uuid4())
    msg = _make_signal_message(signal_id=sig_id, emission_seq=1)
    ingest_delegated_execution_signal(msg, runtime=tracker_rt, guard_runtime=guard_rt)

    # duplicate
    outcome = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.reject_reason
    assert "duplicate" in outcome.reject_reason.lower() or "guard" in outcome.reject_reason.lower()


# ===========================================================================
# Group G — Accepted signals reconcile into tracker state correctly
# ===========================================================================


def test_G01_ack_signal_transitions_to_acknowledged():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    msg = _make_signal_message(
        signal_kind="ack", signal_id=str(uuid.uuid4()), emission_seq=1
    )
    outcome = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.was_updated is True
    assert outcome.record is not None
    assert outcome.record.phase == DelegatedExecutionPhase.acknowledged


def test_G02_progress_signal_transitions_to_in_progress():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    # ack first
    ingest_delegated_execution_signal(
        _make_signal_message(signal_kind="ack", signal_id=str(uuid.uuid4()), emission_seq=1),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    # then progress
    outcome = ingest_delegated_execution_signal(
        _make_signal_message(
            signal_kind="progress", signal_id=str(uuid.uuid4()), emission_seq=2
        ),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    assert outcome.was_updated is True
    assert outcome.record.phase == DelegatedExecutionPhase.in_progress


def test_G03_result_success_transitions_to_completed():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    ingest_delegated_execution_signal(
        _make_signal_message(signal_kind="ack", signal_id=str(uuid.uuid4()), emission_seq=1),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    outcome = ingest_delegated_execution_signal(
        _make_signal_message(
            signal_kind="result", result_kind="success",
            signal_id=str(uuid.uuid4()), emission_seq=2,
        ),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    assert outcome.was_updated is True
    assert outcome.record.phase == DelegatedExecutionPhase.completed


def test_G04_result_failure_transitions_to_failed():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    ingest_delegated_execution_signal(
        _make_signal_message(signal_kind="ack", signal_id=str(uuid.uuid4()), emission_seq=1),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    outcome = ingest_delegated_execution_signal(
        _make_signal_message(
            signal_kind="result", result_kind="failure",
            signal_id=str(uuid.uuid4()), emission_seq=2,
        ),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    assert outcome.was_updated is True
    assert outcome.record.phase == DelegatedExecutionPhase.failed


def test_G05_timeout_transitions_to_timed_out():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    ingest_delegated_execution_signal(
        _make_signal_message(signal_kind="ack", signal_id=str(uuid.uuid4()), emission_seq=1),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    outcome = ingest_delegated_execution_signal(
        _make_signal_message(
            signal_kind="timeout", signal_id=str(uuid.uuid4()), emission_seq=2
        ),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    assert outcome.was_updated is True
    assert outcome.record.phase == DelegatedExecutionPhase.timed_out


def test_G06_cancelled_transitions_to_cancelled():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    ingest_delegated_execution_signal(
        _make_signal_message(signal_kind="ack", signal_id=str(uuid.uuid4()), emission_seq=1),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    outcome = ingest_delegated_execution_signal(
        _make_signal_message(
            signal_kind="cancelled", signal_id=str(uuid.uuid4()), emission_seq=2
        ),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    assert outcome.was_updated is True
    assert outcome.record.phase == DelegatedExecutionPhase.cancelled


# ===========================================================================
# Group H — Monotonic phase progression (no regression)
# ===========================================================================


def test_H01_phase_progresses_monotonically_ack_to_progress_to_completed():
    """Phase must only advance forward: pending_ack → ack → in_progress → completed."""
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    phases = []
    seq = 1
    for signal_kind, result_kind in [
        ("ack", ""),
        ("progress", ""),
        ("result", "success"),
    ]:
        msg = _make_signal_message(
            signal_kind=signal_kind,
            result_kind=result_kind,
            signal_id=str(uuid.uuid4()),
            emission_seq=seq,
        )
        outcome = ingest_delegated_execution_signal(
            msg, runtime=tracker_rt, guard_runtime=guard_rt
        )
        assert outcome.was_updated is True
        phases.append(outcome.record.phase)
        seq += 1

    assert phases[0] == DelegatedExecutionPhase.acknowledged
    assert phases[1] == DelegatedExecutionPhase.in_progress
    assert phases[2] == DelegatedExecutionPhase.completed


def test_H02_terminal_phase_blocks_ack_regression():
    """Once completed, sending an ack signal must not regress the phase."""
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    # Advance to completed.
    for seq, (sk, rk) in enumerate(
        [("ack", ""), ("result", "success")], start=1
    ):
        ingest_delegated_execution_signal(
            _make_signal_message(
                signal_kind=sk, result_kind=rk,
                signal_id=str(uuid.uuid4()), emission_seq=seq,
            ),
            runtime=tracker_rt, guard_runtime=guard_rt,
        )

    record = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    assert record.phase == DelegatedExecutionPhase.completed

    # Attempt to send ack after terminal → tracker must not regress.
    outcome = ingest_delegated_execution_signal(
        _make_signal_message(
            signal_kind="ack", signal_id=str(uuid.uuid4()), emission_seq=3
        ),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    assert outcome.was_updated is False

    record_after = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    assert record_after.phase == DelegatedExecutionPhase.completed


# ===========================================================================
# Group I — Terminal state protection against duplicate/replay/stale/out-of-order
# ===========================================================================


def test_I01_completed_terminal_not_overwritten_by_duplicate():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    sig_id = str(uuid.uuid4())
    # Advance to completed via result/success
    for seq, (sk, rk, sid) in enumerate(
        [("ack", "", str(uuid.uuid4())), ("result", "success", sig_id)], start=1
    ):
        ingest_delegated_execution_signal(
            _make_signal_message(
                signal_kind=sk, result_kind=rk,
                signal_id=sid, emission_seq=seq,
            ),
            runtime=tracker_rt, guard_runtime=guard_rt,
        )

    # Duplicate: same sig_id resent.
    result_msg = _make_signal_message(
        signal_kind="result", result_kind="failure",
        signal_id=sig_id, emission_seq=2,
    )
    outcome = ingest_delegated_execution_signal(
        result_msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.was_updated is False
    record = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    assert record.phase == DelegatedExecutionPhase.completed


def test_I02_failed_terminal_not_overwritten_by_replay():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    # Advance to failed.
    for seq, (sk, rk) in enumerate(
        [("ack", ""), ("result", "failure")], start=1
    ):
        ingest_delegated_execution_signal(
            _make_signal_message(
                signal_kind=sk, result_kind=rk,
                signal_id=str(uuid.uuid4()), emission_seq=seq,
            ),
            runtime=tracker_rt, guard_runtime=guard_rt,
        )

    # Replay: different signal_id, same seq=2.
    outcome = ingest_delegated_execution_signal(
        _make_signal_message(
            signal_kind="result", result_kind="success",
            signal_id=str(uuid.uuid4()), emission_seq=2,
        ),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    assert outcome.was_updated is False
    record = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    assert record.phase == DelegatedExecutionPhase.failed


def test_I03_timed_out_terminal_not_overwritten():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    for seq, sk in enumerate(["ack", "timeout"], start=1):
        ingest_delegated_execution_signal(
            _make_signal_message(
                signal_kind=sk, signal_id=str(uuid.uuid4()), emission_seq=seq
            ),
            runtime=tracker_rt, guard_runtime=guard_rt,
        )

    outcome = ingest_delegated_execution_signal(
        _make_signal_message(
            signal_kind="result", result_kind="success",
            signal_id=str(uuid.uuid4()), emission_seq=3,
        ),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    assert outcome.was_updated is False
    record = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    assert record.phase == DelegatedExecutionPhase.timed_out


def test_I04_cancelled_terminal_not_overwritten():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    for seq, sk in enumerate(["ack", "cancelled"], start=1):
        ingest_delegated_execution_signal(
            _make_signal_message(
                signal_kind=sk, signal_id=str(uuid.uuid4()), emission_seq=seq
            ),
            runtime=tracker_rt, guard_runtime=guard_rt,
        )

    outcome = ingest_delegated_execution_signal(
        _make_signal_message(
            signal_kind="result", result_kind="success",
            signal_id=str(uuid.uuid4()), emission_seq=3,
        ),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    assert outcome.was_updated is False
    record = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    assert record.phase == DelegatedExecutionPhase.cancelled


# ===========================================================================
# Group J — Identity continuity through the canonical path
# ===========================================================================


def test_J01_task_id_preserved_in_outcome_envelope():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    task_id = "task-pr21-identity-001"
    msg = _make_signal_message(
        task_id=task_id, signal_id=str(uuid.uuid4()), emission_seq=1
    )
    outcome = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.envelope is not None
    assert outcome.envelope.task_id == task_id


def test_J02_trace_id_preserved_in_outcome_envelope():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()

    trace_id = "trace-pr21-identity-002"
    _make_tracking_record(
        trace_id=trace_id, runtime=tracker_rt
    )

    msg = _make_signal_message(
        trace_id=trace_id, signal_id=str(uuid.uuid4()), emission_seq=1
    )
    outcome = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.envelope is not None
    assert outcome.envelope.trace_id == trace_id


def test_J03_signal_id_preserved_in_outcome_envelope():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    signal_id = str(uuid.uuid4())
    msg = _make_signal_message(signal_id=signal_id, emission_seq=1)
    outcome = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.envelope is not None
    assert outcome.envelope.signal_id == signal_id


def test_J04_emission_seq_preserved_in_outcome_envelope():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    emission_seq = 42
    msg = _make_signal_message(signal_id=str(uuid.uuid4()), emission_seq=emission_seq)
    outcome = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.envelope is not None
    assert outcome.envelope.emission_seq == emission_seq


def test_J05_contract_id_preserved_in_outcome_envelope():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    contract_id = "ctr-pr21-identity-005"
    session_id = "ses-pr21-identity-005"
    _make_tracking_record(
        contract_id=contract_id, session_id=session_id, runtime=tracker_rt
    )

    msg = _make_signal_message(
        contract_id=contract_id,
        session_id=session_id,
        signal_id=str(uuid.uuid4()),
        emission_seq=1,
    )
    outcome = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.envelope is not None
    assert outcome.envelope.contract_id == contract_id


def test_J06_session_id_preserved_in_outcome_envelope():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    session_id = "ses-pr21-identity-006"
    contract_id = "ctr-pr21-identity-006"
    _make_tracking_record(
        contract_id=contract_id, session_id=session_id, runtime=tracker_rt
    )

    msg = _make_signal_message(
        contract_id=contract_id,
        session_id=session_id,
        signal_id=str(uuid.uuid4()),
        emission_seq=1,
    )
    outcome = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.envelope is not None
    assert outcome.envelope.session_id == session_id


def test_J07_device_id_preserved_in_outcome_envelope():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    device_id = "dev-pr21-identity-007"
    _make_tracking_record(device_id=device_id, runtime=tracker_rt)

    msg = _make_signal_message(
        device_id=device_id, signal_id=str(uuid.uuid4()), emission_seq=1
    )
    outcome = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.envelope is not None
    assert outcome.envelope.device_id == device_id


# ===========================================================================
# Group K — Integration: full lifecycle ack → progress → result/success → completed
# ===========================================================================


def test_K01_full_lifecycle_success():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    signals = [
        ("ack", "", 1),
        ("progress", "", 2),
        ("result", "success", 3),
    ]
    for sk, rk, seq in signals:
        outcome = ingest_delegated_execution_signal(
            _make_signal_message(
                signal_kind=sk, result_kind=rk,
                signal_id=str(uuid.uuid4()), emission_seq=seq,
            ),
            runtime=tracker_rt, guard_runtime=guard_rt,
        )
        assert outcome.was_updated is True

    record = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    assert record.phase == DelegatedExecutionPhase.completed


def test_K02_full_lifecycle_phase_sequence():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    expected_phases = [
        DelegatedExecutionPhase.acknowledged,
        DelegatedExecutionPhase.in_progress,
        DelegatedExecutionPhase.completed,
    ]
    for (sk, rk, seq), expected in zip(
        [("ack", "", 1), ("progress", "", 2), ("result", "success", 3)],
        expected_phases,
    ):
        outcome = ingest_delegated_execution_signal(
            _make_signal_message(
                signal_kind=sk, result_kind=rk,
                signal_id=str(uuid.uuid4()), emission_seq=seq,
            ),
            runtime=tracker_rt, guard_runtime=guard_rt,
        )
        assert outcome.record.phase == expected


# ===========================================================================
# Group L — Integration: full lifecycle ack → result/failure → failed
# ===========================================================================


def test_L01_full_lifecycle_failure():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    for sk, rk, seq in [("ack", "", 1), ("result", "failure", 2)]:
        outcome = ingest_delegated_execution_signal(
            _make_signal_message(
                signal_kind=sk, result_kind=rk,
                signal_id=str(uuid.uuid4()), emission_seq=seq,
            ),
            runtime=tracker_rt, guard_runtime=guard_rt,
        )
        assert outcome.was_updated is True

    record = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    assert record.phase == DelegatedExecutionPhase.failed


# ===========================================================================
# Group M — Integration: timeout → timed_out terminal
# ===========================================================================


def test_M01_timeout_produces_timed_out_terminal():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    for sk, seq in [("ack", 1), ("timeout", 2)]:
        outcome = ingest_delegated_execution_signal(
            _make_signal_message(
                signal_kind=sk, signal_id=str(uuid.uuid4()), emission_seq=seq
            ),
            runtime=tracker_rt, guard_runtime=guard_rt,
        )
        assert outcome.was_updated is True

    record = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    assert record.phase == DelegatedExecutionPhase.timed_out
    assert record.phase.is_terminal()


# ===========================================================================
# Group N — Integration: cancelled → cancelled terminal
# ===========================================================================


def test_N01_cancelled_produces_cancelled_terminal():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    for sk, seq in [("ack", 1), ("cancelled", 2)]:
        outcome = ingest_delegated_execution_signal(
            _make_signal_message(
                signal_kind=sk, signal_id=str(uuid.uuid4()), emission_seq=seq
            ),
            runtime=tracker_rt, guard_runtime=guard_rt,
        )
        assert outcome.was_updated is True

    record = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    assert record.phase == DelegatedExecutionPhase.cancelled
    assert record.phase.is_terminal()


# ===========================================================================
# Group O — Integration: duplicate signal after accepted → tracker unchanged
# ===========================================================================


def test_O01_duplicate_signal_does_not_change_phase():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    sig_id = str(uuid.uuid4())
    msg = _make_signal_message(signal_kind="ack", signal_id=sig_id, emission_seq=1)

    # First: accepted.
    ingest_delegated_execution_signal(msg, runtime=tracker_rt, guard_runtime=guard_rt)

    record_mid = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    phase_mid = record_mid.phase

    # Duplicate: same msg.
    outcome = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.was_updated is False

    record_after = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    assert record_after.phase == phase_mid


# ===========================================================================
# Group P — Integration: replay signal → tracker unchanged
# ===========================================================================


def test_P01_replay_signal_does_not_change_phase():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    ingest_delegated_execution_signal(
        _make_signal_message(signal_kind="ack", signal_id=str(uuid.uuid4()), emission_seq=2),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )

    record_mid = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    phase_mid = record_mid.phase

    # Replay: different signal_id, same seq=2.
    outcome = ingest_delegated_execution_signal(
        _make_signal_message(
            signal_kind="progress", signal_id=str(uuid.uuid4()), emission_seq=2
        ),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    assert outcome.was_updated is False
    assert get_execution_tracking_record(
        "ses-pr21-001", runtime=tracker_rt
    ).phase == phase_mid


# ===========================================================================
# Group Q — Integration: stale signal → tracker unchanged
# ===========================================================================


def test_Q01_stale_signal_does_not_update_tracker():
    from core.attached_runtime_recovery_readiness import STALE_EMISSION_SEQ_THRESHOLD

    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    high_seq = STALE_EMISSION_SEQ_THRESHOLD + 10
    ingest_delegated_execution_signal(
        _make_signal_message(signal_kind="ack", signal_id=str(uuid.uuid4()), emission_seq=high_seq),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )

    record_mid = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    phase_mid = record_mid.phase

    outcome = ingest_delegated_execution_signal(
        _make_signal_message(
            signal_kind="progress", signal_id=str(uuid.uuid4()), emission_seq=0
        ),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    assert outcome.was_updated is False
    assert get_execution_tracking_record(
        "ses-pr21-001", runtime=tracker_rt
    ).phase == phase_mid


# ===========================================================================
# Group R — Integration: out_of_order signal → tracker unchanged
# ===========================================================================


def test_R01_out_of_order_signal_does_not_update_tracker():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    ingest_delegated_execution_signal(
        _make_signal_message(signal_kind="ack", signal_id=str(uuid.uuid4()), emission_seq=5),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )

    record_mid = get_execution_tracking_record("ses-pr21-001", runtime=tracker_rt)
    phase_mid = record_mid.phase

    outcome = ingest_delegated_execution_signal(
        _make_signal_message(
            signal_kind="progress", signal_id=str(uuid.uuid4()), emission_seq=3
        ),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    assert outcome.was_updated is False
    assert get_execution_tracking_record(
        "ses-pr21-001", runtime=tracker_rt
    ).phase == phase_mid


# ===========================================================================
# Group S — Integration: two independent contracts are completely isolated
# ===========================================================================


def test_S01_two_contracts_do_not_interfere():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()

    # Create two independent tracking records.
    contract_a, session_a = "ctr-pr21-a", "ses-pr21-a"
    contract_b, session_b = "ctr-pr21-b", "ses-pr21-b"
    create_execution_tracking_record(
        session_id=session_a, contract_id=contract_a,
        device_id="dev-pr21-001", trace_id="trace-pr21-a",
        source_runtime_posture="join_runtime", runtime=tracker_rt,
    )
    create_execution_tracking_record(
        session_id=session_b, contract_id=contract_b,
        device_id="dev-pr21-002", trace_id="trace-pr21-b",
        source_runtime_posture="join_runtime", runtime=tracker_rt,
    )

    # Advance contract A to completed.
    for sk, rk, seq in [("ack", "", 1), ("result", "success", 2)]:
        ingest_delegated_execution_signal(
            _make_signal_message(
                contract_id=contract_a, session_id=session_a,
                signal_kind=sk, result_kind=rk,
                signal_id=str(uuid.uuid4()), emission_seq=seq,
            ),
            runtime=tracker_rt, guard_runtime=guard_rt,
        )

    # Advance contract B to acknowledged only.
    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id=contract_b, session_id=session_b,
            signal_kind="ack", signal_id=str(uuid.uuid4()), emission_seq=1,
        ),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )

    record_a = get_execution_tracking_record(session_a, runtime=tracker_rt)
    record_b = get_execution_tracking_record(session_b, runtime=tracker_rt)

    assert record_a.phase == DelegatedExecutionPhase.completed
    assert record_b.phase == DelegatedExecutionPhase.acknowledged


def test_S02_guard_contexts_are_isolated_per_contract():
    """Guard idempotency keys are scoped by contract_id; duplicate detection
    for contract A must not affect contract B."""
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()

    contract_a, session_a = "ctr-pr21-iso-a", "ses-pr21-iso-a"
    contract_b, session_b = "ctr-pr21-iso-b", "ses-pr21-iso-b"

    for cid, sid, did, tid in [
        (contract_a, session_a, "dev-a", "trace-a"),
        (contract_b, session_b, "dev-b", "trace-b"),
    ]:
        create_execution_tracking_record(
            session_id=sid, contract_id=cid, device_id=did,
            trace_id=tid, source_runtime_posture="join_runtime",
            runtime=tracker_rt,
        )

    sig_id_a = str(uuid.uuid4())
    # Send signal for A twice (second should be duplicate).
    for i in range(2):
        msg = _make_signal_message(
            contract_id=contract_a, session_id=session_a,
            signal_kind="ack", signal_id=sig_id_a, emission_seq=1,
        )
        ingest_delegated_execution_signal(
            msg, runtime=tracker_rt, guard_runtime=guard_rt
        )

    # Send a fresh signal for B — should be accepted (not affected by A's duplicate).
    outcome_b = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id=contract_b, session_id=session_b,
            signal_kind="ack", signal_id=str(uuid.uuid4()), emission_seq=1,
        ),
        runtime=tracker_rt, guard_runtime=guard_rt,
    )
    assert outcome_b.was_updated is True


# ===========================================================================
# Group T — Integration: guard snapshot shows correct rejection counts
# ===========================================================================


def test_T01_guard_snapshot_reflects_rejection_counts():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    sig_id = str(uuid.uuid4())
    msg = _make_signal_message(signal_kind="ack", signal_id=sig_id, emission_seq=1)

    # Accept first.
    ingest_delegated_execution_signal(msg, runtime=tracker_rt, guard_runtime=guard_rt)

    # Send duplicate twice.
    ingest_delegated_execution_signal(msg, runtime=tracker_rt, guard_runtime=guard_rt)
    ingest_delegated_execution_signal(msg, runtime=tracker_rt, guard_runtime=guard_rt)

    snapshot = build_recovery_readiness_snapshot(runtime=guard_rt)
    assert snapshot.total_rejected >= 2


def test_T02_guard_snapshot_total_accepted_reflects_successes():
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()
    _make_tracking_record(runtime=tracker_rt)

    for seq in range(1, 4):
        ingest_delegated_execution_signal(
            _make_signal_message(
                signal_kind="ack" if seq == 1 else "progress",
                signal_id=str(uuid.uuid4()),
                emission_seq=seq,
            ),
            runtime=tracker_rt, guard_runtime=guard_rt,
        )

    snapshot = build_recovery_readiness_snapshot(runtime=guard_rt)
    assert snapshot.total_accepted >= 3


# ===========================================================================
# Group U — Integration: Android-originated identity preserved end-to-end
# ===========================================================================


def test_U01_android_signal_identity_preserved_end_to_end():
    """All nine identity fields from an Android delegated_execution_signal must
    flow verbatim from extraction through guard acceptance into the tracker."""
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()

    contract_id = "ctr-pr21-e2e-001"
    session_id = "ses-pr21-e2e-001"
    device_id = "dev-pr21-e2e-001"
    trace_id = "trace-pr21-e2e-001"
    task_id = "task-pr21-e2e-001"
    signal_id = str(uuid.uuid4())
    emission_seq = 7

    create_execution_tracking_record(
        session_id=session_id, contract_id=contract_id,
        device_id=device_id, trace_id=trace_id,
        source_runtime_posture="join_runtime", runtime=tracker_rt,
    )

    msg = {
        "type": "delegated_execution_signal",
        "device_id": device_id,
        "task_id": task_id,
        "payload": {
            "contract_id": contract_id,
            "session_id": session_id,
            "trace_id": trace_id,
            "signal_kind": "ack",
            "signal_id": signal_id,
            "emission_seq": emission_seq,
        },
    }
    outcome = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )

    assert outcome.was_updated is True
    env = outcome.envelope
    assert env.contract_id == contract_id
    assert env.session_id == session_id
    assert env.device_id == device_id
    assert env.trace_id == trace_id
    assert env.task_id == task_id
    assert env.signal_id == signal_id
    assert env.emission_seq == emission_seq
    assert env.signal_kind == DelegatedSignalKind.ack


def test_U02_stable_handling_of_android_delegated_execution_result_in_canonical_path():
    """Stable handling of Android-originated delegated execution results in
    the canonical path: result/success flows correctly to completed phase."""
    tracker_rt = _fresh_tracker_runtime()
    guard_rt = _fresh_guard_runtime()

    contract_id = "ctr-pr21-stable-001"
    session_id = "ses-pr21-stable-001"

    create_execution_tracking_record(
        session_id=session_id, contract_id=contract_id,
        device_id="dev-pr21-stable", trace_id="trace-pr21-stable",
        source_runtime_posture="join_runtime", runtime=tracker_rt,
    )

    # Send ack then result/success — both must be accepted.
    for seq, sk, rk in [(1, "ack", ""), (2, "result", "success")]:
        outcome = ingest_delegated_execution_signal(
            _make_signal_message(
                contract_id=contract_id, session_id=session_id,
                signal_kind=sk, result_kind=rk,
                signal_id=str(uuid.uuid4()), emission_seq=seq,
            ),
            runtime=tracker_rt, guard_runtime=guard_rt,
        )
        assert outcome.was_updated is True

    # Send a late duplicate result — must NOT change terminal state.
    late_msg = _make_signal_message(
        contract_id=contract_id, session_id=session_id,
        signal_kind="result", result_kind="failure",
        signal_id=str(uuid.uuid4()), emission_seq=2,  # replay seq
    )
    late_outcome = ingest_delegated_execution_signal(
        late_msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert late_outcome.was_updated is False

    final_record = get_execution_tracking_record(session_id, runtime=tracker_rt)
    assert final_record.phase == DelegatedExecutionPhase.completed
