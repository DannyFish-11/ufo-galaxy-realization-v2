"""tests/test_android_delegated_runtime_structural_consolidation.py
===================================================================
PR-11-V2: Tests for Android delegated runtime structural consolidation modules.

Coverage groups
---------------
A.  core.takeover_tracking — imports and sentinels.
B.  TakeoverDecision — enum values and from_bool / from_string.
C.  TakeoverTrackingRecord — field defaults, to_dict, to_json.
D.  TakeoverTrackingRuntime — record(), get_by_takeover_id(), get_by_session_id(), snapshot().
E.  record_takeover_response() — accepted / rejected, never raises.
F.  Query helpers — get_takeover_record(), list_takeover_records_for_session(),
    takeover_tracking_snapshot().
G.  Singleton — get_takeover_tracking_runtime(), reset().

H.  core.android_participant_session_state — imports and sentinels.
I.  AndroidParticipantSessionPhase — enum values, is_terminal(), is_active().
J.  AndroidParticipantSessionSignal — enum values and from_string().
K.  AndroidParticipantSessionRecord — field defaults, to_dict, to_json.
L.  create_participant_session_record() — produces pre_dispatch record.
M.  advance_participant_session() — valid transitions.
N.  advance_participant_session() — terminal phase is absorbing.
O.  advance_participant_session() — unknown signal is noop.
P.  AndroidParticipantSessionRuntime — record(), get_by_session_id(), list_active(), snapshot().
Q.  Persistence helpers — record_participant_session(), get_participant_session().
R.  list_active_participant_sessions() — excludes terminal records.
S.  participant_session_snapshot() — counts are correct.
T.  Singleton — get_participant_session_runtime(), reset().

U.  core.android_runtime_transition_reducer — imports and sentinels.
V.  AndroidRuntimeSignalInput — dataclass fields.
W.  AndroidRuntimeTransitionResult — dataclass fields.
X.  reduce_handoff_result() — handoff_ack → execution_started.
Y.  reduce_handoff_result() — handoff_result → result_success.
Z.  reduce_handoff_result() — handoff_failure → result_failure.
AA. reduce_takeover_response() — accepted → takeover_accepted phase.
AB. reduce_takeover_response() — rejected → handoff_dispatched phase.
AC. reduce_reconciliation_signal() — terminal truth kinds.
AD. reduce_reconciliation_signal() — not reconciled is noop.
AE. reduce_execution_signal() — ack → execution.
AF. reduce_execution_signal() — not updated is noop.
AG. reduce_participant_truth() — result → terminal_success.
AH. reduce_android_runtime_signal() — dispatches to correct helper.
AI. reduce_android_runtime_signal() — unknown domain is noop.

AJ. core.android_delegated_runtime_lifecycle_coordinator — imports.
AK. AndroidLifecycleCoordinatorOutcome — dataclass fields.
AL. on_handoff_dispatched() — creates and advances session record.
AM. on_takeover_requested() — advances to takeover_pending.
AN. on_takeover_response() — accepted path writes to tracking.
AO. on_takeover_response() — rejected path updates session.
AP. on_reconciliation_signal() — delegates and returns outcome.
AQ. on_execution_signal() — delegates and returns outcome.
AR. on_participant_truth_update() — delegates and returns outcome.
AS. All on_* methods return was_handled=True on normal path.
AT. Singleton — get_lifecycle_coordinator(), reset_lifecycle_coordinator().

AU. Integration — full handoff → takeover → execution → terminal path.
AV. Integration — takeover rejected restores to handoff_dispatched.
AW. Takeover handler integrates with takeover_tracking (regression guard).
"""

from __future__ import annotations

import json
import os
import sys
import uuid

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Guard imports
# ---------------------------------------------------------------------------

try:
    from core.takeover_tracking import (
        TAKEOVER_TRACKING_AUTHORITY,
        TAKEOVER_TRACKING_CONTRACT_VERSION,
        TakeoverDecision,
        TakeoverTrackingRecord,
        TakeoverTrackingRuntime,
        TakeoverTrackingSnapshot,
        get_takeover_record,
        get_takeover_tracking_runtime,
        list_takeover_records_for_session,
        record_takeover_response,
        reset_takeover_tracking_runtime,
        takeover_tracking_snapshot,
    )

    _TT_AVAILABLE = True
except ImportError as _ie:
    _TT_AVAILABLE = False
    _TT_IE = str(_ie)

try:
    from core.android_participant_session_state import (
        ANDROID_PARTICIPANT_SESSION_STATE_AUTHORITY,
        ANDROID_PARTICIPANT_SESSION_STATE_CONTRACT_VERSION,
        AndroidParticipantSessionPhase,
        AndroidParticipantSessionRecord,
        AndroidParticipantSessionRuntime,
        AndroidParticipantSessionSignal,
        AndroidParticipantSessionSnapshot,
        advance_participant_session,
        create_participant_session_record,
        get_participant_session,
        get_participant_session_runtime,
        list_active_participant_sessions,
        participant_session_snapshot,
        record_participant_session,
        reset_participant_session_runtime,
    )

    _SS_AVAILABLE = True
except ImportError as _ie2:
    _SS_AVAILABLE = False
    _SS_IE = str(_ie2)

try:
    from core.android_runtime_transition_reducer import (
        ANDROID_RUNTIME_TRANSITION_REDUCER_AUTHORITY,
        ANDROID_RUNTIME_TRANSITION_REDUCER_CONTRACT_VERSION,
        AndroidRuntimeSignalInput,
        AndroidRuntimeTransitionResult,
        reduce_android_runtime_signal,
        reduce_execution_signal,
        reduce_handoff_result,
        reduce_participant_truth,
        reduce_reconciliation_signal,
        reduce_takeover_response,
    )

    _TR_AVAILABLE = True
except ImportError as _ie3:
    _TR_AVAILABLE = False
    _TR_IE = str(_ie3)

