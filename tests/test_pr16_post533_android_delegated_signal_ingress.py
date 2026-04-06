"""tests/test_pr16_post533_android_delegated_signal_ingress.py
===============================================================
Tests for PR package 16 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical Ingress Path for Android Delegated Execution
Signals.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — DelegatedSignalKind enum: all values, from_string(), is_terminal(),
     defaults.
C  — ResultKind enum: all values, from_string(), defaults.
D  — _resolve_android_signal_kind: all (DelegatedSignalKind, ResultKind) pairs.
E  — DelegatedExecutionSignalEnvelope: construction, defaults, has_lookup_key(),
     resolved_android_signal_kind, to_dict(), to_android_execution_signal_envelope().
F  — extract_delegated_signal_envelope: contract_id / session_id from payload.
G  — extract_delegated_signal_envelope: device_id / task_id from top-level.
H  — extract_delegated_signal_envelope: signal_kind / result_kind from payload.
I  — extract_delegated_signal_envelope: signal_id extraction.
J  — extract_delegated_signal_envelope: emission_seq extraction (int coercion).
K  — extract_delegated_signal_envelope: trace_id from payload then top-level.
L  — extract_delegated_signal_envelope: payload snapshot content.
M  — extract_delegated_signal_envelope: has_lookup_key() correct on result.
N  — ingest_delegated_execution_signal: no matching record → not updated.
O  — ingest_delegated_execution_signal: ack signal → acknowledged phase.
P  — ingest_delegated_execution_signal: progress signal → in_progress phase.
Q  — ingest_delegated_execution_signal: result/success → completed phase.
R  — ingest_delegated_execution_signal: result/failure → failed phase.
S  — ingest_delegated_execution_signal: timeout → timed_out phase.
T  — ingest_delegated_execution_signal: cancelled → cancelled phase.
U  — ingest_delegated_execution_signal: missing lookup key → rejected.
V  — ingest_delegated_execution_signal: terminal record → not updated.
W  — ingest_delegated_execution_signal: signal_id preserved in outcome envelope.
X  — ingest_delegated_execution_signal: emission_seq preserved in outcome envelope.
Y  — ingest_delegated_execution_signal: result_kind preserved in outcome envelope.
Z  — Integration: full lifecycle ack → progress → result/success → completed.
AA — Integration: ack → progress → result/failure → failed.
AB — Integration: ack → timeout → timed_out (terminal).
AC — Integration: ack → cancelled → cancelled (terminal).
AD — Integration: signal after terminal record → was_updated=False.
AE — Integration: contract_id lookup priority over session_id.
AF — Integration: session_id fallback when no contract_id.
AG — core.runtime re-exports: all PR-16 symbols accessible from core.runtime.
AH — projection.py sentinel: ANDROID_DELEGATED_SIGNAL_INGRESS_ALIGNED_PR16
     present and not UNAVAILABLE.
AI — All 10 policy sentinels are non-empty strings.
AJ — ANDROID_DELEGATED_SIGNAL_INGRESS_PR16_SENTINEL contains 'package=16'.
AK — DelegatedExecutionSignalEnvelope: envelope_id is a UUID string.
AL — DelegatedExecutionSignalEnvelope: received_at is a float.
AM — ingest_delegated_execution_signal: was_updated=True on successful reconcile.
AN — ingest_delegated_execution_signal: outcome.record.result set for result/success.
AO — ingest_delegated_execution_signal: outcome.record.result set for result/failure.
AP — extract_delegated_signal_envelope: emission_seq defaults to 0 when absent.
AQ — extract_delegated_signal_envelope: emission_seq defaults to 0 for bad value.
AR — extract_delegated_signal_envelope: signal_id defaults to empty when absent.
AS — extract_delegated_signal_envelope: result_kind defaults to unknown when absent.
AT — MessageType.DELEGATED_EXECUTION_SIGNAL present in aip_v3 enum.
AU — DelegatedSignalKind.from_string: case-insensitive.
AV — DelegatedSignalKind.from_string: non-string → progress.
AW — ResultKind.from_string: case-insensitive.
AX — extract_delegated_signal_envelope: session_id from runtime_session_id fallback.
AY — ingest_delegated_execution_signal: result/unknown → completed (optimistic).
AZ — Integration: two separate sessions are independent.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

import pytest

from core.android_delegated_signal_ingress import (
    ANDROID_DELEGATED_SIGNAL_INGRESS_AUTHORITY,
    ANDROID_DELEGATED_SIGNAL_INGRESS_PR16_SENTINEL,
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
    DelegatedSignalKind,
    ResultKind,
    DelegatedExecutionSignalEnvelope,
    extract_delegated_signal_envelope,
    ingest_delegated_execution_signal,
)
from core.android_execution_signal_reconciler import AndroidSignalKind
from core.delegated_runtime_execution_tracker import (
    DelegatedExecutionPhase,
    DelegatedExecutionTrackingRuntime,
    create_execution_tracking_record,
    reset_execution_tracking_runtime,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALL_POLICIES = [
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
]


def _fresh_runtime() -> DelegatedExecutionTrackingRuntime:
    """Return a fresh isolated runtime (not the process singleton)."""
    return DelegatedExecutionTrackingRuntime()


def _make_tracking_record(
    *,
    session_id: str = "ses-pr16-001",
    contract_id: str = "ctr-pr16-001",
    device_id: str = "dev-pr16-001",
    trace_id: str = "trace-pr16-001",
    runtime: Optional[DelegatedExecutionTrackingRuntime] = None,
):
    rt = runtime or _fresh_runtime()
    return create_execution_tracking_record(
        session_id=session_id,
        contract_id=contract_id,
        device_id=device_id,
        trace_id=trace_id,
        source_runtime_posture="join_runtime",
        runtime=rt,
    ), rt


def _make_delegated_signal_message(
    *,
    device_id: str = "dev-pr16-001",
    task_id: str = "task-pr16-001",
    contract_id: str = "ctr-pr16-001",
    session_id: str = "ses-pr16-001",
    trace_id: str = "trace-pr16-001",
    signal_kind: str = "progress",
    result_kind: str = "",
    signal_id: str = "",
    emission_seq: int = 1,
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
# Group A — Authority / policy sentinel presence and correctness
# ===========================================================================


def test_A01_authority_sentinel_present():
    assert ANDROID_DELEGATED_SIGNAL_INGRESS_AUTHORITY
    assert "PR16" in ANDROID_DELEGATED_SIGNAL_INGRESS_AUTHORITY


def test_A02_authority_sentinel_contains_canonical_ingress():
    assert "canonical-ingress" in ANDROID_DELEGATED_SIGNAL_INGRESS_AUTHORITY


# ===========================================================================
# Group B — DelegatedSignalKind enum
# ===========================================================================


def test_B01_delegated_signal_kind_values():
    assert DelegatedSignalKind.ack.value == "ack"
    assert DelegatedSignalKind.progress.value == "progress"
    assert DelegatedSignalKind.result.value == "result"
    assert DelegatedSignalKind.timeout.value == "timeout"
    assert DelegatedSignalKind.cancelled.value == "cancelled"


def test_B02_delegated_signal_kind_from_string_known():
    assert DelegatedSignalKind.from_string("ack") == DelegatedSignalKind.ack
    assert DelegatedSignalKind.from_string("progress") == DelegatedSignalKind.progress
    assert DelegatedSignalKind.from_string("result") == DelegatedSignalKind.result
    assert DelegatedSignalKind.from_string("timeout") == DelegatedSignalKind.timeout
    assert DelegatedSignalKind.from_string("cancelled") == DelegatedSignalKind.cancelled


def test_B03_delegated_signal_kind_from_string_unknown_defaults_to_progress():
    assert DelegatedSignalKind.from_string("unknown_xyz") == DelegatedSignalKind.progress
    assert DelegatedSignalKind.from_string("") == DelegatedSignalKind.progress


def test_B04_delegated_signal_kind_from_string_non_string():
    assert DelegatedSignalKind.from_string(None) == DelegatedSignalKind.progress  # type: ignore[arg-type]
    assert DelegatedSignalKind.from_string(42) == DelegatedSignalKind.progress  # type: ignore[arg-type]


def test_B05_is_terminal_result_timeout_cancelled():
    assert DelegatedSignalKind.result.is_terminal() is True
    assert DelegatedSignalKind.timeout.is_terminal() is True
    assert DelegatedSignalKind.cancelled.is_terminal() is True


def test_B06_is_terminal_ack_progress_not_terminal():
    assert DelegatedSignalKind.ack.is_terminal() is False
    assert DelegatedSignalKind.progress.is_terminal() is False


# ===========================================================================
# Group C — ResultKind enum
# ===========================================================================


def test_C01_result_kind_values():
    assert ResultKind.success.value == "success"
    assert ResultKind.failure.value == "failure"
    assert ResultKind.unknown.value == "unknown"


def test_C02_result_kind_from_string_known():
    assert ResultKind.from_string("success") == ResultKind.success
    assert ResultKind.from_string("failure") == ResultKind.failure
    assert ResultKind.from_string("unknown") == ResultKind.unknown


def test_C03_result_kind_from_string_unknown_defaults_to_unknown():
    assert ResultKind.from_string("xyz") == ResultKind.unknown
    assert ResultKind.from_string("") == ResultKind.unknown


def test_C04_result_kind_from_string_non_string():
    assert ResultKind.from_string(None) == ResultKind.unknown  # type: ignore[arg-type]


# ===========================================================================
# Group D — _resolve_android_signal_kind mapping
# ===========================================================================


def test_D01_ack_maps_to_android_ack():
    env = DelegatedExecutionSignalEnvelope(signal_kind=DelegatedSignalKind.ack)
    assert env.resolved_android_signal_kind == AndroidSignalKind.ack


def test_D02_progress_maps_to_android_progress():
    env = DelegatedExecutionSignalEnvelope(signal_kind=DelegatedSignalKind.progress)
    assert env.resolved_android_signal_kind == AndroidSignalKind.progress


def test_D03_result_success_maps_to_final_result():
    env = DelegatedExecutionSignalEnvelope(
        signal_kind=DelegatedSignalKind.result,
        result_kind=ResultKind.success,
    )
    assert env.resolved_android_signal_kind == AndroidSignalKind.final_result


def test_D04_result_failure_maps_to_error():
    env = DelegatedExecutionSignalEnvelope(
        signal_kind=DelegatedSignalKind.result,
        result_kind=ResultKind.failure,
    )
    assert env.resolved_android_signal_kind == AndroidSignalKind.error


def test_D05_result_unknown_maps_to_final_result_optimistic():
    env = DelegatedExecutionSignalEnvelope(
        signal_kind=DelegatedSignalKind.result,
        result_kind=ResultKind.unknown,
    )
    assert env.resolved_android_signal_kind == AndroidSignalKind.final_result


def test_D06_timeout_maps_to_android_timeout():
    env = DelegatedExecutionSignalEnvelope(signal_kind=DelegatedSignalKind.timeout)
    assert env.resolved_android_signal_kind == AndroidSignalKind.timeout


def test_D07_cancelled_maps_to_android_cancelled():
    env = DelegatedExecutionSignalEnvelope(signal_kind=DelegatedSignalKind.cancelled)
    assert env.resolved_android_signal_kind == AndroidSignalKind.cancelled


# ===========================================================================
# Group E — DelegatedExecutionSignalEnvelope
# ===========================================================================


def test_E01_defaults():
    env = DelegatedExecutionSignalEnvelope()
    assert env.signal_kind == DelegatedSignalKind.progress
    assert env.result_kind == ResultKind.unknown
    assert env.contract_id == ""
    assert env.session_id == ""
    assert env.device_id == ""
    assert env.trace_id == ""
    assert env.task_id == ""
    assert env.signal_id == ""
    assert env.emission_seq == 0
    assert isinstance(env.payload, dict)
    assert isinstance(env.envelope_id, str)
    assert isinstance(env.received_at, float)


def test_E02_has_lookup_key_with_contract_id():
    env = DelegatedExecutionSignalEnvelope(contract_id="ctr-001")
    assert env.has_lookup_key() is True


def test_E03_has_lookup_key_with_session_id():
    env = DelegatedExecutionSignalEnvelope(session_id="ses-001")
    assert env.has_lookup_key() is True


def test_E04_has_lookup_key_both_empty():
    env = DelegatedExecutionSignalEnvelope()
    assert env.has_lookup_key() is False


def test_E05_to_dict_contains_all_fields():
    sig_id = str(uuid.uuid4())
    env = DelegatedExecutionSignalEnvelope(
        signal_kind=DelegatedSignalKind.result,
        result_kind=ResultKind.success,
        contract_id="ctr-001",
        session_id="ses-001",
        device_id="dev-001",
        trace_id="trace-001",
        task_id="task-001",
        signal_id=sig_id,
        emission_seq=5,
    )
    d = env.to_dict()
    assert d["signal_kind"] == "result"
    assert d["result_kind"] == "success"
    assert d["contract_id"] == "ctr-001"
    assert d["session_id"] == "ses-001"
    assert d["device_id"] == "dev-001"
    assert d["trace_id"] == "trace-001"
    assert d["task_id"] == "task-001"
    assert d["signal_id"] == sig_id
    assert d["emission_seq"] == 5
    assert d["resolved_android_signal_kind"] == "final_result"


def test_E06_to_android_execution_signal_envelope_sets_signal_kind():
    env = DelegatedExecutionSignalEnvelope(
        signal_kind=DelegatedSignalKind.result,
        result_kind=ResultKind.success,
        contract_id="ctr-001",
        session_id="ses-001",
    )
    ae = env.to_android_execution_signal_envelope()
    assert ae.signal_kind == AndroidSignalKind.final_result
    assert ae.contract_id == "ctr-001"
    assert ae.session_id == "ses-001"


def test_E07_to_android_execution_signal_envelope_propagates_signal_id():
    sig_id = str(uuid.uuid4())
    env = DelegatedExecutionSignalEnvelope(
        signal_kind=DelegatedSignalKind.ack,
        contract_id="ctr-001",
        signal_id=sig_id,
        emission_seq=3,
    )
    ae = env.to_android_execution_signal_envelope()
    assert ae.signal_id == sig_id
    assert ae.emission_seq == 3


# ===========================================================================
# Group F — extract_delegated_signal_envelope: contract_id / session_id
# ===========================================================================


def test_F01_contract_id_from_payload():
    msg = _make_delegated_signal_message(contract_id="ctr-payload")
    env = extract_delegated_signal_envelope(msg)
    assert env.contract_id == "ctr-payload"


def test_F02_session_id_from_payload():
    msg = _make_delegated_signal_message(session_id="ses-payload")
    env = extract_delegated_signal_envelope(msg)
    assert env.session_id == "ses-payload"


def test_F03_contract_id_fallback_to_top_level():
    msg = {
        "type": "delegated_execution_signal",
        "device_id": "dev-001",
        "task_id": "task-001",
        "contract_id": "ctr-top",
        "payload": {},
    }
    env = extract_delegated_signal_envelope(msg)
    assert env.contract_id == "ctr-top"


def test_F04_session_id_from_runtime_session_id_payload():
    msg = {
        "type": "delegated_execution_signal",
        "device_id": "dev-001",
        "task_id": "task-001",
        "payload": {"runtime_session_id": "rses-001"},
    }
    env = extract_delegated_signal_envelope(msg)
    assert env.session_id == "rses-001"


# ===========================================================================
# Group G — extract_delegated_signal_envelope: device_id / task_id
# ===========================================================================


def test_G01_device_id_from_top_level():
    msg = _make_delegated_signal_message(device_id="dev-top")
    env = extract_delegated_signal_envelope(msg)
    assert env.device_id == "dev-top"


def test_G02_device_id_fallback_to_payload():
    msg = {
        "type": "delegated_execution_signal",
        "task_id": "task-001",
        "payload": {
            "device_id": "dev-payload",
            "contract_id": "ctr-001",
            "session_id": "ses-001",
            "signal_kind": "ack",
        },
    }
    env = extract_delegated_signal_envelope(msg)
    assert env.device_id == "dev-payload"


def test_G03_task_id_from_top_level():
    msg = _make_delegated_signal_message(task_id="task-top")
    env = extract_delegated_signal_envelope(msg)
    assert env.task_id == "task-top"


# ===========================================================================
# Group H — extract_delegated_signal_envelope: signal_kind / result_kind
# ===========================================================================


def test_H01_signal_kind_ack_from_payload():
    msg = _make_delegated_signal_message(signal_kind="ack")
    env = extract_delegated_signal_envelope(msg)
    assert env.signal_kind == DelegatedSignalKind.ack


def test_H02_signal_kind_progress_from_payload():
    msg = _make_delegated_signal_message(signal_kind="progress")
    env = extract_delegated_signal_envelope(msg)
    assert env.signal_kind == DelegatedSignalKind.progress


def test_H03_signal_kind_result_from_payload():
    msg = _make_delegated_signal_message(signal_kind="result", result_kind="success")
    env = extract_delegated_signal_envelope(msg)
    assert env.signal_kind == DelegatedSignalKind.result
    assert env.result_kind == ResultKind.success


def test_H04_signal_kind_timeout_from_payload():
    msg = _make_delegated_signal_message(signal_kind="timeout")
    env = extract_delegated_signal_envelope(msg)
    assert env.signal_kind == DelegatedSignalKind.timeout


def test_H05_signal_kind_cancelled_from_payload():
    msg = _make_delegated_signal_message(signal_kind="cancelled")
    env = extract_delegated_signal_envelope(msg)
    assert env.signal_kind == DelegatedSignalKind.cancelled


def test_H06_result_kind_failure():
    msg = _make_delegated_signal_message(signal_kind="result", result_kind="failure")
    env = extract_delegated_signal_envelope(msg)
    assert env.result_kind == ResultKind.failure


def test_H07_result_kind_absent_defaults_to_unknown():
    msg = _make_delegated_signal_message(signal_kind="result")
    env = extract_delegated_signal_envelope(msg)
    assert env.result_kind == ResultKind.unknown


# ===========================================================================
# Group I — extract_delegated_signal_envelope: signal_id
# ===========================================================================


def test_I01_signal_id_from_payload():
    sig_id = str(uuid.uuid4())
    msg = _make_delegated_signal_message(signal_id=sig_id)
    env = extract_delegated_signal_envelope(msg)
    assert env.signal_id == sig_id


def test_I02_signal_id_from_top_level():
    sig_id = str(uuid.uuid4())
    msg = {
        "type": "delegated_execution_signal",
        "device_id": "dev-001",
        "task_id": "task-001",
        "signal_id": sig_id,
        "payload": {
            "contract_id": "ctr-001",
            "session_id": "ses-001",
            "signal_kind": "ack",
            "emission_seq": 1,
        },
    }
    env = extract_delegated_signal_envelope(msg)
    assert env.signal_id == sig_id


# ===========================================================================
# Group J — extract_delegated_signal_envelope: emission_seq
# ===========================================================================


def test_J01_emission_seq_from_payload():
    msg = _make_delegated_signal_message(emission_seq=7)
    env = extract_delegated_signal_envelope(msg)
    assert env.emission_seq == 7


def test_J02_emission_seq_coerced_from_string():
    msg = _make_delegated_signal_message()
    msg["payload"]["emission_seq"] = "3"
    env = extract_delegated_signal_envelope(msg)
    assert env.emission_seq == 3


def test_J03_emission_seq_defaults_to_zero_when_absent():
    msg = _make_delegated_signal_message()
    del msg["payload"]["emission_seq"]
    env = extract_delegated_signal_envelope(msg)
    assert env.emission_seq == 0


def test_J04_emission_seq_defaults_to_zero_for_bad_value():
    msg = _make_delegated_signal_message()
    msg["payload"]["emission_seq"] = "not_a_number"
    env = extract_delegated_signal_envelope(msg)
    assert env.emission_seq == 0


# ===========================================================================
# Group K — extract_delegated_signal_envelope: trace_id
# ===========================================================================


def test_K01_trace_id_from_payload():
    msg = _make_delegated_signal_message(trace_id="trace-payload")
    env = extract_delegated_signal_envelope(msg)
    assert env.trace_id == "trace-payload"


def test_K02_trace_id_fallback_to_top_level():
    msg = {
        "type": "delegated_execution_signal",
        "device_id": "dev-001",
        "task_id": "task-001",
        "trace_id": "trace-top",
        "payload": {
            "contract_id": "ctr-001",
            "session_id": "ses-001",
            "signal_kind": "ack",
            "emission_seq": 1,
        },
    }
    env = extract_delegated_signal_envelope(msg)
    assert env.trace_id == "trace-top"


# ===========================================================================
# Group L — extract_delegated_signal_envelope: payload snapshot
# ===========================================================================


def test_L01_payload_snapshot_includes_result():
    msg = _make_delegated_signal_message(
        signal_kind="result",
        result_kind="success",
        extra_payload={"result": "execution output"},
    )
    env = extract_delegated_signal_envelope(msg)
    assert env.payload.get("result") == "execution output"


def test_L02_payload_snapshot_includes_error_message():
    msg = _make_delegated_signal_message(
        signal_kind="result",
        result_kind="failure",
        extra_payload={"error_message": "execution failed"},
    )
    env = extract_delegated_signal_envelope(msg)
    assert env.payload.get("error_message") == "execution failed"


def test_L03_payload_snapshot_includes_task_id_and_device_id():
    msg = _make_delegated_signal_message()
    env = extract_delegated_signal_envelope(msg)
    assert env.payload.get("task_id") == "task-pr16-001"
    assert env.payload.get("device_id") == "dev-pr16-001"


# ===========================================================================
# Group M — extract_delegated_signal_envelope: has_lookup_key
# ===========================================================================


def test_M01_has_lookup_key_with_contract_id():
    msg = _make_delegated_signal_message(contract_id="ctr-001")
    env = extract_delegated_signal_envelope(msg)
    assert env.has_lookup_key() is True


def test_M02_has_lookup_key_no_lookup_keys():
    msg = {
        "type": "delegated_execution_signal",
        "device_id": "dev-001",
        "task_id": "task-001",
        "payload": {"signal_kind": "ack", "emission_seq": 1},
    }
    env = extract_delegated_signal_envelope(msg)
    assert env.has_lookup_key() is False


# ===========================================================================
# Group N — ingest_delegated_execution_signal: no matching record
# ===========================================================================


def test_N01_no_matching_record_returns_not_updated():
    rt = _fresh_runtime()
    msg = _make_delegated_signal_message(signal_kind="ack")
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.was_updated is False
    assert outcome.reject_reason


def test_N02_no_lookup_key_returns_not_updated():
    rt = _fresh_runtime()
    msg = {
        "type": "delegated_execution_signal",
        "device_id": "dev-001",
        "payload": {"signal_kind": "ack"},
    }
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.was_updated is False


# ===========================================================================
# Group O — ingest: ack signal → acknowledged phase
# ===========================================================================


def test_O01_ack_signal_advances_to_acknowledged():
    record, rt = _make_tracking_record()
    msg = _make_delegated_signal_message(signal_kind="ack")
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.was_updated is True
    assert outcome.record is not None
    assert outcome.record.phase == DelegatedExecutionPhase.acknowledged


# ===========================================================================
# Group P — ingest: progress signal → in_progress phase
# ===========================================================================


def test_P01_progress_signal_advances_to_in_progress():
    record, rt = _make_tracking_record()
    msg = _make_delegated_signal_message(signal_kind="progress")
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.was_updated is True
    assert outcome.record is not None
    assert outcome.record.phase == DelegatedExecutionPhase.in_progress


# ===========================================================================
# Group Q — ingest: result/success → completed phase
# ===========================================================================


def test_Q01_result_success_advances_to_completed():
    record, rt = _make_tracking_record()
    msg = _make_delegated_signal_message(
        signal_kind="result",
        result_kind="success",
        extra_payload={"result": "done"},
    )
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.was_updated is True
    assert outcome.record is not None
    assert outcome.record.phase == DelegatedExecutionPhase.completed


def test_Q02_result_success_sets_result_on_record():
    record, rt = _make_tracking_record()
    msg = _make_delegated_signal_message(
        signal_kind="result",
        result_kind="success",
    )
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.record is not None
    assert outcome.record.result is not None
    assert outcome.record.result.success is True


# ===========================================================================
# Group R — ingest: result/failure → failed phase
# ===========================================================================


def test_R01_result_failure_advances_to_failed():
    record, rt = _make_tracking_record()
    msg = _make_delegated_signal_message(
        signal_kind="result",
        result_kind="failure",
        extra_payload={"error_message": "something went wrong"},
    )
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.was_updated is True
    assert outcome.record is not None
    assert outcome.record.phase == DelegatedExecutionPhase.failed


def test_R02_result_failure_sets_result_on_record():
    record, rt = _make_tracking_record()
    msg = _make_delegated_signal_message(
        signal_kind="result",
        result_kind="failure",
    )
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.record is not None
    assert outcome.record.result is not None
    assert outcome.record.result.success is False


# ===========================================================================
# Group S — ingest: timeout → timed_out phase
# ===========================================================================


def test_S01_timeout_advances_to_timed_out():
    record, rt = _make_tracking_record()
    msg = _make_delegated_signal_message(signal_kind="timeout")
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.was_updated is True
    assert outcome.record is not None
    assert outcome.record.phase == DelegatedExecutionPhase.timed_out


# ===========================================================================
# Group T — ingest: cancelled → cancelled phase
# ===========================================================================


def test_T01_cancelled_advances_to_cancelled():
    record, rt = _make_tracking_record()
    msg = _make_delegated_signal_message(signal_kind="cancelled")
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.was_updated is True
    assert outcome.record is not None
    assert outcome.record.phase == DelegatedExecutionPhase.cancelled


# ===========================================================================
# Group U — ingest: missing lookup key → rejected
# ===========================================================================


def test_U01_missing_lookup_key_rejected():
    _, rt = _make_tracking_record()
    msg = {
        "type": "delegated_execution_signal",
        "device_id": "dev-001",
        "payload": {"signal_kind": "ack", "emission_seq": 1},
    }
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.was_updated is False
    assert outcome.reject_reason


# ===========================================================================
# Group V — ingest: terminal record → not updated
# ===========================================================================


def test_V01_terminal_record_blocks_further_signals():
    record, rt = _make_tracking_record()
    # First advance to terminal
    msg_final = _make_delegated_signal_message(signal_kind="result", result_kind="success")
    outcome1 = ingest_delegated_execution_signal(msg_final, runtime=rt)
    assert outcome1.record is not None
    assert outcome1.record.phase == DelegatedExecutionPhase.completed
    # Now send another signal — should be blocked
    msg_progress = _make_delegated_signal_message(signal_kind="progress")
    outcome2 = ingest_delegated_execution_signal(msg_progress, runtime=rt)
    assert outcome2.was_updated is False
    assert outcome2.record is not None
    assert outcome2.record.phase == DelegatedExecutionPhase.completed


# ===========================================================================
# Group W — ingest: signal_id preserved in outcome envelope
# ===========================================================================


def test_W01_signal_id_preserved_in_converted_envelope():
    record, rt = _make_tracking_record()
    sig_id = str(uuid.uuid4())
    msg = _make_delegated_signal_message(signal_kind="ack", signal_id=sig_id)
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.envelope is not None
    assert outcome.envelope.signal_id == sig_id


# ===========================================================================
# Group X — ingest: emission_seq preserved in outcome envelope
# ===========================================================================


def test_X01_emission_seq_preserved_in_converted_envelope():
    record, rt = _make_tracking_record()
    msg = _make_delegated_signal_message(signal_kind="progress", emission_seq=42)
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.envelope is not None
    assert outcome.envelope.emission_seq == 42


# ===========================================================================
# Group Y — ingest: result_kind preserved in outcome envelope
# ===========================================================================


def test_Y01_result_kind_preserved_in_converted_envelope():
    record, rt = _make_tracking_record()
    msg = _make_delegated_signal_message(signal_kind="result", result_kind="success")
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.envelope is not None
    assert outcome.envelope.result_kind == "success"


# ===========================================================================
# Group Z — Integration: full lifecycle tests
# ===========================================================================


def test_Z01_full_lifecycle_ack_progress_result_success():
    record, rt = _make_tracking_record()

    outcome_ack = ingest_delegated_execution_signal(
        _make_delegated_signal_message(signal_kind="ack", emission_seq=1), runtime=rt
    )
    assert outcome_ack.record is not None
    assert outcome_ack.record.phase == DelegatedExecutionPhase.acknowledged

    outcome_prog = ingest_delegated_execution_signal(
        _make_delegated_signal_message(signal_kind="progress", emission_seq=2), runtime=rt
    )
    assert outcome_prog.record is not None
    assert outcome_prog.record.phase == DelegatedExecutionPhase.in_progress

    outcome_result = ingest_delegated_execution_signal(
        _make_delegated_signal_message(
            signal_kind="result", result_kind="success", emission_seq=3
        ),
        runtime=rt,
    )
    assert outcome_result.record is not None
    assert outcome_result.record.phase == DelegatedExecutionPhase.completed
    assert outcome_result.record.result is not None
    assert outcome_result.record.result.success is True


def test_AA01_ack_progress_result_failure():
    record, rt = _make_tracking_record()

    ingest_delegated_execution_signal(
        _make_delegated_signal_message(signal_kind="ack", emission_seq=1), runtime=rt
    )
    ingest_delegated_execution_signal(
        _make_delegated_signal_message(signal_kind="progress", emission_seq=2), runtime=rt
    )
    outcome = ingest_delegated_execution_signal(
        _make_delegated_signal_message(
            signal_kind="result", result_kind="failure", emission_seq=3,
            extra_payload={"error_message": "delegated execution failed"},
        ),
        runtime=rt,
    )
    assert outcome.record is not None
    assert outcome.record.phase == DelegatedExecutionPhase.failed
    assert outcome.record.result is not None
    assert outcome.record.result.success is False


def test_AB01_ack_timeout_timed_out():
    record, rt = _make_tracking_record()

    ingest_delegated_execution_signal(
        _make_delegated_signal_message(signal_kind="ack", emission_seq=1), runtime=rt
    )
    outcome = ingest_delegated_execution_signal(
        _make_delegated_signal_message(signal_kind="timeout", emission_seq=2), runtime=rt
    )
    assert outcome.record is not None
    assert outcome.record.phase == DelegatedExecutionPhase.timed_out


def test_AC01_ack_cancelled_cancelled():
    record, rt = _make_tracking_record()

    ingest_delegated_execution_signal(
        _make_delegated_signal_message(signal_kind="ack", emission_seq=1), runtime=rt
    )
    outcome = ingest_delegated_execution_signal(
        _make_delegated_signal_message(signal_kind="cancelled", emission_seq=2), runtime=rt
    )
    assert outcome.record is not None
    assert outcome.record.phase == DelegatedExecutionPhase.cancelled


def test_AD01_signal_after_terminal_not_updated():
    record, rt = _make_tracking_record()

    ingest_delegated_execution_signal(
        _make_delegated_signal_message(signal_kind="result", result_kind="success"),
        runtime=rt,
    )
    outcome = ingest_delegated_execution_signal(
        _make_delegated_signal_message(signal_kind="progress"), runtime=rt
    )
    assert outcome.was_updated is False


def test_AE01_contract_id_lookup_takes_precedence():
    rt = _fresh_runtime()
    # Create two records with different contract_ids
    record1, _ = _make_tracking_record(
        contract_id="ctr-A", session_id="ses-A", runtime=rt
    )
    record2, _ = _make_tracking_record(
        contract_id="ctr-B", session_id="ses-B", runtime=rt
    )
    # Send ack targeting ctr-A
    msg = _make_delegated_signal_message(
        contract_id="ctr-A",
        session_id="ses-A",
        signal_kind="ack",
    )
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.was_updated is True
    assert outcome.record is not None
    assert outcome.record.identity.contract_id == "ctr-A"


def test_AF01_session_id_fallback_when_no_contract_id():
    rt = _fresh_runtime()
    record, _ = _make_tracking_record(
        contract_id="ctr-af-001", session_id="ses-af-001", runtime=rt
    )
    msg = {
        "type": "delegated_execution_signal",
        "device_id": "dev-af-001",
        "task_id": "task-af-001",
        "payload": {
            "session_id": "ses-af-001",
            "signal_kind": "ack",
            "emission_seq": 1,
        },
    }
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.was_updated is True


# ===========================================================================
# Group AG — core.runtime re-exports
# ===========================================================================


def test_AG01_core_runtime_exports_all_pr16_symbols():
    from core import runtime as rt_module
    assert hasattr(rt_module, "ANDROID_DELEGATED_SIGNAL_INGRESS_AUTHORITY")
    assert hasattr(rt_module, "ANDROID_DELEGATED_SIGNAL_INGRESS_PR16_SENTINEL")
    assert hasattr(rt_module, "DelegatedSignalKind")
    assert hasattr(rt_module, "ResultKind")
    assert hasattr(rt_module, "DelegatedExecutionSignalEnvelope")
    assert hasattr(rt_module, "extract_delegated_signal_envelope")
    assert hasattr(rt_module, "ingest_delegated_execution_signal")


def test_AG02_core_runtime_exports_all_policy_sentinels():
    from core import runtime as rt_module
    assert hasattr(rt_module, "INGRESS_DELEGATED_SIGNAL_TYPE_IS_CANONICAL_POLICY")
    assert hasattr(rt_module, "INGRESS_SIGNAL_KIND_IS_EXPLICIT_FIELD_POLICY")
    assert hasattr(rt_module, "INGRESS_RESULT_KIND_DISAMBIGUATES_RESULT_SIGNALS_POLICY")
    assert hasattr(rt_module, "INGRESS_SIGNAL_ID_IS_PRESERVED_POLICY")
    assert hasattr(rt_module, "INGRESS_EMISSION_SEQ_IS_PRESERVED_POLICY")
    assert hasattr(rt_module, "INGRESS_IDENTITY_FIELDS_ARE_VERBATIM_POLICY")
    assert hasattr(rt_module, "INGRESS_REQUIRES_LOOKUP_KEY_POLICY")
    assert hasattr(rt_module, "INGRESS_DELEGATES_TO_RECONCILER_POLICY")
    assert hasattr(rt_module, "INGRESS_TRACKER_PHASE_CONSISTENT_WITH_SIGNAL_KIND_POLICY")
    assert hasattr(rt_module, "INGRESS_NON_DESTRUCTIVE_ON_MISS_POLICY")


# ===========================================================================
# Group AH — projection.py sentinel
# ===========================================================================


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("fastapi"),
    reason="fastapi not available",
)
def test_AH01_projection_sentinel_present():
    from core.routes.projection import ANDROID_DELEGATED_SIGNAL_INGRESS_ALIGNED_PR16
    assert ANDROID_DELEGATED_SIGNAL_INGRESS_ALIGNED_PR16
    assert "UNAVAILABLE" not in ANDROID_DELEGATED_SIGNAL_INGRESS_ALIGNED_PR16


# ===========================================================================
# Group AI — all 10 policy sentinels are non-empty
# ===========================================================================


def test_AI01_all_10_policies_non_empty():
    assert len(_ALL_POLICIES) == 10
    for policy in _ALL_POLICIES:
        assert isinstance(policy, str)
        assert len(policy) > 0
        assert "INGRESS_POLICY::" in policy


# ===========================================================================
# Group AJ — PR16 sentinel
# ===========================================================================


def test_AJ01_pr16_sentinel_contains_package_16():
    assert "package=16" in ANDROID_DELEGATED_SIGNAL_INGRESS_PR16_SENTINEL


def test_AJ02_pr16_sentinel_contains_authority():
    assert "ANDROID_DELEGATED_SIGNAL_INGRESS_AUTHORITY" in ANDROID_DELEGATED_SIGNAL_INGRESS_PR16_SENTINEL


# ===========================================================================
# Group AK — envelope_id is UUID
# ===========================================================================


def test_AK01_envelope_id_is_uuid():
    env = DelegatedExecutionSignalEnvelope()
    parsed = uuid.UUID(env.envelope_id)
    assert str(parsed) == env.envelope_id


# ===========================================================================
# Group AL — received_at is float
# ===========================================================================


def test_AL01_received_at_is_float():
    import time
    before = time.time()
    env = DelegatedExecutionSignalEnvelope()
    after = time.time()
    assert isinstance(env.received_at, float)
    assert before <= env.received_at <= after


# ===========================================================================
# Group AM — was_updated=True on successful reconcile
# ===========================================================================


def test_AM01_was_updated_true_on_success():
    record, rt = _make_tracking_record()
    msg = _make_delegated_signal_message(signal_kind="ack")
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.was_updated is True
    assert outcome.reject_reason == ""


# ===========================================================================
# Group AN/AO — result set for result/success and result/failure
# ===========================================================================


def test_AN01_result_set_for_result_success():
    record, rt = _make_tracking_record()
    msg = _make_delegated_signal_message(
        signal_kind="result", result_kind="success",
        extra_payload={"result": "ok output"},
    )
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.record is not None
    assert outcome.record.result is not None
    assert outcome.record.result.success is True


def test_AO01_result_set_for_result_failure():
    record, rt = _make_tracking_record()
    msg = _make_delegated_signal_message(
        signal_kind="result", result_kind="failure",
        extra_payload={"error_message": "oops"},
    )
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.record is not None
    assert outcome.record.result is not None
    assert outcome.record.result.success is False


# ===========================================================================
# Group AP–AR — defaults for absent fields
# ===========================================================================


def test_AP01_emission_seq_defaults_to_zero():
    msg = _make_delegated_signal_message()
    del msg["payload"]["emission_seq"]
    env = extract_delegated_signal_envelope(msg)
    assert env.emission_seq == 0


def test_AQ01_emission_seq_default_for_bad_value():
    msg = _make_delegated_signal_message()
    msg["payload"]["emission_seq"] = "bad"
    env = extract_delegated_signal_envelope(msg)
    assert env.emission_seq == 0


def test_AR01_signal_id_defaults_to_empty():
    msg = _make_delegated_signal_message()
    env = extract_delegated_signal_envelope(msg)
    assert env.signal_id == ""


def test_AS01_result_kind_defaults_to_unknown():
    msg = _make_delegated_signal_message(signal_kind="result")
    env = extract_delegated_signal_envelope(msg)
    assert env.result_kind == ResultKind.unknown


# ===========================================================================
# Group AT — MessageType.DELEGATED_EXECUTION_SIGNAL in aip_v3
# ===========================================================================


def test_AT01_message_type_delegated_execution_signal_exists():
    from galaxy_gateway.protocol.aip_v3 import MessageType
    assert MessageType.DELEGATED_EXECUTION_SIGNAL.value == "delegated_execution_signal"


# ===========================================================================
# Group AU/AV — DelegatedSignalKind.from_string case-insensitive
# ===========================================================================


def test_AU01_delegated_signal_kind_case_insensitive():
    assert DelegatedSignalKind.from_string("ACK") == DelegatedSignalKind.ack
    assert DelegatedSignalKind.from_string("PROGRESS") == DelegatedSignalKind.progress
    assert DelegatedSignalKind.from_string("RESULT") == DelegatedSignalKind.result
    assert DelegatedSignalKind.from_string("TIMEOUT") == DelegatedSignalKind.timeout
    assert DelegatedSignalKind.from_string("CANCELLED") == DelegatedSignalKind.cancelled


def test_AV01_delegated_signal_kind_non_string():
    assert DelegatedSignalKind.from_string(0) == DelegatedSignalKind.progress  # type: ignore[arg-type]
    assert DelegatedSignalKind.from_string([]) == DelegatedSignalKind.progress  # type: ignore[arg-type]


# ===========================================================================
# Group AW — ResultKind.from_string case-insensitive
# ===========================================================================


def test_AW01_result_kind_case_insensitive():
    assert ResultKind.from_string("SUCCESS") == ResultKind.success
    assert ResultKind.from_string("FAILURE") == ResultKind.failure
    assert ResultKind.from_string("UNKNOWN") == ResultKind.unknown


# ===========================================================================
# Group AX — session_id from runtime_session_id fallback
# ===========================================================================


def test_AX01_session_id_from_runtime_session_id_in_payload():
    msg = {
        "type": "delegated_execution_signal",
        "device_id": "dev-001",
        "task_id": "task-001",
        "payload": {
            "runtime_session_id": "rses-999",
            "contract_id": "ctr-001",
            "signal_kind": "ack",
            "emission_seq": 1,
        },
    }
    env = extract_delegated_signal_envelope(msg)
    assert env.session_id == "rses-999"


# ===========================================================================
# Group AY — result/unknown → completed (optimistic)
# ===========================================================================


def test_AY01_result_unknown_maps_to_completed():
    record, rt = _make_tracking_record()
    msg = _make_delegated_signal_message(signal_kind="result")  # no result_kind
    outcome = ingest_delegated_execution_signal(msg, runtime=rt)
    assert outcome.record is not None
    assert outcome.record.phase == DelegatedExecutionPhase.completed


# ===========================================================================
# Group AZ — two separate sessions are independent
# ===========================================================================


def test_AZ01_two_sessions_independent():
    rt = _fresh_runtime()
    record_a, _ = _make_tracking_record(
        session_id="ses-az-A", contract_id="ctr-az-A", runtime=rt
    )
    record_b, _ = _make_tracking_record(
        session_id="ses-az-B", contract_id="ctr-az-B", runtime=rt
    )

    # Advance A to completed
    msg_a = _make_delegated_signal_message(
        session_id="ses-az-A",
        contract_id="ctr-az-A",
        signal_kind="result",
        result_kind="success",
    )
    outcome_a = ingest_delegated_execution_signal(msg_a, runtime=rt)
    assert outcome_a.record is not None
    assert outcome_a.record.phase == DelegatedExecutionPhase.completed

    # B should still be in pending_ack
    msg_b_progress = _make_delegated_signal_message(
        session_id="ses-az-B",
        contract_id="ctr-az-B",
        signal_kind="progress",
    )
    outcome_b = ingest_delegated_execution_signal(msg_b_progress, runtime=rt)
    assert outcome_b.record is not None
    assert outcome_b.record.phase == DelegatedExecutionPhase.in_progress
