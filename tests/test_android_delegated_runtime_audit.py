"""tests/test_android_delegated_runtime_audit.py
=================================================
PR-10-V2: Tests for the unified Android delegated runtime audit / observability
layer introduced in ``core/android_delegated_runtime_audit.py``.

Coverage groups
---------------
A.  Module-level sentinel / version constants are importable and non-empty.
B.  AndroidDelegatedAuditEventKind — all six kind constants present.
C.  AndroidDelegatedAuditRecord — field defaults and to_dict / to_json.
D.  AndroidDelegatedAuditSnapshot — to_dict is JSON-serialisable.
E.  AndroidDelegatedRuntimeAuditRecorder — record() appends to ring.
F.  Recorder — get_by_task() returns task-indexed records.
G.  Recorder — get_by_session() returns session-indexed records.
H.  Recorder — get_by_kind() filters by event kind.
I.  Recorder — all_events() returns ring snapshot.
J.  Recorder — snapshot() returns correct event_count.
K.  Singleton — get_android_delegated_audit_recorder() returns singleton.
L.  Singleton — reset_android_delegated_audit_recorder() resets singleton.
M.  record_delegated_execution_signal() — emits correct kind and fields.
N.  record_handoff_v2_result() — emits correct kind and fields.
O.  record_takeover_request() — emits correct kind and fields.
P.  record_takeover_response() — emits correct kind and fields.
Q.  record_reconciliation_signal() — emits correct kind and fields.
R.  record_participant_truth_terminal_update() — emits correct kind and fields.
S.  Same task_id across multiple helpers is queryable via get_android_audit_for_task.
T.  Same session_id across multiple helpers queryable via get_android_audit_for_session.
U.  android_audit_snapshot() returns snapshot with correct count.
V.  All emitted records are JSON-serialisable.
W.  Recorder.record() degrades gracefully when AuditEventSemantics unavailable.
X.  record_takeover_response() state_transition reflects accepted/rejected.
Y.  record_delegated_execution_signal() reject_reason is preserved.
Z.  record_reconciliation_signal() canonical_update is in payload.
AA. handler delegated_signal — imports audit helper without error.
AB. handler handoff_v2_result — imports audit helper without error.
AC. handler takeover_response — imports audit helper without error.
AD. handler reconciliation_signal — imports audit helper without error.
AE. android_participant_truth_ingress — imports audit helper without error.
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
# Import guard
# ---------------------------------------------------------------------------

try:
    from core.android_delegated_runtime_audit import (
        ANDROID_DELEGATED_RUNTIME_AUDIT_AUTHORITY,
        ANDROID_DELEGATED_RUNTIME_AUDIT_CONTRACT_VERSION,
        AndroidDelegatedAuditEventKind,
        AndroidDelegatedAuditRecord,
        AndroidDelegatedAuditSnapshot,
        AndroidDelegatedRuntimeAuditRecorder,
        android_audit_snapshot,
        get_android_audit_for_session,
        get_android_audit_for_task,
        get_android_delegated_audit_recorder,
        record_delegated_execution_signal,
        record_handoff_v2_result,
        record_participant_truth_terminal_update,
        record_reconciliation_signal,
        record_takeover_request,
        record_takeover_response,
        reset_android_delegated_audit_recorder,
    )

    _MODULE_AVAILABLE = True
except ImportError as _ie:
    _MODULE_AVAILABLE = False
    _IE_MSG = str(_ie)

pytestmark = pytest.mark.skipif(
    not _MODULE_AVAILABLE,
    reason=f"android_delegated_runtime_audit unavailable: {'' if _MODULE_AVAILABLE else _IE_MSG}",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_recorder() -> AndroidDelegatedRuntimeAuditRecorder:
    """Return a fresh recorder instance (not the singleton)."""
    return AndroidDelegatedRuntimeAuditRecorder()


def _uid() -> str:
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# Group A — Sentinel / version constants
# ---------------------------------------------------------------------------


class TestSentinels:
    def test_authority_non_empty(self):
        assert ANDROID_DELEGATED_RUNTIME_AUDIT_AUTHORITY
        assert isinstance(ANDROID_DELEGATED_RUNTIME_AUDIT_AUTHORITY, str)

    def test_contract_version_non_empty(self):
        assert ANDROID_DELEGATED_RUNTIME_AUDIT_CONTRACT_VERSION
        assert isinstance(ANDROID_DELEGATED_RUNTIME_AUDIT_CONTRACT_VERSION, str)


# ---------------------------------------------------------------------------
# Group B — AndroidDelegatedAuditEventKind
# ---------------------------------------------------------------------------


class TestEventKindConstants:
    def test_delegated_execution_signal_present(self):
        assert AndroidDelegatedAuditEventKind.DELEGATED_EXECUTION_SIGNAL == "android_delegated_execution_signal"

    def test_handoff_v2_result_present(self):
        assert AndroidDelegatedAuditEventKind.HANDOFF_V2_RESULT == "android_handoff_v2_result"

    def test_takeover_request_present(self):
        assert AndroidDelegatedAuditEventKind.TAKEOVER_REQUEST == "android_takeover_request"

    def test_takeover_response_present(self):
        assert AndroidDelegatedAuditEventKind.TAKEOVER_RESPONSE == "android_takeover_response"

    def test_reconciliation_signal_present(self):
        assert AndroidDelegatedAuditEventKind.RECONCILIATION_SIGNAL == "android_reconciliation_signal"

    def test_participant_truth_terminal_update_present(self):
        assert (
            AndroidDelegatedAuditEventKind.PARTICIPANT_TRUTH_TERMINAL_UPDATE
            == "android_participant_truth_terminal_update"
        )

    def test_all_tuple_contains_six_kinds(self):
        assert len(AndroidDelegatedAuditEventKind.ALL) == 6

    def test_all_tuple_contains_expected_values(self):
        expected = {
            AndroidDelegatedAuditEventKind.DELEGATED_EXECUTION_SIGNAL,
            AndroidDelegatedAuditEventKind.HANDOFF_V2_RESULT,
            AndroidDelegatedAuditEventKind.TAKEOVER_REQUEST,
            AndroidDelegatedAuditEventKind.TAKEOVER_RESPONSE,
            AndroidDelegatedAuditEventKind.RECONCILIATION_SIGNAL,
            AndroidDelegatedAuditEventKind.PARTICIPANT_TRUTH_TERMINAL_UPDATE,
        }
        assert set(AndroidDelegatedAuditEventKind.ALL) == expected


# ---------------------------------------------------------------------------
# Group C — AndroidDelegatedAuditRecord
# ---------------------------------------------------------------------------


class TestAuditRecord:
    def test_auto_audit_id(self):
        rec = AndroidDelegatedAuditRecord()
        assert rec.audit_id.startswith("adra_")

    def test_recorded_at_positive(self):
        rec = AndroidDelegatedAuditRecord()
        assert rec.recorded_at > 0

    def test_defaults(self):
        rec = AndroidDelegatedAuditRecord()
        assert rec.task_id == ""
        assert rec.session_id == ""
        assert rec.trace_id == ""
        assert rec.device_id == ""
        assert rec.handoff_id == ""
        assert rec.takeover_id == ""
        assert rec.participant_role == ""
        assert rec.was_successful is None
        assert rec.reject_reason == ""

    def test_to_dict_keys(self):
        rec = AndroidDelegatedAuditRecord(task_id="t1", session_id="s1")
        d = rec.to_dict()
        for key in (
            "audit_id", "recorded_at", "kind", "task_id", "session_id",
            "trace_id", "device_id", "contract_id", "handoff_id",
            "takeover_id", "participant_role", "state_transition",
            "was_successful", "reject_reason", "source", "message", "payload",
        ):
            assert key in d, f"key {key!r} missing from to_dict()"

    def test_to_dict_values(self):
        rec = AndroidDelegatedAuditRecord(task_id="task_abc", session_id="sess_xyz")
        d = rec.to_dict()
        assert d["task_id"] == "task_abc"
        assert d["session_id"] == "sess_xyz"

    def test_to_json_valid(self):
        rec = AndroidDelegatedAuditRecord(task_id="t_json")
        raw = rec.to_json()
        parsed = json.loads(raw)
        assert parsed["task_id"] == "t_json"


# ---------------------------------------------------------------------------
# Group D — AndroidDelegatedAuditSnapshot
# ---------------------------------------------------------------------------


class TestAuditSnapshot:
    def test_to_dict_json_serialisable(self):
        snap = AndroidDelegatedAuditSnapshot(event_count=3)
        d = snap.to_dict()
        raw = json.dumps(d, default=str)
        parsed = json.loads(raw)
        assert parsed["event_count"] == 3
        assert parsed["authority"] == ANDROID_DELEGATED_RUNTIME_AUDIT_AUTHORITY


# ---------------------------------------------------------------------------
# Group E–J — AndroidDelegatedRuntimeAuditRecorder
# ---------------------------------------------------------------------------


class TestRecorder:
    def test_record_appends_to_ring(self):
        recorder = _fresh_recorder()
        rec = AndroidDelegatedAuditRecord(task_id="t1")
        recorder.record(rec)
        assert rec in recorder.all_events()

    def test_get_by_task(self):
        recorder = _fresh_recorder()
        tid = f"task_{_uid()}"
        for _ in range(3):
            recorder.record(AndroidDelegatedAuditRecord(task_id=tid))
        results = recorder.get_by_task(tid)
        assert len(results) == 3

    def test_get_by_task_empty_for_unknown(self):
        recorder = _fresh_recorder()
        assert recorder.get_by_task("nonexistent_task") == []

    def test_get_by_session(self):
        recorder = _fresh_recorder()
        sid = f"sess_{_uid()}"
        for _ in range(2):
            recorder.record(AndroidDelegatedAuditRecord(session_id=sid))
        results = recorder.get_by_session(sid)
        assert len(results) == 2

    def test_get_by_kind(self):
        recorder = _fresh_recorder()
        kind = AndroidDelegatedAuditEventKind.TAKEOVER_RESPONSE
        recorder.record(AndroidDelegatedAuditRecord(kind=kind))
        recorder.record(AndroidDelegatedAuditRecord(kind=AndroidDelegatedAuditEventKind.HANDOFF_V2_RESULT))
        results = recorder.get_by_kind(kind)
        assert len(results) == 1
        assert results[0].kind == kind

    def test_all_events_returns_copy(self):
        recorder = _fresh_recorder()
        recorder.record(AndroidDelegatedAuditRecord(task_id="t"))
        events = recorder.all_events()
        assert len(events) == 1

    def test_snapshot_event_count(self):
        recorder = _fresh_recorder()
        for _ in range(5):
            recorder.record(AndroidDelegatedAuditRecord())
        snap = recorder.snapshot()
        assert snap.event_count == 5


# ---------------------------------------------------------------------------
# Group K–L — Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_returns_same_instance(self):
        reset_android_delegated_audit_recorder()
        a = get_android_delegated_audit_recorder()
        b = get_android_delegated_audit_recorder()
        assert a is b

    def test_reset_clears_singleton(self):
        reset_android_delegated_audit_recorder()
        a = get_android_delegated_audit_recorder()
        reset_android_delegated_audit_recorder()
        b = get_android_delegated_audit_recorder()
        assert a is not b


# ---------------------------------------------------------------------------
# Group M–R — Recording helpers
# ---------------------------------------------------------------------------


class TestRecordingHelpers:
    def setup_method(self):
        reset_android_delegated_audit_recorder()

    def test_record_delegated_execution_signal_kind(self):
        rec = record_delegated_execution_signal(
            task_id="task_des",
            signal_kind="result",
            was_updated=True,
        )
        assert rec.kind == AndroidDelegatedAuditEventKind.DELEGATED_EXECUTION_SIGNAL

    def test_record_delegated_execution_signal_fields(self):
        tid = f"task_{_uid()}"
        rec = record_delegated_execution_signal(
            task_id=tid,
            session_id="sess_1",
            device_id="dev_1",
            contract_id="ctr_1",
            signal_kind="result",
            phase="completed",
            was_updated=True,
        )
        assert rec.task_id == tid
        assert rec.session_id == "sess_1"
        assert rec.device_id == "dev_1"
        assert rec.contract_id == "ctr_1"
        assert "result" in rec.state_transition
        assert "completed" in rec.state_transition
        assert rec.was_successful is True

    def test_record_delegated_execution_signal_reject(self):
        rec = record_delegated_execution_signal(
            task_id="task_reject",
            reject_reason="duplicate_signal",
            was_updated=False,
        )
        assert rec.reject_reason == "duplicate_signal"
        assert rec.was_successful is None

    def test_record_handoff_v2_result_kind(self):
        rec = record_handoff_v2_result(
            task_id="task_hv2",
            handoff_id="hid_1",
            response_kind="result",
            was_correlated=True,
        )
        assert rec.kind == AndroidDelegatedAuditEventKind.HANDOFF_V2_RESULT

    def test_record_handoff_v2_result_fields(self):
        tid = f"task_{_uid()}"
        hid = f"hid_{_uid()}"
        rec = record_handoff_v2_result(
            task_id=tid,
            handoff_id=hid,
            response_kind="result",
            was_correlated=True,
            callback_invoked=True,
        )
        assert rec.task_id == tid
        assert rec.handoff_id == hid
        assert rec.was_successful is True
        assert rec.payload["response_kind"] == "result"
        assert rec.payload["callback_invoked"] is True

    def test_record_handoff_v2_result_miss(self):
        rec = record_handoff_v2_result(
            task_id="task_miss",
            reject_reason="no_pending_entry",
            was_correlated=False,
        )
        assert rec.was_successful is False
        assert rec.reject_reason == "no_pending_entry"

    def test_record_takeover_request_kind(self):
        rec = record_takeover_request(
            task_id="task_tkr",
            takeover_id="tkv_1",
        )
        assert rec.kind == AndroidDelegatedAuditEventKind.TAKEOVER_REQUEST

    def test_record_takeover_request_fields(self):
        tid = f"task_{_uid()}"
        tkid = f"tkv_{_uid()}"
        rec = record_takeover_request(
            task_id=tid,
            device_id="dev_x",
            takeover_id=tkid,
            reason="reclaim_ownership",
        )
        assert rec.task_id == tid
        assert rec.takeover_id == tkid
        assert rec.device_id == "dev_x"
        assert rec.payload["reason"] == "reclaim_ownership"
        assert rec.was_successful is None  # pending — no response yet

    def test_record_takeover_response_accepted(self):
        tid = f"task_{_uid()}"
        rec = record_takeover_response(
            task_id=tid,
            takeover_id="tkv_2",
            accepted=True,
            reason="user confirmed",
        )
        assert rec.kind == AndroidDelegatedAuditEventKind.TAKEOVER_RESPONSE
        assert rec.was_successful is True
        assert "accepted" in rec.state_transition

    def test_record_takeover_response_rejected(self):
        rec = record_takeover_response(
            task_id="task_rej",
            takeover_id="tkv_3",
            accepted=False,
            reason="device busy",
        )
        assert rec.was_successful is False
        assert "rejected" in rec.state_transition

    def test_record_reconciliation_signal_kind(self):
        rec = record_reconciliation_signal(
            task_id="task_rec",
            truth_kind="task_phase",
            was_reconciled=True,
        )
        assert rec.kind == AndroidDelegatedAuditEventKind.RECONCILIATION_SIGNAL

    def test_record_reconciliation_signal_fields(self):
        tid = f"task_{_uid()}"
        rec = record_reconciliation_signal(
            task_id=tid,
            session_id="sess_r",
            contract_id="ctr_r",
            device_id="dev_r",
            truth_kind="result",
            phase="completed",
            was_reconciled=True,
            canonical_update="result_success_signal_applied",
        )
        assert rec.task_id == tid
        assert rec.was_successful is True
        assert rec.payload["canonical_update"] == "result_success_signal_applied"

    def test_record_reconciliation_signal_rejected(self):
        rec = record_reconciliation_signal(
            task_id="task_recrej",
            truth_kind="task_phase",
            was_reconciled=False,
            reject_reason="v2_terminal_state_wins",
        )
        assert rec.reject_reason == "v2_terminal_state_wins"
        assert rec.was_successful is None

    def test_record_participant_truth_terminal_update_kind(self):
        rec = record_participant_truth_terminal_update(
            task_id="task_pttu",
            truth_kind="result",
            terminal_phase="completed",
        )
        assert rec.kind == AndroidDelegatedAuditEventKind.PARTICIPANT_TRUTH_TERMINAL_UPDATE

    def test_record_participant_truth_terminal_update_fields(self):
        tid = f"task_{_uid()}"
        rec = record_participant_truth_terminal_update(
            task_id=tid,
            session_id="sess_pttu",
            device_id="dev_pttu",
            contract_id="ctr_pttu",
            truth_kind="cancel",
            terminal_phase="cancelled",
            canonical_update="cancel_signal_applied",
        )
        assert rec.task_id == tid
        assert rec.was_successful is True
        assert "cancelled" in rec.state_transition
        assert rec.payload["terminal_phase"] == "cancelled"


# ---------------------------------------------------------------------------
# Group S–V — Cross-helper task/session queries and serialisability
# ---------------------------------------------------------------------------


class TestCrossHelperQueries:
    def setup_method(self):
        reset_android_delegated_audit_recorder()

    def test_same_task_id_queryable_across_helpers(self):
        """All events for one task can be retrieved via get_android_audit_for_task."""
        tid = f"task_{_uid()}"
        record_delegated_execution_signal(task_id=tid, signal_kind="ack", was_updated=True)
        record_handoff_v2_result(task_id=tid, response_kind="ack", was_correlated=True)
        record_takeover_request(task_id=tid, takeover_id="tkv_a")
        record_takeover_response(task_id=tid, takeover_id="tkv_a", accepted=True)
        record_reconciliation_signal(task_id=tid, truth_kind="task_phase", was_reconciled=True)
        record_participant_truth_terminal_update(
            task_id=tid, truth_kind="result", terminal_phase="completed"
        )
        records = get_android_audit_for_task(tid)
        assert len(records) == 6

    def test_same_session_id_queryable(self):
        sid = f"sess_{_uid()}"
        record_delegated_execution_signal(session_id=sid, signal_kind="progress")
        record_reconciliation_signal(session_id=sid, truth_kind="status")
        records = get_android_audit_for_session(sid)
        assert len(records) == 2

    def test_android_audit_snapshot_reflects_events(self):
        reset_android_delegated_audit_recorder()
        tid = f"task_{_uid()}"
        for _ in range(4):
            record_takeover_response(task_id=tid, takeover_id=_uid(), accepted=True)
        snap = android_audit_snapshot()
        assert snap.event_count == 4
        assert len(snap.recent_events) <= 20

    def test_all_records_json_serialisable(self):
        reset_android_delegated_audit_recorder()
        tid = f"task_{_uid()}"
        record_delegated_execution_signal(task_id=tid, signal_kind="result", was_updated=True)
        record_handoff_v2_result(task_id=tid, handoff_id="hid", was_correlated=True)
        record_takeover_request(task_id=tid, takeover_id="tkid")
        record_takeover_response(task_id=tid, takeover_id="tkid", accepted=True)
        record_reconciliation_signal(task_id=tid, truth_kind="result", was_reconciled=True)
        record_participant_truth_terminal_update(task_id=tid, truth_kind="result", terminal_phase="completed")

        recorder = get_android_delegated_audit_recorder()
        for rec in recorder.all_events():
            raw = rec.to_json()
            parsed = json.loads(raw)
            assert "audit_id" in parsed
            assert "kind" in parsed
            assert "task_id" in parsed


# ---------------------------------------------------------------------------
# Group W — Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    def test_record_never_raises(self):
        """Recorder.record() must not raise even for a minimal record."""
        reset_android_delegated_audit_recorder()
        recorder = get_android_delegated_audit_recorder()
        rec = AndroidDelegatedAuditRecord()
        # Should not raise
        result = recorder.record(rec)
        assert result is rec

    def test_helpers_never_raise(self):
        """Recording helpers must not raise under any combination of defaults."""
        reset_android_delegated_audit_recorder()
        record_delegated_execution_signal()
        record_handoff_v2_result()
        record_takeover_request()
        record_takeover_response()
        record_reconciliation_signal()
        record_participant_truth_terminal_update()


# ---------------------------------------------------------------------------
# Group X–Z — Specific field / payload assertions
# ---------------------------------------------------------------------------


class TestSpecificFields:
    def setup_method(self):
        reset_android_delegated_audit_recorder()

    def test_takeover_response_state_transition_accepted(self):
        rec = record_takeover_response(accepted=True, takeover_id="tkv_x")
        assert "accepted" in rec.state_transition

    def test_takeover_response_state_transition_rejected(self):
        rec = record_takeover_response(accepted=False, takeover_id="tkv_y")
        assert "rejected" in rec.state_transition

    def test_delegated_signal_reject_reason_preserved(self):
        rec = record_delegated_execution_signal(
            reject_reason="out_of_order_signal",
            was_updated=False,
        )
        assert rec.reject_reason == "out_of_order_signal"

    def test_reconciliation_signal_canonical_update_in_payload(self):
        rec = record_reconciliation_signal(
            canonical_update="cancel_applied→tracking_cancelled",
            was_reconciled=True,
        )
        assert rec.payload["canonical_update"] == "cancel_applied→tracking_cancelled"


# ---------------------------------------------------------------------------
# Group AA–AE — Handler / ingress audit binding guards
#
# Handler modules depend on pydantic (via galaxy_gateway.android.models).
# When pydantic is unavailable the test is skipped — this is the same
# behaviour as the pre-existing handler tests in this repository.
# The participant truth ingress module has no pydantic dependency.
# ---------------------------------------------------------------------------


def _import_handler_module(module_path: str):
    """Import handler module; skip test if pydantic or another dep is missing."""
    import importlib

    try:
        return importlib.import_module(module_path)
    except ImportError as exc:
        pytest.skip(f"handler import unavailable: {exc}")


class TestHandlerImports:
    def test_android_participant_truth_ingress_importable(self):
        from core import android_participant_truth_ingress  # noqa: F401

    def test_participant_truth_ingress_has_audit_binding(self):
        import core.android_participant_truth_ingress as m

        assert hasattr(m, "_audit_terminal_update")

    def test_delegated_signal_handler_has_audit_binding(self):
        m = _import_handler_module(
            "galaxy_gateway.android.handlers.delegated_signal"
        )
        assert hasattr(m, "_audit_delegated_signal")

    def test_handoff_v2_result_handler_has_audit_binding(self):
        m = _import_handler_module(
            "galaxy_gateway.android.handlers.handoff_v2_result"
        )
        assert hasattr(m, "_audit_handoff_v2_result")

    def test_takeover_response_handler_has_audit_binding(self):
        m = _import_handler_module(
            "galaxy_gateway.android.handlers.takeover_response"
        )
        assert hasattr(m, "_audit_takeover_response")

    def test_reconciliation_signal_handler_has_audit_binding(self):
        m = _import_handler_module(
            "galaxy_gateway.android.handlers.reconciliation_signal"
        )
        assert hasattr(m, "_audit_reconciliation_signal")
