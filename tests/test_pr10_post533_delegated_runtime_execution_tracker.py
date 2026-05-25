"""tests/test_pr10_post533_delegated_runtime_execution_tracker.py
=================================================================
Tests for PR package 10 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical Delegated-Runtime Execution-Tracking and
Acknowledgment Basis.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — DelegatedExecutionPhase enum: all values present, from_string(), defaults.
C  — DelegatedExecutionPhase: is_terminal(), is_active(), can_advance_to().
D  — AcknowledgmentSignal enum: all values present, from_string(), defaults.
E  — AcknowledgmentSignal.target_phase() mapping.
F  — DelegatedExecutionIdentity: construction, defaults, to_dict(),
     to_json(), from_dict().
G  — DelegatedExecutionAcknowledgment: construction, defaults, to_dict(),
     to_json(), from_dict().
H  — DelegatedExecutionResult: construction, defaults, to_dict(),
     to_json(), from_dict().
I  — DelegatedExecutionTrackingRecord: construction, defaults, to_dict(),
     to_json(), from_dict(), is_accepted(), is_rejected(), is_active(),
     is_terminal(), next_sequence().
J  — DelegatedExecutionTrackingSnapshot: construction, defaults, to_dict(),
     to_json().
K  — DelegatedExecutionTrackingRuntime: push, list_all, list_active,
     get_latest_for_session, get_latest_for_contract, clear, size, capacity.
L  — create_execution_tracking_record: valid inputs → pending_ack record.
M  — create_execution_tracking_record: empty session_id → rejected (cancelled).
N  — create_execution_tracking_record: empty contract_id → rejected (cancelled).
O  — create_execution_tracking_record: trace_id auto-generated when absent.
P  — create_execution_tracking_record: tracker_id override honoured.
Q  — create_execution_tracking_record: posture propagated unchanged.
R  — create_execution_tracking_record: coordination_role forwarded.
S  — create_execution_tracking_record: persisted to runtime ring-buffer.
T  — create_execution_tracking_record: custom runtime isolation.
U  — apply_acknowledgment_signal: ack → acknowledged phase.
V  — apply_acknowledgment_signal: progress → in_progress phase.
W  — apply_acknowledgment_signal: partial_result → in_progress (not terminal).
X  — apply_acknowledgment_signal: final_result → completed phase.
Y  — apply_acknowledgment_signal: error → failed phase.
Z  — apply_acknowledgment_signal: timeout → timed_out phase.
AA — apply_acknowledgment_signal: cancelled → cancelled phase.
AB — apply_acknowledgment_signal: terminal record returned unchanged.
AC — apply_acknowledgment_signal: sequence increments monotonically.
AD — apply_acknowledgment_signal: payload stored in acknowledgment entry.
AE — apply_acknowledgment_signal: persisted to runtime ring-buffer.
AF — apply_result: success=True → completed phase.
AG — apply_result: success=False → failed phase.
AH — apply_result: terminal record returned unchanged.
AI — apply_result: result stored in record.
AJ — apply_result: persisted to runtime ring-buffer.
AK — record_execution_tracking: persists record to runtime.
AL — get_execution_tracking_record: returns most recent for session_id.
AM — get_execution_tracking_record: returns None for unknown session_id.
AN — list_active_execution_tracking_records: returns non-terminal only.
AO — list_active_execution_tracking_records: empty when all terminal.
AP — build_execution_tracking_snapshot: counts active and total correctly.
AQ — build_execution_tracking_snapshot: includes policy sentinels.
AR — build_execution_tracking_snapshot: empty runtime → zero counts.
AS — core.runtime re-exports: all PR-10 symbols accessible from core.runtime.
AT — projection.py sentinel: DELEGATED_RUNTIME_EXECUTION_TRACKER_ALIGNED_PR10
     is present and not UNAVAILABLE.
AU — Ring buffer capacity: 128.
AV — Ring buffer eviction: oldest entry evicted when full.
AW — Serialisation round-trip: DelegatedExecutionTrackingRecord to_dict → from_dict.
AX — Serialisation round-trip: to_json produces valid JSON.
AY — Serialisation: from_dict with non-dict raises ValueError.
AZ — Multiple sessions: each gets its own tracking record.
BA — All 10 policy sentinels are non-empty strings.
BB — DelegatedExecutionPhase.can_advance_to: terminal → False.
BC — DelegatedExecutionPhase.can_advance_to: pending_ack → acknowledged → True.
BD — DelegatedExecutionPhase.can_advance_to: acknowledged → in_progress → True.
BE — DelegatedExecutionPhase.can_advance_to: in_progress → completed → True.
BF — DelegatedExecutionPhase.can_advance_to: pending_ack → cancelled → True.
BG — DelegatedExecutionPhase.can_advance_to: in_progress → pending_ack → False.
BH — DelegatedExecutionTrackingRecord.is_accepted: True when no reject_reason and anchored.
BI — DelegatedExecutionTrackingRecord.is_accepted: False when reject_reason set.
BJ — DelegatedExecutionTrackingRecord.is_rejected: True when reject_reason set.
BK — DelegatedExecutionTrackingRecord.is_active: True when non-terminal.
BL — DelegatedExecutionTrackingRecord.is_terminal: True when terminal.
BM — tracker_id is auto-generated UUID when not provided.
BN — Snapshot to_dict contains 'records', 'active_count', 'total_count'.
BO — Record to_dict: reject_reason empty when accepted.
BP — Record to_dict: identity sub-dict has expected keys.
BQ — Record to_dict: acknowledgments is a list.
BR — get_execution_tracking_runtime returns same singleton.
BS — reset_execution_tracking_runtime clears singleton for isolation.
BT — Two separate sessions: list_active returns both when both active.
BU — create_execution_tracking_record: does not mutate other records in runtime.
BV — end-to-end: create → ack → progress → result → snapshot reflects completed.
BW — DELEGATED_RUNTIME_EXECUTION_TRACKER_PR10_SENTINEL contains 'package=10'.
BX — DelegatedExecutionTrackingRecord from_dict: missing fields use safe defaults.
BY — DelegatedExecutionIdentity from_dict: non-dict raises ValueError.
BZ — DelegatedExecutionAcknowledgment from_dict: non-dict raises ValueError.
CA — DelegatedExecutionResult from_dict: non-dict raises ValueError.
CB — DelegatedExecutionTrackingRecord from_dict: non-dict raises ValueError.
CC — apply_acknowledgment_signal: already-completed record unchanged.
CD — apply_acknowledgment_signal: already-failed record unchanged.
CE — Snapshot to_json is valid JSON.
CF — DelegatedExecutionTrackingRuntime: clear() empties the buffer.
CG — tracker_id is stable across to_dict/from_dict round-trip.
CH — list_active excludes terminal phases.
CI — build_execution_tracking_snapshot: records are newest-first.
CJ — AcknowledgmentSignal.from_string: unknown string → ack.
CK — DelegatedExecutionPhase.from_string: unknown string → pending_ack.
CL — DelegatedExecutionTrackingRuntime.get_latest_for_contract returns correct record.
CM — apply_result: updated_at is later than created_at.
CN — apply_acknowledgment_signal: next_sequence starts at 0 for fresh record.
CO — apply_acknowledgment_signal: multiple signals accumulate in acknowledgments list.
"""

from __future__ import annotations

import json
import time
import uuid

import pytest

