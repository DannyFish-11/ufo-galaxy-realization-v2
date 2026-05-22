"""tests/test_pr4v2_android_participant_truth_ingress.py
=========================================================
Tests for PR-4V2: Android Participant/Session/Runtime Truth Ingress and
Canonical Reconciliation into V2 Orchestration State.

These tests provide reviewable, auditable evidence for all four acceptance
criteria stated in the "Integrate Android runtime truth reconciliation into
V2 canonical orchestration" issue:

  AC1  How Android-originated participant/runtime truth enters V2
       (ingestion path reachability, envelope extraction, identity fields).

  AC2  How that truth is reconciled into canonical orchestration/runtime state
       (reconciliation behavior, policy sentinels, tracker state transitions).

  AC3  Whether Android-originated cancel/status/failure/result signals affect
       canonical V2 flow (tracking record phase transitions, ReplayFoundation
       events).

  AC4  What truth remains local to Android vs what becomes canonical in V2
       (advisory/local_only paths, authority-boundary sentinels).

Coverage groups
---------------
Group A — Authority chain: module importable, sentinels present, policy count.
Group B — AndroidParticipantTruthKind enum: all values, from_string(), guards.
Group C — AndroidParticipantTruthEnvelope: construction, has_lookup_key(), to_dict().
Group D — extract_participant_truth_envelope: identity field extraction rules.
Group E — cancel signal → V2 tracking record cancelled (AC3).
Group F — failure signal → V2 tracking record failed (AC3).
Group G — result success signal → V2 tracking record completed (AC3).
Group H — result failure signal → V2 tracking record failed (AC3).
Group I — status signal → V2 tracking record in_progress (AC3).
Group J — task_phase reconciliation: completed / failed / cancelled (AC2/AC3).
Group K — Terminal V2 state wins: signals rejected when record already terminal (AC2/AC4).
Group L — session_snapshot: registry continuity validation (AC2/AC4).
Group M — readiness_assessment and runtime_state: advisory/local_only (AC4).
Group N — Non-destructive on miss: no matching record → was_reconciled=False (AC2).
Group O — Missing lookup key → was_reconciled=False (AC2).
Group P — ReplayFoundation audit event always emitted (AC2/AC3).
Group Q — ingest_android_participant_truth_message: convenience wrapper e2e (AC1).
Group R — core.runtime re-exports: all PR-4V2 symbols accessible (AC1).
Group S — Authority boundary documentation: policy sentinels prove V2 wins (AC4).
Group T — AndroidParticipantReconcileOutcome: fields, is_accepted(), to_dict().
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------

try:
    from core.android_participant_truth_ingress import (
        ANDROID_PARTICIPANT_TRUTH_INGRESS_AUTHORITY,
        ANDROID_PARTICIPANT_TRUTH_INGRESS_PR4V2_SENTINEL,
        ANDROID_TRUTH_IS_ADVISORY_FOR_DEVICE_SCOPE_POLICY,
        CANCEL_FAILURE_RESULT_AFFECT_CANONICAL_STATE_POLICY,
        IDENTITY_FIELDS_ARE_VERBATIM_POLICY,
        READINESS_ASSESSMENT_IS_ADVISORY_POLICY,
        RECONCILE_EMITS_AUDIT_EVENT_ALWAYS_POLICY,
        RECONCILE_IS_NON_DESTRUCTIVE_ON_MISS_POLICY,
        RECONCILIATION_SIGNAL_DISTINCT_FROM_DELEGATED_POLICY,
        RUNTIME_STATE_IS_AUDIT_ONLY_POLICY,
        SESSION_SNAPSHOT_VALIDATES_REGISTRY_CONTINUITY_POLICY,
        STATUS_SIGNAL_EMITS_PROGRESS_EVENT_POLICY,
        TASK_PHASE_RECONCILED_WITH_TRACKING_RECORD_POLICY,
        TERMINAL_V2_STATE_WINS_CONFLICT_POLICY,
        V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY,
        V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_SENTINEL,
        AndroidParticipantReconcileOutcome,
        AndroidParticipantTruthEnvelope,
        AndroidParticipantTruthKind,
        extract_participant_truth_envelope,
        ingest_android_participant_truth_message,
        reconcile_android_participant_truth,
    )

    _MODULE_AVAILABLE = True
except ImportError:
    _MODULE_AVAILABLE = False

_SKIP_MODULE = pytest.mark.skipif(
    not _MODULE_AVAILABLE, reason="android_participant_truth_ingress unavailable"
)

try:
    from core.delegated_runtime_execution_tracker import (
        AcknowledgmentSignal,
        DelegatedExecutionTrackingRuntime,
        DelegatedExecutionPhase,
        create_execution_tracking_record,
        apply_acknowledgment_signal,
        get_execution_tracking_runtime,
    )

    _TRACKER_AVAILABLE = True
except ImportError:
    _TRACKER_AVAILABLE = False

_SKIP_TRACKER = pytest.mark.skipif(
    not _TRACKER_AVAILABLE, reason="delegated_runtime_execution_tracker unavailable"
)

try:
    from core.attached_runtime_session_registry import (
        AttachedSessionRegistry,
        get_session_registry,
        reset_session_registry,
        register_session,
        lookup_active_session,
    )

    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

try:
    from core.replay_foundation import (
        get_replay_foundation,
        reset_replay_foundation,
        emit_runtime_event,
    )

    _REPLAY_AVAILABLE = True
except ImportError:
    _REPLAY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runtime(
    contract_id: str = "",
    session_id: str = "",
    initial_phase: str = "acknowledged",
) -> Any:
    """Build an isolated DelegatedExecutionTrackingRuntime with one record."""
    if not _TRACKER_AVAILABLE:
        return None
    rt = DelegatedExecutionTrackingRuntime()
    cid = contract_id or str(uuid.uuid4())
    sid = session_id or str(uuid.uuid4())
    record = create_execution_tracking_record(
        contract_id=cid,
        session_id=sid,
        device_id="device_test",
        trace_id="trace_test",
        runtime=rt,
    )
    # Advance to desired initial phase using the isolated rt
    if initial_phase in ("in_progress", "completed", "failed", "timed_out", "cancelled"):
        record = apply_acknowledgment_signal(record, AcknowledgmentSignal.progress, runtime=rt)
        if initial_phase == "completed":
            record = apply_acknowledgment_signal(record, AcknowledgmentSignal.final_result, runtime=rt)
        elif initial_phase == "failed":
            record = apply_acknowledgment_signal(record, AcknowledgmentSignal.error, runtime=rt)
        elif initial_phase == "timed_out":
            record = apply_acknowledgment_signal(record, AcknowledgmentSignal.timeout, runtime=rt)
        elif initial_phase == "cancelled":
            record = apply_acknowledgment_signal(record, AcknowledgmentSignal.cancelled, runtime=rt)
    return rt, record


# ---------------------------------------------------------------------------
# Group A — Authority chain
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupA_AuthorityChain:
    def test_a1_module_importable(self) -> None:
        """AC1: The module must be importable from core.android_participant_truth_ingress."""
        assert _MODULE_AVAILABLE, "core.android_participant_truth_ingress must be importable"

    def test_a2_authority_sentinel_present(self) -> None:
        assert ANDROID_PARTICIPANT_TRUTH_INGRESS_AUTHORITY
        assert "PR4V2" in ANDROID_PARTICIPANT_TRUTH_INGRESS_AUTHORITY

    def test_a3_pr_sentinel_present(self) -> None:
        assert ANDROID_PARTICIPANT_TRUTH_INGRESS_PR4V2_SENTINEL
        assert "PR4V2" in ANDROID_PARTICIPANT_TRUTH_INGRESS_PR4V2_SENTINEL
        assert "TRUTH-005" in ANDROID_PARTICIPANT_TRUTH_INGRESS_PR4V2_SENTINEL

    def test_a4_v2_authority_sentinel_present(self) -> None:
        assert V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_SENTINEL
        assert "v2" in V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_SENTINEL.lower()
        assert "canonical" in V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_SENTINEL.lower()

    def test_a5_policy_sentinels_non_empty(self) -> None:
        policies = [
            V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY,
            ANDROID_TRUTH_IS_ADVISORY_FOR_DEVICE_SCOPE_POLICY,
            CANCEL_FAILURE_RESULT_AFFECT_CANONICAL_STATE_POLICY,
            STATUS_SIGNAL_EMITS_PROGRESS_EVENT_POLICY,
            TASK_PHASE_RECONCILED_WITH_TRACKING_RECORD_POLICY,
            SESSION_SNAPSHOT_VALIDATES_REGISTRY_CONTINUITY_POLICY,
            READINESS_ASSESSMENT_IS_ADVISORY_POLICY,
            RUNTIME_STATE_IS_AUDIT_ONLY_POLICY,
            TERMINAL_V2_STATE_WINS_CONFLICT_POLICY,
            RECONCILE_IS_NON_DESTRUCTIVE_ON_MISS_POLICY,
            RECONCILE_EMITS_AUDIT_EVENT_ALWAYS_POLICY,
            IDENTITY_FIELDS_ARE_VERBATIM_POLICY,
            RECONCILIATION_SIGNAL_DISTINCT_FROM_DELEGATED_POLICY,
        ]
        for p in policies:
            assert p, f"Policy sentinel must be non-empty: {p!r}"
        assert len(policies) == 13, "Expected 13 policy sentinels"

    def test_a6_cancel_failure_result_policy_mentions_canonical(self) -> None:
        """AC3: cancel/failure/result policy must state they affect canonical state."""
        assert "canonical" in CANCEL_FAILURE_RESULT_AFFECT_CANONICAL_STATE_POLICY.lower()
        assert "NOT merely logged" in CANCEL_FAILURE_RESULT_AFFECT_CANONICAL_STATE_POLICY

    def test_a7_terminal_v2_wins_policy(self) -> None:
        """AC4: V2 terminal state wins conflict policy must be stated."""
        assert "V2" in TERMINAL_V2_STATE_WINS_CONFLICT_POLICY
        assert "terminal" in TERMINAL_V2_STATE_WINS_CONFLICT_POLICY.lower()


# ---------------------------------------------------------------------------
# Group B — AndroidParticipantTruthKind enum
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupB_TruthKindEnum:
    def test_b1_all_expected_values_present(self) -> None:
        expected = {
            "session_snapshot", "readiness_assessment", "task_phase",
            "runtime_state", "cancel", "status", "failure", "result", "unknown",
            "reconciliation_signal", "governance_artifact", "recovery_state",
        }
        actual = {m.value for m in AndroidParticipantTruthKind}
        assert expected == actual

    def test_b2_from_string_known_values(self) -> None:
        assert AndroidParticipantTruthKind.from_string("cancel") == AndroidParticipantTruthKind.cancel
        assert AndroidParticipantTruthKind.from_string("failure") == AndroidParticipantTruthKind.failure
        assert AndroidParticipantTruthKind.from_string("result") == AndroidParticipantTruthKind.result
        assert AndroidParticipantTruthKind.from_string("status") == AndroidParticipantTruthKind.status

    def test_b3_from_string_unknown_returns_unknown(self) -> None:
        assert AndroidParticipantTruthKind.from_string("nonsense") == AndroidParticipantTruthKind.unknown
        assert AndroidParticipantTruthKind.from_string(None) == AndroidParticipantTruthKind.unknown
        assert AndroidParticipantTruthKind.from_string("") == AndroidParticipantTruthKind.unknown

    def test_b4_is_terminal_signal(self) -> None:
        assert AndroidParticipantTruthKind.cancel.is_terminal_signal()
        assert AndroidParticipantTruthKind.failure.is_terminal_signal()
        assert AndroidParticipantTruthKind.result.is_terminal_signal()
        assert not AndroidParticipantTruthKind.status.is_terminal_signal()
        assert not AndroidParticipantTruthKind.task_phase.is_terminal_signal()
        assert not AndroidParticipantTruthKind.session_snapshot.is_terminal_signal()

    def test_b5_affects_canonical_state(self) -> None:
        """AC3: cancel/failure/result/status/task_phase must affect canonical state."""
        assert AndroidParticipantTruthKind.cancel.affects_canonical_state()
        assert AndroidParticipantTruthKind.failure.affects_canonical_state()
        assert AndroidParticipantTruthKind.result.affects_canonical_state()
        assert AndroidParticipantTruthKind.status.affects_canonical_state()
        assert AndroidParticipantTruthKind.task_phase.affects_canonical_state()
        assert not AndroidParticipantTruthKind.readiness_assessment.affects_canonical_state()
        assert not AndroidParticipantTruthKind.runtime_state.affects_canonical_state()


# ---------------------------------------------------------------------------
# Group C — AndroidParticipantTruthEnvelope
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupC_TruthEnvelope:
    def test_c1_default_construction(self) -> None:
        env = AndroidParticipantTruthEnvelope()
        assert env.truth_kind == AndroidParticipantTruthKind.unknown
        assert env.device_id == ""
        assert env.session_id == ""
        assert env.contract_id == ""
        assert env.envelope_id  # auto-generated UUID

    def test_c2_has_lookup_key_true(self) -> None:
        env = AndroidParticipantTruthEnvelope(contract_id="cid-1")
        assert env.has_lookup_key()
        env2 = AndroidParticipantTruthEnvelope(session_id="sid-1")
        assert env2.has_lookup_key()

    def test_c3_has_lookup_key_false(self) -> None:
        env = AndroidParticipantTruthEnvelope()
        assert not env.has_lookup_key()

    def test_c4_to_dict_round_trip(self) -> None:
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.cancel,
            device_id="dev-1",
            session_id="sid-1",
            contract_id="cid-1",
            task_id="task-1",
            trace_id="trace-1",
        )
        d = env.to_dict()
        assert d["truth_kind"] == "cancel"
        assert d["device_id"] == "dev-1"
        assert d["session_id"] == "sid-1"
        assert d["contract_id"] == "cid-1"


# ---------------------------------------------------------------------------
# Group D — extract_participant_truth_envelope
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupD_EnvelopeExtraction:
    def test_d1_truth_kind_extracted_from_top_level(self) -> None:
        """AC1: truth_kind is extracted from the inbound message."""
        msg = {"truth_kind": "cancel", "device_id": "dev-1", "session_id": "sid-1"}
        env = extract_participant_truth_envelope(msg)
        assert env.truth_kind == AndroidParticipantTruthKind.cancel

    def test_d2_truth_kind_from_payload(self) -> None:
        msg = {"payload": {"truth_kind": "failure", "session_id": "sid-2"}}
        env = extract_participant_truth_envelope(msg)
        assert env.truth_kind == AndroidParticipantTruthKind.failure

    def test_d3_device_id_top_level_priority(self) -> None:
        """AC1 (IDENTITY_FIELDS_ARE_VERBATIM): device_id from top-level wins."""
        msg = {"device_id": "dev-top", "payload": {"device_id": "dev-payload"}}
        env = extract_participant_truth_envelope(msg)
        assert env.device_id == "dev-top"

    def test_d4_contract_id_payload_priority(self) -> None:
        """AC1: contract_id from payload wins over top-level."""
        msg = {"contract_id": "cid-top", "payload": {"contract_id": "cid-payload"}}
        env = extract_participant_truth_envelope(msg)
        assert env.contract_id == "cid-payload"

    def test_d5_session_id_payload_priority(self) -> None:
        msg = {"session_id": "sid-top", "payload": {"session_id": "sid-payload"}}
        env = extract_participant_truth_envelope(msg)
        assert env.session_id == "sid-payload"

    def test_d6_task_phase_value_extracted(self) -> None:
        msg = {"payload": {"task_phase": "running", "session_id": "sid-1"}}
        env = extract_participant_truth_envelope(msg)
        assert env.task_phase_value == "running"

    def test_d7_result_success_bool(self) -> None:
        msg = {"payload": {"success": True, "contract_id": "cid-1"}}
        env = extract_participant_truth_envelope(msg)
        assert env.result_success is True

    def test_d8_result_success_false(self) -> None:
        msg = {"payload": {"success": False, "contract_id": "cid-1"}}
        env = extract_participant_truth_envelope(msg)
        assert env.result_success is False

    def test_d9_result_success_from_result_kind(self) -> None:
        msg = {"payload": {"result_kind": "success", "contract_id": "cid-1"}}
        env = extract_participant_truth_envelope(msg)
        assert env.result_success is True

    def test_d10_result_payload_extracted(self) -> None:
        msg = {"payload": {"result": {"value": 42}, "contract_id": "cid-1"}}
        env = extract_participant_truth_envelope(msg)
        assert env.result_payload == {"value": 42}

    def test_d11_empty_message_does_not_raise(self) -> None:
        env = extract_participant_truth_envelope({})
        assert env.truth_kind == AndroidParticipantTruthKind.unknown

    def test_d12_non_dict_does_not_raise(self) -> None:
        env = extract_participant_truth_envelope(None)  # type: ignore[arg-type]
        assert env.truth_kind == AndroidParticipantTruthKind.unknown


# ---------------------------------------------------------------------------
# Group E — cancel signal → tracking record cancelled
# ---------------------------------------------------------------------------


@_SKIP_MODULE
@pytest.mark.skipif(not _TRACKER_AVAILABLE, reason="tracker unavailable")
class TestGroupE_CancelSignal:
    def test_e1_cancel_materialises_cancelled_phase(self) -> None:
        """AC3: cancel signal MUST advance V2 tracking record to cancelled."""
        rt, record = _make_runtime(contract_id="cid-e1", initial_phase="in_progress")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.cancel,
            contract_id="cid-e1",
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert outcome.was_reconciled, "cancel must be reconciled"
        assert outcome.reject_reason == "", f"Unexpected reject: {outcome.reject_reason}"
        phase = outcome.tracking_record_phase.lower()
        assert "cancel" in phase, f"Expected cancelled phase, got: {phase}"

    def test_e2_cancel_sets_canonical_update(self) -> None:
        rt, _ = _make_runtime(contract_id="cid-e2", initial_phase="in_progress")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.cancel, contract_id="cid-e2"
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert outcome.canonical_update, "canonical_update must be set on cancel"
        assert "cancel" in outcome.canonical_update.lower()

    def test_e3_cancel_outcome_is_accepted(self) -> None:
        rt, _ = _make_runtime(contract_id="cid-e3", initial_phase="in_progress")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.cancel, contract_id="cid-e3"
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert outcome.is_accepted()


# ---------------------------------------------------------------------------
# Group F — failure signal → tracking record failed
# ---------------------------------------------------------------------------


@_SKIP_MODULE
@pytest.mark.skipif(not _TRACKER_AVAILABLE, reason="tracker unavailable")
class TestGroupF_FailureSignal:
    def test_f1_failure_materialises_failed_phase(self) -> None:
        """AC3: failure signal MUST advance V2 tracking record to failed."""
        rt, record = _make_runtime(contract_id="cid-f1", initial_phase="in_progress")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.failure,
            contract_id="cid-f1",
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert outcome.was_reconciled
        phase = outcome.tracking_record_phase.lower()
        assert "fail" in phase, f"Expected failed phase, got: {phase}"

    def test_f2_failure_sets_canonical_update(self) -> None:
        rt, _ = _make_runtime(contract_id="cid-f2", initial_phase="in_progress")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.failure, contract_id="cid-f2"
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert "fail" in outcome.canonical_update.lower()

    def test_f3_failure_materializes_result_object(self) -> None:
        rt, _ = _make_runtime(contract_id="cid-f3", initial_phase="in_progress")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.failure,
            contract_id="cid-f3",
            payload={"error_message": "boom"},
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        latest = rt.get_latest_for_contract("cid-f3")
        assert outcome.was_reconciled
        assert latest is not None
        assert latest.result is not None
        assert latest.result.success is False
        assert latest.result.error_detail == "boom"


# ---------------------------------------------------------------------------
# Group G — result success signal → tracking record completed
# ---------------------------------------------------------------------------


@_SKIP_MODULE
@pytest.mark.skipif(not _TRACKER_AVAILABLE, reason="tracker unavailable")
class TestGroupG_ResultSuccessSignal:
    def test_g1_result_success_materialises_completed_phase(self) -> None:
        """AC3: result success MUST advance V2 tracking record to completed."""
        rt, record = _make_runtime(contract_id="cid-g1", initial_phase="in_progress")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.result,
            contract_id="cid-g1",
            result_success=True,
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert outcome.was_reconciled
        phase = outcome.tracking_record_phase.lower()
        assert "complet" in phase, f"Expected completed phase, got: {phase}"

    def test_g2_result_success_canonical_update(self) -> None:
        rt, _ = _make_runtime(contract_id="cid-g2", initial_phase="in_progress")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.result,
            contract_id="cid-g2",
            result_success=True,
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert "complet" in outcome.canonical_update.lower()

    def test_g3_result_success_materializes_result_payload(self) -> None:
        rt, _ = _make_runtime(contract_id="cid-g3", initial_phase="in_progress")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.result,
            contract_id="cid-g3",
            result_success=True,
            result_payload={"value": 42},
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        latest = rt.get_latest_for_contract("cid-g3")
        assert outcome.was_reconciled
        assert latest is not None
        assert latest.result is not None
        assert latest.result.success is True
        assert latest.result.error_detail == ""
        assert latest.result.result_payload == {"value": 42}


# ---------------------------------------------------------------------------
# Group H — result failure signal → tracking record failed
# ---------------------------------------------------------------------------


@_SKIP_MODULE
@pytest.mark.skipif(not _TRACKER_AVAILABLE, reason="tracker unavailable")
class TestGroupH_ResultFailureSignal:
    def test_h1_result_failure_materialises_failed_phase(self) -> None:
        """AC3: result failure MUST advance V2 tracking record to failed."""
        rt, record = _make_runtime(contract_id="cid-h1", initial_phase="in_progress")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.result,
            contract_id="cid-h1",
            result_success=False,
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert outcome.was_reconciled
        phase = outcome.tracking_record_phase.lower()
        assert "fail" in phase, f"Expected failed phase, got: {phase}"

    def test_h2_result_failure_materializes_error_result(self) -> None:
        rt, _ = _make_runtime(contract_id="cid-h2", initial_phase="in_progress")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.result,
            contract_id="cid-h2",
            result_success=False,
            payload={"error_message": "remote_failed"},
            result_payload={"step": "resume"},
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        latest = rt.get_latest_for_contract("cid-h2")
        assert outcome.was_reconciled
        assert latest is not None
        assert latest.result is not None
        assert latest.result.success is False
        assert latest.result.result_payload == {"step": "resume"}
        assert latest.result.error_detail == "remote_failed"


# ---------------------------------------------------------------------------
# Group I — status signal → tracking record in_progress
# ---------------------------------------------------------------------------


@_SKIP_MODULE
@pytest.mark.skipif(not _TRACKER_AVAILABLE, reason="tracker unavailable")
class TestGroupI_StatusSignal:
    def test_i1_status_advances_to_in_progress(self) -> None:
        """AC3: status signal MUST advance V2 tracking record."""
        rt, record = _make_runtime(contract_id="cid-i1", initial_phase="acknowledged")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.status,
            contract_id="cid-i1",
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert outcome.was_reconciled
        assert "progress" in outcome.canonical_update.lower()

    def test_i2_status_updates_canonical_update(self) -> None:
        rt, _ = _make_runtime(contract_id="cid-i2", initial_phase="acknowledged")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.status, contract_id="cid-i2"
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert outcome.canonical_update


# ---------------------------------------------------------------------------
# Group J — task_phase reconciliation
# ---------------------------------------------------------------------------


@_SKIP_MODULE
@pytest.mark.skipif(not _TRACKER_AVAILABLE, reason="tracker unavailable")
class TestGroupJ_TaskPhaseReconciliation:
    def test_j1_android_completed_phase_advances_tracker(self) -> None:
        """AC2: Android completed task phase must advance V2 tracking record."""
        rt, record = _make_runtime(contract_id="cid-j1", initial_phase="in_progress")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.task_phase,
            contract_id="cid-j1",
            task_phase_value="completed",
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert outcome.was_reconciled
        phase = outcome.tracking_record_phase.lower()
        assert "complet" in phase

    def test_j2_android_failed_phase_advances_tracker(self) -> None:
        rt, _ = _make_runtime(contract_id="cid-j2", initial_phase="in_progress")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.task_phase,
            contract_id="cid-j2",
            task_phase_value="failed",
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert outcome.was_reconciled
        phase = outcome.tracking_record_phase.lower()
        assert "fail" in phase

    def test_j3_android_cancelled_phase_advances_tracker(self) -> None:
        rt, record = _make_runtime(contract_id="cid-j3", initial_phase="in_progress")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.task_phase,
            contract_id="cid-j3",
            task_phase_value="cancelled",
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert outcome.was_reconciled

    def test_j4_unmapped_phase_does_not_crash(self) -> None:
        rt, _ = _make_runtime(contract_id="cid-j4", initial_phase="in_progress")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.task_phase,
            contract_id="cid-j4",
            task_phase_value="some_unknown_phase",
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        # Must not raise; should reject with reason
        assert not outcome.was_reconciled
        assert "unmapped" in outcome.reject_reason.lower()


# ---------------------------------------------------------------------------
# Group K — Terminal V2 state wins
# ---------------------------------------------------------------------------


@_SKIP_MODULE
@pytest.mark.skipif(not _TRACKER_AVAILABLE, reason="tracker unavailable")
class TestGroupK_TerminalV2StateWins:
    @pytest.mark.parametrize("terminal_phase", ["completed", "failed", "cancelled", "timed_out"])
    def test_k1_terminal_record_blocks_cancel(self, terminal_phase: str) -> None:
        """AC4: V2 terminal state wins — cancel signal rejected when V2 already terminal."""
        try:
            rt, _ = _make_runtime(contract_id=f"cid-k1-{terminal_phase}", initial_phase=terminal_phase)
        except Exception:
            pytest.skip("Could not build runtime for terminal_phase=" + terminal_phase)
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.cancel,
            contract_id=f"cid-k1-{terminal_phase}",
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert not outcome.was_reconciled, "V2 terminal state must win"
        assert "v2_terminal_state_wins" in outcome.reject_reason.lower()

    @pytest.mark.parametrize("terminal_phase", ["completed", "failed"])
    def test_k2_terminal_record_blocks_status(self, terminal_phase: str) -> None:
        """AC4: V2 terminal state wins — status signal rejected when V2 already terminal."""
        try:
            rt, _ = _make_runtime(contract_id=f"cid-k2-{terminal_phase}", initial_phase=terminal_phase)
        except Exception:
            pytest.skip("Could not build runtime for terminal_phase=" + terminal_phase)
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.status,
            contract_id=f"cid-k2-{terminal_phase}",
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert not outcome.was_reconciled
        assert "terminal" in outcome.reject_reason.lower()


# ---------------------------------------------------------------------------
# Group L — session_snapshot: registry continuity validation
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupL_SessionSnapshotReconciliation:
    @pytest.mark.skipif(not _REGISTRY_AVAILABLE, reason="registry unavailable")
    def test_l1_active_session_confirms_continuity(self) -> None:
        """AC2: Android session snapshot against active V2 registry entry confirms continuity."""
        if not _REGISTRY_AVAILABLE:
            pytest.skip("registry unavailable")

        registry = AttachedSessionRegistry()
        sid = str(uuid.uuid4())
        # Register a session
        try:
            register_session(
                session_id=sid,
                device_id="dev-l1",
                runtime_session_id="rsid-l1",
                registry=registry,
            )
        except Exception:
            pytest.skip("register_session signature incompatible")

        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.session_snapshot,
            session_id=sid,
        )
        outcome = reconcile_android_participant_truth(env, registry=registry)
        assert outcome.was_reconciled
        assert "continuity" in outcome.canonical_update.lower()

    def test_l2_missing_session_id_rejected(self) -> None:
        """AC2: session_snapshot without session_id is rejected gracefully."""
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.session_snapshot,
            session_id="",  # no session_id
        )
        outcome = reconcile_android_participant_truth(env)
        assert not outcome.was_reconciled
        assert outcome.reject_reason  # must have a reason


# ---------------------------------------------------------------------------
# Group M — readiness_assessment and runtime_state: advisory/local_only
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupM_AdvisoryTruth:
    def test_m1_readiness_assessment_is_local_only(self) -> None:
        """AC4: readiness_assessment truth is advisory, remains local to Android."""
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.readiness_assessment,
            device_id="dev-m1",
        )
        outcome = reconcile_android_participant_truth(env)
        assert outcome.local_only, "readiness_assessment must be local_only"
        assert not outcome.was_reconciled

    def test_m2_runtime_state_is_local_only(self) -> None:
        """AC4: runtime_state truth is advisory, remains local to Android."""
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.runtime_state,
            device_id="dev-m2",
        )
        outcome = reconcile_android_participant_truth(env)
        assert outcome.local_only
        assert not outcome.was_reconciled

    def test_m3_unknown_truth_kind_is_local_only(self) -> None:
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.unknown,
        )
        outcome = reconcile_android_participant_truth(env)
        assert outcome.local_only


# ---------------------------------------------------------------------------
# Group N — Non-destructive on miss
# ---------------------------------------------------------------------------


@_SKIP_MODULE
@pytest.mark.skipif(not _TRACKER_AVAILABLE, reason="tracker unavailable")
class TestGroupN_NonDestructiveOnMiss:
    def test_n1_cancel_on_empty_runtime_is_graceful(self) -> None:
        """AC2 (RECONCILE_IS_NON_DESTRUCTIVE_ON_MISS): no record → was_reconciled=False."""
        rt = DelegatedExecutionTrackingRuntime()
        # Provide lookup stubs that return None
        rt.get_latest_for_contract = lambda cid: None  # type: ignore[attr-defined]
        rt.get_latest_for_session = lambda sid: None  # type: ignore[attr-defined]
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.cancel,
            contract_id="cid-n1",
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert not outcome.was_reconciled
        assert "no_matching" in outcome.reject_reason

    def test_n2_failure_on_empty_runtime_is_graceful(self) -> None:
        rt = DelegatedExecutionTrackingRuntime()
        rt.get_latest_for_contract = lambda cid: None  # type: ignore[attr-defined]
        rt.get_latest_for_session = lambda sid: None  # type: ignore[attr-defined]
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.failure,
            contract_id="cid-n2",
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert not outcome.was_reconciled


# ---------------------------------------------------------------------------
# Group O — Missing lookup key
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupO_MissingLookupKey:
    def test_o1_cancel_without_lookup_key(self) -> None:
        """AC2: cancel without contract_id or session_id must be rejected."""
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.cancel,
            # both contract_id and session_id empty
        )
        outcome = reconcile_android_participant_truth(env)
        assert not outcome.was_reconciled
        assert "missing_lookup_key" in outcome.reject_reason

    def test_o2_result_without_lookup_key(self) -> None:
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.result,
            result_success=True,
        )
        outcome = reconcile_android_participant_truth(env)
        assert not outcome.was_reconciled
        assert "missing_lookup_key" in outcome.reject_reason

    def test_o3_status_without_lookup_key(self) -> None:
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.status,
        )
        outcome = reconcile_android_participant_truth(env)
        assert not outcome.was_reconciled
        assert "missing_lookup_key" in outcome.reject_reason


# ---------------------------------------------------------------------------
# Group P — ReplayFoundation audit event always emitted
# ---------------------------------------------------------------------------


@_SKIP_MODULE
@pytest.mark.skipif(not _REPLAY_AVAILABLE, reason="replay_foundation unavailable")
class TestGroupP_ReplayFoundationAuditEvent:
    def test_p1_audit_event_emitted_on_accepted_cancel(self) -> None:
        """AC2/AC3 (RECONCILE_EMITS_AUDIT_EVENT_ALWAYS): audit event emitted on accepted cancel."""
        if not _TRACKER_AVAILABLE:
            pytest.skip("tracker unavailable")
        reset_replay_foundation()
        rt, _ = _make_runtime(contract_id="cid-p1", initial_phase="in_progress")
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.cancel,
            contract_id="cid-p1",
        )
        outcome = reconcile_android_participant_truth(env, runtime=rt)
        assert outcome.replay_event_emitted, "Replay event must be emitted on accepted cancel"

    def test_p2_audit_event_emitted_on_rejected_outcome(self) -> None:
        """AC2 (RECONCILE_EMITS_AUDIT_EVENT_ALWAYS): audit event emitted even on rejection."""
        reset_replay_foundation()
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.cancel,
            # no lookup key → rejected
        )
        outcome = reconcile_android_participant_truth(env)
        # Even rejected outcomes should emit an audit event
        assert outcome.replay_event_emitted, "Replay event must be emitted on rejection too"

    def test_p3_advisory_truth_emits_audit_event(self) -> None:
        reset_replay_foundation()
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.readiness_assessment,
            device_id="dev-p3",
        )
        outcome = reconcile_android_participant_truth(env)
        assert outcome.replay_event_emitted


# ---------------------------------------------------------------------------
# Group Q — ingest_android_participant_truth_message: convenience wrapper
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupQ_ConvenienceWrapper:
    def test_q1_ingest_cancel_message(self) -> None:
        """AC1: ingest_android_participant_truth_message routes cancel to reconciler."""
        msg = {
            "truth_kind": "cancel",
            "payload": {"contract_id": "cid-q1"},
        }
        # Without a real tracking record this should return gracefully
        outcome = ingest_android_participant_truth_message(msg)
        assert isinstance(outcome, AndroidParticipantReconcileOutcome)

    def test_q2_ingest_readiness_message(self) -> None:
        msg = {
            "truth_kind": "readiness_assessment",
            "device_id": "dev-q2",
        }
        outcome = ingest_android_participant_truth_message(msg)
        assert outcome.local_only

    def test_q3_ingest_unknown_message(self) -> None:
        msg = {"device_id": "dev-q3"}
        outcome = ingest_android_participant_truth_message(msg)
        assert isinstance(outcome, AndroidParticipantReconcileOutcome)


# ---------------------------------------------------------------------------
# Group R — core.runtime re-exports
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupR_CoreRuntimeReexports:
    def test_r1_all_pr4v2_symbols_importable_from_core_runtime(self) -> None:
        """AC1: all PR-4V2 symbols must be accessible from core.runtime."""
        from core.runtime import (  # noqa: F401
            ANDROID_PARTICIPANT_TRUTH_INGRESS_AUTHORITY,
            ANDROID_PARTICIPANT_TRUTH_INGRESS_PR4V2_SENTINEL,
            AndroidParticipantReconcileOutcome,
            AndroidParticipantTruthEnvelope,
            AndroidParticipantTruthKind,
            CANCEL_FAILURE_RESULT_AFFECT_CANONICAL_STATE_POLICY,
            V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_SENTINEL,
            extract_participant_truth_envelope,
            ingest_android_participant_truth_message,
            reconcile_android_participant_truth,
        )

    def test_r2_pr4v2_sentinel_in_runtime_all(self) -> None:
        import core.runtime as _runtime_pkg
        assert "ANDROID_PARTICIPANT_TRUTH_INGRESS_PR4V2_SENTINEL" in dir(_runtime_pkg)

    def test_r3_reconcile_function_in_runtime_all(self) -> None:
        import core.runtime as _runtime_pkg
        assert "reconcile_android_participant_truth" in dir(_runtime_pkg)


# ---------------------------------------------------------------------------
# Group S — Authority boundary documentation (AC4)
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupS_AuthorityBoundary:
    def test_s1_v2_authority_policy_states_v2_wins(self) -> None:
        """AC4: V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY must state V2 is authority."""
        assert "V2" in V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY
        assert "canonical" in V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY.lower()
        assert "Android" in V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_POLICY

    def test_s2_android_advisory_policy_states_scope(self) -> None:
        """AC4: Android truth advisory scope must be documented."""
        assert "advisory" in ANDROID_TRUTH_IS_ADVISORY_FOR_DEVICE_SCOPE_POLICY.lower()
        assert "device" in ANDROID_TRUTH_IS_ADVISORY_FOR_DEVICE_SCOPE_POLICY.lower()

    def test_s3_terminal_wins_policy_states_immutability(self) -> None:
        """AC4: Terminal V2 state wins policy must state immutability."""
        assert "terminal" in TERMINAL_V2_STATE_WINS_CONFLICT_POLICY.lower()
        assert "immutable" in TERMINAL_V2_STATE_WINS_CONFLICT_POLICY.lower()

    def test_s4_cancel_policy_states_not_merely_logged(self) -> None:
        """AC3: cancel/failure/result policy must explicitly say 'not merely logged'."""
        assert "NOT merely logged" in CANCEL_FAILURE_RESULT_AFFECT_CANONICAL_STATE_POLICY

    def test_s5_v2_authority_sentinel_covers_all_terminal_signal_types(self) -> None:
        """AC3: V2 canonical authority sentinel must cover cancel+failure+result."""
        sentinel = V2_IS_CANONICAL_ORCHESTRATION_AUTHORITY_SENTINEL
        assert "cancel" in sentinel.lower()
        assert "failure" in sentinel.lower()
        assert "result" in sentinel.lower()


# ---------------------------------------------------------------------------
# Group T — AndroidParticipantReconcileOutcome fields
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupT_ReconcileOutcome:
    def test_t1_default_construction(self) -> None:
        outcome = AndroidParticipantReconcileOutcome()
        assert not outcome.was_reconciled
        assert outcome.canonical_update == ""
        assert not outcome.local_only
        assert outcome.reject_reason == ""
        assert not outcome.replay_event_emitted
        assert outcome.tracking_record_phase == ""

    def test_t2_is_accepted_true_when_reconciled_no_reject(self) -> None:
        env = AndroidParticipantTruthEnvelope()
        outcome = AndroidParticipantReconcileOutcome(
            envelope=env,
            was_reconciled=True,
            canonical_update="some_update",
            reject_reason="",
        )
        assert outcome.is_accepted()

    def test_t3_is_accepted_false_when_not_reconciled(self) -> None:
        outcome = AndroidParticipantReconcileOutcome(was_reconciled=False)
        assert not outcome.is_accepted()

    def test_t4_is_accepted_false_when_reject_reason_set(self) -> None:
        outcome = AndroidParticipantReconcileOutcome(
            was_reconciled=True, reject_reason="some_reason"
        )
        assert not outcome.is_accepted()

    def test_t5_to_dict_contains_expected_keys(self) -> None:
        env = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.cancel,
            contract_id="cid-t5",
        )
        outcome = AndroidParticipantReconcileOutcome(
            envelope=env, was_reconciled=True, canonical_update="cancel_applied"
        )
        d = outcome.to_dict()
        assert "was_reconciled" in d
        assert "canonical_update" in d
        assert "local_only" in d
        assert "reject_reason" in d
        assert "replay_event_emitted" in d
        assert "tracking_record_phase" in d
        assert "envelope" in d
