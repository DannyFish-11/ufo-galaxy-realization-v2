"""tests/test_pr13_post533_android_execution_signal_reconciler.py
=================================================================
Tests for PR package 13 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical Host-Side Android Execution Signal Reconciliation
Binding.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — AndroidSignalKind enum: all values, from_string(), to_ack_signal(),
     is_terminal(), defaults.
C  — normalize_android_message_to_signal_kind: task_result mappings.
D  — normalize_android_message_to_signal_kind: task_progress mappings.
E  — normalize_android_message_to_signal_kind: task_end mappings.
F  — normalize_android_message_to_signal_kind: goal_execution_result mappings.
G  — normalize_android_message_to_signal_kind: error mappings.
H  — normalize_android_message_to_signal_kind: agent_result / agent_status.
I  — normalize_android_message_to_signal_kind: unknown type defaults to progress.
J  — normalize_android_message_to_signal_kind: case-insensitive matching.
K  — normalize_android_message_to_signal_kind: None / empty inputs.
L  — extract_signal_envelope: contract_id / session_id from payload.
M  — extract_signal_envelope: device_id / task_id from top-level.
N  — extract_signal_envelope: trace_id from payload, then top-level.
O  — extract_signal_envelope: status resolution order.
P  — extract_signal_envelope: success field (bool) → status.
Q  — extract_signal_envelope: payload snapshot includes result/error fields.
R  — extract_signal_envelope: has_lookup_key() logic.
S  — AndroidExecutionSignalEnvelope: construction, defaults, to_dict().
T  — AndroidSignalReconcileOutcome: construction, defaults, is_accepted(),
     to_dict().
U  — reconcile_android_execution_signal: empty lookup keys → rejected.
V  — reconcile_android_execution_signal: no matching record → rejected.
W  — reconcile_android_execution_signal: ack signal → acknowledged phase.
X  — reconcile_android_execution_signal: progress signal → in_progress phase.
Y  — reconcile_android_execution_signal: partial_result → in_progress (not terminal).
Z  — reconcile_android_execution_signal: final_result → completed + result applied.
AA — reconcile_android_execution_signal: error → failed + result applied.
AB — reconcile_android_execution_signal: timeout → timed_out.
AC — reconcile_android_execution_signal: cancelled → cancelled.
AD — reconcile_android_execution_signal: terminal record → rejected unchanged.
AE — reconcile_android_execution_signal: contract_id lookup takes precedence.
AF — reconcile_android_execution_signal: session_id fallback when no contract_id.
AG — reconcile_android_execution_signal: was_updated=True when advanced.
AH — reconcile_android_execution_signal: was_updated=False when rejected.
AI — reconcile_android_execution_signal: identity fields preserved in tracker.
AJ — reconcile_android_execution_signal: result payload forwarded for final_result.
AK — reconcile_android_execution_signal: error_message forwarded for error.
AL — reconcile_android_execution_signal: custom runtime isolation.
AM — reconcile_inbound_message: convenience wrapper end-to-end.
AN — reconcile_inbound_message: no lookup key → not_updated.
AO — reconcile_inbound_message: task_result completed → reconciled.
AP — reconcile_inbound_message: goal_execution_result success → reconciled.
AQ — reconcile_inbound_message: error message → error signal reconciled.
AR — reconcile_inbound_message: task_progress → progress reconciled.
AS — core.runtime re-exports: all PR-13 symbols accessible from core.runtime.
AT — projection.py sentinel: ANDROID_EXECUTION_SIGNAL_RECONCILER_ALIGNED_PR13
     is present and not UNAVAILABLE.
AU — All 10 policy sentinels are non-empty strings.
AV — ANDROID_EXECUTION_SIGNAL_RECONCILER_PR13_SENTINEL contains 'package=13'.
AW — AndroidSignalKind.to_ack_signal: maps to AcknowledgmentSignal correctly.
AX — AndroidSignalKind.is_terminal: final_result/error/timeout/cancelled True.
AY — AndroidSignalKind.is_terminal: ack/progress/partial_result False.
AZ — reconcile: ack sequence increments across multiple signals.
BA — reconcile: full lifecycle ack→progress→final_result → completed phase.
BB — reconcile: error after progress → failed phase (terminal).
BC — reconcile: timeout after ack → timed_out phase (terminal).
BD — reconcile: cancelled after progress → cancelled phase (terminal).
BE — reconcile: signal after terminal record → was_updated=False.
BF — extract_signal_envelope: envelope_id is a UUID string.
BG — extract_signal_envelope: received_at is a float.
BH — reconcile: outcome.envelope contains original envelope.
BI — reconcile: outcome.record.result is set for final_result.
BJ — reconcile: outcome.record.result is set for error.
BK — reconcile: result success=True for final_result.
BL — reconcile: result success=False for error.
BM — reconcile: reject_reason empty on success.
BN — reconcile: reject_reason non-empty on miss.
BO — AndroidSignalKind.from_string: known value returns correct kind.
BP — AndroidSignalKind.from_string: unknown value returns progress.
BQ — AndroidSignalKind.from_string: None returns progress.
BR — normalize: parallel_result completed → final_result.
BS — normalize: task_assign → ack.
BT — normalize: task_result timeout → timeout.
BU — reconcile_inbound_message: task_end failed → error signal.
BV — reconcile_inbound_message: task_end cancelled → cancelled signal.
BW — reconcile: two separate sessions independent.
BX — reconcile: contract_id lookup when session_id also present but different record.
BY — reconcile: payload snapshot includes task_id and device_id.
BZ — reconcile: partial_result does not close record (is_active still True).
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

import pytest

from core.android_execution_signal_reconciler import (
    ANDROID_EXECUTION_SIGNAL_RECONCILER_AUTHORITY,
    ANDROID_EXECUTION_SIGNAL_RECONCILER_PR13_SENTINEL,
    RECONCILER_REQUIRES_CONTRACT_ID_OR_SESSION_ID_POLICY,
    RECONCILER_SIGNAL_MAPPING_IS_CANONICAL_POLICY,
    RECONCILER_TERMINAL_RECORD_BLOCKS_FURTHER_SIGNALS_POLICY,
    RECONCILER_IDENTITY_IS_PRESERVED_ACROSS_RECONCILE_POLICY,
    RECONCILER_UNKNOWN_SIGNAL_DEFAULTS_TO_PROGRESS_POLICY,
    RECONCILER_TASK_STATUS_MAPS_TO_ACK_SIGNAL_CANONICALLY_POLICY,
    RECONCILER_ERROR_SIGNAL_CLOSES_TRACKING_RECORD_POLICY,
    RECONCILER_TIMEOUT_SIGNAL_CLOSES_TRACKING_RECORD_POLICY,
    RECONCILER_CANCELLED_SIGNAL_CLOSES_TRACKING_RECORD_POLICY,
    RECONCILER_RESULT_PAYLOAD_IS_FORWARDED_TO_TRACKER_POLICY,
    AndroidSignalKind,
    AndroidExecutionSignalEnvelope,
    AndroidSignalReconcileOutcome,
    normalize_android_message_to_signal_kind,
    extract_signal_envelope,
    reconcile_android_execution_signal,
    reconcile_inbound_message,
)
from core.delegated_runtime_execution_tracker import (
    AcknowledgmentSignal,
    DelegatedExecutionPhase,
    DelegatedExecutionTrackingRuntime,
    create_execution_tracking_record,
    reset_execution_tracking_runtime,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALL_POLICIES = [
    RECONCILER_REQUIRES_CONTRACT_ID_OR_SESSION_ID_POLICY,
    RECONCILER_SIGNAL_MAPPING_IS_CANONICAL_POLICY,
    RECONCILER_TERMINAL_RECORD_BLOCKS_FURTHER_SIGNALS_POLICY,
    RECONCILER_IDENTITY_IS_PRESERVED_ACROSS_RECONCILE_POLICY,
    RECONCILER_UNKNOWN_SIGNAL_DEFAULTS_TO_PROGRESS_POLICY,
    RECONCILER_TASK_STATUS_MAPS_TO_ACK_SIGNAL_CANONICALLY_POLICY,
    RECONCILER_ERROR_SIGNAL_CLOSES_TRACKING_RECORD_POLICY,
    RECONCILER_TIMEOUT_SIGNAL_CLOSES_TRACKING_RECORD_POLICY,
    RECONCILER_CANCELLED_SIGNAL_CLOSES_TRACKING_RECORD_POLICY,
    RECONCILER_RESULT_PAYLOAD_IS_FORWARDED_TO_TRACKER_POLICY,
]


def _fresh_tracker_runtime() -> DelegatedExecutionTrackingRuntime:
    """Return a fresh isolated runtime (not the process singleton)."""
    return DelegatedExecutionTrackingRuntime()


def _make_tracking_record(
    *,
    session_id: str = "ses-001",
    contract_id: str = "ctr-001",
    device_id: str = "dev-001",
    trace_id: str = "trace-001",
    runtime: Optional[DelegatedExecutionTrackingRuntime] = None,
):
    rt = runtime or _fresh_tracker_runtime()
    return create_execution_tracking_record(
        session_id=session_id,
        contract_id=contract_id,
        device_id=device_id,
        trace_id=trace_id,
        source_runtime_posture="join_runtime",
        runtime=rt,
    ), rt


def _make_envelope(
    *,
    signal_kind: AndroidSignalKind = AndroidSignalKind.progress,
    contract_id: str = "ctr-001",
    session_id: str = "ses-001",
    device_id: str = "dev-001",
    trace_id: str = "trace-001",
    task_id: str = "task-001",
    payload: Optional[Dict[str, Any]] = None,
) -> AndroidExecutionSignalEnvelope:
    return AndroidExecutionSignalEnvelope(
        signal_kind=signal_kind,
        contract_id=contract_id,
        session_id=session_id,
        device_id=device_id,
        trace_id=trace_id,
        task_id=task_id,
        payload=payload or {},
    )


# ===========================================================================
# Group A — Authority / policy sentinel presence and correctness
# ===========================================================================


def test_A01_authority_sentinel_present():
    assert ANDROID_EXECUTION_SIGNAL_RECONCILER_AUTHORITY
    assert "PR13" in ANDROID_EXECUTION_SIGNAL_RECONCILER_AUTHORITY


def test_A02_pr13_sentinel_present():
    assert ANDROID_EXECUTION_SIGNAL_RECONCILER_PR13_SENTINEL
    assert "package=13" in ANDROID_EXECUTION_SIGNAL_RECONCILER_PR13_SENTINEL


# ===========================================================================
# Group B — AndroidSignalKind enum
# ===========================================================================


def test_B01_all_values_present():
    values = {k.value for k in AndroidSignalKind}
    assert values == {"ack", "progress", "partial_result", "final_result", "error", "timeout", "cancelled"}


def test_B02_from_string_known():
    assert AndroidSignalKind.from_string("error") == AndroidSignalKind.error


def test_B03_from_string_case_insensitive():
    assert AndroidSignalKind.from_string("FINAL_RESULT") == AndroidSignalKind.final_result


def test_B04_from_string_unknown_returns_progress():
    assert AndroidSignalKind.from_string("bogus") == AndroidSignalKind.progress


def test_B05_from_string_none_returns_progress():
    assert AndroidSignalKind.from_string(None) == AndroidSignalKind.progress  # type: ignore[arg-type]


# ===========================================================================
# Group C — normalize task_result mappings
# ===========================================================================


def test_C01_task_result_completed_is_final_result():
    assert normalize_android_message_to_signal_kind("task_result", "completed") == AndroidSignalKind.final_result


def test_C02_task_result_success_is_final_result():
    assert normalize_android_message_to_signal_kind("task_result", "success") == AndroidSignalKind.final_result


def test_C03_task_result_failed_is_error():
    assert normalize_android_message_to_signal_kind("task_result", "failed") == AndroidSignalKind.error


def test_C04_task_result_failure_is_error():
    assert normalize_android_message_to_signal_kind("task_result", "failure") == AndroidSignalKind.error


def test_C05_task_result_cancelled_is_cancelled():
    assert normalize_android_message_to_signal_kind("task_result", "cancelled") == AndroidSignalKind.cancelled


def test_C06_task_result_timeout_is_timeout():
    assert normalize_android_message_to_signal_kind("task_result", "timeout") == AndroidSignalKind.timeout


def test_C07_task_result_empty_status_is_final_result():
    assert normalize_android_message_to_signal_kind("task_result", "") == AndroidSignalKind.final_result


def test_C08_task_result_none_status_is_final_result():
    assert normalize_android_message_to_signal_kind("task_result", None) == AndroidSignalKind.final_result


# ===========================================================================
# Group D — normalize task_progress mappings
# ===========================================================================


def test_D01_task_progress_empty_is_progress():
    assert normalize_android_message_to_signal_kind("task_progress", "") == AndroidSignalKind.progress


def test_D02_task_progress_running_is_progress():
    assert normalize_android_message_to_signal_kind("task_progress", "running") == AndroidSignalKind.progress


def test_D03_task_progress_pending_is_ack():
    assert normalize_android_message_to_signal_kind("task_progress", "pending") == AndroidSignalKind.ack


def test_D04_task_progress_continue_is_progress():
    assert normalize_android_message_to_signal_kind("task_progress", "continue") == AndroidSignalKind.progress


# ===========================================================================
# Group E — normalize task_end mappings
# ===========================================================================


def test_E01_task_end_completed_is_final_result():
    assert normalize_android_message_to_signal_kind("task_end", "completed") == AndroidSignalKind.final_result


def test_E02_task_end_failed_is_error():
    assert normalize_android_message_to_signal_kind("task_end", "failed") == AndroidSignalKind.error


def test_E03_task_end_cancelled_is_cancelled():
    assert normalize_android_message_to_signal_kind("task_end", "cancelled") == AndroidSignalKind.cancelled


def test_E04_task_end_timeout_is_timeout():
    assert normalize_android_message_to_signal_kind("task_end", "timeout") == AndroidSignalKind.timeout


def test_E05_task_end_empty_is_final_result():
    assert normalize_android_message_to_signal_kind("task_end", "") == AndroidSignalKind.final_result


# ===========================================================================
# Group F — normalize goal_execution_result mappings
# ===========================================================================


def test_F01_goal_execution_result_completed_is_final_result():
    assert normalize_android_message_to_signal_kind("goal_execution_result", "completed") == AndroidSignalKind.final_result


def test_F02_goal_execution_result_success_is_final_result():
    assert normalize_android_message_to_signal_kind("goal_execution_result", "success") == AndroidSignalKind.final_result


def test_F03_goal_execution_result_true_is_final_result():
    assert normalize_android_message_to_signal_kind("goal_execution_result", "true") == AndroidSignalKind.final_result


def test_F04_goal_execution_result_failed_is_error():
    assert normalize_android_message_to_signal_kind("goal_execution_result", "failed") == AndroidSignalKind.error


def test_F05_goal_execution_result_false_is_error():
    assert normalize_android_message_to_signal_kind("goal_execution_result", "false") == AndroidSignalKind.error


def test_F06_goal_execution_result_cancelled_is_cancelled():
    assert normalize_android_message_to_signal_kind("goal_execution_result", "cancelled") == AndroidSignalKind.cancelled


def test_F07_goal_execution_result_empty_is_final_result():
    assert normalize_android_message_to_signal_kind("goal_execution_result", "") == AndroidSignalKind.final_result


# ===========================================================================
# Group G — normalize error mappings
# ===========================================================================


def test_G01_error_empty_is_error():
    assert normalize_android_message_to_signal_kind("error", "") == AndroidSignalKind.error


def test_G02_error_timeout_is_timeout():
    assert normalize_android_message_to_signal_kind("error", "timeout") == AndroidSignalKind.timeout


def test_G03_error_cancelled_is_cancelled():
    assert normalize_android_message_to_signal_kind("error", "cancelled") == AndroidSignalKind.cancelled


# ===========================================================================
# Group H — normalize agent_result / agent_status
# ===========================================================================


def test_H01_agent_result_success_is_final_result():
    assert normalize_android_message_to_signal_kind("agent_result", "success") == AndroidSignalKind.final_result


def test_H02_agent_result_failed_is_error():
    assert normalize_android_message_to_signal_kind("agent_result", "failed") == AndroidSignalKind.error


def test_H03_agent_status_running_is_progress():
    assert normalize_android_message_to_signal_kind("agent_status", "running") == AndroidSignalKind.progress


def test_H04_agent_status_pending_is_ack():
    assert normalize_android_message_to_signal_kind("agent_status", "pending") == AndroidSignalKind.ack


def test_H05_agent_status_completed_is_final_result():
    assert normalize_android_message_to_signal_kind("agent_status", "completed") == AndroidSignalKind.final_result


# ===========================================================================
# Group I — normalize unknown type defaults to progress
# ===========================================================================


def test_I01_unknown_type_defaults_to_progress():
    assert normalize_android_message_to_signal_kind("totally_unknown_type", "anything") == AndroidSignalKind.progress


def test_I02_empty_type_defaults_to_progress():
    assert normalize_android_message_to_signal_kind("", "completed") == AndroidSignalKind.progress


# ===========================================================================
# Group J — normalize case-insensitive
# ===========================================================================


def test_J01_type_uppercase_normalised():
    assert normalize_android_message_to_signal_kind("TASK_RESULT", "COMPLETED") == AndroidSignalKind.final_result


def test_J02_mixed_case_status():
    assert normalize_android_message_to_signal_kind("task_result", "Failed") == AndroidSignalKind.error


# ===========================================================================
# Group K — normalize None / empty inputs
# ===========================================================================


def test_K01_both_none_returns_progress():
    assert normalize_android_message_to_signal_kind(None, None) == AndroidSignalKind.progress  # type: ignore[arg-type]


def test_K02_none_type_returns_progress():
    assert normalize_android_message_to_signal_kind(None, "completed") == AndroidSignalKind.progress  # type: ignore[arg-type]


# ===========================================================================
# Group L — extract_signal_envelope: contract_id / session_id from payload
# ===========================================================================


def test_L01_contract_id_from_payload():
    msg = {"type": "task_result", "payload": {"contract_id": "ctr-x", "session_id": "ses-x"}}
    env = extract_signal_envelope(msg)
    assert env.contract_id == "ctr-x"
    assert env.session_id == "ses-x"


def test_L02_session_id_from_payload_runtime_session_id():
    msg = {"type": "task_progress", "payload": {"runtime_session_id": "rs-001"}}
    env = extract_signal_envelope(msg)
    assert env.session_id == "rs-001"


def test_L03_contract_id_from_top_level_fallback():
    msg = {"type": "task_result", "contract_id": "ctr-top", "payload": {}}
    env = extract_signal_envelope(msg)
    assert env.contract_id == "ctr-top"


def test_L04_session_id_from_top_level_fallback():
    msg = {"type": "task_result", "session_id": "ses-top", "payload": {}}
    env = extract_signal_envelope(msg)
    assert env.session_id == "ses-top"


def test_L05_payload_contract_id_takes_precedence_over_top_level():
    msg = {
        "type": "task_result",
        "contract_id": "ctr-top",
        "payload": {"contract_id": "ctr-payload"},
    }
    env = extract_signal_envelope(msg)
    assert env.contract_id == "ctr-payload"


# ===========================================================================
# Group M — extract_signal_envelope: device_id / task_id from top-level
# ===========================================================================


def test_M01_device_id_from_top_level():
    msg = {"type": "task_result", "device_id": "dev-A", "payload": {}}
    env = extract_signal_envelope(msg)
    assert env.device_id == "dev-A"


def test_M02_task_id_from_top_level():
    msg = {"type": "task_result", "task_id": "task-A", "payload": {}}
    env = extract_signal_envelope(msg)
    assert env.task_id == "task-A"


def test_M03_device_id_from_payload_fallback():
    msg = {"type": "task_result", "payload": {"device_id": "dev-B"}}
    env = extract_signal_envelope(msg)
    assert env.device_id == "dev-B"


def test_M04_top_level_device_id_takes_precedence():
    msg = {"type": "task_result", "device_id": "dev-top", "payload": {"device_id": "dev-payload"}}
    env = extract_signal_envelope(msg)
    assert env.device_id == "dev-top"


# ===========================================================================
# Group N — extract_signal_envelope: trace_id
# ===========================================================================


def test_N01_trace_id_from_payload():
    msg = {"type": "task_result", "payload": {"trace_id": "tr-001"}}
    env = extract_signal_envelope(msg)
    assert env.trace_id == "tr-001"


def test_N02_trace_id_from_top_level_fallback():
    msg = {"type": "task_result", "trace_id": "tr-top", "payload": {}}
    env = extract_signal_envelope(msg)
    assert env.trace_id == "tr-top"


# ===========================================================================
# Group O — extract_signal_envelope: status resolution order
# ===========================================================================


def test_O01_status_from_top_level():
    msg = {"type": "task_result", "status": "completed", "payload": {"status": "running"}}
    env = extract_signal_envelope(msg)
    # top-level status is used; task_result+completed = final_result
    assert env.signal_kind == AndroidSignalKind.final_result


def test_O02_status_from_payload_when_no_top_level():
    msg = {"type": "task_end", "payload": {"status": "cancelled"}}
    env = extract_signal_envelope(msg)
    assert env.signal_kind == AndroidSignalKind.cancelled


# ===========================================================================
# Group P — extract_signal_envelope: success field (bool)
# ===========================================================================


def test_P01_success_true_maps_to_final_result():
    msg = {"type": "goal_execution_result", "payload": {"success": True}}
    env = extract_signal_envelope(msg)
    assert env.signal_kind == AndroidSignalKind.final_result


def test_P02_success_false_maps_to_error():
    msg = {"type": "goal_execution_result", "payload": {"success": False}}
    env = extract_signal_envelope(msg)
    assert env.signal_kind == AndroidSignalKind.error


# ===========================================================================
# Group Q — extract_signal_envelope: payload snapshot
# ===========================================================================


def test_Q01_result_key_included_in_payload_snapshot():
    msg = {"type": "task_result", "payload": {"result": "output text", "session_id": "s1"}}
    env = extract_signal_envelope(msg)
    assert env.payload.get("result") == "output text"


def test_Q02_error_message_included_in_payload_snapshot():
    msg = {"type": "error", "payload": {"error_message": "crash!", "session_id": "s1"}}
    env = extract_signal_envelope(msg)
    assert env.payload.get("error_message") == "crash!"


# ===========================================================================
# Group R — extract_signal_envelope: has_lookup_key()
# ===========================================================================


def test_R01_has_lookup_key_with_contract_id():
    env = _make_envelope(contract_id="ctr-1", session_id="")
    assert env.has_lookup_key()


def test_R02_has_lookup_key_with_session_id():
    env = _make_envelope(contract_id="", session_id="ses-1")
    assert env.has_lookup_key()


def test_R03_no_lookup_key_when_both_empty():
    env = _make_envelope(contract_id="", session_id="")
    assert not env.has_lookup_key()


# ===========================================================================
# Group S — AndroidExecutionSignalEnvelope: construction, defaults, to_dict()
# ===========================================================================


def test_S01_default_signal_kind_is_progress():
    env = AndroidExecutionSignalEnvelope()
    assert env.signal_kind == AndroidSignalKind.progress


def test_S02_to_dict_contains_expected_keys():
    env = _make_envelope()
    d = env.to_dict()
    for k in ("signal_kind", "contract_id", "session_id", "device_id", "trace_id",
              "task_id", "payload", "envelope_id", "received_at"):
        assert k in d


def test_S03_envelope_id_is_uuid_string():
    env = _make_envelope()
    assert isinstance(env.envelope_id, str)
    uuid.UUID(env.envelope_id)  # raises if not valid UUID


def test_S04_received_at_is_float():
    env = _make_envelope()
    assert isinstance(env.received_at, float)


# ===========================================================================
# Group T — AndroidSignalReconcileOutcome: construction, defaults, is_accepted()
# ===========================================================================


def test_T01_default_was_updated_false():
    outcome = AndroidSignalReconcileOutcome()
    assert not outcome.was_updated


def test_T02_default_reject_reason_empty():
    outcome = AndroidSignalReconcileOutcome()
    assert outcome.reject_reason == ""


def test_T03_is_accepted_true_when_updated_no_reason():
    outcome = AndroidSignalReconcileOutcome(was_updated=True, reject_reason="")
    assert outcome.is_accepted()


def test_T04_is_accepted_false_when_not_updated():
    outcome = AndroidSignalReconcileOutcome(was_updated=False, reject_reason="")
    assert not outcome.is_accepted()


def test_T05_to_dict_contains_expected_keys():
    outcome = AndroidSignalReconcileOutcome(was_updated=False, reject_reason="test")
    d = outcome.to_dict()
    assert "was_updated" in d
    assert "reject_reason" in d


# ===========================================================================
# Group U — reconcile: empty lookup keys rejected
# ===========================================================================


def test_U01_empty_contract_and_session_rejected():
    rt = _fresh_tracker_runtime()
    env = _make_envelope(contract_id="", session_id="")
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert not outcome.was_updated
    assert "both are empty" in outcome.reject_reason


# ===========================================================================
# Group V — reconcile: no matching record rejected
# ===========================================================================


def test_V01_no_record_found_returns_not_updated():
    rt = _fresh_tracker_runtime()
    env = _make_envelope(contract_id="nonexistent-ctr", session_id="nonexistent-ses")
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert not outcome.was_updated
    assert "no tracking record found" in outcome.reject_reason


# ===========================================================================
# Group W — reconcile: ack signal → acknowledged
# ===========================================================================


def test_W01_ack_signal_advances_to_acknowledged():
    record, rt = _make_tracking_record()
    env = _make_envelope(signal_kind=AndroidSignalKind.ack, contract_id=record.identity.contract_id)
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.was_updated
    assert outcome.record.phase == DelegatedExecutionPhase.acknowledged


# ===========================================================================
# Group X — reconcile: progress signal → in_progress
# ===========================================================================


def test_X01_progress_signal_advances_to_in_progress():
    record, rt = _make_tracking_record()
    env = _make_envelope(signal_kind=AndroidSignalKind.progress, contract_id=record.identity.contract_id)
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.was_updated
    assert outcome.record.phase == DelegatedExecutionPhase.in_progress


# ===========================================================================
# Group Y — reconcile: partial_result → in_progress (not terminal)
# ===========================================================================


def test_Y01_partial_result_advances_to_in_progress_not_terminal():
    record, rt = _make_tracking_record()
    env = _make_envelope(signal_kind=AndroidSignalKind.partial_result, contract_id=record.identity.contract_id)
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.was_updated
    assert outcome.record.phase == DelegatedExecutionPhase.in_progress
    assert outcome.record.phase.is_active()


# ===========================================================================
# Group Z — reconcile: final_result → completed + result applied
# ===========================================================================


def test_Z01_final_result_advances_to_completed():
    record, rt = _make_tracking_record()
    env = _make_envelope(
        signal_kind=AndroidSignalKind.final_result,
        contract_id=record.identity.contract_id,
        payload={"result": "done"},
    )
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.was_updated
    assert outcome.record.phase == DelegatedExecutionPhase.completed


def test_Z02_final_result_sets_result_object():
    record, rt = _make_tracking_record()
    env = _make_envelope(signal_kind=AndroidSignalKind.final_result, contract_id=record.identity.contract_id)
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.record.result is not None
    assert outcome.record.result.success is True


# ===========================================================================
# Group AA — reconcile: error → failed + result applied
# ===========================================================================


def test_AA01_error_signal_advances_to_failed():
    record, rt = _make_tracking_record()
    env = _make_envelope(signal_kind=AndroidSignalKind.error, contract_id=record.identity.contract_id)
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.was_updated
    assert outcome.record.phase == DelegatedExecutionPhase.failed


def test_AA02_error_sets_result_with_success_false():
    record, rt = _make_tracking_record()
    env = _make_envelope(
        signal_kind=AndroidSignalKind.error,
        contract_id=record.identity.contract_id,
        payload={"error_message": "network error"},
    )
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.record.result is not None
    assert outcome.record.result.success is False
    assert outcome.record.result.error_detail == "network error"


# ===========================================================================
# Group AB — reconcile: timeout → timed_out
# ===========================================================================


def test_AB01_timeout_signal_advances_to_timed_out():
    record, rt = _make_tracking_record()
    env = _make_envelope(signal_kind=AndroidSignalKind.timeout, contract_id=record.identity.contract_id)
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.was_updated
    assert outcome.record.phase == DelegatedExecutionPhase.timed_out


# ===========================================================================
# Group AC — reconcile: cancelled → cancelled
# ===========================================================================


def test_AC01_cancelled_signal_advances_to_cancelled():
    record, rt = _make_tracking_record()
    env = _make_envelope(signal_kind=AndroidSignalKind.cancelled, contract_id=record.identity.contract_id)
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.was_updated
    assert outcome.record.phase == DelegatedExecutionPhase.cancelled


# ===========================================================================
# Group AD — reconcile: terminal record rejected unchanged
# ===========================================================================


def test_AD01_terminal_record_returned_unchanged():
    record, rt = _make_tracking_record()
    # advance to terminal
    env1 = _make_envelope(signal_kind=AndroidSignalKind.error, contract_id=record.identity.contract_id)
    outcome1 = reconcile_android_execution_signal(env1, runtime=rt)
    assert outcome1.record.phase == DelegatedExecutionPhase.failed

    # try to advance again
    env2 = _make_envelope(signal_kind=AndroidSignalKind.progress, contract_id=record.identity.contract_id)
    outcome2 = reconcile_android_execution_signal(env2, runtime=rt)
    assert not outcome2.was_updated
    assert "terminal" in outcome2.reject_reason


# ===========================================================================
# Group AE — reconcile: contract_id lookup takes precedence
# ===========================================================================


def test_AE01_contract_id_lookup_preferred_over_session_id():
    rt = _fresh_tracker_runtime()
    rec1, _ = _make_tracking_record(session_id="ses-A", contract_id="ctr-A", runtime=rt)
    rec2, _ = _make_tracking_record(session_id="ses-B", contract_id="ctr-B", runtime=rt)

    # envelope targets ctr-A by contract_id but uses session_id of B
    env = _make_envelope(signal_kind=AndroidSignalKind.ack, contract_id="ctr-A", session_id="ses-B")
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.was_updated
    # the record that was updated must have identity.contract_id == ctr-A
    assert outcome.record.identity.contract_id == "ctr-A"


# ===========================================================================
# Group AF — reconcile: session_id fallback
# ===========================================================================


def test_AF01_session_id_fallback_when_no_contract_id():
    record, rt = _make_tracking_record(session_id="ses-X", contract_id="ctr-X")
    env = _make_envelope(signal_kind=AndroidSignalKind.ack, contract_id="", session_id="ses-X")
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.was_updated
    assert outcome.record.identity.session_id == "ses-X"


# ===========================================================================
# Group AG — reconcile: was_updated=True when advanced
# ===========================================================================


def test_AG01_was_updated_true_on_advance():
    record, rt = _make_tracking_record()
    env = _make_envelope(signal_kind=AndroidSignalKind.ack, contract_id=record.identity.contract_id)
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.was_updated is True


# ===========================================================================
# Group AH — reconcile: was_updated=False when rejected
# ===========================================================================


def test_AH01_was_updated_false_on_miss():
    rt = _fresh_tracker_runtime()
    env = _make_envelope(contract_id="no-such-contract")
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.was_updated is False


# ===========================================================================
# Group AI — reconcile: identity fields preserved
# ===========================================================================


def test_AI01_identity_preserved_across_reconcile():
    record, rt = _make_tracking_record(
        session_id="ses-ID", contract_id="ctr-ID", device_id="dev-ID", trace_id="trace-ID"
    )
    env = _make_envelope(signal_kind=AndroidSignalKind.ack, contract_id="ctr-ID")
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.record.identity.session_id == "ses-ID"
    assert outcome.record.identity.contract_id == "ctr-ID"
    assert outcome.record.identity.device_id == "dev-ID"
    assert outcome.record.identity.trace_id == "trace-ID"


# ===========================================================================
# Group AJ — reconcile: result payload forwarded for final_result
# ===========================================================================


def test_AJ01_result_payload_forwarded():
    record, rt = _make_tracking_record()
    env = _make_envelope(
        signal_kind=AndroidSignalKind.final_result,
        contract_id=record.identity.contract_id,
        payload={"result": "my output"},
    )
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.record.result is not None
    assert outcome.record.result.result_payload.get("result") == "my output"


# ===========================================================================
# Group AK — reconcile: error_message forwarded for error
# ===========================================================================


def test_AK01_error_message_forwarded():
    record, rt = _make_tracking_record()
    env = _make_envelope(
        signal_kind=AndroidSignalKind.error,
        contract_id=record.identity.contract_id,
        payload={"error_message": "device crash"},
    )
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.record.result.error_detail == "device crash"


def test_AK02_error_detail_fallback_to_error_key():
    record, rt = _make_tracking_record()
    env = _make_envelope(
        signal_kind=AndroidSignalKind.error,
        contract_id=record.identity.contract_id,
        payload={"error": "generic error"},
    )
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.record.result.error_detail == "generic error"


# ===========================================================================
# Group AL — reconcile: custom runtime isolation
# ===========================================================================


def test_AL01_custom_runtime_isolated():
    rt1 = _fresh_tracker_runtime()
    rt2 = _fresh_tracker_runtime()
    record, _ = _make_tracking_record(runtime=rt1)
    env = _make_envelope(signal_kind=AndroidSignalKind.ack, contract_id=record.identity.contract_id)

    # reconcile against rt2 (different runtime — no record there)
    outcome = reconcile_android_execution_signal(env, runtime=rt2)
    assert not outcome.was_updated

    # reconcile against rt1 — should succeed
    outcome2 = reconcile_android_execution_signal(env, runtime=rt1)
    assert outcome2.was_updated


# ===========================================================================
# Group AM — reconcile_inbound_message: convenience wrapper end-to-end
# ===========================================================================


def test_AM01_convenience_wrapper_end_to_end():
    record, rt = _make_tracking_record(session_id="ses-e2e", contract_id="ctr-e2e")
    msg = {
        "type": "task_result",
        "status": "completed",
        "device_id": "dev-001",
        "payload": {"contract_id": "ctr-e2e", "session_id": "ses-e2e", "result": "done"},
    }
    outcome = reconcile_inbound_message(msg, runtime=rt)
    assert outcome.was_updated
    assert outcome.record.phase == DelegatedExecutionPhase.completed


# ===========================================================================
# Group AN — reconcile_inbound_message: no lookup key
# ===========================================================================


def test_AN01_no_lookup_key_not_updated():
    msg = {"type": "task_result", "status": "completed", "payload": {}}
    outcome = reconcile_inbound_message(msg)
    assert not outcome.was_updated


# ===========================================================================
# Group AO — reconcile_inbound_message: task_result completed
# ===========================================================================


def test_AO01_task_result_completed_reconciled():
    record, rt = _make_tracking_record()
    msg = {
        "type": "task_result",
        "status": "completed",
        "payload": {"contract_id": record.identity.contract_id},
    }
    outcome = reconcile_inbound_message(msg, runtime=rt)
    assert outcome.was_updated
    assert outcome.record.phase == DelegatedExecutionPhase.completed


# ===========================================================================
# Group AP — reconcile_inbound_message: goal_execution_result success
# ===========================================================================


def test_AP01_goal_execution_result_success_reconciled():
    record, rt = _make_tracking_record()
    msg = {
        "type": "goal_execution_result",
        "payload": {"contract_id": record.identity.contract_id, "success": True},
    }
    outcome = reconcile_inbound_message(msg, runtime=rt)
    assert outcome.was_updated
    assert outcome.record.phase == DelegatedExecutionPhase.completed


# ===========================================================================
# Group AQ — reconcile_inbound_message: error
# ===========================================================================


def test_AQ01_error_message_reconciled():
    record, rt = _make_tracking_record()
    msg = {
        "type": "error",
        "payload": {"contract_id": record.identity.contract_id, "error_message": "crash"},
    }
    outcome = reconcile_inbound_message(msg, runtime=rt)
    assert outcome.was_updated
    assert outcome.record.phase == DelegatedExecutionPhase.failed


# ===========================================================================
# Group AR — reconcile_inbound_message: task_progress
# ===========================================================================


def test_AR01_task_progress_reconciled():
    record, rt = _make_tracking_record()
    msg = {
        "type": "task_progress",
        "payload": {"session_id": record.identity.session_id, "progress": 50},
    }
    outcome = reconcile_inbound_message(msg, runtime=rt)
    assert outcome.was_updated
    assert outcome.record.phase == DelegatedExecutionPhase.in_progress


# ===========================================================================
# Group AS — core.runtime re-exports
# ===========================================================================


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("pydantic"),
    reason="pydantic not available",
)
def test_AS01_all_pr13_symbols_in_core_runtime():
    from core.runtime import (
        ANDROID_EXECUTION_SIGNAL_RECONCILER_AUTHORITY,
        ANDROID_EXECUTION_SIGNAL_RECONCILER_PR13_SENTINEL,
        AndroidSignalKind,
        AndroidExecutionSignalEnvelope,
        AndroidSignalReconcileOutcome,
        normalize_android_message_to_signal_kind,
        extract_signal_envelope,
        reconcile_android_execution_signal,
        reconcile_inbound_message,
    )
    assert ANDROID_EXECUTION_SIGNAL_RECONCILER_AUTHORITY
    assert ANDROID_EXECUTION_SIGNAL_RECONCILER_PR13_SENTINEL
    assert AndroidSignalKind is not None
    assert AndroidExecutionSignalEnvelope is not None
    assert AndroidSignalReconcileOutcome is not None


# ===========================================================================
# Group AT — projection.py sentinel
# ===========================================================================


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("fastapi"),
    reason="fastapi not available",
)
def test_AT01_projection_sentinel_present_and_not_unavailable():
    from core.routes.projection import ANDROID_EXECUTION_SIGNAL_RECONCILER_ALIGNED_PR13
    assert ANDROID_EXECUTION_SIGNAL_RECONCILER_ALIGNED_PR13
    assert "UNAVAILABLE" not in ANDROID_EXECUTION_SIGNAL_RECONCILER_ALIGNED_PR13


# ===========================================================================
# Group AU — All 10 policy sentinels non-empty
# ===========================================================================


def test_AU01_all_10_policy_sentinels_non_empty():
    assert len(_ALL_POLICIES) == 10
    for sentinel in _ALL_POLICIES:
        assert isinstance(sentinel, str)
        assert len(sentinel) > 0


# ===========================================================================
# Group AV — PR13 sentinel contains 'package=13'
# ===========================================================================


def test_AV01_pr13_sentinel_contains_package_13():
    assert "package=13" in ANDROID_EXECUTION_SIGNAL_RECONCILER_PR13_SENTINEL


# ===========================================================================
# Group AW — AndroidSignalKind.to_ack_signal maps correctly
# ===========================================================================


def test_AW01_ack_maps_to_ack_signal():
    assert AndroidSignalKind.ack.to_ack_signal() == AcknowledgmentSignal.ack


def test_AW02_progress_maps_to_progress_signal():
    assert AndroidSignalKind.progress.to_ack_signal() == AcknowledgmentSignal.progress


def test_AW03_partial_result_maps_to_partial_result_signal():
    assert AndroidSignalKind.partial_result.to_ack_signal() == AcknowledgmentSignal.partial_result


def test_AW04_final_result_maps_to_final_result_signal():
    assert AndroidSignalKind.final_result.to_ack_signal() == AcknowledgmentSignal.final_result


def test_AW05_error_maps_to_error_signal():
    assert AndroidSignalKind.error.to_ack_signal() == AcknowledgmentSignal.error


def test_AW06_timeout_maps_to_timeout_signal():
    assert AndroidSignalKind.timeout.to_ack_signal() == AcknowledgmentSignal.timeout


def test_AW07_cancelled_maps_to_cancelled_signal():
    assert AndroidSignalKind.cancelled.to_ack_signal() == AcknowledgmentSignal.cancelled


# ===========================================================================
# Group AX/AY — is_terminal()
# ===========================================================================


def test_AX01_final_result_is_terminal():
    assert AndroidSignalKind.final_result.is_terminal()


def test_AX02_error_is_terminal():
    assert AndroidSignalKind.error.is_terminal()


def test_AX03_timeout_is_terminal():
    assert AndroidSignalKind.timeout.is_terminal()


def test_AX04_cancelled_is_terminal():
    assert AndroidSignalKind.cancelled.is_terminal()


def test_AY01_ack_is_not_terminal():
    assert not AndroidSignalKind.ack.is_terminal()


def test_AY02_progress_is_not_terminal():
    assert not AndroidSignalKind.progress.is_terminal()


def test_AY03_partial_result_is_not_terminal():
    assert not AndroidSignalKind.partial_result.is_terminal()


# ===========================================================================
# Group AZ — ack sequence increments across multiple signals
# ===========================================================================


def test_AZ01_ack_sequence_increments():
    record, rt = _make_tracking_record()
    e1 = _make_envelope(signal_kind=AndroidSignalKind.ack, contract_id=record.identity.contract_id)
    o1 = reconcile_android_execution_signal(e1, runtime=rt)
    e2 = _make_envelope(signal_kind=AndroidSignalKind.progress, contract_id=record.identity.contract_id)
    o2 = reconcile_android_execution_signal(e2, runtime=rt)
    assert len(o2.record.acknowledgments) == 2
    assert o2.record.acknowledgments[0].sequence == 0
    assert o2.record.acknowledgments[1].sequence == 1


# ===========================================================================
# Group BA — full lifecycle ack→progress→final_result → completed
# ===========================================================================


def test_BA01_full_lifecycle_ack_progress_final_result():
    record, rt = _make_tracking_record()
    ctr = record.identity.contract_id

    o1 = reconcile_android_execution_signal(
        _make_envelope(signal_kind=AndroidSignalKind.ack, contract_id=ctr), runtime=rt
    )
    assert o1.record.phase == DelegatedExecutionPhase.acknowledged

    o2 = reconcile_android_execution_signal(
        _make_envelope(signal_kind=AndroidSignalKind.progress, contract_id=ctr), runtime=rt
    )
    assert o2.record.phase == DelegatedExecutionPhase.in_progress

    o3 = reconcile_android_execution_signal(
        _make_envelope(signal_kind=AndroidSignalKind.final_result, contract_id=ctr), runtime=rt
    )
    assert o3.record.phase == DelegatedExecutionPhase.completed
    assert o3.record.result.success is True


# ===========================================================================
# Group BB — error after progress → failed
# ===========================================================================


def test_BB01_error_after_progress_advances_to_failed():
    record, rt = _make_tracking_record()
    ctr = record.identity.contract_id
    reconcile_android_execution_signal(
        _make_envelope(signal_kind=AndroidSignalKind.progress, contract_id=ctr), runtime=rt
    )
    o2 = reconcile_android_execution_signal(
        _make_envelope(signal_kind=AndroidSignalKind.error, contract_id=ctr), runtime=rt
    )
    assert o2.record.phase == DelegatedExecutionPhase.failed


# ===========================================================================
# Group BC — timeout after ack → timed_out
# ===========================================================================


def test_BC01_timeout_after_ack_advances_to_timed_out():
    record, rt = _make_tracking_record()
    ctr = record.identity.contract_id
    reconcile_android_execution_signal(
        _make_envelope(signal_kind=AndroidSignalKind.ack, contract_id=ctr), runtime=rt
    )
    o2 = reconcile_android_execution_signal(
        _make_envelope(signal_kind=AndroidSignalKind.timeout, contract_id=ctr), runtime=rt
    )
    assert o2.record.phase == DelegatedExecutionPhase.timed_out


# ===========================================================================
# Group BD — cancelled after progress → cancelled
# ===========================================================================


def test_BD01_cancelled_after_progress_advances_to_cancelled():
    record, rt = _make_tracking_record()
    ctr = record.identity.contract_id
    reconcile_android_execution_signal(
        _make_envelope(signal_kind=AndroidSignalKind.progress, contract_id=ctr), runtime=rt
    )
    o2 = reconcile_android_execution_signal(
        _make_envelope(signal_kind=AndroidSignalKind.cancelled, contract_id=ctr), runtime=rt
    )
    assert o2.record.phase == DelegatedExecutionPhase.cancelled


# ===========================================================================
# Group BE — signal after terminal → was_updated=False
# ===========================================================================


def test_BE01_signal_after_terminal_not_updated():
    record, rt = _make_tracking_record()
    ctr = record.identity.contract_id
    reconcile_android_execution_signal(
        _make_envelope(signal_kind=AndroidSignalKind.final_result, contract_id=ctr), runtime=rt
    )
    outcome = reconcile_android_execution_signal(
        _make_envelope(signal_kind=AndroidSignalKind.ack, contract_id=ctr), runtime=rt
    )
    assert not outcome.was_updated


# ===========================================================================
# Group BF/BG — extract_signal_envelope: envelope_id, received_at
# ===========================================================================


def test_BF01_envelope_id_is_uuid():
    env = extract_signal_envelope({"type": "task_result", "payload": {}})
    uuid.UUID(env.envelope_id)


def test_BG01_received_at_is_recent():
    before = time.time()
    env = extract_signal_envelope({"type": "task_progress", "payload": {}})
    after = time.time()
    assert before <= env.received_at <= after


# ===========================================================================
# Group BH — outcome.envelope contains original envelope
# ===========================================================================


def test_BH01_outcome_envelope_is_set():
    record, rt = _make_tracking_record()
    env = _make_envelope(signal_kind=AndroidSignalKind.ack, contract_id=record.identity.contract_id)
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.envelope is env


# ===========================================================================
# Group BI/BJ/BK/BL — result fields
# ===========================================================================


def test_BI01_outcome_record_result_set_for_final_result():
    record, rt = _make_tracking_record()
    env = _make_envelope(signal_kind=AndroidSignalKind.final_result, contract_id=record.identity.contract_id)
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.record.result is not None


def test_BJ01_outcome_record_result_set_for_error():
    record, rt = _make_tracking_record()
    env = _make_envelope(signal_kind=AndroidSignalKind.error, contract_id=record.identity.contract_id)
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.record.result is not None


def test_BK01_result_success_true_for_final_result():
    record, rt = _make_tracking_record()
    env = _make_envelope(signal_kind=AndroidSignalKind.final_result, contract_id=record.identity.contract_id)
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.record.result.success is True


def test_BL01_result_success_false_for_error():
    record, rt = _make_tracking_record()
    env = _make_envelope(signal_kind=AndroidSignalKind.error, contract_id=record.identity.contract_id)
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.record.result.success is False


# ===========================================================================
# Group BM/BN — reject_reason
# ===========================================================================


def test_BM01_reject_reason_empty_on_success():
    record, rt = _make_tracking_record()
    env = _make_envelope(signal_kind=AndroidSignalKind.ack, contract_id=record.identity.contract_id)
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.reject_reason == ""


def test_BN01_reject_reason_non_empty_on_miss():
    rt = _fresh_tracker_runtime()
    env = _make_envelope(contract_id="no-such")
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.reject_reason != ""


# ===========================================================================
# Group BO/BP/BQ — from_string
# ===========================================================================


def test_BO01_from_string_known_value():
    assert AndroidSignalKind.from_string("timeout") == AndroidSignalKind.timeout


def test_BP01_from_string_unknown_returns_progress():
    assert AndroidSignalKind.from_string("xyz") == AndroidSignalKind.progress


def test_BQ01_from_string_none_returns_progress():
    assert AndroidSignalKind.from_string(None) == AndroidSignalKind.progress  # type: ignore[arg-type]


# ===========================================================================
# Group BR/BS/BT — edge case signal kinds
# ===========================================================================


def test_BR01_parallel_result_completed_is_final_result():
    assert normalize_android_message_to_signal_kind("parallel_result", "completed") == AndroidSignalKind.final_result


def test_BS01_task_assign_is_ack():
    assert normalize_android_message_to_signal_kind("task_assign", "") == AndroidSignalKind.ack


def test_BT01_task_result_timeout_is_timeout():
    assert normalize_android_message_to_signal_kind("task_result", "timeout") == AndroidSignalKind.timeout


# ===========================================================================
# Group BU/BV — task_end failed/cancelled via reconcile_inbound_message
# ===========================================================================


def test_BU01_task_end_failed_reconciled():
    record, rt = _make_tracking_record()
    msg = {
        "type": "task_end",
        "status": "failed",
        "payload": {"contract_id": record.identity.contract_id},
    }
    outcome = reconcile_inbound_message(msg, runtime=rt)
    assert outcome.was_updated
    assert outcome.record.phase == DelegatedExecutionPhase.failed


def test_BV01_task_end_cancelled_reconciled():
    record, rt = _make_tracking_record()
    msg = {
        "type": "task_end",
        "status": "cancelled",
        "payload": {"contract_id": record.identity.contract_id},
    }
    outcome = reconcile_inbound_message(msg, runtime=rt)
    assert outcome.was_updated
    assert outcome.record.phase == DelegatedExecutionPhase.cancelled


# ===========================================================================
# Group BW — two separate sessions independent
# ===========================================================================


def test_BW01_two_sessions_independent():
    rt = _fresh_tracker_runtime()
    r1, _ = _make_tracking_record(session_id="ses-1", contract_id="ctr-1", runtime=rt)
    r2, _ = _make_tracking_record(session_id="ses-2", contract_id="ctr-2", runtime=rt)

    e1 = _make_envelope(signal_kind=AndroidSignalKind.final_result, contract_id="ctr-1")
    o1 = reconcile_android_execution_signal(e1, runtime=rt)

    e2 = _make_envelope(signal_kind=AndroidSignalKind.ack, contract_id="ctr-2")
    o2 = reconcile_android_execution_signal(e2, runtime=rt)

    assert o1.record.phase == DelegatedExecutionPhase.completed
    assert o2.record.phase == DelegatedExecutionPhase.acknowledged


# ===========================================================================
# Group BX — contract_id lookup when session also present
# ===========================================================================


def test_BX01_contract_id_lookup_with_both_present():
    rt = _fresh_tracker_runtime()
    rec, _ = _make_tracking_record(session_id="ses-both", contract_id="ctr-both", runtime=rt)
    env = _make_envelope(
        signal_kind=AndroidSignalKind.progress,
        contract_id="ctr-both",
        session_id="ses-both",
    )
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.was_updated
    assert outcome.record.identity.contract_id == "ctr-both"


# ===========================================================================
# Group BY — payload snapshot includes task_id and device_id
# ===========================================================================


def test_BY01_payload_snapshot_includes_task_and_device_id():
    msg = {
        "type": "task_result",
        "task_id": "t-123",
        "device_id": "d-456",
        "payload": {"session_id": "s-789"},
    }
    env = extract_signal_envelope(msg)
    assert env.payload.get("task_id") == "t-123"
    assert env.payload.get("device_id") == "d-456"


# ===========================================================================
# Group BZ — partial_result does not close record
# ===========================================================================


def test_BZ01_partial_result_does_not_close_record():
    record, rt = _make_tracking_record()
    env = _make_envelope(
        signal_kind=AndroidSignalKind.partial_result,
        contract_id=record.identity.contract_id,
        payload={"partial": True},
    )
    outcome = reconcile_android_execution_signal(env, runtime=rt)
    assert outcome.was_updated
    assert outcome.record.phase.is_active()
    assert outcome.record.result is None  # no result applied for partial_result