try:
    from core.android_delegated_runtime_lifecycle_coordinator import (
        ANDROID_DELEGATED_RUNTIME_LIFECYCLE_COORDINATOR_AUTHORITY,
        ANDROID_DELEGATED_RUNTIME_LIFECYCLE_COORDINATOR_CONTRACT_VERSION,
        AndroidDelegatedRuntimeLifecycleCoordinator,
        AndroidLifecycleCoordinatorOutcome,
        get_lifecycle_coordinator,
        reset_lifecycle_coordinator,
    )

    _LC_AVAILABLE = True
except ImportError as _ie4:
    _LC_AVAILABLE = False
    _LC_IE = str(_ie4)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return str(uuid.uuid4())


def _fresh_tt_runtime() -> "TakeoverTrackingRuntime":
    return TakeoverTrackingRuntime()


def _fresh_ss_runtime() -> "AndroidParticipantSessionRuntime":
    return AndroidParticipantSessionRuntime()


def _make_session_record(**kwargs) -> "AndroidParticipantSessionRecord":
    defaults = dict(session_id=_uid(), device_id="dev-1")
    defaults.update(kwargs)
    return create_participant_session_record(**defaults)


# ===========================================================================
# Group A–G: core.takeover_tracking
# ===========================================================================


@pytest.mark.skipif(not _TT_AVAILABLE, reason="takeover_tracking unavailable")
class TestTakeoverTrackingImports:
    def test_A01_authority_non_empty(self):
        assert TAKEOVER_TRACKING_AUTHORITY and isinstance(TAKEOVER_TRACKING_AUTHORITY, str)

    def test_A02_contract_version_non_empty(self):
        assert TAKEOVER_TRACKING_CONTRACT_VERSION


@pytest.mark.skipif(not _TT_AVAILABLE, reason="takeover_tracking unavailable")
class TestTakeoverDecision:
    def test_B01_enum_values_present(self):
        assert TakeoverDecision.accepted.value == "accepted"
        assert TakeoverDecision.rejected.value == "rejected"
        assert TakeoverDecision.unknown.value == "unknown"

    def test_B02_from_bool_true(self):
        assert TakeoverDecision.from_bool(True) == TakeoverDecision.accepted

    def test_B03_from_bool_false(self):
        assert TakeoverDecision.from_bool(False) == TakeoverDecision.rejected

    def test_B04_from_string_valid(self):
        assert TakeoverDecision.from_string("accepted") == TakeoverDecision.accepted
        assert TakeoverDecision.from_string("rejected") == TakeoverDecision.rejected

    def test_B05_from_string_unknown(self):
        assert TakeoverDecision.from_string("garbage") == TakeoverDecision.unknown

    def test_B06_from_string_non_string(self):
        assert TakeoverDecision.from_string(None) == TakeoverDecision.unknown  # type: ignore[arg-type]


@pytest.mark.skipif(not _TT_AVAILABLE, reason="takeover_tracking unavailable")
class TestTakeoverTrackingRecord:
    def test_C01_default_fields(self):
        rec = TakeoverTrackingRecord()
        assert rec.record_id
        assert rec.decision == TakeoverDecision.unknown

    def test_C02_was_accepted(self):
        rec = TakeoverTrackingRecord(decision=TakeoverDecision.accepted)
        assert rec.was_accepted is True
        assert rec.was_rejected is False

    def test_C03_was_rejected(self):
        rec = TakeoverTrackingRecord(decision=TakeoverDecision.rejected)
        assert rec.was_accepted is False
        assert rec.was_rejected is True

    def test_C04_to_dict_serialisable(self):
        rec = TakeoverTrackingRecord(takeover_id="t1", device_id="d1")
        d = rec.to_dict()
        assert d["takeover_id"] == "t1"
        assert d["device_id"] == "d1"
        json.dumps(d)  # must not raise

    def test_C05_to_json_roundtrip(self):
        rec = TakeoverTrackingRecord(takeover_id="t2")
        s = rec.to_json()
        loaded = json.loads(s)
        assert loaded["takeover_id"] == "t2"


@pytest.mark.skipif(not _TT_AVAILABLE, reason="takeover_tracking unavailable")
class TestTakeoverTrackingRuntime:
    def test_D01_record_increases_count(self):
        rt = _fresh_tt_runtime()
        rt.record(TakeoverTrackingRecord(takeover_id="x1"))
        snap = rt.snapshot()
        assert snap.total_count == 1

    def test_D02_get_by_takeover_id_found(self):
        rt = _fresh_tt_runtime()
        rec = TakeoverTrackingRecord(takeover_id="search_this")
        rt.record(rec)
        found = rt.get_by_takeover_id("search_this")
        assert found is not None
        assert found.takeover_id == "search_this"

    def test_D03_get_by_takeover_id_not_found(self):
        rt = _fresh_tt_runtime()
        assert rt.get_by_takeover_id("no_such") is None

    def test_D04_get_by_session_id(self):
        rt = _fresh_tt_runtime()
        sid = _uid()
        rt.record(TakeoverTrackingRecord(takeover_id="a", session_id=sid))
        rt.record(TakeoverTrackingRecord(takeover_id="b", session_id=sid))
        rt.record(TakeoverTrackingRecord(takeover_id="c", session_id="other"))
        results = rt.get_by_session_id(sid)
        assert len(results) == 2
        assert all(r.session_id == sid for r in results)

    def test_D05_snapshot_to_dict(self):
        rt = _fresh_tt_runtime()
        rt.record(TakeoverTrackingRecord(takeover_id="snap_test"))
        snap = rt.snapshot()
        d = snap.to_dict()
        json.dumps(d)