from core.delegated_runtime_execution_tracker import (
    ACK_SEQUENCE_IS_MONOTONICALLY_INCREASING_POLICY,
    DELEGATED_RUNTIME_EXECUTION_TRACKER_AUTHORITY,
    DELEGATED_RUNTIME_EXECUTION_TRACKER_PR10_SENTINEL,
    EXECUTION_PHASE_IS_MONOTONIC_POLICY,
    EXECUTION_TRACKING_POSTURE_IS_PROPAGATED_POLICY,
    EXECUTION_TRACKING_REQUIRES_CONTRACT_ID_POLICY,
    EXECUTION_TRACKING_REQUIRES_SESSION_ID_POLICY,
    PARTIAL_RESULT_DOES_NOT_CLOSE_TRACKING_POLICY,
    RESULT_IS_IMMUTABLE_ONCE_RECORDED_POLICY,
    TERMINAL_PHASE_BLOCKS_FURTHER_SIGNALS_POLICY,
    TRACKING_RECORD_IS_CONTRACT_ANCHORED_POLICY,
    AcknowledgmentSignal,
    DelegatedExecutionAcknowledgment,
    DelegatedExecutionIdentity,
    DelegatedExecutionPhase,
    DelegatedExecutionResult,
    DelegatedExecutionTrackingRecord,
    DelegatedExecutionTrackingRuntime,
    DelegatedExecutionTrackingSnapshot,
    apply_acknowledgment_signal,
    apply_result,
    build_execution_tracking_snapshot,
    create_execution_tracking_record,
    get_active_execution_tracking_for_session,
    get_execution_tracking_record,
    get_execution_tracking_runtime,
    list_active_execution_tracking_records,
    record_execution_tracking,
    reset_execution_tracking_runtime,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_runtime() -> DelegatedExecutionTrackingRuntime:
    return DelegatedExecutionTrackingRuntime()


def _make_record(
    session_id: str = "sess-1",
    contract_id: str = "contract-1",
    device_id: str = "dev-1",
    trace_id: str = "",
    posture: str = "join_runtime",
    role: str = "joined_runtime_participant",
    runtime: DelegatedExecutionTrackingRuntime | None = None,
) -> DelegatedExecutionTrackingRecord:
    rt = runtime if runtime is not None else _fresh_runtime()
    return create_execution_tracking_record(
        session_id=session_id,
        contract_id=contract_id,
        device_id=device_id,
        trace_id=trace_id,
        source_runtime_posture=posture,
        coordination_role=role,
        runtime=rt,
    )


# ---------------------------------------------------------------------------
# A — Authority / policy sentinel presence and correctness
# ---------------------------------------------------------------------------


def test_A01_authority_sentinel_non_empty():
    assert DELEGATED_RUNTIME_EXECUTION_TRACKER_AUTHORITY
    assert isinstance(DELEGATED_RUNTIME_EXECUTION_TRACKER_AUTHORITY, str)


def test_A02_authority_sentinel_contains_module_name():
    assert "core.delegated_runtime_execution_tracker" in DELEGATED_RUNTIME_EXECUTION_TRACKER_AUTHORITY


def test_A03_authority_sentinel_contains_pr10():
    assert "PR package 10" in DELEGATED_RUNTIME_EXECUTION_TRACKER_AUTHORITY


def test_A04_pr10_sentinel_non_empty():
    assert DELEGATED_RUNTIME_EXECUTION_TRACKER_PR10_SENTINEL
    assert isinstance(DELEGATED_RUNTIME_EXECUTION_TRACKER_PR10_SENTINEL, str)


# ---------------------------------------------------------------------------
# B — DelegatedExecutionPhase enum
# ---------------------------------------------------------------------------


def test_B01_phase_all_values_present():
    values = {p.value for p in DelegatedExecutionPhase}
    assert values == {
        "pending_ack",
        "acknowledged",
        "in_progress",
        "completed",
        "failed",
        "timed_out",
        "cancelled",
    }


def test_B02_phase_from_string_known():
    assert DelegatedExecutionPhase.from_string("completed") == DelegatedExecutionPhase.completed


def test_B03_phase_from_string_case_insensitive():
    assert DelegatedExecutionPhase.from_string("IN_PROGRESS") == DelegatedExecutionPhase.in_progress


def test_B04_phase_from_string_unknown_defaults_to_pending_ack():
    assert DelegatedExecutionPhase.from_string("bogus") == DelegatedExecutionPhase.pending_ack


def test_B05_phase_from_string_non_string_defaults():
    assert DelegatedExecutionPhase.from_string(None) == DelegatedExecutionPhase.pending_ack  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# C — DelegatedExecutionPhase: is_terminal, is_active, can_advance_to
# ---------------------------------------------------------------------------


def test_C01_terminal_phases():
    for phase in (
        DelegatedExecutionPhase.completed,
        DelegatedExecutionPhase.failed,
        DelegatedExecutionPhase.timed_out,
        DelegatedExecutionPhase.cancelled,
    ):
        assert phase.is_terminal()


def test_C02_non_terminal_phases():
    for phase in (
        DelegatedExecutionPhase.pending_ack,
        DelegatedExecutionPhase.acknowledged,
        DelegatedExecutionPhase.in_progress,
    ):
        assert not phase.is_terminal()
        assert phase.is_active()


def test_C03_terminal_blocks_can_advance_to():
    for terminal in (
        DelegatedExecutionPhase.completed,
        DelegatedExecutionPhase.failed,
        DelegatedExecutionPhase.timed_out,
        DelegatedExecutionPhase.cancelled,
    ):
        assert not terminal.can_advance_to(DelegatedExecutionPhase.pending_ack)
        assert not terminal.can_advance_to(DelegatedExecutionPhase.completed)


def test_C04_pending_ack_can_advance_to_acknowledged():
    assert DelegatedExecutionPhase.pending_ack.can_advance_to(
        DelegatedExecutionPhase.acknowledged
    )


def test_C05_acknowledged_can_advance_to_in_progress():
    assert DelegatedExecutionPhase.acknowledged.can_advance_to(
        DelegatedExecutionPhase.in_progress
    )


def test_C06_in_progress_can_advance_to_completed():
    assert DelegatedExecutionPhase.in_progress.can_advance_to(
        DelegatedExecutionPhase.completed
    )


def test_C07_pending_ack_can_advance_to_cancelled():
    assert DelegatedExecutionPhase.pending_ack.can_advance_to(
        DelegatedExecutionPhase.cancelled
    )


def test_C08_in_progress_cannot_regress_to_pending_ack():
    assert not DelegatedExecutionPhase.in_progress.can_advance_to(
        DelegatedExecutionPhase.pending_ack
    )


# ---------------------------------------------------------------------------
# D — AcknowledgmentSignal enum
# ---------------------------------------------------------------------------


def test_D01_signal_all_values_present():
    values = {s.value for s in AcknowledgmentSignal}
    assert values == {
        "ack",
        "progress",
        "partial_result",
        "final_result",
        "error",
        "timeout",
        "cancelled",
    }


def test_D02_signal_from_string_known():
    assert AcknowledgmentSignal.from_string("error") == AcknowledgmentSignal.error


def test_D03_signal_from_string_case_insensitive():
    assert AcknowledgmentSignal.from_string("FINAL_RESULT") == AcknowledgmentSignal.final_result


def test_D04_signal_from_string_unknown_defaults_to_ack():
    assert AcknowledgmentSignal.from_string("bogus") == AcknowledgmentSignal.ack


def test_D05_signal_from_string_non_string():
    assert AcknowledgmentSignal.from_string(None) == AcknowledgmentSignal.ack  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# E — AcknowledgmentSignal.target_phase()
# ---------------------------------------------------------------------------


def test_E01_ack_targets_acknowledged():
    assert AcknowledgmentSignal.ack.target_phase() == DelegatedExecutionPhase.acknowledged


def test_E02_progress_targets_in_progress():
    assert AcknowledgmentSignal.progress.target_phase() == DelegatedExecutionPhase.in_progress


def test_E03_partial_result_targets_in_progress():
    assert AcknowledgmentSignal.partial_result.target_phase() == DelegatedExecutionPhase.in_progress


def test_E04_final_result_targets_completed():
    assert AcknowledgmentSignal.final_result.target_phase() == DelegatedExecutionPhase.completed


def test_E05_error_targets_failed():
    assert AcknowledgmentSignal.error.target_phase() == DelegatedExecutionPhase.failed


def test_E06_timeout_targets_timed_out():
    assert AcknowledgmentSignal.timeout.target_phase() == DelegatedExecutionPhase.timed_out


def test_E07_cancelled_targets_cancelled():
    assert AcknowledgmentSignal.cancelled.target_phase() == DelegatedExecutionPhase.cancelled


# ---------------------------------------------------------------------------
# F — DelegatedExecutionIdentity
# ---------------------------------------------------------------------------


def test_F01_identity_defaults():
    identity = DelegatedExecutionIdentity()
    assert identity.tracker_id  # auto-generated
    assert identity.session_id == ""
    assert identity.contract_id == ""
    assert identity.device_id == ""
    assert identity.trace_id == ""


def test_F02_identity_construction():
    identity = DelegatedExecutionIdentity(
        tracker_id="t1",
        session_id="s1",
        contract_id="c1",
        device_id="d1",
        trace_id="tr1",
    )
    assert identity.tracker_id == "t1"
    assert identity.session_id == "s1"
    assert identity.contract_id == "c1"
    assert identity.device_id == "d1"
    assert identity.trace_id == "tr1"


def test_F03_identity_to_dict():
    identity = DelegatedExecutionIdentity(
        tracker_id="t1", session_id="s1", contract_id="c1"
    )
    d = identity.to_dict()
    assert d["tracker_id"] == "t1"
    assert d["session_id"] == "s1"
    assert d["contract_id"] == "c1"


def test_F04_identity_to_json():
    identity = DelegatedExecutionIdentity(tracker_id="t1", session_id="s1")
    parsed = json.loads(identity.to_json())
    assert parsed["tracker_id"] == "t1"


def test_F05_identity_from_dict_roundtrip():
    identity = DelegatedExecutionIdentity(
        tracker_id="t1", session_id="s1", contract_id="c1", device_id="d1", trace_id="tr1"
    )
    recovered = DelegatedExecutionIdentity.from_dict(identity.to_dict())
    assert recovered.tracker_id == "t1"
    assert recovered.session_id == "s1"
    assert recovered.contract_id == "c1"


def test_F06_identity_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedExecutionIdentity.from_dict("not-a-dict")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# G — DelegatedExecutionAcknowledgment
# ---------------------------------------------------------------------------


def test_G01_ack_defaults():
    ack = DelegatedExecutionAcknowledgment()
    assert ack.signal == AcknowledgmentSignal.ack
    assert ack.sequence == 0
    assert ack.payload == {}


def test_G02_ack_construction():
    ack = DelegatedExecutionAcknowledgment(
        signal=AcknowledgmentSignal.progress,
        sequence=3,
        payload={"pct": 50},
    )
    assert ack.signal == AcknowledgmentSignal.progress
    assert ack.sequence == 3
    assert ack.payload == {"pct": 50}


def test_G03_ack_to_dict():
    ack = DelegatedExecutionAcknowledgment(signal=AcknowledgmentSignal.error, sequence=1)
    d = ack.to_dict()
    assert d["signal"] == "error"
    assert d["sequence"] == 1


def test_G04_ack_to_json():
    ack = DelegatedExecutionAcknowledgment(signal=AcknowledgmentSignal.ack)
    parsed = json.loads(ack.to_json())
    assert parsed["signal"] == "ack"


def test_G05_ack_from_dict_roundtrip():
    ack = DelegatedExecutionAcknowledgment(
        signal=AcknowledgmentSignal.progress, sequence=2, payload={"x": 1}
    )
    recovered = DelegatedExecutionAcknowledgment.from_dict(ack.to_dict())
    assert recovered.signal == AcknowledgmentSignal.progress
    assert recovered.sequence == 2
    assert recovered.payload == {"x": 1}


def test_G06_ack_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedExecutionAcknowledgment.from_dict(42)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# H — DelegatedExecutionResult
# ---------------------------------------------------------------------------


def test_H01_result_defaults():
    result = DelegatedExecutionResult()
    assert result.success is False
    assert result.result_payload == {}
    assert result.error_detail == ""
    assert result.metadata == {}


def test_H02_result_construction():
    result = DelegatedExecutionResult(
        success=True, result_payload={"answer": 42}, error_detail=""
    )
    assert result.success is True
    assert result.result_payload == {"answer": 42}


def test_H03_result_to_dict():
    result = DelegatedExecutionResult(success=False, error_detail="timeout")
    d = result.to_dict()
    assert d["success"] is False
    assert d["error_detail"] == "timeout"


def test_H04_result_to_json():
    result = DelegatedExecutionResult(success=True)
    parsed = json.loads(result.to_json())
    assert parsed["success"] is True


def test_H05_result_from_dict_roundtrip():
    result = DelegatedExecutionResult(
        success=True, result_payload={"k": "v"}, error_detail="", metadata={"m": 1}
    )
    recovered = DelegatedExecutionResult.from_dict(result.to_dict())
    assert recovered.success is True
    assert recovered.result_payload == {"k": "v"}
    assert recovered.metadata == {"m": 1}


def test_H06_result_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedExecutionResult.from_dict([])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# I — DelegatedExecutionTrackingRecord
# ---------------------------------------------------------------------------


def test_I01_record_defaults():
    record = DelegatedExecutionTrackingRecord()
    assert record.phase == DelegatedExecutionPhase.pending_ack
    assert record.acknowledgments == []
    assert record.result is None
    assert record.reject_reason == ""
    assert record.source_runtime_posture == "control_only"


def test_I02_record_is_accepted_no_reject():
    record = DelegatedExecutionTrackingRecord(
        identity=DelegatedExecutionIdentity(session_id="s1", contract_id="c1"),
        reject_reason="",
    )
    assert record.is_accepted()


def test_I03_record_is_accepted_false_with_reject():
    record = DelegatedExecutionTrackingRecord(
        identity=DelegatedExecutionIdentity(session_id="s1", contract_id="c1"),
        reject_reason="missing session",
    )
    assert not record.is_accepted()


def test_I04_record_is_rejected():
    record = DelegatedExecutionTrackingRecord(reject_reason="bad contract")
    assert record.is_rejected()


def test_I05_record_is_active_when_pending():
    record = DelegatedExecutionTrackingRecord(phase=DelegatedExecutionPhase.pending_ack)
    assert record.is_active()
    assert not record.is_terminal()


def test_I06_record_is_terminal_when_completed():
    record = DelegatedExecutionTrackingRecord(phase=DelegatedExecutionPhase.completed)
    assert record.is_terminal()
    assert not record.is_active()


def test_I07_record_next_sequence_empty():
    record = DelegatedExecutionTrackingRecord()
    assert record.next_sequence() == 0


def test_I08_record_next_sequence_after_acks():
    acks = [
        DelegatedExecutionAcknowledgment(sequence=0),
        DelegatedExecutionAcknowledgment(sequence=1),
    ]
    record = DelegatedExecutionTrackingRecord(acknowledgments=acks)
    assert record.next_sequence() == 2


def test_I09_record_to_dict_keys():
    record = DelegatedExecutionTrackingRecord(
        identity=DelegatedExecutionIdentity(session_id="s1", contract_id="c1"),
    )
    d = record.to_dict()
    assert "identity" in d
    assert "phase" in d
    assert "acknowledgments" in d
    assert "result" in d
    assert "source_runtime_posture" in d
    assert "coordination_role" in d
    assert "reject_reason" in d


def test_I10_record_to_json_valid():
    record = DelegatedExecutionTrackingRecord()
    parsed = json.loads(record.to_json())
    assert parsed["phase"] == "pending_ack"


def test_I11_record_from_dict_roundtrip():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    recovered = DelegatedExecutionTrackingRecord.from_dict(record.to_dict())
    assert recovered.identity.session_id == record.identity.session_id
    assert recovered.phase == record.phase
    assert recovered.source_runtime_posture == record.source_runtime_posture


def test_I12_record_from_dict_missing_fields_safe_defaults():
    recovered = DelegatedExecutionTrackingRecord.from_dict({})
    assert recovered.phase == DelegatedExecutionPhase.pending_ack
    assert recovered.acknowledgments == []
    assert recovered.result is None


def test_I13_record_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedExecutionTrackingRecord.from_dict("bad")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# J — DelegatedExecutionTrackingSnapshot
# ---------------------------------------------------------------------------


def test_J01_snapshot_defaults():
    snap = DelegatedExecutionTrackingSnapshot()
    assert snap.records == []
    assert snap.active_count == 0
    assert snap.total_count == 0
    assert snap.snapshot_id


def test_J02_snapshot_to_dict_keys():
    snap = DelegatedExecutionTrackingSnapshot()
    d = snap.to_dict()
    assert "snapshot_id" in d
    assert "records" in d
    assert "active_count" in d
    assert "total_count" in d
    assert "snapshotted_at" in d
    assert "policy_sentinels" in d


def test_J03_snapshot_to_json():
    snap = DelegatedExecutionTrackingSnapshot()
    parsed = json.loads(snap.to_json())
    assert "snapshot_id" in parsed


# ---------------------------------------------------------------------------
# K — DelegatedExecutionTrackingRuntime
# ---------------------------------------------------------------------------


def test_K01_runtime_initial_size_zero():
    rt = _fresh_runtime()
    assert rt.size == 0


def test_K02_runtime_capacity():
    rt = _fresh_runtime()
    assert rt.capacity == 128


def test_K03_runtime_push_and_list_all():
    rt = _fresh_runtime()
    r = _make_record(runtime=rt)
    all_records = rt.list_all()
    assert len(all_records) == 1
    assert all_records[0].identity.session_id == r.identity.session_id


def test_K04_runtime_list_active():
    rt = _fresh_runtime()
    _make_record(session_id="s1", runtime=rt)
    r2 = _make_record(session_id="s2", runtime=rt)
    # Manually push a terminal record
    terminal = DelegatedExecutionTrackingRecord(
        identity=DelegatedExecutionIdentity(session_id="s3", contract_id="c3"),
        phase=DelegatedExecutionPhase.completed,
    )
    rt.push(terminal)
    active = rt.list_active()
    assert len(active) == 2
    session_ids = {r.identity.session_id for r in active}
    assert "s1" in session_ids
    assert "s2" in session_ids
    assert "s3" not in session_ids


def test_K05_runtime_get_latest_for_session():
    rt = _fresh_runtime()
    _make_record(session_id="s1", runtime=rt)
    found = rt.get_latest_for_session("s1")
    assert found is not None
    assert found.identity.session_id == "s1"


def test_K06_runtime_get_latest_for_session_none_unknown():
    rt = _fresh_runtime()
    assert rt.get_latest_for_session("nonexistent") is None


def test_K07_runtime_get_latest_for_contract():
    rt = _fresh_runtime()
    _make_record(contract_id="c-abc", runtime=rt)
    found = rt.get_latest_for_contract("c-abc")
    assert found is not None
    assert found.identity.contract_id == "c-abc"


def test_K08_runtime_clear():
    rt = _fresh_runtime()
    _make_record(runtime=rt)
    rt.clear()
    assert rt.size == 0


def test_K09_runtime_list_all_newest_first():
    rt = _fresh_runtime()
    r1 = _make_record(session_id="s1", runtime=rt)
    r2 = _make_record(session_id="s2", runtime=rt)
    all_records = rt.list_all()
    assert all_records[0].identity.session_id == r2.identity.session_id
    assert all_records[1].identity.session_id == r1.identity.session_id


# ---------------------------------------------------------------------------
# L — create_execution_tracking_record: valid inputs
# ---------------------------------------------------------------------------


def test_L01_valid_inputs_phase_pending_ack():
    rt = _fresh_runtime()
    record = create_execution_tracking_record(
        session_id="s1", contract_id="c1", runtime=rt
    )
    assert record.phase == DelegatedExecutionPhase.pending_ack
    assert record.is_accepted()
    assert not record.reject_reason


def test_L02_valid_inputs_identity_set():
    rt = _fresh_runtime()
    record = create_execution_tracking_record(
        session_id="s1", contract_id="c1", device_id="d1", runtime=rt
    )
    assert record.identity.session_id == "s1"
    assert record.identity.contract_id == "c1"
    assert record.identity.device_id == "d1"


def test_L03_valid_inputs_acks_empty():
    rt = _fresh_runtime()
    record = create_execution_tracking_record(
        session_id="s1", contract_id="c1", runtime=rt
    )
    assert record.acknowledgments == []


def test_L04_valid_inputs_result_none():
    rt = _fresh_runtime()
    record = create_execution_tracking_record(
        session_id="s1", contract_id="c1", runtime=rt
    )
    assert record.result is None


# ---------------------------------------------------------------------------
# M — create_execution_tracking_record: empty session_id
# ---------------------------------------------------------------------------


def test_M01_empty_session_id_rejected():
    rt = _fresh_runtime()
    record = create_execution_tracking_record(
        session_id="", contract_id="c1", runtime=rt
    )
    assert record.is_rejected()
    assert record.phase == DelegatedExecutionPhase.cancelled
    assert "session_id" in record.reject_reason.lower()


def test_M02_empty_session_id_persisted():
    rt = _fresh_runtime()
    create_execution_tracking_record(session_id="", contract_id="c1", runtime=rt)
    assert rt.size == 1


# ---------------------------------------------------------------------------
# N — create_execution_tracking_record: empty contract_id
# ---------------------------------------------------------------------------


def test_N01_empty_contract_id_rejected():
    rt = _fresh_runtime()
    record = create_execution_tracking_record(
        session_id="s1", contract_id="", runtime=rt
    )
    assert record.is_rejected()
    assert record.phase == DelegatedExecutionPhase.cancelled
    assert "contract_id" in record.reject_reason.lower()


def test_N02_empty_contract_id_persisted():
    rt = _fresh_runtime()
    create_execution_tracking_record(session_id="s1", contract_id="", runtime=rt)
    assert rt.size == 1


# ---------------------------------------------------------------------------
# O — trace_id auto-generated when absent
# ---------------------------------------------------------------------------


def test_O01_trace_id_auto_generated():
    rt = _fresh_runtime()
    record = create_execution_tracking_record(
        session_id="s1", contract_id="c1", trace_id="", runtime=rt
    )
    assert record.identity.trace_id  # non-empty auto-generated UUID


def test_O02_trace_id_propagated_when_provided():
    rt = _fresh_runtime()
    record = create_execution_tracking_record(
        session_id="s1", contract_id="c1", trace_id="my-trace-id", runtime=rt
    )
    assert record.identity.trace_id == "my-trace-id"


# ---------------------------------------------------------------------------
# P — tracker_id override
# ---------------------------------------------------------------------------


def test_P01_tracker_id_override_honoured():
    rt = _fresh_runtime()
    record = create_execution_tracking_record(
        session_id="s1", contract_id="c1", tracker_id="fixed-id", runtime=rt
    )
    assert record.identity.tracker_id == "fixed-id"


def test_P02_tracker_id_auto_generated_when_absent():
    rt = _fresh_runtime()
    record = create_execution_tracking_record(
        session_id="s1", contract_id="c1", runtime=rt
    )
    assert record.identity.tracker_id


# ---------------------------------------------------------------------------
# Q — posture propagated unchanged
# ---------------------------------------------------------------------------


def test_Q01_posture_join_runtime_preserved():
    rt = _fresh_runtime()
    record = create_execution_tracking_record(
        session_id="s1",
        contract_id="c1",
        source_runtime_posture="join_runtime",
        runtime=rt,
    )
    assert record.source_runtime_posture == "join_runtime"


def test_Q02_posture_control_only_preserved():
    rt = _fresh_runtime()
    record = create_execution_tracking_record(
        session_id="s1",
        contract_id="c1",
        source_runtime_posture="control_only",
        runtime=rt,
    )
    assert record.source_runtime_posture == "control_only"


# ---------------------------------------------------------------------------
# R — coordination_role forwarded
# ---------------------------------------------------------------------------


def test_R01_coordination_role_forwarded():
    rt = _fresh_runtime()
    record = create_execution_tracking_record(
        session_id="s1",
        contract_id="c1",
        coordination_role="joined_runtime_participant",
        runtime=rt,
    )
    assert record.coordination_role == "joined_runtime_participant"


# ---------------------------------------------------------------------------
# S — persisted to runtime ring-buffer
# ---------------------------------------------------------------------------


def test_S01_create_persists_to_runtime():
    rt = _fresh_runtime()
    create_execution_tracking_record(session_id="s1", contract_id="c1", runtime=rt)
    assert rt.size == 1


def test_S02_multiple_creates_accumulate():
    rt = _fresh_runtime()
    create_execution_tracking_record(session_id="s1", contract_id="c1", runtime=rt)
    create_execution_tracking_record(session_id="s2", contract_id="c2", runtime=rt)
    assert rt.size == 2


# ---------------------------------------------------------------------------
# T — custom runtime isolation
# ---------------------------------------------------------------------------


def test_T01_custom_runtime_does_not_affect_singleton():
    reset_execution_tracking_runtime()
    rt = _fresh_runtime()
    create_execution_tracking_record(session_id="s1", contract_id="c1", runtime=rt)
    singleton = get_execution_tracking_runtime()
    assert singleton.size == 0


# ---------------------------------------------------------------------------
# U-AA — apply_acknowledgment_signal phase transitions
# ---------------------------------------------------------------------------


def test_U01_ack_signal_advances_to_acknowledged():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    updated = apply_acknowledgment_signal(record, AcknowledgmentSignal.ack, runtime=rt)
    assert updated.phase == DelegatedExecutionPhase.acknowledged


def test_V01_progress_signal_advances_to_in_progress():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    updated = apply_acknowledgment_signal(record, AcknowledgmentSignal.progress, runtime=rt)
    assert updated.phase == DelegatedExecutionPhase.in_progress


def test_W01_partial_result_advances_to_in_progress():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    updated = apply_acknowledgment_signal(
        record, AcknowledgmentSignal.partial_result, runtime=rt
    )
    assert updated.phase == DelegatedExecutionPhase.in_progress
    assert not updated.phase.is_terminal()


def test_X01_final_result_signal_advances_to_completed():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    updated = apply_acknowledgment_signal(
        record, AcknowledgmentSignal.final_result, runtime=rt
    )
    assert updated.phase == DelegatedExecutionPhase.completed


def test_Y01_error_signal_advances_to_failed():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    updated = apply_acknowledgment_signal(record, AcknowledgmentSignal.error, runtime=rt)
    assert updated.phase == DelegatedExecutionPhase.failed


def test_Z01_timeout_signal_advances_to_timed_out():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    updated = apply_acknowledgment_signal(record, AcknowledgmentSignal.timeout, runtime=rt)
    assert updated.phase == DelegatedExecutionPhase.timed_out


def test_AA01_cancelled_signal_advances_to_cancelled():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    updated = apply_acknowledgment_signal(
        record, AcknowledgmentSignal.cancelled, runtime=rt
    )
    assert updated.phase == DelegatedExecutionPhase.cancelled


# ---------------------------------------------------------------------------
# AB — apply_acknowledgment_signal: terminal record returned unchanged
# ---------------------------------------------------------------------------


def test_AB01_terminal_record_unchanged_on_ack():
    rt = _fresh_runtime()
    record = DelegatedExecutionTrackingRecord(
        identity=DelegatedExecutionIdentity(session_id="s1", contract_id="c1"),
        phase=DelegatedExecutionPhase.completed,
    )
    returned = apply_acknowledgment_signal(record, AcknowledgmentSignal.ack, runtime=rt)
    assert returned is record


# ---------------------------------------------------------------------------
# AC — apply_acknowledgment_signal: sequence increments
# ---------------------------------------------------------------------------


def test_AC01_sequence_increments_monotonically():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    r1 = apply_acknowledgment_signal(record, AcknowledgmentSignal.ack, runtime=rt)
    r2 = apply_acknowledgment_signal(r1, AcknowledgmentSignal.progress, runtime=rt)
    assert r1.acknowledgments[-1].sequence == 0
    assert r2.acknowledgments[-1].sequence == 1


# ---------------------------------------------------------------------------
# AD — apply_acknowledgment_signal: payload stored
# ---------------------------------------------------------------------------


def test_AD01_payload_stored_in_ack():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    updated = apply_acknowledgment_signal(
        record, AcknowledgmentSignal.progress, payload={"pct": 75}, runtime=rt
    )
    assert updated.acknowledgments[-1].payload == {"pct": 75}


# ---------------------------------------------------------------------------
# AE — apply_acknowledgment_signal: persisted to runtime
# ---------------------------------------------------------------------------


def test_AE01_ack_persists_to_runtime():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    size_before = rt.size
    apply_acknowledgment_signal(record, AcknowledgmentSignal.ack, runtime=rt)
    assert rt.size == size_before + 1


# ---------------------------------------------------------------------------
# AF-AJ — apply_result
# ---------------------------------------------------------------------------


def test_AF01_success_result_advances_to_completed():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    result = DelegatedExecutionResult(success=True, result_payload={"ans": 1})
    updated = apply_result(record, result, runtime=rt)
    assert updated.phase == DelegatedExecutionPhase.completed
    assert updated.result is not None
    assert updated.result.success is True


def test_AG01_failure_result_advances_to_failed():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    result = DelegatedExecutionResult(success=False, error_detail="crash")
    updated = apply_result(record, result, runtime=rt)
    assert updated.phase == DelegatedExecutionPhase.failed
    assert updated.result is not None
    assert updated.result.error_detail == "crash"


def test_AH01_terminal_record_unchanged_on_apply_result():
    rt = _fresh_runtime()
    record = DelegatedExecutionTrackingRecord(
        identity=DelegatedExecutionIdentity(session_id="s1", contract_id="c1"),
        phase=DelegatedExecutionPhase.failed,
        result=DelegatedExecutionResult(success=False),
    )
    new_result = DelegatedExecutionResult(success=True)
    returned = apply_result(record, new_result, runtime=rt)
    assert returned is record


def test_AI01_result_stored_in_record():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    result = DelegatedExecutionResult(success=True, result_payload={"k": "v"})
    updated = apply_result(record, result, runtime=rt)
    assert updated.result is not None
    assert updated.result.result_payload == {"k": "v"}


def test_AJ01_apply_result_persists_to_runtime():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    size_before = rt.size
    apply_result(record, DelegatedExecutionResult(success=True), runtime=rt)
    assert rt.size == size_before + 1


# ---------------------------------------------------------------------------
# AK — record_execution_tracking
# ---------------------------------------------------------------------------


def test_AK01_record_persists():
    rt = _fresh_runtime()
    record = DelegatedExecutionTrackingRecord(
        identity=DelegatedExecutionIdentity(session_id="s1", contract_id="c1")
    )
    record_execution_tracking(record, runtime=rt)
    assert rt.size == 1


# ---------------------------------------------------------------------------
# AL-AM — get_execution_tracking_record
# ---------------------------------------------------------------------------


def test_AL01_get_returns_most_recent_for_session():
    rt = _fresh_runtime()
    create_execution_tracking_record(session_id="s1", contract_id="c1", runtime=rt)
    found = get_execution_tracking_record("s1", runtime=rt)
    assert found is not None
    assert found.identity.session_id == "s1"


def test_AM01_get_returns_none_for_unknown():
    rt = _fresh_runtime()
    assert get_execution_tracking_record("nonexistent", runtime=rt) is None


# ---------------------------------------------------------------------------
# AN-AO — list_active_execution_tracking_records
# ---------------------------------------------------------------------------


def test_AN01_list_active_returns_non_terminal():
    rt = _fresh_runtime()
    create_execution_tracking_record(session_id="s1", contract_id="c1", runtime=rt)
    terminal = DelegatedExecutionTrackingRecord(
        identity=DelegatedExecutionIdentity(session_id="s2", contract_id="c2"),
        phase=DelegatedExecutionPhase.completed,
    )
    rt.push(terminal)
    active = list_active_execution_tracking_records(runtime=rt)
    assert len(active) == 1
    assert active[0].identity.session_id == "s1"


def test_AO01_list_active_empty_when_all_terminal():
    rt = _fresh_runtime()
    for i in range(3):
        rt.push(
            DelegatedExecutionTrackingRecord(
                identity=DelegatedExecutionIdentity(
                    session_id=f"s{i}", contract_id=f"c{i}"
                ),
                phase=DelegatedExecutionPhase.failed,
            )
        )
    assert list_active_execution_tracking_records(runtime=rt) == []


# ---------------------------------------------------------------------------
# AP-AR — build_execution_tracking_snapshot
# ---------------------------------------------------------------------------


def test_AP01_snapshot_counts_active_and_total():
    rt = _fresh_runtime()
    create_execution_tracking_record(session_id="s1", contract_id="c1", runtime=rt)
    terminal = DelegatedExecutionTrackingRecord(
        identity=DelegatedExecutionIdentity(session_id="s2", contract_id="c2"),
        phase=DelegatedExecutionPhase.completed,
    )
    rt.push(terminal)
    snap = build_execution_tracking_snapshot(runtime=rt)
    assert snap.total_count == 2
    assert snap.active_count == 1


def test_AQ01_snapshot_includes_policy_sentinels():
    rt = _fresh_runtime()
    snap = build_execution_tracking_snapshot(runtime=rt)
    assert len(snap.policy_sentinels) >= 10
    assert DELEGATED_RUNTIME_EXECUTION_TRACKER_AUTHORITY in snap.policy_sentinels


def test_AR01_snapshot_empty_runtime_zero_counts():
    rt = _fresh_runtime()
    snap = build_execution_tracking_snapshot(runtime=rt)
    assert snap.total_count == 0
    assert snap.active_count == 0
    assert snap.records == []


# ---------------------------------------------------------------------------
# AS — core.runtime re-exports
# ---------------------------------------------------------------------------


def test_AS01_core_runtime_reexports_all_pr10_symbols():
    pytest.importorskip("pydantic")
    import core.runtime as cr

    assert hasattr(cr, "DELEGATED_RUNTIME_EXECUTION_TRACKER_AUTHORITY")
    assert hasattr(cr, "DELEGATED_RUNTIME_EXECUTION_TRACKER_PR10_SENTINEL")
    assert hasattr(cr, "DelegatedExecutionPhase")
    assert hasattr(cr, "AcknowledgmentSignal")
    assert hasattr(cr, "DelegatedExecutionIdentity")
    assert hasattr(cr, "DelegatedExecutionAcknowledgment")
    assert hasattr(cr, "DelegatedExecutionResult")
    assert hasattr(cr, "DelegatedExecutionTrackingRecord")
    assert hasattr(cr, "DelegatedExecutionTrackingSnapshot")
    assert hasattr(cr, "DelegatedExecutionTrackingRuntime")
    assert hasattr(cr, "create_execution_tracking_record")
    assert hasattr(cr, "apply_acknowledgment_signal")
    assert hasattr(cr, "apply_result")
    assert hasattr(cr, "record_execution_tracking")
    assert hasattr(cr, "get_execution_tracking_record")
    assert hasattr(cr, "list_active_execution_tracking_records")
    assert hasattr(cr, "build_execution_tracking_snapshot")
    assert hasattr(cr, "get_execution_tracking_runtime")
    assert hasattr(cr, "reset_execution_tracking_runtime")


def test_AS02_policy_sentinels_in_core_runtime():
    pytest.importorskip("pydantic")
    import core.runtime as cr

    assert hasattr(cr, "EXECUTION_TRACKING_REQUIRES_CONTRACT_ID_POLICY")
    assert hasattr(cr, "EXECUTION_TRACKING_REQUIRES_SESSION_ID_POLICY")
    assert hasattr(cr, "EXECUTION_PHASE_IS_MONOTONIC_POLICY")
    assert hasattr(cr, "ACK_SEQUENCE_IS_MONOTONICALLY_INCREASING_POLICY")
    assert hasattr(cr, "RESULT_IS_IMMUTABLE_ONCE_RECORDED_POLICY")
    assert hasattr(cr, "EXECUTION_TRACKING_POSTURE_IS_PROPAGATED_POLICY")
    assert hasattr(cr, "TERMINAL_PHASE_BLOCKS_FURTHER_SIGNALS_POLICY")
    assert hasattr(cr, "TRACKING_RECORD_IS_CONTRACT_ANCHORED_POLICY")
    assert hasattr(cr, "PARTIAL_RESULT_DOES_NOT_CLOSE_TRACKING_POLICY")


# ---------------------------------------------------------------------------
# AT — projection.py sentinel
# ---------------------------------------------------------------------------


def test_AT01_projection_sentinel_present_and_not_unavailable():
    pytest.importorskip("fastapi")
    from core.routes.projection import DELEGATED_RUNTIME_EXECUTION_TRACKER_ALIGNED_PR10

    assert DELEGATED_RUNTIME_EXECUTION_TRACKER_ALIGNED_PR10
    assert "UNAVAILABLE" not in DELEGATED_RUNTIME_EXECUTION_TRACKER_ALIGNED_PR10


def test_AT02_projection_sentinel_contains_pr10():
    pytest.importorskip("fastapi")
    from core.routes.projection import DELEGATED_RUNTIME_EXECUTION_TRACKER_ALIGNED_PR10

    assert "PR10" in DELEGATED_RUNTIME_EXECUTION_TRACKER_ALIGNED_PR10 or (
        "package 10" in DELEGATED_RUNTIME_EXECUTION_TRACKER_ALIGNED_PR10
        or "ALIGNED_PR10" in DELEGATED_RUNTIME_EXECUTION_TRACKER_ALIGNED_PR10
    )


# ---------------------------------------------------------------------------
# AU-AV — Ring buffer capacity and eviction
# ---------------------------------------------------------------------------


def test_AU01_ring_buffer_capacity_128():
    rt = _fresh_runtime()
    assert rt.capacity == 128


def test_AV01_ring_buffer_evicts_oldest():
    rt = _fresh_runtime()
    for i in range(129):
        rt.push(
            DelegatedExecutionTrackingRecord(
                identity=DelegatedExecutionIdentity(
                    tracker_id=f"t{i}", session_id=f"s{i}", contract_id=f"c{i}"
                )
            )
        )
    assert rt.size == 128
    all_records = rt.list_all()
    tracker_ids = {r.identity.tracker_id for r in all_records}
    assert "t0" not in tracker_ids
    assert "t128" in tracker_ids


# ---------------------------------------------------------------------------
# AW-AY — Serialisation
# ---------------------------------------------------------------------------


def test_AW01_serialisation_roundtrip():
    rt = _fresh_runtime()
    record = _make_record(session_id="s1", contract_id="c1", runtime=rt)
    recovered = DelegatedExecutionTrackingRecord.from_dict(record.to_dict())
    assert recovered.identity.session_id == "s1"
    assert recovered.phase == DelegatedExecutionPhase.pending_ack
    assert recovered.source_runtime_posture == "join_runtime"


def test_AX01_to_json_valid():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    parsed = json.loads(record.to_json())
    assert isinstance(parsed, dict)
    assert parsed["phase"] == "pending_ack"


def test_AY01_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedExecutionTrackingRecord.from_dict(123)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AZ — Multiple sessions
# ---------------------------------------------------------------------------


def test_AZ01_multiple_sessions_independent():
    rt = _fresh_runtime()
    r1 = create_execution_tracking_record(session_id="sA", contract_id="cA", runtime=rt)
    r2 = create_execution_tracking_record(session_id="sB", contract_id="cB", runtime=rt)
    found_a = rt.get_latest_for_session("sA")
    found_b = rt.get_latest_for_session("sB")
    assert found_a is not None and found_a.identity.session_id == "sA"
    assert found_b is not None and found_b.identity.session_id == "sB"


# ---------------------------------------------------------------------------
# BA — All 10 policy sentinels are non-empty
# ---------------------------------------------------------------------------


def test_BA01_all_policy_sentinels_non_empty():
    sentinels = [
        DELEGATED_RUNTIME_EXECUTION_TRACKER_AUTHORITY,
        EXECUTION_TRACKING_REQUIRES_CONTRACT_ID_POLICY,
        EXECUTION_TRACKING_REQUIRES_SESSION_ID_POLICY,
        EXECUTION_PHASE_IS_MONOTONIC_POLICY,
        ACK_SEQUENCE_IS_MONOTONICALLY_INCREASING_POLICY,
        RESULT_IS_IMMUTABLE_ONCE_RECORDED_POLICY,
        EXECUTION_TRACKING_POSTURE_IS_PROPAGATED_POLICY,
        TERMINAL_PHASE_BLOCKS_FURTHER_SIGNALS_POLICY,
        TRACKING_RECORD_IS_CONTRACT_ANCHORED_POLICY,
        PARTIAL_RESULT_DOES_NOT_CLOSE_TRACKING_POLICY,
    ]
    for sentinel in sentinels:
        assert sentinel, f"Sentinel is empty: {sentinel!r}"
        assert isinstance(sentinel, str)


# ---------------------------------------------------------------------------
# BB-BG — can_advance_to detailed
# ---------------------------------------------------------------------------


def test_BB01_terminal_cannot_advance():
    for terminal in (
        DelegatedExecutionPhase.completed,
        DelegatedExecutionPhase.failed,
        DelegatedExecutionPhase.timed_out,
        DelegatedExecutionPhase.cancelled,
    ):
        assert not terminal.can_advance_to(DelegatedExecutionPhase.completed)


def test_BC01_pending_ack_to_acknowledged():
    assert DelegatedExecutionPhase.pending_ack.can_advance_to(
        DelegatedExecutionPhase.acknowledged
    )


def test_BD01_acknowledged_to_in_progress():
    assert DelegatedExecutionPhase.acknowledged.can_advance_to(
        DelegatedExecutionPhase.in_progress
    )


def test_BE01_in_progress_to_completed():
    assert DelegatedExecutionPhase.in_progress.can_advance_to(
        DelegatedExecutionPhase.completed
    )


def test_BF01_pending_ack_to_cancelled():
    assert DelegatedExecutionPhase.pending_ack.can_advance_to(
        DelegatedExecutionPhase.cancelled
    )


def test_BG01_in_progress_cannot_regress():
    assert not DelegatedExecutionPhase.in_progress.can_advance_to(
        DelegatedExecutionPhase.pending_ack
    )
    assert not DelegatedExecutionPhase.in_progress.can_advance_to(
        DelegatedExecutionPhase.acknowledged
    )


# ---------------------------------------------------------------------------
# BH-BL — Record convenience accessors
# ---------------------------------------------------------------------------


def test_BH01_is_accepted_true_when_anchored_no_reject():
    record = DelegatedExecutionTrackingRecord(
        identity=DelegatedExecutionIdentity(session_id="s1", contract_id="c1"),
        reject_reason="",
    )
    assert record.is_accepted()


def test_BI01_is_accepted_false_with_empty_session():
    record = DelegatedExecutionTrackingRecord(
        identity=DelegatedExecutionIdentity(session_id="", contract_id="c1")
    )
    assert not record.is_accepted()


def test_BJ01_is_rejected_true_when_reject_reason_set():
    record = DelegatedExecutionTrackingRecord(reject_reason="missing contract")
    assert record.is_rejected()


def test_BK01_is_active_non_terminal():
    record = DelegatedExecutionTrackingRecord(phase=DelegatedExecutionPhase.in_progress)
    assert record.is_active()


def test_BL01_is_terminal_terminal():
    record = DelegatedExecutionTrackingRecord(phase=DelegatedExecutionPhase.timed_out)
    assert record.is_terminal()


def test_BM01_tracker_id_auto_generated():
    record = DelegatedExecutionTrackingRecord()
    assert record.identity.tracker_id


# ---------------------------------------------------------------------------
# BN-BQ — to_dict structure
# ---------------------------------------------------------------------------


def test_BN01_snapshot_to_dict_has_required_keys():
    snap = DelegatedExecutionTrackingSnapshot(active_count=1, total_count=2)
    d = snap.to_dict()
    assert d["active_count"] == 1
    assert d["total_count"] == 2


def test_BO01_record_reject_reason_empty_when_accepted():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    assert record.to_dict()["reject_reason"] == ""


def test_BP01_record_identity_sub_dict_keys():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    identity_dict = record.to_dict()["identity"]
    assert "tracker_id" in identity_dict
    assert "session_id" in identity_dict
    assert "contract_id" in identity_dict
    assert "device_id" in identity_dict
    assert "trace_id" in identity_dict


def test_BQ01_acknowledgments_is_list():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    assert isinstance(record.to_dict()["acknowledgments"], list)


# ---------------------------------------------------------------------------
# BR-BS — Singleton accessor and reset
# ---------------------------------------------------------------------------


def test_BR01_get_runtime_returns_same_singleton():
    reset_execution_tracking_runtime()
    rt1 = get_execution_tracking_runtime()
    rt2 = get_execution_tracking_runtime()
    assert rt1 is rt2


def test_BS01_reset_clears_singleton():
    reset_execution_tracking_runtime()
    create_execution_tracking_record(session_id="s1", contract_id="c1")
    reset_execution_tracking_runtime()
    singleton = get_execution_tracking_runtime()
    assert singleton.size == 0


# ---------------------------------------------------------------------------
# BT — Two separate sessions both active
# ---------------------------------------------------------------------------


def test_BT01_two_sessions_both_appear_in_list_active():
    rt = _fresh_runtime()
    create_execution_tracking_record(session_id="sX", contract_id="cX", runtime=rt)
    create_execution_tracking_record(session_id="sY", contract_id="cY", runtime=rt)
    active = list_active_execution_tracking_records(runtime=rt)
    session_ids = {r.identity.session_id for r in active}
    assert "sX" in session_ids
    assert "sY" in session_ids


# ---------------------------------------------------------------------------
# BU — create does not mutate other records
# ---------------------------------------------------------------------------


def test_BU01_does_not_mutate_other_records():
    rt = _fresh_runtime()
    r1 = create_execution_tracking_record(session_id="s1", contract_id="c1", runtime=rt)
    create_execution_tracking_record(session_id="s2", contract_id="c2", runtime=rt)
    still_r1 = rt.get_latest_for_session("s1")
    assert still_r1 is not None
    assert still_r1.identity.session_id == r1.identity.session_id


# ---------------------------------------------------------------------------
# BV — End-to-end: create → ack → result → snapshot
# ---------------------------------------------------------------------------


def test_BV01_end_to_end_lifecycle():
    rt = _fresh_runtime()
    record = create_execution_tracking_record(
        session_id="e2e-session",
        contract_id="e2e-contract",
        source_runtime_posture="join_runtime",
        runtime=rt,
    )
    assert record.phase == DelegatedExecutionPhase.pending_ack

    record = apply_acknowledgment_signal(record, AcknowledgmentSignal.ack, runtime=rt)
    assert record.phase == DelegatedExecutionPhase.acknowledged

    record = apply_acknowledgment_signal(
        record, AcknowledgmentSignal.progress, payload={"pct": 50}, runtime=rt
    )
    assert record.phase == DelegatedExecutionPhase.in_progress

    result = DelegatedExecutionResult(success=True, result_payload={"output": "done"})
    record = apply_result(record, result, runtime=rt)
    assert record.phase == DelegatedExecutionPhase.completed
    assert record.result is not None and record.result.success

    snap = build_execution_tracking_snapshot(runtime=rt)
    completed = [r for r in snap.records if r.phase == DelegatedExecutionPhase.completed]
    assert len(completed) >= 1
    # The most recent record for this session should be completed
    latest = rt.get_latest_for_session("e2e-session")
    assert latest is not None
    assert latest.phase == DelegatedExecutionPhase.completed


# ---------------------------------------------------------------------------
# BW — PR10_SENTINEL contains 'package=10'
# ---------------------------------------------------------------------------


def test_BW01_pr10_sentinel_contains_package10():
    assert "package=10" in DELEGATED_RUNTIME_EXECUTION_TRACKER_PR10_SENTINEL


# ---------------------------------------------------------------------------
# BX — from_dict with missing fields uses safe defaults
# ---------------------------------------------------------------------------


def test_BX01_from_dict_missing_fields():
    recovered = DelegatedExecutionTrackingRecord.from_dict({"phase": "in_progress"})
    assert recovered.phase == DelegatedExecutionPhase.in_progress
    assert recovered.acknowledgments == []
    assert recovered.result is None


# ---------------------------------------------------------------------------
# BY-CB — Individual sub-dict non-dict raises ValueError
# ---------------------------------------------------------------------------


def test_BY01_identity_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedExecutionIdentity.from_dict("bad")  # type: ignore[arg-type]


def test_BZ01_ack_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedExecutionAcknowledgment.from_dict(42)  # type: ignore[arg-type]


def test_CA01_result_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedExecutionResult.from_dict([])  # type: ignore[arg-type]


def test_CB01_record_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedExecutionTrackingRecord.from_dict("bad")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# CC-CD — apply_acknowledgment_signal on terminal records
# ---------------------------------------------------------------------------


def test_CC01_already_completed_unchanged():
    rt = _fresh_runtime()
    record = DelegatedExecutionTrackingRecord(
        identity=DelegatedExecutionIdentity(session_id="s1", contract_id="c1"),
        phase=DelegatedExecutionPhase.completed,
    )
    returned = apply_acknowledgment_signal(record, AcknowledgmentSignal.ack, runtime=rt)
    assert returned is record


def test_CD01_already_failed_unchanged():
    rt = _fresh_runtime()
    record = DelegatedExecutionTrackingRecord(
        identity=DelegatedExecutionIdentity(session_id="s1", contract_id="c1"),
        phase=DelegatedExecutionPhase.failed,
    )
    returned = apply_acknowledgment_signal(record, AcknowledgmentSignal.progress, runtime=rt)
    assert returned is record


# ---------------------------------------------------------------------------
# CE — Snapshot to_json is valid JSON
# ---------------------------------------------------------------------------


def test_CE01_snapshot_to_json_valid():
    rt = _fresh_runtime()
    create_execution_tracking_record(session_id="s1", contract_id="c1", runtime=rt)
    snap = build_execution_tracking_snapshot(runtime=rt)
    parsed = json.loads(snap.to_json())
    assert isinstance(parsed, dict)
    assert "records" in parsed


# ---------------------------------------------------------------------------
# CF — clear() empties buffer
# ---------------------------------------------------------------------------


def test_CF01_clear_empties_buffer():
    rt = _fresh_runtime()
    create_execution_tracking_record(session_id="s1", contract_id="c1", runtime=rt)
    assert rt.size > 0
    rt.clear()
    assert rt.size == 0


# ---------------------------------------------------------------------------
# CG — tracker_id stable across serialisation roundtrip
# ---------------------------------------------------------------------------


def test_CG01_tracker_id_stable_roundtrip():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    tracker_id = record.identity.tracker_id
    recovered = DelegatedExecutionTrackingRecord.from_dict(record.to_dict())
    assert recovered.identity.tracker_id == tracker_id


# ---------------------------------------------------------------------------
# CH — list_active excludes terminal phases
# ---------------------------------------------------------------------------


def test_CH01_list_active_excludes_all_terminal_phases():
    rt = _fresh_runtime()
    for phase in (
        DelegatedExecutionPhase.completed,
        DelegatedExecutionPhase.failed,
        DelegatedExecutionPhase.timed_out,
        DelegatedExecutionPhase.cancelled,
    ):
        rt.push(
            DelegatedExecutionTrackingRecord(
                identity=DelegatedExecutionIdentity(
                    session_id=f"s-{phase.value}", contract_id=f"c-{phase.value}"
                ),
                phase=phase,
            )
        )
    active = list_active_execution_tracking_records(runtime=rt)
    assert active == []


# ---------------------------------------------------------------------------
# CI — build_execution_tracking_snapshot records newest-first
# ---------------------------------------------------------------------------


def test_CI01_snapshot_records_newest_first():
    rt = _fresh_runtime()
    r1 = create_execution_tracking_record(session_id="s1", contract_id="c1", runtime=rt)
    r2 = create_execution_tracking_record(session_id="s2", contract_id="c2", runtime=rt)
    snap = build_execution_tracking_snapshot(runtime=rt)
    assert len(snap.records) >= 2
    assert snap.records[0].identity.session_id == r2.identity.session_id


# ---------------------------------------------------------------------------
# CJ-CK — from_string unknown input defaults
# ---------------------------------------------------------------------------


def test_CJ01_ack_signal_from_string_unknown():
    assert AcknowledgmentSignal.from_string("does_not_exist") == AcknowledgmentSignal.ack


def test_CK01_phase_from_string_unknown():
    assert (
        DelegatedExecutionPhase.from_string("does_not_exist")
        == DelegatedExecutionPhase.pending_ack
    )


# ---------------------------------------------------------------------------
# CL — get_latest_for_contract returns correct record
# ---------------------------------------------------------------------------


def test_CL01_get_latest_for_contract():
    rt = _fresh_runtime()
    create_execution_tracking_record(
        session_id="s1", contract_id="c-target", runtime=rt
    )
    create_execution_tracking_record(
        session_id="s2", contract_id="c-other", runtime=rt
    )
    found = rt.get_latest_for_contract("c-target")
    assert found is not None
    assert found.identity.contract_id == "c-target"
    assert found.identity.session_id == "s1"


# ---------------------------------------------------------------------------
# CM — apply_result: updated_at >= created_at
# ---------------------------------------------------------------------------


def test_CM01_apply_result_updated_at_later():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    created = record.created_at
    time.sleep(0.01)
    result = DelegatedExecutionResult(success=True)
    updated = apply_result(record, result, runtime=rt)
    assert updated.updated_at >= created


# ---------------------------------------------------------------------------
# CN — apply_acknowledgment_signal: next_sequence starts at 0
# ---------------------------------------------------------------------------


def test_CN01_next_sequence_starts_at_zero():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    assert record.next_sequence() == 0
    updated = apply_acknowledgment_signal(record, AcknowledgmentSignal.ack, runtime=rt)
    assert updated.acknowledgments[0].sequence == 0


# ---------------------------------------------------------------------------
# CO — apply_acknowledgment_signal: multiple signals accumulate
# ---------------------------------------------------------------------------


def test_CO01_multiple_signals_accumulate():
    rt = _fresh_runtime()
    record = _make_record(runtime=rt)
    r1 = apply_acknowledgment_signal(record, AcknowledgmentSignal.ack, runtime=rt)
    r2 = apply_acknowledgment_signal(r1, AcknowledgmentSignal.progress, runtime=rt)
    r3 = apply_acknowledgment_signal(
        r2, AcknowledgmentSignal.partial_result, payload={"part": 1}, runtime=rt
    )
    assert len(r3.acknowledgments) == 3
    assert r3.acknowledgments[0].signal == AcknowledgmentSignal.ack
    assert r3.acknowledgments[1].signal == AcknowledgmentSignal.progress
    assert r3.acknowledgments[2].signal == AcknowledgmentSignal.partial_result
    assert r3.acknowledgments[2].payload == {"part": 1}


def test_CP01_durable_runtime_restores_terminal_record(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "GALAXY_DELEGATED_RUNTIME_EXECUTION_TRACKER_STATE_PATH",
        str(tmp_path / "tracker-state.json"),
    )
    reset_execution_tracking_runtime(clear_durable_state=True)
    record = create_execution_tracking_record(
        session_id="sess-durable-terminal",
        contract_id="contract-durable-terminal",
        device_id="android-durable",
    )
    apply_result(
        record,
        DelegatedExecutionResult(success=True, result_payload={"ok": True}),
    )

    reset_execution_tracking_runtime(clear_durable_state=False)
    restored = get_execution_tracking_record("sess-durable-terminal")
    assert restored is not None
    assert restored.phase == DelegatedExecutionPhase.completed
    assert restored.recovered_from_durable_state is True
    assert restored.recovery_status == "recovered_terminal_historical"


def test_CQ01_recovered_nonterminal_record_requires_revalidation(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "GALAXY_DELEGATED_RUNTIME_EXECUTION_TRACKER_STATE_PATH",
        str(tmp_path / "tracker-state.json"),
    )
    reset_execution_tracking_runtime(clear_durable_state=True)
    create_execution_tracking_record(
        session_id="sess-recover-active",
        contract_id="contract-recover-active",
        device_id="android-recover-active",
    )

    reset_execution_tracking_runtime(clear_durable_state=False)
    restored = get_execution_tracking_record("sess-recover-active")
    assert restored is not None
    assert restored.recovery_status == "recovered_unrevalidated"
    assert restored.is_active() is False
    assert get_active_execution_tracking_for_session("sess-recover-active") is None

    revalidated = apply_acknowledgment_signal(restored, AcknowledgmentSignal.ack)
    assert revalidated.recovery_status == "revalidated_live"
    assert get_active_execution_tracking_for_session("sess-recover-active") is not None


def test_CR01_stale_recovered_nonterminal_record_is_marked_stale(tmp_path, monkeypatch):
    state_path = tmp_path / "tracker-state.json"
    monkeypatch.setenv(
        "GALAXY_DELEGATED_RUNTIME_EXECUTION_TRACKER_STATE_PATH",
        str(state_path),
    )
    reset_execution_tracking_runtime(clear_durable_state=True)
    create_execution_tracking_record(
        session_id="sess-stale-recovery",
        contract_id="contract-stale-recovery",
        device_id="android-stale-recovery",
    )

    with state_path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)
    payload["records"][0]["updated_at"] = time.time() - 901.0
    with state_path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp)

    reset_execution_tracking_runtime(clear_durable_state=False)
    restored = get_execution_tracking_record("sess-stale-recovery")
    assert restored is not None
    assert restored.recovery_status == "recovered_stale"
    snapshot = build_execution_tracking_snapshot()
    assert snapshot.recovered_stale_count >= 1


def test_CS01_custom_runtime_has_no_durable_state_path():
    runtime = DelegatedExecutionTrackingRuntime()
    create_execution_tracking_record(
        session_id="sess-custom-runtime",
        contract_id="contract-custom-runtime",
        runtime=runtime,
    )
    assert runtime.state_path == ""
