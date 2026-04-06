"""tests/test_pr18_post533_ingress_recovery_guard.py
====================================================
Tests for PR package 18 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Ingress Recovery Guard before Android Signal Reconciliation.

This test suite verifies that:

1. The recovery-readiness guard module (PR-15) exists with the correct public
   API (enums, dataclasses, functions, sentinels).
2. ``ingest_delegated_execution_signal()`` calls ``guard_inbound_signal()``
   before forwarding any signal to the reconciler.
3. All four rejection decisions are handled correctly:
   - ``duplicate`` → was_updated=False, reject_reason encodes "guard:duplicate"
   - ``replay``    → was_updated=False, reject_reason encodes "guard:replay"
   - ``stale``     → was_updated=False, reject_reason encodes "guard:stale"
   - ``out_of_order`` → was_updated=False, reject_reason encodes "guard:out_of_order"
4. Rejected signals do not mutate the host-side tracker record.
5. Accepted signals flow through to reconciliation as before.
6. Observability: guard decisions are returned in the outcome's reject_reason
   and the RecoveryReadinessSnapshot captures rejection counts.
7. Projection sentinel is present and not UNAVAILABLE.
8. core.runtime re-exports all PR-15 symbols.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — SignalGuardDecision enum: all values, from_string(), is_rejected().
C  — RecoveryReadinessStatus enum: all values.
D  — IdempotencyKey: construction, context_key derivation, has_context(), to_dict().
E  — SeenSignalRecord: construction, to_dict().
F  — SignalGuardOutcome: construction, is_accepted(), to_dict().
G  — RecoveryReadinessSnapshot: construction, to_dict().
H  — RecoveryReadinessRuntime: initial state, has_signal_id(), get_max_seq().
I  — RecoveryReadinessRuntime.record(): updates signal_id index and seq index.
J  — RecoveryReadinessRuntime.record(): FIFO eviction at capacity.
K  — RecoveryReadinessRuntime.record_rejection(): increments rejection counters.
L  — RecoveryReadinessRuntime.build_snapshot(): correct counts and status.
M  — build_idempotency_key(): correct field mapping and context_key derivation.
N  — check_signal_guard(): accept when no prior context.
O  — check_signal_guard(): duplicate detection via signal_id.
P  — check_signal_guard(): replay detection (same seq, different signal_id).
Q  — check_signal_guard(): stale detection (far behind max_seen).
R  — check_signal_guard(): out_of_order detection (slightly behind max_seen).
S  — check_signal_guard(): accept when emission_seq > max_seen.
T  — record_seen_signal(): adds entry to runtime.
U  — guard_inbound_signal(): accept path returns accept decision.
V  — guard_inbound_signal(): duplicate path returns duplicate decision.
W  — guard_inbound_signal(): replay path returns replay decision.
X  — guard_inbound_signal(): stale path returns stale decision.
Y  — guard_inbound_signal(): out_of_order path returns out_of_order decision.
Z  — guard_inbound_signal(): reject_reason is non-empty for rejected signals.
AA — guard_inbound_signal(): outcome carries idempotency_key and emission_seq.
AB — guard_inbound_signal(): max_seen_seq in outcome reflects prior state.
AC — guard_inbound_signal(): accepted signal is recorded into runtime.
AD — guard_inbound_signal(): rejected signals NOT recorded into runtime.
AE — guard_inbound_signal(): dict envelope support.
AF — guard_inbound_signal(): empty signal_id still checks seq-based guards.
AG — ingest_delegated_execution_signal(): accept path → reconcile succeeds.
AH — ingest_delegated_execution_signal(): duplicate → was_updated=False, no tracker mutation.
AI — ingest_delegated_execution_signal(): replay → was_updated=False, no tracker mutation.
AJ — ingest_delegated_execution_signal(): stale → was_updated=False, no tracker mutation.
AK — ingest_delegated_execution_signal(): out_of_order → was_updated=False, no tracker mutation.
AL — ingest_delegated_execution_signal(): reject_reason encodes guard decision.
AM — ingest_delegated_execution_signal(): rejected signals do not pollute tracker phase.
AN — Integration: full lifecycle accept path (ack→progress→result/success→completed).
AO — Integration: duplicate signal sent twice → second rejected, tracker not mutated.
AP — Integration: out_of_order signal skipped, next in-order accepted.
AQ — Integration: stale signal (emission_seq far behind max) rejected.
AR — Integration: replay (same seq, new signal_id) rejected.
AS — Integration: two independent contracts are guard-isolated.
AT — Integration: guard snapshot shows correct counts after mixed signals.
AU — Observability: build_recovery_readiness_snapshot() returns RecoveryReadinessSnapshot.
AV — Observability: snapshot reflects rejection counts per decision.
AW — core.runtime re-exports: all PR-15 symbols accessible from core.runtime.
AX — projection.py sentinel: INGRESS_RECOVERY_GUARD_ALIGNED_PR18 present and not UNAVAILABLE.
AY — All 11 policy sentinels are non-empty strings.
AZ — ATTACHED_RUNTIME_RECOVERY_READINESS_PR15_SENTINEL contains 'package=15'.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

import pytest

from core.attached_runtime_recovery_readiness import (
    ATTACHED_RUNTIME_RECOVERY_READINESS_AUTHORITY,
    ATTACHED_RUNTIME_RECOVERY_READINESS_PR15_SENTINEL,
    GUARD_MUST_PRECEDE_RECONCILE_POLICY,
    DUPLICATE_SIGNAL_ID_IS_REJECTED_POLICY,
    REPLAY_AT_SAME_SEQ_IS_REJECTED_POLICY,
    STALE_EMISSION_SEQ_IS_REJECTED_POLICY,
    OUT_OF_ORDER_EMISSION_SEQ_IS_REJECTED_POLICY,
    ACCEPTED_SIGNAL_IS_RECORDED_POLICY,
    GUARD_DECISION_IS_OBSERVABLE_POLICY,
    RING_BUFFER_IS_BOUNDED_POLICY,
    IDEMPOTENCY_KEY_USES_SIGNAL_ID_AND_CONTEXT_POLICY,
    SEQ_INDEX_TRACKS_MAX_PER_CONTEXT_POLICY,
    REJECTED_SIGNAL_MUST_NOT_REACH_TRACKER_POLICY,
    RECOVERY_READINESS_RING_BUFFER_SIZE,
    STALE_EMISSION_SEQ_THRESHOLD,
    SignalGuardDecision,
    RecoveryReadinessStatus,
    IdempotencyKey,
    SeenSignalRecord,
    SignalGuardOutcome,
    RecoveryReadinessSnapshot,
    RecoveryReadinessRuntime,
    build_idempotency_key,
    check_signal_guard,
    record_seen_signal,
    guard_inbound_signal,
    build_recovery_readiness_snapshot,
    get_recovery_readiness_runtime,
    reset_recovery_readiness_runtime,
)
from core.android_delegated_signal_ingress import (
    INGRESS_RECOVERY_GUARD_IS_MANDATORY_POLICY,
    INGRESS_GUARD_REJECTED_SIGNAL_IS_DROPPED_POLICY,
    ingest_delegated_execution_signal,
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

_ALL_GUARD_POLICIES = [
    GUARD_MUST_PRECEDE_RECONCILE_POLICY,
    DUPLICATE_SIGNAL_ID_IS_REJECTED_POLICY,
    REPLAY_AT_SAME_SEQ_IS_REJECTED_POLICY,
    STALE_EMISSION_SEQ_IS_REJECTED_POLICY,
    OUT_OF_ORDER_EMISSION_SEQ_IS_REJECTED_POLICY,
    ACCEPTED_SIGNAL_IS_RECORDED_POLICY,
    GUARD_DECISION_IS_OBSERVABLE_POLICY,
    RING_BUFFER_IS_BOUNDED_POLICY,
    IDEMPOTENCY_KEY_USES_SIGNAL_ID_AND_CONTEXT_POLICY,
    SEQ_INDEX_TRACKS_MAX_PER_CONTEXT_POLICY,
    REJECTED_SIGNAL_MUST_NOT_REACH_TRACKER_POLICY,
]


def _fresh_guard_runtime() -> RecoveryReadinessRuntime:
    """Return a fresh isolated guard runtime (not the process singleton)."""
    return RecoveryReadinessRuntime()


def _fresh_tracker_runtime() -> DelegatedExecutionTrackingRuntime:
    """Return a fresh isolated tracker runtime (not the process singleton)."""
    return DelegatedExecutionTrackingRuntime()


def _make_tracking_record(
    *,
    session_id: str = "ses-pr18-001",
    contract_id: str = "ctr-pr18-001",
    device_id: str = "dev-pr18-001",
    trace_id: str = "trace-pr18-001",
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
    device_id: str = "dev-pr18-001",
    task_id: str = "task-pr18-001",
    contract_id: str = "ctr-pr18-001",
    session_id: str = "ses-pr18-001",
    trace_id: str = "trace-pr18-001",
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
# Group A — Authority / policy sentinels
# ===========================================================================


def test_A01_authority_sentinel_present():
    assert ATTACHED_RUNTIME_RECOVERY_READINESS_AUTHORITY
    assert "PR15" in ATTACHED_RUNTIME_RECOVERY_READINESS_AUTHORITY


def test_A02_authority_sentinel_contains_recovery_readiness():
    assert "recovery-readiness" in ATTACHED_RUNTIME_RECOVERY_READINESS_AUTHORITY


def test_A03_ingress_guard_mandatory_policy_present():
    assert INGRESS_RECOVERY_GUARD_IS_MANDATORY_POLICY
    assert "INGRESS_RECOVERY_GUARD_IS_MANDATORY" in INGRESS_RECOVERY_GUARD_IS_MANDATORY_POLICY


def test_A04_ingress_guard_drop_policy_present():
    assert INGRESS_GUARD_REJECTED_SIGNAL_IS_DROPPED_POLICY
    assert "INGRESS_GUARD_REJECTED_SIGNAL_IS_DROPPED" in INGRESS_GUARD_REJECTED_SIGNAL_IS_DROPPED_POLICY


# ===========================================================================
# Group B — SignalGuardDecision enum
# ===========================================================================


def test_B01_signal_guard_decision_values():
    assert SignalGuardDecision.accept.value == "accept"
    assert SignalGuardDecision.duplicate.value == "duplicate"
    assert SignalGuardDecision.replay.value == "replay"
    assert SignalGuardDecision.stale.value == "stale"
    assert SignalGuardDecision.out_of_order.value == "out_of_order"


def test_B02_signal_guard_decision_from_string():
    assert SignalGuardDecision.from_string("accept") is SignalGuardDecision.accept
    assert SignalGuardDecision.from_string("duplicate") is SignalGuardDecision.duplicate
    assert SignalGuardDecision.from_string("replay") is SignalGuardDecision.replay
    assert SignalGuardDecision.from_string("stale") is SignalGuardDecision.stale
    assert SignalGuardDecision.from_string("out_of_order") is SignalGuardDecision.out_of_order


def test_B03_signal_guard_decision_from_string_case_insensitive():
    assert SignalGuardDecision.from_string("ACCEPT") is SignalGuardDecision.accept
    assert SignalGuardDecision.from_string("DUPLICATE") is SignalGuardDecision.duplicate
    assert SignalGuardDecision.from_string("STALE") is SignalGuardDecision.stale


def test_B04_signal_guard_decision_from_string_unknown_defaults_to_accept():
    assert SignalGuardDecision.from_string("unknown_value") is SignalGuardDecision.accept


def test_B05_signal_guard_decision_from_string_non_string_defaults_to_accept():
    assert SignalGuardDecision.from_string(42) is SignalGuardDecision.accept
    assert SignalGuardDecision.from_string(None) is SignalGuardDecision.accept


def test_B06_is_rejected_only_true_for_non_accept():
    assert not SignalGuardDecision.accept.is_rejected()
    assert SignalGuardDecision.duplicate.is_rejected()
    assert SignalGuardDecision.replay.is_rejected()
    assert SignalGuardDecision.stale.is_rejected()
    assert SignalGuardDecision.out_of_order.is_rejected()


# ===========================================================================
# Group C — RecoveryReadinessStatus enum
# ===========================================================================


def test_C01_recovery_readiness_status_values():
    assert RecoveryReadinessStatus.ready.value == "ready"
    assert RecoveryReadinessStatus.recovering.value == "recovering"
    assert RecoveryReadinessStatus.degraded.value == "degraded"


# ===========================================================================
# Group D — IdempotencyKey
# ===========================================================================


def test_D01_idempotency_key_construction():
    key = IdempotencyKey(signal_id="sig-1", contract_id="ctr-1", session_id="ses-1")
    assert key.signal_id == "sig-1"
    assert key.contract_id == "ctr-1"
    assert key.session_id == "ses-1"


def test_D02_context_key_prefers_contract_id():
    key = IdempotencyKey(contract_id="ctr-1", session_id="ses-1")
    assert key.context_key == "ctr-1"


def test_D03_context_key_falls_back_to_session_id():
    key = IdempotencyKey(session_id="ses-1")
    assert key.context_key == "ses-1"


def test_D04_context_key_empty_when_both_absent():
    key = IdempotencyKey(signal_id="sig-1")
    assert key.context_key == ""


def test_D05_has_context_returns_true_when_contract_id_set():
    key = IdempotencyKey(contract_id="ctr-1")
    assert key.has_context()


def test_D06_has_context_returns_true_when_session_id_set():
    key = IdempotencyKey(session_id="ses-1")
    assert key.has_context()


def test_D07_has_context_returns_false_when_neither_set():
    key = IdempotencyKey(signal_id="sig-1")
    assert not key.has_context()


def test_D08_to_dict_contains_all_fields():
    key = IdempotencyKey(signal_id="s", contract_id="c", session_id="ss")
    d = key.to_dict()
    assert "signal_id" in d
    assert "contract_id" in d
    assert "session_id" in d
    assert "context_key" in d


# ===========================================================================
# Group E — SeenSignalRecord
# ===========================================================================


def test_E01_seen_signal_record_construction():
    key = IdempotencyKey(signal_id="sig-1", contract_id="ctr-1")
    rec = SeenSignalRecord(idempotency_key=key, emission_seq=5)
    assert rec.emission_seq == 5
    assert rec.idempotency_key is key


def test_E02_seen_signal_record_has_record_id():
    key = IdempotencyKey(signal_id="sig-1")
    rec = SeenSignalRecord(idempotency_key=key)
    assert isinstance(rec.record_id, str)
    assert len(rec.record_id) > 0


def test_E03_seen_signal_record_to_dict():
    key = IdempotencyKey(signal_id="sig-1", contract_id="ctr-1")
    rec = SeenSignalRecord(idempotency_key=key, emission_seq=3)
    d = rec.to_dict()
    assert d["emission_seq"] == 3
    assert "record_id" in d
    assert "idempotency_key" in d
    assert "seen_at" in d


# ===========================================================================
# Group F — SignalGuardOutcome
# ===========================================================================


def test_F01_signal_guard_outcome_defaults():
    o = SignalGuardOutcome()
    assert o.decision is SignalGuardDecision.accept
    assert o.is_accepted()


def test_F02_signal_guard_outcome_reject_not_accepted():
    o = SignalGuardOutcome(decision=SignalGuardDecision.duplicate)
    assert not o.is_accepted()


def test_F03_signal_guard_outcome_to_dict():
    key = IdempotencyKey(signal_id="sig-1", contract_id="ctr-1")
    o = SignalGuardOutcome(
        decision=SignalGuardDecision.stale,
        idempotency_key=key,
        emission_seq=2,
        reject_reason="guard:stale ...",
        max_seen_seq=15,
    )
    d = o.to_dict()
    assert d["decision"] == "stale"
    assert d["emission_seq"] == 2
    assert d["reject_reason"] == "guard:stale ..."
    assert d["max_seen_seq"] == 15
    assert "outcome_id" in d
    assert "idempotency_key" in d


def test_F04_signal_guard_outcome_has_unique_outcome_id():
    o1 = SignalGuardOutcome()
    o2 = SignalGuardOutcome()
    assert o1.outcome_id != o2.outcome_id


# ===========================================================================
# Group G — RecoveryReadinessSnapshot
# ===========================================================================


def test_G01_snapshot_defaults():
    snap = RecoveryReadinessSnapshot()
    assert snap.status is RecoveryReadinessStatus.ready
    assert snap.ring_buffer_size == 0
    assert snap.total_accepted == 0
    assert snap.total_rejected == 0


def test_G02_snapshot_to_dict():
    snap = RecoveryReadinessSnapshot(
        status=RecoveryReadinessStatus.recovering,
        ring_buffer_size=5,
        total_accepted=10,
        total_rejected=3,
        reject_counts={"duplicate": 3},
    )
    d = snap.to_dict()
    assert d["status"] == "recovering"
    assert d["ring_buffer_size"] == 5
    assert d["total_accepted"] == 10
    assert d["total_rejected"] == 3
    assert d["reject_counts"] == {"duplicate": 3}


# ===========================================================================
# Group H — RecoveryReadinessRuntime initial state
# ===========================================================================


def test_H01_fresh_runtime_has_no_signal_id():
    rt = RecoveryReadinessRuntime()
    assert not rt.has_signal_id("sig-1")


def test_H02_fresh_runtime_get_max_seq_returns_minus_one():
    rt = RecoveryReadinessRuntime()
    assert rt.get_max_seq("ctr-1") == -1


def test_H03_fresh_runtime_get_max_seq_signal_id_returns_empty():
    rt = RecoveryReadinessRuntime()
    assert rt.get_max_seq_signal_id("ctr-1") == ""


# ===========================================================================
# Group I — RecoveryReadinessRuntime.record()
# ===========================================================================


def test_I01_record_adds_signal_id_to_index():
    rt = RecoveryReadinessRuntime()
    key = IdempotencyKey(signal_id="sig-1", contract_id="ctr-1")
    seen = SeenSignalRecord(idempotency_key=key, emission_seq=0)
    rt.record(seen)
    assert rt.has_signal_id("sig-1")


def test_I02_record_updates_max_seq():
    rt = RecoveryReadinessRuntime()
    key = IdempotencyKey(signal_id="sig-1", contract_id="ctr-1")
    seen = SeenSignalRecord(idempotency_key=key, emission_seq=5)
    rt.record(seen)
    assert rt.get_max_seq("ctr-1") == 5


def test_I03_record_max_seq_only_increases():
    rt = RecoveryReadinessRuntime()
    for seq in [3, 1, 5, 2]:
        sid = str(uuid.uuid4())
        key = IdempotencyKey(signal_id=sid, contract_id="ctr-1")
        seen = SeenSignalRecord(idempotency_key=key, emission_seq=seq)
        rt.record(seen)
    assert rt.get_max_seq("ctr-1") == 5


def test_I04_record_increments_total_accepted():
    rt = RecoveryReadinessRuntime()
    key = IdempotencyKey(signal_id="sig-1", contract_id="ctr-1")
    seen = SeenSignalRecord(idempotency_key=key, emission_seq=0)
    rt.record(seen)
    snap = rt.build_snapshot()
    assert snap.total_accepted == 1


# ===========================================================================
# Group J — RecoveryReadinessRuntime FIFO eviction
# ===========================================================================


def test_J01_ring_buffer_evicts_at_capacity():
    rt = RecoveryReadinessRuntime(max_size=3)
    for i in range(4):
        key = IdempotencyKey(signal_id=f"sig-{i}", contract_id="ctr-1")
        seen = SeenSignalRecord(idempotency_key=key, emission_seq=i)
        rt.record(seen)
    # sig-0 was evicted; sig-1, sig-2, sig-3 remain
    assert not rt.has_signal_id("sig-0")
    assert rt.has_signal_id("sig-1")
    assert rt.has_signal_id("sig-2")
    assert rt.has_signal_id("sig-3")


# ===========================================================================
# Group K — RecoveryReadinessRuntime.record_rejection()
# ===========================================================================


def test_K01_record_rejection_increments_total_rejected():
    rt = RecoveryReadinessRuntime()
    rt.record_rejection(SignalGuardDecision.duplicate)
    snap = rt.build_snapshot()
    assert snap.total_rejected == 1
    assert snap.reject_counts.get("duplicate") == 1


def test_K02_record_rejection_multiple_decisions():
    rt = RecoveryReadinessRuntime()
    rt.record_rejection(SignalGuardDecision.duplicate)
    rt.record_rejection(SignalGuardDecision.stale)
    rt.record_rejection(SignalGuardDecision.out_of_order)
    snap = rt.build_snapshot()
    assert snap.total_rejected == 3
    assert snap.reject_counts["duplicate"] == 1
    assert snap.reject_counts["stale"] == 1
    assert snap.reject_counts["out_of_order"] == 1


# ===========================================================================
# Group L — RecoveryReadinessRuntime.build_snapshot()
# ===========================================================================


def test_L01_snapshot_ready_when_no_rejections():
    rt = RecoveryReadinessRuntime()
    key = IdempotencyKey(signal_id="sig-1", contract_id="ctr-1")
    rt.record(SeenSignalRecord(idempotency_key=key, emission_seq=0))
    snap = rt.build_snapshot()
    assert snap.status is RecoveryReadinessStatus.ready
    assert snap.total_accepted == 1
    assert snap.total_rejected == 0


def test_L02_snapshot_recovering_with_some_rejections():
    rt = RecoveryReadinessRuntime()
    for i in range(5):
        key = IdempotencyKey(signal_id=f"sig-{i}", contract_id="ctr-1")
        rt.record(SeenSignalRecord(idempotency_key=key, emission_seq=i))
    rt.record_rejection(SignalGuardDecision.duplicate)
    snap = rt.build_snapshot()
    assert snap.status is RecoveryReadinessStatus.recovering


def test_L03_snapshot_degraded_with_majority_rejections():
    rt = RecoveryReadinessRuntime()
    key = IdempotencyKey(signal_id="sig-0", contract_id="ctr-1")
    rt.record(SeenSignalRecord(idempotency_key=key, emission_seq=0))
    # 2 accepted, 10 rejected → rejection ratio > 0.5
    for _ in range(10):
        rt.record_rejection(SignalGuardDecision.duplicate)
    snap = rt.build_snapshot()
    assert snap.status is RecoveryReadinessStatus.degraded


# ===========================================================================
# Group M — build_idempotency_key()
# ===========================================================================


def test_M01_build_idempotency_key_all_fields():
    key = build_idempotency_key(
        signal_id="sig-1", contract_id="ctr-1", session_id="ses-1"
    )
    assert key.signal_id == "sig-1"
    assert key.contract_id == "ctr-1"
    assert key.session_id == "ses-1"
    assert key.context_key == "ctr-1"


def test_M02_build_idempotency_key_empty_fields():
    key = build_idempotency_key()
    assert key.signal_id == ""
    assert key.contract_id == ""
    assert key.session_id == ""
    assert key.context_key == ""


def test_M03_build_idempotency_key_coerces_to_str():
    key = build_idempotency_key(signal_id=123)
    assert key.signal_id == "123"


# ===========================================================================
# Group N — check_signal_guard(): accept when no prior context
# ===========================================================================


def test_N01_accept_when_no_prior_context():
    rt = _fresh_guard_runtime()
    key = build_idempotency_key(signal_id="sig-1", contract_id="ctr-n-001")
    decision = check_signal_guard(key, emission_seq=0, runtime=rt)
    assert decision is SignalGuardDecision.accept


def test_N02_accept_when_no_context_key():
    rt = _fresh_guard_runtime()
    key = build_idempotency_key(signal_id="sig-1")
    decision = check_signal_guard(key, emission_seq=5, runtime=rt)
    assert decision is SignalGuardDecision.accept


# ===========================================================================
# Group O — check_signal_guard(): duplicate detection
# ===========================================================================


def test_O01_duplicate_when_signal_id_already_seen():
    rt = _fresh_guard_runtime()
    # Record signal-1 first
    key = build_idempotency_key(signal_id="sig-dup-1", contract_id="ctr-o-001")
    record_seen_signal(key, emission_seq=0, runtime=rt)
    # Same signal_id again → duplicate
    decision = check_signal_guard(key, emission_seq=0, runtime=rt)
    assert decision is SignalGuardDecision.duplicate


def test_O02_duplicate_different_emission_seq_still_rejected():
    rt = _fresh_guard_runtime()
    key = build_idempotency_key(signal_id="sig-dup-2", contract_id="ctr-o-002")
    record_seen_signal(key, emission_seq=0, runtime=rt)
    # Same signal_id but higher seq → still duplicate (signal_id check is first)
    decision = check_signal_guard(key, emission_seq=1, runtime=rt)
    assert decision is SignalGuardDecision.duplicate


def test_O03_no_duplicate_when_signal_id_empty():
    rt = _fresh_guard_runtime()
    key = build_idempotency_key(signal_id="", contract_id="ctr-o-003")
    record_seen_signal(key, emission_seq=0, runtime=rt)
    # signal_id is empty → no duplicate check possible; seq == max_seq == 0
    # and both signal_ids are "" (equal) → not replay; seq not < max → accept
    key2 = build_idempotency_key(signal_id="", contract_id="ctr-o-003")
    decision = check_signal_guard(key2, emission_seq=0, runtime=rt)
    # Empty signal_id: duplicate check is skipped; seq == max_seq but both
    # signal_ids are "" (equal) → not replay; not out_of_order; → accept
    assert decision is SignalGuardDecision.accept


# ===========================================================================
# Group P — check_signal_guard(): replay detection
# ===========================================================================


def test_P01_replay_when_same_seq_and_different_signal_id():
    rt = _fresh_guard_runtime()
    # Record first signal at seq=5
    key1 = build_idempotency_key(signal_id="sig-p-1", contract_id="ctr-p-001")
    record_seen_signal(key1, emission_seq=5, runtime=rt)
    # Same seq, different signal_id → replay
    key2 = build_idempotency_key(signal_id="sig-p-2", contract_id="ctr-p-001")
    decision = check_signal_guard(key2, emission_seq=5, runtime=rt)
    assert decision is SignalGuardDecision.replay


def test_P02_replay_not_triggered_for_higher_seq():
    rt = _fresh_guard_runtime()
    key1 = build_idempotency_key(signal_id="sig-p-3", contract_id="ctr-p-002")
    record_seen_signal(key1, emission_seq=5, runtime=rt)
    key2 = build_idempotency_key(signal_id="sig-p-4", contract_id="ctr-p-002")
    decision = check_signal_guard(key2, emission_seq=6, runtime=rt)
    assert decision is SignalGuardDecision.accept


# ===========================================================================
# Group Q — check_signal_guard(): stale detection
# ===========================================================================


def test_Q01_stale_when_emission_seq_far_behind_max():
    rt = _fresh_guard_runtime()
    # Set max_seq to STALE_THRESHOLD + 5 = 15
    max_seq = STALE_EMISSION_SEQ_THRESHOLD + 5
    key1 = build_idempotency_key(signal_id="sig-q-1", contract_id="ctr-q-001")
    record_seen_signal(key1, emission_seq=max_seq, runtime=rt)
    # Candidate at seq=0: max_seq - 0 = 15 > STALE_THRESHOLD(10) → stale
    key2 = build_idempotency_key(signal_id="sig-q-2", contract_id="ctr-q-001")
    decision = check_signal_guard(key2, emission_seq=0, runtime=rt)
    assert decision is SignalGuardDecision.stale


def test_Q02_stale_boundary_at_threshold():
    rt = _fresh_guard_runtime()
    # max_seq = 10; candidate at seq=0: 10 - 0 = 10; NOT > 10 → out_of_order
    key1 = build_idempotency_key(signal_id="sig-q-3", contract_id="ctr-q-002")
    record_seen_signal(key1, emission_seq=10, runtime=rt)
    key2 = build_idempotency_key(signal_id="sig-q-4", contract_id="ctr-q-002")
    # 10 - 0 = 10, not > 10 → NOT stale → out_of_order
    decision = check_signal_guard(key2, emission_seq=0, runtime=rt)
    assert decision is SignalGuardDecision.out_of_order


def test_Q03_stale_one_above_threshold():
    rt = _fresh_guard_runtime()
    # max_seq = 11; candidate at seq=0: 11 - 0 = 11 > 10 → stale
    key1 = build_idempotency_key(signal_id="sig-q-5", contract_id="ctr-q-003")
    record_seen_signal(key1, emission_seq=11, runtime=rt)
    key2 = build_idempotency_key(signal_id="sig-q-6", contract_id="ctr-q-003")
    decision = check_signal_guard(key2, emission_seq=0, runtime=rt)
    assert decision is SignalGuardDecision.stale


# ===========================================================================
# Group R — check_signal_guard(): out_of_order detection
# ===========================================================================


def test_R01_out_of_order_when_seq_slightly_behind_max():
    rt = _fresh_guard_runtime()
    key1 = build_idempotency_key(signal_id="sig-r-1", contract_id="ctr-r-001")
    record_seen_signal(key1, emission_seq=5, runtime=rt)
    key2 = build_idempotency_key(signal_id="sig-r-2", contract_id="ctr-r-001")
    decision = check_signal_guard(key2, emission_seq=3, runtime=rt)
    assert decision is SignalGuardDecision.out_of_order


def test_R02_out_of_order_one_behind_max():
    rt = _fresh_guard_runtime()
    key1 = build_idempotency_key(signal_id="sig-r-3", contract_id="ctr-r-002")
    record_seen_signal(key1, emission_seq=3, runtime=rt)
    key2 = build_idempotency_key(signal_id="sig-r-4", contract_id="ctr-r-002")
    decision = check_signal_guard(key2, emission_seq=2, runtime=rt)
    assert decision is SignalGuardDecision.out_of_order


# ===========================================================================
# Group S — check_signal_guard(): accept when emission_seq >= max_seen
# ===========================================================================


def test_S01_accept_when_emission_seq_greater_than_max():
    rt = _fresh_guard_runtime()
    key1 = build_idempotency_key(signal_id="sig-s-1", contract_id="ctr-s-001")
    record_seen_signal(key1, emission_seq=3, runtime=rt)
    key2 = build_idempotency_key(signal_id="sig-s-2", contract_id="ctr-s-001")
    decision = check_signal_guard(key2, emission_seq=4, runtime=rt)
    assert decision is SignalGuardDecision.accept


def test_S02_accept_when_no_prior_context_and_any_seq():
    rt = _fresh_guard_runtime()
    key = build_idempotency_key(signal_id="sig-s-3", contract_id="ctr-s-002")
    decision = check_signal_guard(key, emission_seq=100, runtime=rt)
    assert decision is SignalGuardDecision.accept


# ===========================================================================
# Group T — record_seen_signal()
# ===========================================================================


def test_T01_record_seen_signal_adds_to_runtime():
    rt = _fresh_guard_runtime()
    key = build_idempotency_key(signal_id="sig-t-1", contract_id="ctr-t-001")
    rec = record_seen_signal(key, emission_seq=7, runtime=rt)
    assert rt.has_signal_id("sig-t-1")
    assert rt.get_max_seq("ctr-t-001") == 7
    assert isinstance(rec, SeenSignalRecord)


def test_T02_record_seen_signal_returns_seen_record():
    rt = _fresh_guard_runtime()
    key = build_idempotency_key(signal_id="sig-t-2", contract_id="ctr-t-002")
    rec = record_seen_signal(key, emission_seq=2, runtime=rt)
    assert rec.emission_seq == 2
    assert rec.idempotency_key.signal_id == "sig-t-2"


# ===========================================================================
# Group U — guard_inbound_signal(): accept path
# ===========================================================================


def test_U01_guard_accept_returns_accept_decision():
    rt = _fresh_guard_runtime()
    # Use a plain dict as envelope
    envelope = {
        "signal_id": "sig-u-1",
        "contract_id": "ctr-u-001",
        "session_id": "ses-u-001",
        "emission_seq": 0,
    }
    outcome = guard_inbound_signal(envelope, runtime=rt)
    assert outcome.is_accepted()
    assert outcome.decision is SignalGuardDecision.accept


def test_U01b_guard_accept_returns_accept_decision_dict():
    rt = _fresh_guard_runtime()
    envelope = {
        "signal_id": "sig-u-1b",
        "contract_id": "ctr-u-001",
        "session_id": "ses-u-001",
        "emission_seq": 0,
    }
    outcome = guard_inbound_signal(envelope, runtime=rt)
    assert outcome.is_accepted()
    assert outcome.decision is SignalGuardDecision.accept


def test_U02_guard_accept_records_signal():
    rt = _fresh_guard_runtime()
    envelope = {
        "signal_id": "sig-u-2",
        "contract_id": "ctr-u-002",
        "emission_seq": 3,
    }
    guard_inbound_signal(envelope, runtime=rt)
    assert rt.has_signal_id("sig-u-2")
    assert rt.get_max_seq("ctr-u-002") == 3


# ===========================================================================
# Group V — guard_inbound_signal(): duplicate path
# ===========================================================================


def test_V01_guard_duplicate_returns_duplicate_decision():
    rt = _fresh_guard_runtime()
    envelope1 = {
        "signal_id": "sig-v-1",
        "contract_id": "ctr-v-001",
        "emission_seq": 0,
    }
    guard_inbound_signal(envelope1, runtime=rt)  # first: accept
    outcome = guard_inbound_signal(envelope1, runtime=rt)  # second: duplicate
    assert outcome.decision is SignalGuardDecision.duplicate
    assert not outcome.is_accepted()


def test_V02_guard_duplicate_not_recorded_again():
    rt = _fresh_guard_runtime()
    envelope = {
        "signal_id": "sig-v-2",
        "contract_id": "ctr-v-002",
        "emission_seq": 0,
    }
    guard_inbound_signal(envelope, runtime=rt)
    # Max seq after duplicate attempt should remain the same
    assert rt.get_max_seq("ctr-v-002") == 0
    guard_inbound_signal(envelope, runtime=rt)
    assert rt.get_max_seq("ctr-v-002") == 0  # NOT updated to duplicate's value


# ===========================================================================
# Group W — guard_inbound_signal(): replay path
# ===========================================================================


def test_W01_guard_replay_returns_replay_decision():
    rt = _fresh_guard_runtime()
    envelope1 = {
        "signal_id": "sig-w-1",
        "contract_id": "ctr-w-001",
        "emission_seq": 5,
    }
    guard_inbound_signal(envelope1, runtime=rt)  # accept
    envelope2 = {
        "signal_id": "sig-w-2",  # different signal_id
        "contract_id": "ctr-w-001",  # same context
        "emission_seq": 5,  # same seq → replay
    }
    outcome = guard_inbound_signal(envelope2, runtime=rt)
    assert outcome.decision is SignalGuardDecision.replay
    assert not outcome.is_accepted()


# ===========================================================================
# Group X — guard_inbound_signal(): stale path
# ===========================================================================


def test_X01_guard_stale_returns_stale_decision():
    rt = _fresh_guard_runtime()
    max_seq = STALE_EMISSION_SEQ_THRESHOLD + 5  # = 15
    envelope_high = {
        "signal_id": "sig-x-1",
        "contract_id": "ctr-x-001",
        "emission_seq": max_seq,
    }
    guard_inbound_signal(envelope_high, runtime=rt)  # accept at seq=15
    envelope_low = {
        "signal_id": "sig-x-2",
        "contract_id": "ctr-x-001",
        "emission_seq": 0,  # far behind
    }
    outcome = guard_inbound_signal(envelope_low, runtime=rt)
    assert outcome.decision is SignalGuardDecision.stale
    assert not outcome.is_accepted()


# ===========================================================================
# Group Y — guard_inbound_signal(): out_of_order path
# ===========================================================================


def test_Y01_guard_out_of_order_returns_out_of_order_decision():
    rt = _fresh_guard_runtime()
    envelope_high = {
        "signal_id": "sig-y-1",
        "contract_id": "ctr-y-001",
        "emission_seq": 5,
    }
    guard_inbound_signal(envelope_high, runtime=rt)  # accept at seq=5
    envelope_low = {
        "signal_id": "sig-y-2",
        "contract_id": "ctr-y-001",
        "emission_seq": 3,  # slightly behind (5 - 3 = 2 ≤ STALE_THRESHOLD)
    }
    outcome = guard_inbound_signal(envelope_low, runtime=rt)
    assert outcome.decision is SignalGuardDecision.out_of_order
    assert not outcome.is_accepted()


# ===========================================================================
# Group Z — guard_inbound_signal(): reject_reason is non-empty for rejects
# ===========================================================================


def test_Z01_duplicate_reject_reason_non_empty():
    rt = _fresh_guard_runtime()
    envelope = {"signal_id": "sig-z-1", "contract_id": "ctr-z-001", "emission_seq": 0}
    guard_inbound_signal(envelope, runtime=rt)
    outcome = guard_inbound_signal(envelope, runtime=rt)
    assert outcome.reject_reason
    assert "duplicate" in outcome.reject_reason


def test_Z02_replay_reject_reason_non_empty():
    rt = _fresh_guard_runtime()
    guard_inbound_signal(
        {"signal_id": "sig-z-2", "contract_id": "ctr-z-002", "emission_seq": 5},
        runtime=rt,
    )
    outcome = guard_inbound_signal(
        {"signal_id": "sig-z-3", "contract_id": "ctr-z-002", "emission_seq": 5},
        runtime=rt,
    )
    assert outcome.reject_reason
    assert "replay" in outcome.reject_reason


def test_Z03_stale_reject_reason_non_empty():
    rt = _fresh_guard_runtime()
    guard_inbound_signal(
        {"signal_id": "sig-z-4", "contract_id": "ctr-z-003", "emission_seq": 20},
        runtime=rt,
    )
    outcome = guard_inbound_signal(
        {"signal_id": "sig-z-5", "contract_id": "ctr-z-003", "emission_seq": 0},
        runtime=rt,
    )
    assert outcome.reject_reason
    assert "stale" in outcome.reject_reason


def test_Z04_out_of_order_reject_reason_non_empty():
    rt = _fresh_guard_runtime()
    guard_inbound_signal(
        {"signal_id": "sig-z-6", "contract_id": "ctr-z-004", "emission_seq": 5},
        runtime=rt,
    )
    outcome = guard_inbound_signal(
        {"signal_id": "sig-z-7", "contract_id": "ctr-z-004", "emission_seq": 3},
        runtime=rt,
    )
    assert outcome.reject_reason
    assert "out_of_order" in outcome.reject_reason


def test_Z05_accept_reject_reason_empty():
    rt = _fresh_guard_runtime()
    outcome = guard_inbound_signal(
        {"signal_id": "sig-z-8", "contract_id": "ctr-z-005", "emission_seq": 0},
        runtime=rt,
    )
    assert outcome.reject_reason == ""


# ===========================================================================
# Group AA — guard_inbound_signal(): outcome carries key and seq
# ===========================================================================


def test_AA01_outcome_carries_idempotency_key():
    rt = _fresh_guard_runtime()
    outcome = guard_inbound_signal(
        {"signal_id": "sig-aa-1", "contract_id": "ctr-aa-001", "emission_seq": 3},
        runtime=rt,
    )
    assert outcome.idempotency_key.signal_id == "sig-aa-1"
    assert outcome.idempotency_key.contract_id == "ctr-aa-001"
    assert outcome.emission_seq == 3


# ===========================================================================
# Group AB — guard_inbound_signal(): max_seen_seq in outcome
# ===========================================================================


def test_AB01_max_seen_seq_minus_one_when_no_prior():
    rt = _fresh_guard_runtime()
    outcome = guard_inbound_signal(
        {"signal_id": "sig-ab-1", "contract_id": "ctr-ab-001", "emission_seq": 0},
        runtime=rt,
    )
    assert outcome.max_seen_seq == -1  # no prior context


def test_AB02_max_seen_seq_reflects_prior_state():
    rt = _fresh_guard_runtime()
    guard_inbound_signal(
        {"signal_id": "sig-ab-2", "contract_id": "ctr-ab-002", "emission_seq": 7},
        runtime=rt,
    )
    outcome = guard_inbound_signal(
        {"signal_id": "sig-ab-3", "contract_id": "ctr-ab-002", "emission_seq": 8},
        runtime=rt,
    )
    # max_seen before evaluating sig-ab-3 was 7
    assert outcome.max_seen_seq == 7


# ===========================================================================
# Group AC — guard_inbound_signal(): accepted signal is recorded
# ===========================================================================


def test_AC01_accepted_signal_recorded_into_runtime():
    rt = _fresh_guard_runtime()
    guard_inbound_signal(
        {"signal_id": "sig-ac-1", "contract_id": "ctr-ac-001", "emission_seq": 4},
        runtime=rt,
    )
    assert rt.has_signal_id("sig-ac-1")
    assert rt.get_max_seq("ctr-ac-001") == 4


# ===========================================================================
# Group AD — guard_inbound_signal(): rejected signals NOT recorded
# ===========================================================================


def test_AD01_duplicate_not_recorded():
    rt = _fresh_guard_runtime()
    envelope = {"signal_id": "sig-ad-1", "contract_id": "ctr-ad-001", "emission_seq": 0}
    guard_inbound_signal(envelope, runtime=rt)  # accept: max_seq=0
    guard_inbound_signal(envelope, runtime=rt)  # duplicate: should NOT update max_seq
    assert rt.get_max_seq("ctr-ad-001") == 0  # unchanged


def test_AD02_out_of_order_not_recorded():
    rt = _fresh_guard_runtime()
    guard_inbound_signal(
        {"signal_id": "sig-ad-2", "contract_id": "ctr-ad-002", "emission_seq": 5},
        runtime=rt,
    )  # accept: max_seq=5
    guard_inbound_signal(
        {"signal_id": "sig-ad-3", "contract_id": "ctr-ad-002", "emission_seq": 3},
        runtime=rt,
    )  # out_of_order: NOT recorded
    assert rt.get_max_seq("ctr-ad-002") == 5  # still 5, not updated to 3


# ===========================================================================
# Group AE — guard_inbound_signal(): dict envelope support
# ===========================================================================


def test_AE01_dict_envelope_accepted():
    rt = _fresh_guard_runtime()
    outcome = guard_inbound_signal(
        {"signal_id": "sig-ae-1", "contract_id": "ctr-ae-001", "emission_seq": 0},
        runtime=rt,
    )
    assert outcome.is_accepted()


# ===========================================================================
# Group AF — guard_inbound_signal(): empty signal_id
# ===========================================================================


def test_AF01_empty_signal_id_skips_duplicate_check():
    rt = _fresh_guard_runtime()
    # With empty signal_id, no duplicate check → falls through to seq check
    outcome = guard_inbound_signal(
        {"signal_id": "", "contract_id": "ctr-af-001", "emission_seq": 0},
        runtime=rt,
    )
    # No prior context → accept
    assert outcome.is_accepted()


# ===========================================================================
# Group AG — ingest_delegated_execution_signal(): accept path
# ===========================================================================


def test_AG01_accept_path_reconciles_ack():
    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-ag-001", session_id="ses-ag-001"
    )
    guard_rt = _fresh_guard_runtime()
    msg = _make_signal_message(
        contract_id="ctr-ag-001",
        session_id="ses-ag-001",
        signal_kind="ack",
        signal_id=str(uuid.uuid4()),
        emission_seq=0,
    )
    outcome = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.was_updated
    assert outcome.record is not None
    assert outcome.record.phase is DelegatedExecutionPhase.acknowledged


def test_AG02_accept_path_reconciles_progress():
    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-ag-002", session_id="ses-ag-002"
    )
    guard_rt = _fresh_guard_runtime()
    # First ack to set phase
    ack_msg = _make_signal_message(
        contract_id="ctr-ag-002",
        session_id="ses-ag-002",
        signal_kind="ack",
        signal_id=str(uuid.uuid4()),
        emission_seq=0,
    )
    ingest_delegated_execution_signal(ack_msg, runtime=tracker_rt, guard_runtime=guard_rt)
    # Progress
    progress_msg = _make_signal_message(
        contract_id="ctr-ag-002",
        session_id="ses-ag-002",
        signal_kind="progress",
        signal_id=str(uuid.uuid4()),
        emission_seq=1,
    )
    outcome = ingest_delegated_execution_signal(
        progress_msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.was_updated
    assert outcome.record.phase is DelegatedExecutionPhase.in_progress


# ===========================================================================
# Group AH — duplicate → was_updated=False, tracker not mutated
# ===========================================================================


def test_AH01_duplicate_returns_not_updated():
    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-ah-001", session_id="ses-ah-001"
    )
    guard_rt = _fresh_guard_runtime()
    sig_id = str(uuid.uuid4())
    msg = _make_signal_message(
        contract_id="ctr-ah-001",
        session_id="ses-ah-001",
        signal_kind="ack",
        signal_id=sig_id,
        emission_seq=0,
    )
    ingest_delegated_execution_signal(msg, runtime=tracker_rt, guard_runtime=guard_rt)
    # Send duplicate
    outcome = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert not outcome.was_updated
    assert "duplicate" in outcome.reject_reason


def test_AH02_duplicate_does_not_change_tracker_phase():
    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-ah-002", session_id="ses-ah-002"
    )
    guard_rt = _fresh_guard_runtime()
    sig_id = str(uuid.uuid4())
    ack_msg = _make_signal_message(
        contract_id="ctr-ah-002",
        session_id="ses-ah-002",
        signal_kind="ack",
        signal_id=sig_id,
        emission_seq=0,
    )
    ingest_delegated_execution_signal(ack_msg, runtime=tracker_rt, guard_runtime=guard_rt)
    # Phase is now acknowledged. Send duplicate progress (same signal_id but progress)
    # The guard rejects based on signal_id, so tracker stays at acknowledged.
    dup_msg = dict(ack_msg)  # same message (same signal_id)
    outcome = ingest_delegated_execution_signal(
        dup_msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert not outcome.was_updated
    # Tracker record phase should still be acknowledged
    rec = get_execution_tracking_record("ses-ah-002", runtime=tracker_rt)
    assert rec is not None
    assert rec.phase is DelegatedExecutionPhase.acknowledged


# ===========================================================================
# Group AI — replay → was_updated=False
# ===========================================================================


def test_AI01_replay_returns_not_updated():
    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-ai-001", session_id="ses-ai-001"
    )
    guard_rt = _fresh_guard_runtime()
    # First signal at seq=5
    msg1 = _make_signal_message(
        contract_id="ctr-ai-001",
        session_id="ses-ai-001",
        signal_kind="ack",
        signal_id=str(uuid.uuid4()),
        emission_seq=5,
    )
    ingest_delegated_execution_signal(msg1, runtime=tracker_rt, guard_runtime=guard_rt)
    # Replay: same seq but different signal_id
    msg2 = _make_signal_message(
        contract_id="ctr-ai-001",
        session_id="ses-ai-001",
        signal_kind="progress",
        signal_id=str(uuid.uuid4()),  # different signal_id
        emission_seq=5,  # same seq → replay
    )
    outcome = ingest_delegated_execution_signal(
        msg2, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert not outcome.was_updated
    assert "replay" in outcome.reject_reason


# ===========================================================================
# Group AJ — stale → was_updated=False
# ===========================================================================


def test_AJ01_stale_returns_not_updated():
    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-aj-001", session_id="ses-aj-001"
    )
    guard_rt = _fresh_guard_runtime()
    # First: set high seq
    high_seq = STALE_EMISSION_SEQ_THRESHOLD + 5  # = 15
    msg_high = _make_signal_message(
        contract_id="ctr-aj-001",
        session_id="ses-aj-001",
        signal_kind="ack",
        signal_id=str(uuid.uuid4()),
        emission_seq=high_seq,
    )
    ingest_delegated_execution_signal(msg_high, runtime=tracker_rt, guard_runtime=guard_rt)
    # Stale: far behind
    msg_stale = _make_signal_message(
        contract_id="ctr-aj-001",
        session_id="ses-aj-001",
        signal_kind="progress",
        signal_id=str(uuid.uuid4()),
        emission_seq=0,
    )
    outcome = ingest_delegated_execution_signal(
        msg_stale, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert not outcome.was_updated
    assert "stale" in outcome.reject_reason


# ===========================================================================
# Group AK — out_of_order → was_updated=False
# ===========================================================================


def test_AK01_out_of_order_returns_not_updated():
    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-ak-001", session_id="ses-ak-001"
    )
    guard_rt = _fresh_guard_runtime()
    # First: accept at seq=5
    msg_5 = _make_signal_message(
        contract_id="ctr-ak-001",
        session_id="ses-ak-001",
        signal_kind="ack",
        signal_id=str(uuid.uuid4()),
        emission_seq=5,
    )
    ingest_delegated_execution_signal(msg_5, runtime=tracker_rt, guard_runtime=guard_rt)
    # Out of order: seq=3
    msg_3 = _make_signal_message(
        contract_id="ctr-ak-001",
        session_id="ses-ak-001",
        signal_kind="progress",
        signal_id=str(uuid.uuid4()),
        emission_seq=3,
    )
    outcome = ingest_delegated_execution_signal(
        msg_3, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert not outcome.was_updated
    assert "out_of_order" in outcome.reject_reason


# ===========================================================================
# Group AL — reject_reason encodes guard decision
# ===========================================================================


def test_AL01_reject_reason_encodes_guard_prefix():
    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-al-001", session_id="ses-al-001"
    )
    guard_rt = _fresh_guard_runtime()
    sig_id = str(uuid.uuid4())
    msg = _make_signal_message(
        contract_id="ctr-al-001",
        signal_id=sig_id,
        emission_seq=0,
    )
    ingest_delegated_execution_signal(msg, runtime=tracker_rt, guard_runtime=guard_rt)
    outcome = ingest_delegated_execution_signal(
        msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome.reject_reason.startswith("guard:")


# ===========================================================================
# Group AM — rejected signals do not pollute tracker phase
# ===========================================================================


def test_AM01_rejected_signal_does_not_change_tracker():
    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-am-001", session_id="ses-am-001"
    )
    guard_rt = _fresh_guard_runtime()
    # Accept ack
    ack_msg = _make_signal_message(
        contract_id="ctr-am-001",
        signal_kind="ack",
        signal_id=str(uuid.uuid4()),
        emission_seq=0,
    )
    ingest_delegated_execution_signal(ack_msg, runtime=tracker_rt, guard_runtime=guard_rt)
    # Attempt out_of_order result (which would close the record if it got through)
    rej_msg = _make_signal_message(
        contract_id="ctr-am-001",
        signal_kind="result",
        result_kind="success",
        signal_id=str(uuid.uuid4()),
        emission_seq=0,  # same as max_seen → but different signal_id → replay
    )
    outcome = ingest_delegated_execution_signal(
        rej_msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert not outcome.was_updated
    # Tracker should still be at acknowledged (not completed)
    rec = get_execution_tracking_record("ses-am-001", runtime=tracker_rt)
    assert rec is not None
    assert rec.phase is DelegatedExecutionPhase.acknowledged


# ===========================================================================
# Group AN — Integration: full lifecycle (accept path)
# ===========================================================================


def test_AN01_full_lifecycle_ack_progress_result_completed():
    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-an-001", session_id="ses-an-001"
    )
    guard_rt = _fresh_guard_runtime()

    # Ack
    outcome_ack = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-an-001",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=0,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert outcome_ack.was_updated
    assert outcome_ack.record.phase is DelegatedExecutionPhase.acknowledged

    # Progress
    outcome_progress = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-an-001",
            signal_kind="progress",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert outcome_progress.was_updated
    assert outcome_progress.record.phase is DelegatedExecutionPhase.in_progress

    # Result/success → completed
    outcome_result = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-an-001",
            signal_kind="result",
            result_kind="success",
            signal_id=str(uuid.uuid4()),
            emission_seq=2,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert outcome_result.was_updated
    assert outcome_result.record.phase is DelegatedExecutionPhase.completed


# ===========================================================================
# Group AO — Integration: duplicate signal sent twice
# ===========================================================================


def test_AO01_duplicate_second_attempt_rejected_tracker_not_mutated():
    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-ao-001", session_id="ses-ao-001"
    )
    guard_rt = _fresh_guard_runtime()
    sig_id = str(uuid.uuid4())
    ack_msg = _make_signal_message(
        contract_id="ctr-ao-001",
        signal_kind="ack",
        signal_id=sig_id,
        emission_seq=0,
    )
    outcome1 = ingest_delegated_execution_signal(
        ack_msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert outcome1.was_updated
    assert outcome1.record.phase is DelegatedExecutionPhase.acknowledged

    # Send exact same message again
    outcome2 = ingest_delegated_execution_signal(
        ack_msg, runtime=tracker_rt, guard_runtime=guard_rt
    )
    assert not outcome2.was_updated
    assert "duplicate" in outcome2.reject_reason

    # Tracker unchanged at acknowledged
    rec = get_execution_tracking_record("ses-ao-001", runtime=tracker_rt)
    assert rec.phase is DelegatedExecutionPhase.acknowledged


# ===========================================================================
# Group AP — Integration: out_of_order skipped, next in-order accepted
# ===========================================================================


def test_AP01_out_of_order_skipped_next_in_order_accepted():
    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-ap-001", session_id="ses-ap-001"
    )
    guard_rt = _fresh_guard_runtime()

    # Accept ack at seq=2
    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-ap-001",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=2,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )

    # Out-of-order at seq=1
    outcome_oo = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-ap-001",
            signal_kind="progress",
            signal_id=str(uuid.uuid4()),
            emission_seq=1,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert not outcome_oo.was_updated
    assert "out_of_order" in outcome_oo.reject_reason

    # In-order at seq=3 → accepted
    outcome_ok = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-ap-001",
            signal_kind="progress",
            signal_id=str(uuid.uuid4()),
            emission_seq=3,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert outcome_ok.was_updated


# ===========================================================================
# Group AQ — Integration: stale signal rejected
# ===========================================================================


def test_AQ01_stale_signal_rejected():
    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-aq-001", session_id="ses-aq-001"
    )
    guard_rt = _fresh_guard_runtime()
    high_seq = STALE_EMISSION_SEQ_THRESHOLD + 5
    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-aq-001",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=high_seq,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    outcome = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-aq-001",
            signal_kind="progress",
            signal_id=str(uuid.uuid4()),
            emission_seq=0,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert not outcome.was_updated
    assert "stale" in outcome.reject_reason


# ===========================================================================
# Group AR — Integration: replay (same seq, new signal_id) rejected
# ===========================================================================


def test_AR01_replay_signal_rejected():
    record, tracker_rt = _make_tracking_record(
        contract_id="ctr-ar-001", session_id="ses-ar-001"
    )
    guard_rt = _fresh_guard_runtime()
    ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-ar-001",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=3,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    outcome = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-ar-001",
            signal_kind="progress",
            signal_id=str(uuid.uuid4()),  # new signal_id
            emission_seq=3,  # same seq → replay
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert not outcome.was_updated
    assert "replay" in outcome.reject_reason


# ===========================================================================
# Group AS — Integration: two independent contracts are guard-isolated
# ===========================================================================


def test_AS01_two_contracts_independent_guard_state():
    _, tracker_rt = _make_tracking_record(
        contract_id="ctr-as-001", session_id="ses-as-001"
    )
    create_execution_tracking_record(
        session_id="ses-as-002",
        contract_id="ctr-as-002",
        device_id="dev-pr18-001",
        trace_id="trace-pr18-001",
        source_runtime_posture="join_runtime",
        runtime=tracker_rt,
    )
    guard_rt = _fresh_guard_runtime()

    # Contract 1 at seq=0
    o1 = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-as-001",
            session_id="ses-as-001",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=0,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o1.was_updated

    # Contract 2 at seq=0 (independent context) → also accepted
    o2 = ingest_delegated_execution_signal(
        _make_signal_message(
            contract_id="ctr-as-002",
            session_id="ses-as-002",
            signal_kind="ack",
            signal_id=str(uuid.uuid4()),
            emission_seq=0,
        ),
        runtime=tracker_rt,
        guard_runtime=guard_rt,
    )
    assert o2.was_updated


# ===========================================================================
# Group AT — Integration: guard snapshot shows correct counts
# ===========================================================================


def test_AT01_guard_snapshot_counts_match_decisions():
    guard_rt = _fresh_guard_runtime()

    # 2 accepted signals
    for i in range(2):
        guard_inbound_signal(
            {"signal_id": f"sig-at-{i}", "contract_id": "ctr-at-001", "emission_seq": i},
            runtime=guard_rt,
        )
    # 1 duplicate (same signal_id as sig-at-0)
    guard_inbound_signal(
        {"signal_id": "sig-at-0", "contract_id": "ctr-at-001", "emission_seq": 0},
        runtime=guard_rt,
    )
    # 1 out_of_order (seq=0 behind max=1)
    guard_inbound_signal(
        {"signal_id": "sig-at-new", "contract_id": "ctr-at-001", "emission_seq": 0},
        runtime=guard_rt,
    )

    snap = build_recovery_readiness_snapshot(runtime=guard_rt)
    assert snap.total_accepted == 2
    assert snap.total_rejected == 2
    assert snap.reject_counts.get("duplicate") == 1
    assert snap.reject_counts.get("out_of_order") == 1 or snap.reject_counts.get("replay") == 1


# ===========================================================================
# Group AU — Observability: build_recovery_readiness_snapshot()
# ===========================================================================


def test_AU01_snapshot_returns_correct_type():
    guard_rt = _fresh_guard_runtime()
    snap = build_recovery_readiness_snapshot(runtime=guard_rt)
    assert isinstance(snap, RecoveryReadinessSnapshot)


def test_AU02_snapshot_ring_buffer_size_reflects_records():
    guard_rt = _fresh_guard_runtime()
    for i in range(3):
        guard_inbound_signal(
            {"signal_id": f"sig-au-{i}", "contract_id": "ctr-au-001", "emission_seq": i},
            runtime=guard_rt,
        )
    snap = build_recovery_readiness_snapshot(runtime=guard_rt)
    assert snap.ring_buffer_size == 3


# ===========================================================================
# Group AV — Observability: snapshot reflects rejection counts per decision
# ===========================================================================


def test_AV01_snapshot_per_decision_counts():
    guard_rt = _fresh_guard_runtime()
    # Set up context: accept at seq=20
    guard_inbound_signal(
        {"signal_id": "sig-av-base", "contract_id": "ctr-av-001", "emission_seq": 20},
        runtime=guard_rt,
    )
    # Stale: seq=0
    guard_inbound_signal(
        {"signal_id": "sig-av-stale", "contract_id": "ctr-av-001", "emission_seq": 0},
        runtime=guard_rt,
    )
    # Out_of_order: seq=15 (behind 20, 20-15=5 ≤ 10 threshold)
    guard_inbound_signal(
        {"signal_id": "sig-av-oo", "contract_id": "ctr-av-001", "emission_seq": 15},
        runtime=guard_rt,
    )
    snap = build_recovery_readiness_snapshot(runtime=guard_rt)
    assert snap.reject_counts.get("stale", 0) >= 1
    assert snap.reject_counts.get("out_of_order", 0) >= 1


# ===========================================================================
# Group AW — core.runtime re-exports
# ===========================================================================


def test_AW01_core_runtime_exports_pr15_symbols():
    try:
        from core import runtime as rt_module
    except (ImportError, ModuleNotFoundError):
        pytest.skip("core.runtime unavailable (likely missing pydantic or other dep)")

    assert hasattr(rt_module, "SignalGuardDecision")
    assert hasattr(rt_module, "RecoveryReadinessStatus")
    assert hasattr(rt_module, "IdempotencyKey")
    assert hasattr(rt_module, "SeenSignalRecord")
    assert hasattr(rt_module, "SignalGuardOutcome")
    assert hasattr(rt_module, "RecoveryReadinessSnapshot")
    assert hasattr(rt_module, "RecoveryReadinessRuntime")
    assert hasattr(rt_module, "build_idempotency_key")
    assert hasattr(rt_module, "check_signal_guard")
    assert hasattr(rt_module, "record_seen_signal")
    assert hasattr(rt_module, "guard_inbound_signal")
    assert hasattr(rt_module, "build_recovery_readiness_snapshot")
    assert hasattr(rt_module, "get_recovery_readiness_runtime")
    assert hasattr(rt_module, "reset_recovery_readiness_runtime")


def test_AW02_core_runtime_exports_pr15_sentinel():
    try:
        from core import runtime as rt_module
    except (ImportError, ModuleNotFoundError):
        pytest.skip("core.runtime unavailable (likely missing pydantic or other dep)")

    assert hasattr(rt_module, "ATTACHED_RUNTIME_RECOVERY_READINESS_PR15_SENTINEL")


# ===========================================================================
# Group AX — projection.py sentinel
# ===========================================================================


def test_AX01_projection_sentinel_present_and_not_unavailable():
    try:
        from core.routes.projection import INGRESS_RECOVERY_GUARD_ALIGNED_PR18
        assert INGRESS_RECOVERY_GUARD_ALIGNED_PR18
        assert "UNAVAILABLE" not in INGRESS_RECOVERY_GUARD_ALIGNED_PR18
        assert "PR18" in INGRESS_RECOVERY_GUARD_ALIGNED_PR18
    except ImportError:
        pytest.skip("projection module unavailable (likely missing fastapi)")


# ===========================================================================
# Group AY — All 11 policy sentinels
# ===========================================================================


def test_AY01_all_11_guard_policies_non_empty():
    assert len(_ALL_GUARD_POLICIES) == 11
    for policy in _ALL_GUARD_POLICIES:
        assert isinstance(policy, str)
        assert len(policy) > 0
        assert "RECOVERY_READINESS_POLICY::" in policy


# ===========================================================================
# Group AZ — PR15 sentinel format
# ===========================================================================


def test_AZ01_pr15_sentinel_contains_package_15():
    assert "package=15" in ATTACHED_RUNTIME_RECOVERY_READINESS_PR15_SENTINEL


def test_AZ02_pr15_sentinel_contains_authority():
    assert "authority=" in ATTACHED_RUNTIME_RECOVERY_READINESS_PR15_SENTINEL