@pytest.mark.skipif(not _TT_AVAILABLE, reason="takeover_tracking unavailable")
class TestRecordTakeoverResponse:
    def setup_method(self):
        reset_takeover_tracking_runtime()

    def test_E01_accepted_record(self):
        rec = record_takeover_response(
            takeover_id="tko1", device_id="dev1", accepted=True
        )
        assert rec.decision == TakeoverDecision.accepted
        assert rec.was_accepted is True

    def test_E02_rejected_record(self):
        rec = record_takeover_response(
            takeover_id="tko2", device_id="dev2", accepted=False, reason="busy"
        )
        assert rec.decision == TakeoverDecision.rejected
        assert rec.reason == "busy"

    def test_E03_persisted_to_singleton(self):
        tid = _uid()
        record_takeover_response(takeover_id=tid, device_id="d", accepted=True)
        found = get_takeover_record(tid)
        assert found is not None
        assert found.takeover_id == tid

    def test_E04_never_raises(self):
        # Pass bad types — should not raise
        result = record_takeover_response(
            takeover_id=None,  # type: ignore[arg-type]
            device_id=None,  # type: ignore[arg-type]
            accepted="yes",  # type: ignore[arg-type]
        )
        assert result is not None

    def test_E05_all_fields_propagated(self):
        rec = record_takeover_response(
            takeover_id="tid",
            device_id="dv",
            accepted=True,
            reason="ok",
            session_id="sess",
            task_id="task",
            trace_id="trace",
        )
        assert rec.session_id == "sess"
        assert rec.task_id == "task"
        assert rec.trace_id == "trace"


@pytest.mark.skipif(not _TT_AVAILABLE, reason="takeover_tracking unavailable")
class TestTakeoverQueryHelpers:
    def setup_method(self):
        reset_takeover_tracking_runtime()

    def test_F01_get_takeover_record_found(self):
        tid = _uid()
        record_takeover_response(takeover_id=tid, device_id="d", accepted=True)
        rec = get_takeover_record(tid)
        assert rec is not None

    def test_F02_get_takeover_record_none(self):
        assert get_takeover_record("does_not_exist") is None

    def test_F03_list_for_session(self):
        sid = _uid()
        record_takeover_response(takeover_id="t1", device_id="d", accepted=True, session_id=sid)
        record_takeover_response(takeover_id="t2", device_id="d", accepted=False, session_id=sid)
        results = list_takeover_records_for_session(sid)
        assert len(results) == 2

    def test_F04_snapshot_count(self):
        record_takeover_response(takeover_id=_uid(), device_id="d", accepted=True)
        record_takeover_response(takeover_id=_uid(), device_id="d", accepted=False)
        snap = takeover_tracking_snapshot()
        assert snap.total_count >= 2


@pytest.mark.skipif(not _TT_AVAILABLE, reason="takeover_tracking unavailable")
class TestTakeoverTrackingSingleton:
    def test_G01_get_returns_singleton(self):
        rt1 = get_takeover_tracking_runtime()
        rt2 = get_takeover_tracking_runtime()
        assert rt1 is rt2

    def test_G02_reset_creates_new_singleton(self):
        rt1 = get_takeover_tracking_runtime()
        reset_takeover_tracking_runtime()
        rt2 = get_takeover_tracking_runtime()
        assert rt1 is not rt2


# ===========================================================================
# Group H–T: core.android_participant_session_state
# ===========================================================================


@pytest.mark.skipif(not _SS_AVAILABLE, reason="android_participant_session_state unavailable")
class TestSessionStateImports:
    def test_H01_authority_non_empty(self):
        assert ANDROID_PARTICIPANT_SESSION_STATE_AUTHORITY

    def test_H02_contract_version_non_empty(self):
        assert ANDROID_PARTICIPANT_SESSION_STATE_CONTRACT_VERSION


@pytest.mark.skipif(not _SS_AVAILABLE, reason="android_participant_session_state unavailable")
class TestAndroidParticipantSessionPhase:
    def test_I01_all_phases_present(self):
        phases = [p.value for p in AndroidParticipantSessionPhase]
        assert "pre_dispatch" in phases
        assert "handoff_dispatched" in phases
        assert "takeover_pending" in phases
        assert "takeover_accepted" in phases
        assert "execution" in phases
        assert "reconciling" in phases
        assert "terminal_success" in phases
        assert "terminal_failure" in phases
        assert "terminal_cancelled" in phases

    def test_I02_terminal_phases(self):
        assert AndroidParticipantSessionPhase.terminal_success.is_terminal()
        assert AndroidParticipantSessionPhase.terminal_failure.is_terminal()
        assert AndroidParticipantSessionPhase.terminal_cancelled.is_terminal()

    def test_I03_non_terminal_phases(self):
        assert not AndroidParticipantSessionPhase.pre_dispatch.is_terminal()
        assert not AndroidParticipantSessionPhase.execution.is_terminal()

    def test_I04_is_active_inverse_of_terminal(self):
        for phase in AndroidParticipantSessionPhase:
            assert phase.is_active() != phase.is_terminal()

    def test_I05_from_string_valid(self):
        p = AndroidParticipantSessionPhase.from_string("execution")
        assert p == AndroidParticipantSessionPhase.execution

    def test_I06_from_string_invalid_defaults(self):
        p = AndroidParticipantSessionPhase.from_string("garbage")
        assert p == AndroidParticipantSessionPhase.pre_dispatch


@pytest.mark.skipif(not _SS_AVAILABLE, reason="android_participant_session_state unavailable")
class TestAndroidParticipantSessionSignal:
    def test_J01_all_signals_present(self):
        signals = [s.value for s in AndroidParticipantSessionSignal]
        for expected in [
            "handoff_dispatched", "takeover_requested", "takeover_accepted",
            "takeover_rejected", "execution_started", "execution_progressed",
            "reconciliation_started", "result_success", "result_failure",
            "result_cancelled",
        ]:
            assert expected in signals

    def test_J02_from_string(self):
        s = AndroidParticipantSessionSignal.from_string("result_success")
        assert s == AndroidParticipantSessionSignal.result_success

    def test_J03_from_string_invalid_defaults(self):
        s = AndroidParticipantSessionSignal.from_string("nope")
        assert s == AndroidParticipantSessionSignal.execution_progressed


@pytest.mark.skipif(not _SS_AVAILABLE, reason="android_participant_session_state unavailable")
class TestAndroidParticipantSessionRecord:
    def test_K01_default_phase(self):
        rec = _make_session_record()
        assert rec.phase == AndroidParticipantSessionPhase.pre_dispatch

    def test_K02_to_dict_serialisable(self):
        rec = _make_session_record(task_id="t1")
        d = rec.to_dict()
        assert d["task_id"] == "t1"
        json.dumps(d)

    def test_K03_to_json_roundtrip(self):
        rec = _make_session_record(session_id="s1")
        loaded = json.loads(rec.to_json())
        assert loaded["session_id"] == "s1"


@pytest.mark.skipif(not _SS_AVAILABLE, reason="android_participant_session_state unavailable")
class TestCreateParticipantSessionRecord:
    def test_L01_creates_pre_dispatch(self):
        rec = create_participant_session_record(session_id="s", device_id="d")
        assert rec.phase == AndroidParticipantSessionPhase.pre_dispatch

    def test_L02_fields_propagated(self):
        rec = create_participant_session_record(
            session_id="s", device_id="d", task_id="t", contract_id="c"
        )
        assert rec.session_id == "s"
        assert rec.device_id == "d"
        assert rec.task_id == "t"
        assert rec.contract_id == "c"

    def test_L03_previous_phase_none(self):
        rec = create_participant_session_record(session_id="s")
        assert rec.previous_phase is None
        assert rec.last_signal is None


@pytest.mark.skipif(not _SS_AVAILABLE, reason="android_participant_session_state unavailable")
class TestAdvanceParticipantSession:
    def test_M01_pre_dispatch_to_handoff_dispatched(self):
        rec = _make_session_record()
        updated = advance_participant_session(rec, AndroidParticipantSessionSignal.handoff_dispatched)
        assert updated.phase == AndroidParticipantSessionPhase.handoff_dispatched
        assert updated.previous_phase == AndroidParticipantSessionPhase.pre_dispatch
        assert updated.last_signal == AndroidParticipantSessionSignal.handoff_dispatched

    def test_M02_handoff_dispatched_to_takeover_pending(self):
        rec = _make_session_record()
        rec = advance_participant_session(rec, AndroidParticipantSessionSignal.handoff_dispatched)
        rec = advance_participant_session(rec, AndroidParticipantSessionSignal.takeover_requested)
        assert rec.phase == AndroidParticipantSessionPhase.takeover_pending

    def test_M03_takeover_pending_to_accepted(self):
        rec = _make_session_record()
        for sig in [
            AndroidParticipantSessionSignal.handoff_dispatched,
            AndroidParticipantSessionSignal.takeover_requested,
            AndroidParticipantSessionSignal.takeover_accepted,
        ]:
            rec = advance_participant_session(rec, sig)
        assert rec.phase == AndroidParticipantSessionPhase.takeover_accepted

    def test_M04_takeover_accepted_to_execution(self):
        rec = _make_session_record()
        for sig in [
            AndroidParticipantSessionSignal.handoff_dispatched,
            AndroidParticipantSessionSignal.takeover_requested,
            AndroidParticipantSessionSignal.takeover_accepted,
            AndroidParticipantSessionSignal.execution_started,
        ]:
            rec = advance_participant_session(rec, sig)
        assert rec.phase == AndroidParticipantSessionPhase.execution

    def test_M05_execution_to_terminal_success(self):
        rec = _make_session_record()
        for sig in [
            AndroidParticipantSessionSignal.handoff_dispatched,
            AndroidParticipantSessionSignal.execution_started,
            AndroidParticipantSessionSignal.result_success,
        ]:
            rec = advance_participant_session(rec, sig)
        assert rec.phase == AndroidParticipantSessionPhase.terminal_success

    def test_M06_execution_to_terminal_failure(self):
        rec = _make_session_record()
        for sig in [
            AndroidParticipantSessionSignal.handoff_dispatched,
            AndroidParticipantSessionSignal.execution_started,
            AndroidParticipantSessionSignal.result_failure,
        ]:
            rec = advance_participant_session(rec, sig)
        assert rec.phase == AndroidParticipantSessionPhase.terminal_failure

    def test_M07_execution_to_terminal_cancelled(self):
        rec = _make_session_record()
        for sig in [
            AndroidParticipantSessionSignal.handoff_dispatched,
            AndroidParticipantSessionSignal.execution_started,
            AndroidParticipantSessionSignal.result_cancelled,
        ]:
            rec = advance_participant_session(rec, sig)
        assert rec.phase == AndroidParticipantSessionPhase.terminal_cancelled

    def test_M08_new_record_id_on_transition(self):
        rec = _make_session_record()
        updated = advance_participant_session(rec, AndroidParticipantSessionSignal.handoff_dispatched)
        assert updated.record_id != rec.record_id

    def test_M09_identity_fields_preserved(self):
        rec = _make_session_record(session_id="sid", contract_id="cid")
        updated = advance_participant_session(rec, AndroidParticipantSessionSignal.handoff_dispatched)
        assert updated.session_id == "sid"
        assert updated.contract_id == "cid"


@pytest.mark.skipif(not _SS_AVAILABLE, reason="android_participant_session_state unavailable")
class TestTerminalPhaseAbsorbing:
    def test_N01_terminal_phase_blocks_all_signals(self):
        rec = _make_session_record()
        for sig in [
            AndroidParticipantSessionSignal.handoff_dispatched,
            AndroidParticipantSessionSignal.execution_started,
            AndroidParticipantSessionSignal.result_success,
        ]:
            rec = advance_participant_session(rec, sig)
        # Now terminal — any signal should be a noop
        for further_sig in AndroidParticipantSessionSignal:
            same = advance_participant_session(rec, further_sig)
            assert same is rec


@pytest.mark.skipif(not _SS_AVAILABLE, reason="android_participant_session_state unavailable")
class TestUnknownSignalNoop:
    def test_O01_no_matching_transition_returns_original(self):
        rec = _make_session_record()
        # takeover_accepted in pre_dispatch has no transition
        result = advance_participant_session(rec, AndroidParticipantSessionSignal.takeover_accepted)
        assert result is rec


@pytest.mark.skipif(not _SS_AVAILABLE, reason="android_participant_session_state unavailable")
class TestAndroidParticipantSessionRuntime:
    def test_P01_record_and_get(self):
        rt = _fresh_ss_runtime()
        sid = _uid()
        rec = create_participant_session_record(session_id=sid)
        rt.record(rec)
        found = rt.get_by_session_id(sid)
        assert found is not None
        assert found.session_id == sid

    def test_P02_get_returns_newest(self):
        rt = _fresh_ss_runtime()
        sid = _uid()
        rec1 = create_participant_session_record(session_id=sid)
        rec2 = advance_participant_session(rec1, AndroidParticipantSessionSignal.handoff_dispatched)
        rt.record(rec1)
        rt.record(rec2)
        found = rt.get_by_session_id(sid)
        # Newest (rec2) should be returned
        assert found.phase == AndroidParticipantSessionPhase.handoff_dispatched

    def test_P03_list_active_excludes_terminal(self):
        rt = _fresh_ss_runtime()
        sid = _uid()
        rec = create_participant_session_record(session_id=sid)
        for sig in [
            AndroidParticipantSessionSignal.handoff_dispatched,
            AndroidParticipantSessionSignal.execution_started,
            AndroidParticipantSessionSignal.result_success,
        ]:
            rec = advance_participant_session(rec, sig)
        rt.record(rec)
        active = rt.list_active()
        assert not any(r.session_id == sid for r in active)

    def test_P04_snapshot_counts(self):
        rt = _fresh_ss_runtime()
        # Add one active and one terminal
        s_active = _uid()
        s_terminal = _uid()
        active_rec = create_participant_session_record(session_id=s_active)
        active_rec = advance_participant_session(active_rec, AndroidParticipantSessionSignal.handoff_dispatched)
        terminal_rec = create_participant_session_record(session_id=s_terminal)
        for sig in [
            AndroidParticipantSessionSignal.handoff_dispatched,
            AndroidParticipantSessionSignal.execution_started,
            AndroidParticipantSessionSignal.result_success,
        ]:
            terminal_rec = advance_participant_session(terminal_rec, sig)
        rt.record(active_rec)
        rt.record(terminal_rec)
        snap = rt.snapshot()
        assert snap.active_count >= 1
        assert snap.terminal_count >= 1
        assert snap.total_count >= 2


@pytest.mark.skipif(not _SS_AVAILABLE, reason="android_participant_session_state unavailable")
class TestSessionPersistenceHelpers:
    def setup_method(self):
        reset_participant_session_runtime()

    def test_Q01_record_and_get_participant_session(self):
        sid = _uid()
        rec = create_participant_session_record(session_id=sid)
        record_participant_session(rec)
        found = get_participant_session(sid)
        assert found is not None
        assert found.session_id == sid

    def test_Q02_get_participant_session_none(self):
        assert get_participant_session("no_such_session") is None


@pytest.mark.skipif(not _SS_AVAILABLE, reason="android_participant_session_state unavailable")
class TestListActiveParticipantSessions:
    def setup_method(self):
        reset_participant_session_runtime()

    def test_R01_active_sessions_excludes_terminal(self):
        sid = _uid()
        rec = create_participant_session_record(session_id=sid)
        # Advance to terminal
        for sig in [
            AndroidParticipantSessionSignal.handoff_dispatched,
            AndroidParticipantSessionSignal.execution_started,
            AndroidParticipantSessionSignal.result_failure,
        ]:
            rec = advance_participant_session(rec, sig)
        record_participant_session(rec)

        active = list_active_participant_sessions()
        assert not any(r.session_id == sid for r in active)

    def test_R02_active_sessions_includes_non_terminal(self):
        sid = _uid()
        rec = create_participant_session_record(session_id=sid)
        rec = advance_participant_session(rec, AndroidParticipantSessionSignal.handoff_dispatched)
        record_participant_session(rec)

        active = list_active_participant_sessions()
        assert any(r.session_id == sid for r in active)


@pytest.mark.skipif(not _SS_AVAILABLE, reason="android_participant_session_state unavailable")
class TestParticipantSessionSnapshot:
    def setup_method(self):
        reset_participant_session_runtime()

    def test_S01_snapshot_dict_serialisable(self):
        sid = _uid()
        rec = create_participant_session_record(session_id=sid)
        record_participant_session(rec)
        snap = participant_session_snapshot()
        d = snap.to_dict()
        json.dumps(d)

    def test_S02_snapshot_total_count(self):
        for _ in range(3):
            rec = create_participant_session_record(session_id=_uid())
            record_participant_session(rec)
        snap = participant_session_snapshot()
        assert snap.total_count >= 3


@pytest.mark.skipif(not _SS_AVAILABLE, reason="android_participant_session_state unavailable")
class TestSessionStateSingleton:
    def test_T01_singleton_identity(self):
        rt1 = get_participant_session_runtime()
        rt2 = get_participant_session_runtime()
        assert rt1 is rt2

    def test_T02_reset_new_singleton(self):
        rt1 = get_participant_session_runtime()
        reset_participant_session_runtime()
        rt2 = get_participant_session_runtime()
        assert rt1 is not rt2


# ===========================================================================
# Group U–AI: core.android_runtime_transition_reducer
# ===========================================================================


@pytest.mark.skipif(not _TR_AVAILABLE or not _SS_AVAILABLE, reason="reducer or session state unavailable")
class TestReducerImports:
    def test_U01_authority_non_empty(self):
        assert ANDROID_RUNTIME_TRANSITION_REDUCER_AUTHORITY

    def test_U02_contract_version_non_empty(self):
        assert ANDROID_RUNTIME_TRANSITION_REDUCER_CONTRACT_VERSION


@pytest.mark.skipif(not _TR_AVAILABLE, reason="reducer unavailable")
class TestAndroidRuntimeSignalInput:
    def test_V01_default_fields(self):
        s = AndroidRuntimeSignalInput()
        assert s.signal_domain == ""
        assert s.signal_type == ""
        assert s.was_successful is False


@pytest.mark.skipif(not _TR_AVAILABLE, reason="reducer unavailable")
class TestAndroidRuntimeTransitionResult:
    def test_W01_default_fields(self):
        rec = _make_session_record() if _SS_AVAILABLE else None
        r = AndroidRuntimeTransitionResult(record=rec)
        assert r.was_transitioned is False
        assert r.next_signal is None


@pytest.mark.skipif(not _TR_AVAILABLE or not _SS_AVAILABLE, reason="reducer or session state unavailable")
class TestReduceHandoffResult:
    def _active_execution_record(self):
        rec = _make_session_record()
        return advance_participant_session(rec, AndroidParticipantSessionSignal.handoff_dispatched)

    def test_X01_handoff_ack_transitions_to_execution(self):
        rec = self._active_execution_record()
        result = reduce_handoff_result(rec, response_type="handoff_ack", was_successful=True)
        assert result.was_transitioned
        assert result.record.phase == AndroidParticipantSessionPhase.execution

    def test_Y01_handoff_result_transitions_to_terminal_success(self):
        rec = self._active_execution_record()
        # Need to be in execution phase first
        rec = advance_participant_session(rec, AndroidParticipantSessionSignal.execution_started)
        result = reduce_handoff_result(rec, response_type="handoff_result", was_successful=True)
        assert result.was_transitioned
        assert result.record.phase == AndroidParticipantSessionPhase.terminal_success

    def test_Z01_handoff_failure_transitions_to_terminal_failure(self):
        rec = self._active_execution_record()
        rec = advance_participant_session(rec, AndroidParticipantSessionSignal.execution_started)
        result = reduce_handoff_result(rec, response_type="handoff_failure", was_successful=False)
        assert result.was_transitioned
        assert result.record.phase == AndroidParticipantSessionPhase.terminal_failure


@pytest.mark.skipif(not _TR_AVAILABLE or not _SS_AVAILABLE, reason="reducer or session state unavailable")
class TestReduceTakeoverResponse:
    def _takeover_pending_record(self):
        rec = _make_session_record()
        for sig in [
            AndroidParticipantSessionSignal.handoff_dispatched,
            AndroidParticipantSessionSignal.takeover_requested,
        ]:
            rec = advance_participant_session(rec, sig)
        return rec

    def test_AA01_accepted_advances_to_takeover_accepted(self):
        rec = self._takeover_pending_record()
        result = reduce_takeover_response(rec, accepted=True)
        assert result.was_transitioned
        assert result.record.phase == AndroidParticipantSessionPhase.takeover_accepted

    def test_AB01_rejected_restores_to_handoff_dispatched(self):
        rec = self._takeover_pending_record()
        result = reduce_takeover_response(rec, accepted=False)
        assert result.was_transitioned
        assert result.record.phase == AndroidParticipantSessionPhase.handoff_dispatched


@pytest.mark.skipif(not _TR_AVAILABLE or not _SS_AVAILABLE, reason="reducer or session state unavailable")
class TestReduceReconciliationSignal:
    def _execution_record(self):
        rec = _make_session_record()
        for sig in [
            AndroidParticipantSessionSignal.handoff_dispatched,
            AndroidParticipantSessionSignal.execution_started,
        ]:
            rec = advance_participant_session(rec, sig)
        return rec

    def test_AC01_cancel_truth_transitions_to_terminal_cancelled(self):
        rec = self._execution_record()
        result = reduce_reconciliation_signal(rec, truth_kind="cancel", was_reconciled=True)
        assert result.was_transitioned
        assert result.record.phase == AndroidParticipantSessionPhase.terminal_cancelled

    def test_AC02_failure_truth_transitions_to_terminal_failure(self):
        rec = self._execution_record()
        result = reduce_reconciliation_signal(rec, truth_kind="failure", was_reconciled=True)
        assert result.was_transitioned
        assert result.record.phase == AndroidParticipantSessionPhase.terminal_failure

    def test_AD01_not_reconciled_is_noop(self):
        rec = self._execution_record()
        result = reduce_reconciliation_signal(rec, truth_kind="cancel", was_reconciled=False)
        assert not result.was_transitioned
        assert result.record is rec


@pytest.mark.skipif(not _TR_AVAILABLE or not _SS_AVAILABLE, reason="reducer or session state unavailable")
class TestReduceExecutionSignal:
    def _handoff_dispatched_record(self):
        rec = _make_session_record()
        return advance_participant_session(rec, AndroidParticipantSessionSignal.handoff_dispatched)

    def test_AE01_ack_transitions_to_execution(self):
        rec = self._handoff_dispatched_record()
        result = reduce_execution_signal(rec, signal_kind="ack", was_updated=True)
        assert result.was_transitioned
        assert result.record.phase == AndroidParticipantSessionPhase.execution

    def test_AF01_not_updated_is_noop(self):
        rec = self._handoff_dispatched_record()
        result = reduce_execution_signal(rec, signal_kind="ack", was_updated=False)
        assert not result.was_transitioned


@pytest.mark.skipif(not _TR_AVAILABLE or not _SS_AVAILABLE, reason="reducer or session state unavailable")
class TestReduceParticipantTruth:
    def _execution_record(self):
        rec = _make_session_record()
        for sig in [
            AndroidParticipantSessionSignal.handoff_dispatched,
            AndroidParticipantSessionSignal.execution_started,
        ]:
            rec = advance_participant_session(rec, sig)
        return rec

    def test_AG01_result_truth_transitions_to_success(self):
        rec = self._execution_record()
        result = reduce_participant_truth(rec, truth_kind="result", was_reconciled=True)
        assert result.was_transitioned
        assert result.record.phase == AndroidParticipantSessionPhase.terminal_success


@pytest.mark.skipif(not _TR_AVAILABLE or not _SS_AVAILABLE, reason="reducer or session state unavailable")
class TestReduceAndroidRuntimeSignal:
    def test_AH01_dispatches_to_handoff_helper(self):
        rec = _make_session_record()
        rec = advance_participant_session(rec, AndroidParticipantSessionSignal.handoff_dispatched)
        sig_input = AndroidRuntimeSignalInput(
            signal_domain="handoff",
            signal_type="handoff_ack",
            was_successful=True,
        )
        result = reduce_android_runtime_signal(rec, sig_input)
        assert result.record.phase == AndroidParticipantSessionPhase.execution

    def test_AI01_unknown_domain_is_noop(self):
        rec = _make_session_record()
        sig_input = AndroidRuntimeSignalInput(signal_domain="foobar")
        result = reduce_android_runtime_signal(rec, sig_input)
        assert not result.was_transitioned
        assert "unknown_signal_domain" in result.transition_description


# ===========================================================================
# Group AJ–AT: core.android_delegated_runtime_lifecycle_coordinator
# ===========================================================================


@pytest.mark.skipif(not _LC_AVAILABLE, reason="lifecycle_coordinator unavailable")
class TestLifecycleCoordinatorImports:
    def test_AJ01_authority_non_empty(self):
        assert ANDROID_DELEGATED_RUNTIME_LIFECYCLE_COORDINATOR_AUTHORITY

    def test_AJ02_contract_version_non_empty(self):
        assert ANDROID_DELEGATED_RUNTIME_LIFECYCLE_COORDINATOR_CONTRACT_VERSION


@pytest.mark.skipif(not _LC_AVAILABLE, reason="lifecycle_coordinator unavailable")
class TestAndroidLifecycleCoordinatorOutcome:
    def test_AK01_default_fields(self):
        o = AndroidLifecycleCoordinatorOutcome()
        assert o.was_handled is False
        assert o.event_type == ""
        assert o.was_transitioned is False


@pytest.mark.skipif(not _LC_AVAILABLE or not _SS_AVAILABLE, reason="coordinator or session state unavailable")
class TestOnHandoffDispatched:
    def setup_method(self):
        if _SS_AVAILABLE:
            reset_participant_session_runtime()
        reset_lifecycle_coordinator()

    def test_AL01_returns_was_handled_true(self):
        lc = get_lifecycle_coordinator()
        out = lc.on_handoff_dispatched(session_id=_uid(), device_id="d", contract_id="c")
        assert out.was_handled is True

    def test_AL02_event_type_is_handoff_dispatched(self):
        lc = get_lifecycle_coordinator()
        out = lc.on_handoff_dispatched(session_id=_uid())
        assert out.event_type == "handoff_dispatched"

    def test_AL03_session_persisted(self):
        sid = _uid()
        lc = get_lifecycle_coordinator()
        lc.on_handoff_dispatched(session_id=sid, device_id="d")
        rec = get_participant_session(sid)
        assert rec is not None
        assert rec.phase == AndroidParticipantSessionPhase.handoff_dispatched


@pytest.mark.skipif(not _LC_AVAILABLE or not _SS_AVAILABLE, reason="coordinator or session state unavailable")
class TestOnTakeoverRequested:
    def setup_method(self):
        if _SS_AVAILABLE:
            reset_participant_session_runtime()
        reset_lifecycle_coordinator()

    def test_AM01_returns_was_handled_true(self):
        lc = get_lifecycle_coordinator()
        sid = _uid()
        lc.on_handoff_dispatched(session_id=sid)
        out = lc.on_takeover_requested(session_id=sid, takeover_id=_uid())
        assert out.was_handled is True

    def test_AM02_session_advances_to_takeover_pending(self):
        lc = get_lifecycle_coordinator()
        sid = _uid()
        lc.on_handoff_dispatched(session_id=sid)
        lc.on_takeover_requested(session_id=sid, takeover_id=_uid())
        rec = get_participant_session(sid)
        assert rec is not None
        assert rec.phase == AndroidParticipantSessionPhase.takeover_pending


@pytest.mark.skipif(not _LC_AVAILABLE or not _SS_AVAILABLE or not _TT_AVAILABLE, reason="coordinator, session state, or takeover tracking unavailable")
class TestOnTakeoverResponse:
    def setup_method(self):
        if _SS_AVAILABLE:
            reset_participant_session_runtime()
        if _TT_AVAILABLE:
            reset_takeover_tracking_runtime()
        reset_lifecycle_coordinator()

    def test_AN01_accepted_writes_to_tracking(self):
        lc = get_lifecycle_coordinator()
        sid = _uid()
        tid = _uid()
        lc.on_handoff_dispatched(session_id=sid)
        lc.on_takeover_requested(session_id=sid, takeover_id=tid)
        lc.on_takeover_response(session_id=sid, takeover_id=tid, accepted=True)
        rec = get_takeover_record(tid)
        assert rec is not None
        assert rec.was_accepted is True

    def test_AO01_rejected_writes_to_tracking(self):
        lc = get_lifecycle_coordinator()
        sid = _uid()
        tid = _uid()
        lc.on_handoff_dispatched(session_id=sid)
        lc.on_takeover_requested(session_id=sid, takeover_id=tid)
        out = lc.on_takeover_response(
            session_id=sid, takeover_id=tid, accepted=False, reason="busy"
        )
        assert out.was_handled is True
        rec = get_takeover_record(tid)
        assert rec is not None
        assert rec.was_rejected is True


@pytest.mark.skipif(not _LC_AVAILABLE, reason="lifecycle_coordinator unavailable")
class TestOnReconciliationSignal:
    def test_AP01_returns_outcome(self):
        lc = get_lifecycle_coordinator()
        out = lc.on_reconciliation_signal(
            message={"type": "reconciliation_signal", "device_id": "d"}
        )
        assert out.event_type == "reconciliation_signal"
        assert out.was_handled is True


@pytest.mark.skipif(not _LC_AVAILABLE, reason="lifecycle_coordinator unavailable")
class TestOnExecutionSignal:
    def test_AQ01_returns_outcome(self):
        lc = get_lifecycle_coordinator()
        out = lc.on_execution_signal(
            message={"type": "delegated_execution_signal", "device_id": "d"}
        )
        assert out.event_type == "execution_signal"
        assert out.was_handled is True


@pytest.mark.skipif(not _LC_AVAILABLE, reason="lifecycle_coordinator unavailable")
class TestOnParticipantTruthUpdate:
    def test_AR01_returns_outcome(self):
        lc = get_lifecycle_coordinator()
        out = lc.on_participant_truth_update(
            message={"type": "participant_truth", "device_id": "d"}
        )
        assert out.event_type == "participant_truth_update"
        assert out.was_handled is True


@pytest.mark.skipif(not _LC_AVAILABLE, reason="lifecycle_coordinator unavailable")
class TestAllOnMethodsNonRaising:
    def test_AS01_all_methods_non_raising(self):
        lc = get_lifecycle_coordinator()
        # Pass bad/empty data — must not raise
        assert lc.on_handoff_dispatched(session_id="").was_handled is not None
        assert lc.on_takeover_requested(session_id="").was_handled is not None
        assert lc.on_takeover_response(session_id="", takeover_id="", accepted=True).was_handled is not None
        assert lc.on_reconciliation_signal(message={}).was_handled is not None
        assert lc.on_execution_signal(message={}).was_handled is not None
        assert lc.on_participant_truth_update(message={}).was_handled is not None


@pytest.mark.skipif(not _LC_AVAILABLE, reason="lifecycle_coordinator unavailable")
class TestLifecycleCoordinatorSingleton:
    def test_AT01_singleton_identity(self):
        lc1 = get_lifecycle_coordinator()
        lc2 = get_lifecycle_coordinator()
        assert lc1 is lc2

    def test_AT02_reset_new_instance(self):
        lc1 = get_lifecycle_coordinator()
        reset_lifecycle_coordinator()
        lc2 = get_lifecycle_coordinator()
        assert lc1 is not lc2


# ===========================================================================
# Group AU–AW: Integration tests
# ===========================================================================


@pytest.mark.skipif(
    not _LC_AVAILABLE or not _SS_AVAILABLE or not _TT_AVAILABLE,
    reason="one or more modules unavailable",
)
class TestIntegrationFullLifecycle:
    def setup_method(self):
        reset_participant_session_runtime()
        reset_takeover_tracking_runtime()
        reset_lifecycle_coordinator()

    def test_AU01_full_handoff_takeover_execution_success_path(self):
        """Simulate: handoff → takeover → execution → success."""
        lc = get_lifecycle_coordinator()
        sid = _uid()
        tid = _uid()

        lc.on_handoff_dispatched(session_id=sid, device_id="dev", contract_id="cid")
        lc.on_takeover_requested(session_id=sid, takeover_id=tid)
        lc.on_takeover_response(session_id=sid, takeover_id=tid, accepted=True)

        # After takeover accepted, session should be in takeover_accepted
        rec = get_participant_session(sid)
        assert rec is not None
        assert rec.phase == AndroidParticipantSessionPhase.takeover_accepted

        # Takeover tracking should record the accept
        tr = get_takeover_record(tid)
        assert tr is not None
        assert tr.was_accepted is True

    def test_AV01_takeover_rejected_restores_to_handoff_dispatched(self):
        """Simulate: handoff → takeover → rejection → handoff_dispatched."""
        lc = get_lifecycle_coordinator()
        sid = _uid()
        tid = _uid()

        lc.on_handoff_dispatched(session_id=sid, device_id="dev")
        lc.on_takeover_requested(session_id=sid, takeover_id=tid)
        lc.on_takeover_response(session_id=sid, takeover_id=tid, accepted=False, reason="device_busy")

        # After rejection, session should be back in handoff_dispatched
        rec = get_participant_session(sid)
        assert rec is not None
        assert rec.phase == AndroidParticipantSessionPhase.handoff_dispatched

        # Takeover tracking should record the rejection
        tr = get_takeover_record(tid)
        assert tr is not None
        assert tr.was_rejected is True
        assert tr.reason == "device_busy"


@pytest.mark.skipif(not _TT_AVAILABLE, reason="takeover_tracking unavailable")
class TestTakeoverHandlerIntegration:
    """Regression guard: takeover_response handler integrates with takeover_tracking."""

    def test_AW01_handler_can_import_record_takeover_response(self):
        """The takeover_response handler must be able to import record_takeover_response."""
        import importlib

        # Verify the specific import the handler uses
        try:
            m = importlib.import_module("core.takeover_tracking")
            assert hasattr(m, "record_takeover_response"), (
                "core.takeover_tracking must expose record_takeover_response"
            )
        except ImportError:
            pytest.fail("core.takeover_tracking must be importable")

    def test_AW02_record_takeover_response_signature_compatible(self):
        """Handler calls with keyword args; signature must accept them."""
        rec = record_takeover_response(
            takeover_id="regression_tid",
            device_id="regression_dev",
            accepted=True,
            reason="",
            session_id="regression_sess",
        )
        assert rec is not None
        assert rec.takeover_id == "regression_tid"
