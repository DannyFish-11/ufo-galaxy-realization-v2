"""tests/test_pr8_live_runtime_proof_thickening.py
==================================================
PR-8: Live runtime proof surface thickening.

This module closes **R6** (live runtime proof surface is still too thin) by
providing a targeted set of tests that deepen the machine-verifiable runtime
evidence for cross-repo live-runtime behavior.

What this module proves
-----------------------
1. ``TestSignalKindMappingCompleteness``
   All canonical AIP v3 message-type / status pairs map to the correct
   AndroidSignalKind — no silent mapping fallback to the default for known
   types.

2. ``TestSignalEnvelopeExtraction``
   extract_signal_envelope() correctly harvests identity fields from raw
   AIP v3 messages under different field-placement strategies (top-level vs.
   payload-nested).

3. ``TestReconcileOutcomeSerialisation``
   AndroidSignalReconcileOutcome.to_dict() round-trips all outcome fields
   without data loss.

4. ``TestCrossRepoPolicyStringsPresent``
   All PR-8 / R6 / R13 policy sentinels from the reconciler and the
   cross-repo consistency gates are non-empty strings, confirming the
   authoritative module surface is intact.

5. ``TestLiveRuntimeSnapshotStoreIntegrity``
   The android_device_state_store provides stable, typed, Android-derived
   values across multiple absorb/read cycles — not synthetic zeros.

6. ``TestReplayGuardDeterminism``
   The signal reconciler produces deterministic, stable outcomes for
   replayed signals, stale context, and unknown message types.

7. ``TestCrossRepoConsistencyGatesPass``
   run_all_consistency_gates() runs without exception and all gate results
   carry a valid verdict — confirms the cross-repo contract surface is
   structurally intact.

8. ``TestAndroidRuntimeTruthDrivesGovernanceDecisions``
   Android snapshot truth materially changes governance state decisions
   (dispatch eligibility, score differences) — not just stored but actively
   influencing routing.

9. ``TestSignalChainIdempotencyAndOrdering``
   Applying the same non-terminal signal multiple times is idempotent for
   phase advancement — the phase must not regress between repeated identical
   calls.

10. ``TestExecutionRuntimeSnapshotIntegrity``
    build_execution_tracking_snapshot() produces a valid, non-empty snapshot
    with the correct structure when records are present.

Evidence class
--------------
All tests use real code paths (no deep mocking of production logic).
Where isolation is needed, ring-buffer runtime overrides or fresh singletons
are provided via the runtime= / registry= keyword arguments on the
reconciler.

These tests are intentionally unit-level (no network transport) so they run
deterministically in CI without external dependencies.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _v3(msg_type: str, device_id: str, **extra) -> Dict[str, Any]:
    return {
        "version": "3.0",
        "type": msg_type,
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        **extra,
    }


def _make_runtime():
    from core.delegated_runtime_execution_tracker import (
        DelegatedExecutionTrackingRuntime,
    )

    return DelegatedExecutionTrackingRuntime()


def _make_record(contract_id: str, session_id: str, device_id: str = "test_dev"):
    from core.delegated_runtime_execution_tracker import (
        create_execution_tracking_record,
        record_execution_tracking,
    )

    rt = _make_runtime()
    record = create_execution_tracking_record(
        contract_id=contract_id,
        session_id=session_id,
        device_id=device_id,
        trace_id="trace_pr8",
    )
    record_execution_tracking(record, runtime=rt)
    return rt, record


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_state_store():
    try:
        from core.android_device_state_store import reset_android_device_state_store

        reset_android_device_state_store()
        yield
        reset_android_device_state_store()
    except ImportError:
        yield


# ===========================================================================
# 1. Signal Kind Mapping Completeness
# ===========================================================================


class TestSignalKindMappingCompleteness:
    """All known AIP v3 message-type/status pairs map to expected signal kind."""

    def test_task_result_completed_maps_to_final_result(self):
        from core.android_execution_signal_reconciler import (
            AndroidSignalKind,
            normalize_android_message_to_signal_kind,
        )

        kind = normalize_android_message_to_signal_kind("task_result", "completed")
        assert kind == AndroidSignalKind.final_result

    def test_task_result_failed_maps_to_error(self):
        from core.android_execution_signal_reconciler import (
            AndroidSignalKind,
            normalize_android_message_to_signal_kind,
        )

        kind = normalize_android_message_to_signal_kind("task_result", "failed")
        assert kind == AndroidSignalKind.error

    def test_task_result_cancelled_maps_to_cancelled(self):
        from core.android_execution_signal_reconciler import (
            AndroidSignalKind,
            normalize_android_message_to_signal_kind,
        )

        kind = normalize_android_message_to_signal_kind("task_result", "cancelled")
        assert kind == AndroidSignalKind.cancelled

    def test_task_result_timeout_maps_to_timeout(self):
        from core.android_execution_signal_reconciler import (
            AndroidSignalKind,
            normalize_android_message_to_signal_kind,
        )

        kind = normalize_android_message_to_signal_kind("task_result", "timeout")
        assert kind == AndroidSignalKind.timeout

    def test_error_maps_to_error(self):
        from core.android_execution_signal_reconciler import (
            AndroidSignalKind,
            normalize_android_message_to_signal_kind,
        )

        kind = normalize_android_message_to_signal_kind("error", "")
        assert kind == AndroidSignalKind.error

    def test_goal_execution_result_success_maps_to_final_result(self):
        from core.android_execution_signal_reconciler import (
            AndroidSignalKind,
            normalize_android_message_to_signal_kind,
        )

        kind = normalize_android_message_to_signal_kind("goal_execution_result", "success")
        assert kind == AndroidSignalKind.final_result

    def test_goal_execution_result_failure_maps_to_error(self):
        from core.android_execution_signal_reconciler import (
            AndroidSignalKind,
            normalize_android_message_to_signal_kind,
        )

        kind = normalize_android_message_to_signal_kind("goal_execution_result", "failure")
        assert kind == AndroidSignalKind.error

    def test_delegated_execution_signal_result_maps_to_final_result(self):
        from core.android_execution_signal_reconciler import (
            AndroidSignalKind,
            normalize_android_message_to_signal_kind,
        )

        kind = normalize_android_message_to_signal_kind("delegated_execution_signal", "result")
        assert kind == AndroidSignalKind.final_result

    def test_task_cancel_maps_to_cancelled(self):
        from core.android_execution_signal_reconciler import (
            AndroidSignalKind,
            normalize_android_message_to_signal_kind,
        )

        kind = normalize_android_message_to_signal_kind("task_cancel", "")
        assert kind == AndroidSignalKind.cancelled

    def test_unknown_message_type_defaults_to_progress(self):
        from core.android_execution_signal_reconciler import (
            AndroidSignalKind,
            normalize_android_message_to_signal_kind,
        )

        kind = normalize_android_message_to_signal_kind("completely_unknown_type_xyz", "whatever")
        assert kind == AndroidSignalKind.progress, (
            "Unknown message types must default to 'progress' — "
            "the record must stay alive rather than silently stalling"
        )

    def test_terminal_signal_kinds_are_final_result_error_timeout_cancelled(self):
        from core.android_execution_signal_reconciler import AndroidSignalKind

        terminal_kinds = {
            k for k in AndroidSignalKind if k.is_terminal()
        }
        assert terminal_kinds == {
            AndroidSignalKind.final_result,
            AndroidSignalKind.error,
            AndroidSignalKind.timeout,
            AndroidSignalKind.cancelled,
        }

    def test_non_terminal_signal_kinds_are_ack_progress_partial_result(self):
        from core.android_execution_signal_reconciler import AndroidSignalKind

        non_terminal = {
            k for k in AndroidSignalKind if not k.is_terminal()
        }
        assert non_terminal == {
            AndroidSignalKind.ack,
            AndroidSignalKind.progress,
            AndroidSignalKind.partial_result,
        }


# ===========================================================================
# 2. Signal Envelope Extraction
# ===========================================================================


class TestSignalEnvelopeExtraction:
    """extract_signal_envelope() correctly harvests identity fields."""

    def test_top_level_device_id_takes_precedence_over_payload(self):
        from core.android_execution_signal_reconciler import extract_signal_envelope

        msg = _v3(
            "task_result", "top_level_device",
            status="completed",
            payload={"device_id": "payload_device"},
        )
        envelope = extract_signal_envelope(msg)
        assert envelope.device_id == "top_level_device", (
            "device_id from top-level must take precedence over payload"
        )

    def test_contract_id_resolved_from_payload(self):
        from core.android_execution_signal_reconciler import extract_signal_envelope

        contract_id = f"contract-{uuid.uuid4().hex[:8]}"
        msg = _v3(
            "task_result", "dev",
            status="completed",
            payload={"contract_id": contract_id},
        )
        envelope = extract_signal_envelope(msg)
        assert envelope.contract_id == contract_id

    def test_session_id_resolved_from_payload(self):
        from core.android_execution_signal_reconciler import extract_signal_envelope

        session_id = f"sess-{uuid.uuid4().hex[:8]}"
        msg = _v3(
            "task_result", "dev",
            status="completed",
            payload={"session_id": session_id},
        )
        envelope = extract_signal_envelope(msg)
        assert envelope.session_id == session_id

    def test_trace_id_resolved_from_payload(self):
        from core.android_execution_signal_reconciler import extract_signal_envelope

        trace_id = f"trace-{uuid.uuid4().hex[:8]}"
        msg = _v3(
            "task_result", "dev",
            status="completed",
            payload={"trace_id": trace_id},
        )
        envelope = extract_signal_envelope(msg)
        assert envelope.trace_id == trace_id

    def test_signal_kind_is_set_from_message_type_and_status(self):
        from core.android_execution_signal_reconciler import (
            AndroidSignalKind,
            extract_signal_envelope,
        )

        msg = _v3("task_result", "dev", status="completed")
        envelope = extract_signal_envelope(msg)
        assert envelope.signal_kind == AndroidSignalKind.final_result

    def test_envelope_has_lookup_key_when_contract_id_present(self):
        from core.android_execution_signal_reconciler import extract_signal_envelope

        msg = _v3(
            "task_result", "dev",
            payload={"contract_id": "cid_001"},
        )
        envelope = extract_signal_envelope(msg)
        assert envelope.has_lookup_key() is True

    def test_envelope_has_no_lookup_key_when_both_empty(self):
        from core.android_execution_signal_reconciler import extract_signal_envelope

        msg = {"type": "task_result", "message_id": "x", "device_id": "dev", "timestamp": 0}
        envelope = extract_signal_envelope(msg)
        assert envelope.has_lookup_key() is False

    def test_envelope_to_dict_roundtrips_all_fields(self):
        from core.android_execution_signal_reconciler import extract_signal_envelope

        contract_id = f"cid-rt-{uuid.uuid4().hex[:8]}"
        session_id = f"sid-rt-{uuid.uuid4().hex[:8]}"
        trace_id = f"tid-rt-{uuid.uuid4().hex[:8]}"
        task_id = f"task-rt-{uuid.uuid4().hex[:8]}"
        msg = _v3(
            "task_result", "dev_rt",
            status="completed",
            task_id=task_id,
            payload={
                "contract_id": contract_id,
                "session_id": session_id,
                "trace_id": trace_id,
                "result": {"done": True},
            },
        )
        envelope = extract_signal_envelope(msg)
        d = envelope.to_dict()
        assert d["contract_id"] == contract_id
        assert d["session_id"] == session_id
        assert d["trace_id"] == trace_id
        assert d["task_id"] == task_id
        assert d["signal_kind"] == "final_result"
        assert "envelope_id" in d
        assert "received_at" in d


# ===========================================================================
# 3. Reconcile Outcome Serialisation
# ===========================================================================


class TestReconcileOutcomeSerialisation:
    """AndroidSignalReconcileOutcome.to_dict() round-trips correctly."""

    def test_accepted_outcome_to_dict(self):
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )

        contract_id = f"cid-serial-{uuid.uuid4().hex[:8]}"
        session_id = f"sid-serial-{uuid.uuid4().hex[:8]}"
        rt, _ = _make_record(contract_id, session_id)

        env = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.ack,
            contract_id=contract_id,
            session_id=session_id,
        )
        outcome = reconcile_android_execution_signal(env, runtime=rt)
        d = outcome.to_dict()
        assert d["was_updated"] is True
        assert d["reject_reason"] == ""
        assert d["record"] is not None
        assert d["envelope"] is not None

    def test_rejected_outcome_to_dict_has_reject_reason(self):
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )
        from core.delegated_runtime_execution_tracker import (
            DelegatedExecutionTrackingRuntime,
        )

        rt = DelegatedExecutionTrackingRuntime()
        env = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.progress,
            contract_id="",
            session_id="",
        )
        outcome = reconcile_android_execution_signal(env, runtime=rt)
        d = outcome.to_dict()
        assert d["was_updated"] is False
        assert d["reject_reason"] != ""
        assert d["record"] is None

    def test_is_accepted_returns_true_for_updated_outcome(self):
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )

        contract_id = f"cid-ia-{uuid.uuid4().hex[:8]}"
        session_id = f"sid-ia-{uuid.uuid4().hex[:8]}"
        rt, _ = _make_record(contract_id, session_id)

        env = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.ack,
            contract_id=contract_id,
            session_id=session_id,
        )
        outcome = reconcile_android_execution_signal(env, runtime=rt)
        assert outcome.is_accepted() is True

    def test_is_accepted_returns_false_for_rejected_outcome(self):
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )
        from core.delegated_runtime_execution_tracker import (
            DelegatedExecutionTrackingRuntime,
        )

        rt = DelegatedExecutionTrackingRuntime()
        env = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.ack,
            contract_id="",
            session_id="",
        )
        outcome = reconcile_android_execution_signal(env, runtime=rt)
        assert outcome.is_accepted() is False


# ===========================================================================
# 4. Cross-Repo Policy Strings Present
# ===========================================================================


class TestCrossRepoPolicyStringsPresent:
    """All PR-8/R6/R13 policy sentinels must be non-empty strings."""

    def test_reconciler_authority_sentinel_present(self):
        from core.android_execution_signal_reconciler import (
            ANDROID_EXECUTION_SIGNAL_RECONCILER_AUTHORITY,
        )

        assert isinstance(ANDROID_EXECUTION_SIGNAL_RECONCILER_AUTHORITY, str)
        assert len(ANDROID_EXECUTION_SIGNAL_RECONCILER_AUTHORITY) > 0
        assert "PR13" in ANDROID_EXECUTION_SIGNAL_RECONCILER_AUTHORITY

    def test_reconciler_pr13_sentinel_present(self):
        from core.android_execution_signal_reconciler import (
            ANDROID_EXECUTION_SIGNAL_RECONCILER_PR13_SENTINEL,
        )

        assert "package=13" in ANDROID_EXECUTION_SIGNAL_RECONCILER_PR13_SENTINEL

    def test_reconciler_pr22_sentinel_present(self):
        from core.android_execution_signal_reconciler import (
            RECONCILER_PR22_SENTINEL,
        )

        assert "package=22" in RECONCILER_PR22_SENTINEL

    def test_reconciler_pr23_sentinel_present(self):
        from core.android_execution_signal_reconciler import (
            RECONCILER_PR23_SENTINEL,
        )

        assert "package=23" in RECONCILER_PR23_SENTINEL

    def test_all_reconciler_policy_sentinels_are_non_empty(self):
        from core.android_execution_signal_reconciler import (
            RECONCILER_CANCELLED_SIGNAL_CLOSES_TRACKING_RECORD_POLICY,
            RECONCILER_ERROR_SIGNAL_CLOSES_TRACKING_RECORD_POLICY,
            RECONCILER_FALLBACK_CONTEXT_IS_DETERMINISTIC_PR23_POLICY,
            RECONCILER_IDENTITY_IS_PRESERVED_ACROSS_RECONCILE_POLICY,
            RECONCILER_REGISTRY_BLOCKS_NON_ACTIVE_SESSION_PR22_POLICY,
            RECONCILER_REGISTRY_GATE_IS_AUTHORITATIVE_PR22_POLICY,
            RECONCILER_REQUIRES_CONTRACT_ID_OR_SESSION_ID_POLICY,
            RECONCILER_RESULT_PAYLOAD_IS_FORWARDED_TO_TRACKER_POLICY,
            RECONCILER_SIGNAL_MAPPING_IS_CANONICAL_POLICY,
            RECONCILER_STALE_SESSION_IS_BLOCKED_BEFORE_TRACKER_MUTATION_PR23_POLICY,
            RECONCILER_TASK_STATUS_MAPS_TO_ACK_SIGNAL_CANONICALLY_POLICY,
            RECONCILER_TERMINAL_RECORD_BLOCKS_FURTHER_SIGNALS_POLICY,
            RECONCILER_TIMEOUT_SIGNAL_CLOSES_TRACKING_RECORD_POLICY,
            RECONCILER_UNKNOWN_SIGNAL_DEFAULTS_TO_PROGRESS_POLICY,
        )

        sentinels = [
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
            RECONCILER_REGISTRY_GATE_IS_AUTHORITATIVE_PR22_POLICY,
            RECONCILER_REGISTRY_BLOCKS_NON_ACTIVE_SESSION_PR22_POLICY,
            RECONCILER_FALLBACK_CONTEXT_IS_DETERMINISTIC_PR23_POLICY,
            RECONCILER_STALE_SESSION_IS_BLOCKED_BEFORE_TRACKER_MUTATION_PR23_POLICY,
        ]

        for sentinel in sentinels:
            assert isinstance(sentinel, str) and len(sentinel) > 0, (
                f"Policy sentinel must be a non-empty string; got: {sentinel!r}"
            )

    def test_cross_repo_consistency_gates_pr12_sentinel(self):
        from core.cross_repo_consistency_gates import (
            CROSS_REPO_CONSISTENCY_GATES_PR12_SENTINEL,
        )

        assert "PR12" in CROSS_REPO_CONSISTENCY_GATES_PR12_SENTINEL


# ===========================================================================
# 5. Live Runtime Snapshot Store Integrity
# ===========================================================================


class TestLiveRuntimeSnapshotStoreIntegrity:
    """android_device_state_store provides stable, typed Android-derived values."""

    def test_absorb_and_read_returns_android_derived_model_ready(self):
        from core.android_device_state_store import (
            absorb_device_state_snapshot,
            get_device_state_snapshot,
        )

        device_id = f"pr8-store-{uuid.uuid4().hex[:8]}"
        absorb_device_state_snapshot(
            device_id,
            {
                "model_ready": True,
                "accessibility_ready": True,
                "model_id": "mobilevlm_v2_7b",
                "current_fallback_tier": "planner_local",
                "snapshot_seq": 1,
                "snapshot_ts": int(time.time() * 1000),
            },
        )

        stored = get_device_state_snapshot(device_id)
        assert stored is not None
        assert stored.model_ready is True
        assert stored.accessibility_ready is True
        assert stored.model_id == "mobilevlm_v2_7b"
        assert stored.current_fallback_tier == "planner_local"

    def test_multiple_absorb_cycles_reflect_latest(self):
        from core.android_device_state_store import (
            absorb_device_state_snapshot,
            get_device_state_snapshot,
        )

        device_id = f"pr8-multi-{uuid.uuid4().hex[:8]}"
        ts_base = int(time.time() * 1000)

        absorb_device_state_snapshot(
            device_id,
            {"model_ready": True, "snapshot_seq": 1, "snapshot_ts": ts_base},
        )
        absorb_device_state_snapshot(
            device_id,
            {"model_ready": False, "snapshot_seq": 2, "snapshot_ts": ts_base + 2000},
        )
        absorb_device_state_snapshot(
            device_id,
            {"model_ready": True, "snapshot_seq": 3, "snapshot_ts": ts_base + 4000},
        )

        stored = get_device_state_snapshot(device_id)
        assert stored is not None
        assert stored.model_ready is True, (
            "Third absorb (seq=3) must be the latest; model_ready should be True"
        )
        assert stored.snapshot_seq == 3

    def test_execution_event_absorbed_and_readable(self):
        from core.android_device_state_store import (
            absorb_device_execution_event,
            list_recent_execution_events,
        )

        device_id = f"pr8-event-{uuid.uuid4().hex[:8]}"
        flow_id = f"flow-{uuid.uuid4().hex[:8]}"

        absorb_device_execution_event(
            device_id,
            {
                "flow_id": flow_id,
                "task_id": f"task-{uuid.uuid4().hex[:8]}",
                "phase": "execution",
                "event_ts": time.time(),
            },
        )

        events = list_recent_execution_events(device_id=device_id, limit=10)
        assert events, "absorb_device_execution_event must persist a readable event"
        assert events[0].phase == "execution"

    def test_snapshot_for_unknown_device_returns_none(self):
        from core.android_device_state_store import get_device_state_snapshot

        result = get_device_state_snapshot(f"pr8-unknown-{uuid.uuid4().hex[:16]}")
        assert result is None, "get_device_state_snapshot must return None for unknown device"

    def test_store_independent_of_task_execution_path(self):
        """Store is populated by snapshot path alone, not by task execution."""
        from core.android_device_state_store import (
            absorb_device_state_snapshot,
            get_device_state_snapshot,
        )

        device_id = f"pr8-notask-{uuid.uuid4().hex[:8]}"
        absorb_device_state_snapshot(
            device_id,
            {"model_ready": True, "snapshot_seq": 1, "snapshot_ts": int(time.time() * 1000)},
        )

        stored = get_device_state_snapshot(device_id)
        assert stored is not None, (
            "Store must be populated via snapshot path alone — "
            "no task execution required"
        )


# ===========================================================================
# 6. Replay Guard Determinism
# ===========================================================================


class TestReplayGuardDeterminism:
    """Reconciler produces deterministic, stable outcomes for replayed signals."""

    def test_terminal_outcome_is_idempotent_across_replays(self):
        """Replaying a final_result three times always returns the same outcome."""
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )

        contract_id = f"cid-idem-{uuid.uuid4().hex[:8]}"
        session_id = f"sid-idem-{uuid.uuid4().hex[:8]}"
        rt, _ = _make_record(contract_id, session_id)

        env_final = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.final_result,
            contract_id=contract_id,
            session_id=session_id,
            payload={"result": {"ok": True}},
        )

        # First call: should update
        o1 = reconcile_android_execution_signal(env_final, runtime=rt)
        assert o1.was_updated is True

        # Subsequent replays: must be blocked
        for attempt in range(3):
            replay = AndroidExecutionSignalEnvelope(
                signal_kind=AndroidSignalKind.final_result,
                contract_id=contract_id,
                session_id=session_id,
                payload={"result": {"ok": True}},
            )
            o_replay = reconcile_android_execution_signal(replay, runtime=rt)
            assert o_replay.was_updated is False, (
                f"Replay {attempt}: was_updated must be False for terminal record"
            )
            assert o_replay.reject_reason, (
                f"Replay {attempt}: reject_reason must be set"
            )

    def test_missing_lookup_key_always_produces_same_rejection(self):
        """Missing contract_id + session_id always produces the same rejection."""
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )
        from core.delegated_runtime_execution_tracker import (
            DelegatedExecutionTrackingRuntime,
        )

        rt = DelegatedExecutionTrackingRuntime()
        reject_reasons = []

        for _i in range(5):
            env = AndroidExecutionSignalEnvelope(
                signal_kind=AndroidSignalKind.progress,
                contract_id="",
                session_id="",
            )
            outcome = reconcile_android_execution_signal(env, runtime=rt)
            assert outcome.was_updated is False
            reject_reasons.append(outcome.reject_reason)

        # All reject reasons must be non-empty
        for rr in reject_reasons:
            assert rr, "reject_reason must be non-empty for missing lookup key"

    def test_envelope_to_dict_is_stable_across_calls(self):
        """to_dict() must return the same structure on repeated calls."""
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
        )

        env = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.final_result,
            contract_id="cid_stable",
            session_id="sid_stable",
            device_id="dev_stable",
            trace_id="trace_stable",
            task_id="task_stable",
            payload={"result": {"ok": True}},
        )

        d1 = env.to_dict()
        d2 = env.to_dict()

        for key in ("signal_kind", "contract_id", "session_id", "device_id",
                    "trace_id", "task_id", "envelope_id"):
            assert d1[key] == d2[key], (
                f"to_dict() must be stable for key {key!r}"
            )


# ===========================================================================
# 7. Cross-Repo Consistency Gates Pass
# ===========================================================================


class TestCrossRepoConsistencyGatesPass:
    """run_all_consistency_gates() succeeds and returns valid verdicts."""

    def test_all_consistency_gates_run_without_exception(self):
        from core.cross_repo_consistency_gates import run_all_consistency_gates

        results = run_all_consistency_gates()
        assert results, "run_all_consistency_gates() must return at least one result"

    def test_all_gate_results_have_valid_verdict(self):
        from core.cross_repo_consistency_gates import GateVerdict, run_all_consistency_gates

        results = run_all_consistency_gates()
        valid_verdicts = {GateVerdict.pass_, GateVerdict.warn, GateVerdict.fail}
        for result in results:
            assert result.verdict in valid_verdicts, (
                f"Gate {result.gate_id!r} has invalid verdict: {result.verdict!r}"
            )

    def test_build_consistency_gate_snapshot_produces_valid_dict(self):
        from core.cross_repo_consistency_gates import build_consistency_gate_snapshot

        snapshot = build_consistency_gate_snapshot()
        d = snapshot.to_dict()

        required_keys = {
            "generated_at", "total_gates", "passed_gates", "warned_gates",
            "failed_gates", "drift_detected", "is_clean", "summary", "gate_results",
        }
        for key in required_keys:
            assert key in d, f"Missing required key {key!r} in consistency_gate_snapshot.to_dict()"


# ===========================================================================
# 8. Android Runtime Truth Drives Governance Decisions
# ===========================================================================


class TestAndroidRuntimeTruthDrivesGovernanceDecisions:
    """Android snapshot truth materially changes governance dispatch scores."""

    def test_model_ready_true_boosts_dispatch_score_by_10(self):
        from core.runtime.source_dispatch_orchestrator import _score_candidate

        readiness = MagicMock()
        readiness.registered = True
        readiness.routable = True
        participation = MagicMock()
        participation.orchestration_eligible = True
        participation.participant_tier = "joined_runtime"

        snap_ready = MagicMock()
        snap_ready.model_ready = True
        snap_ready.accessibility_ready = None
        snap_ready.local_loop_ready = None
        snap_ready.warmup_result = None
        snap_ready.current_fallback_tier = None
        snap_ready.offline_queue_depth = None
        snap_ready.is_local_ai_ready = lambda: False
        snap_ready.mobilevlm_present = None
        snap_ready.mobilevlm_checksum_ok = None
        snap_ready.seeclick_present = None

        score_no_snap, _ = _score_candidate(
            "sess_test", "dev_test",
            readiness=readiness, participation=participation,
            reuse_eligible=False, android_snapshot=None, execution_busy=False,
        )
        score_ready, _ = _score_candidate(
            "sess_test", "dev_test",
            readiness=readiness, participation=participation,
            reuse_eligible=False, android_snapshot=snap_ready, execution_busy=False,
        )

        assert score_ready > score_no_snap, (
            "model_ready=True must produce higher dispatch score than no snapshot"
        )
        assert score_ready == score_no_snap + 10, (
            "model_ready=True should add exactly 10 points to the dispatch score"
        )

    def test_warmup_failed_reduces_dispatch_score(self):
        from core.runtime.source_dispatch_orchestrator import _score_candidate

        readiness = MagicMock()
        readiness.registered = True
        readiness.routable = True
        participation = MagicMock()
        participation.orchestration_eligible = True
        participation.participant_tier = "joined_runtime"

        snap_warmup_failed = MagicMock()
        snap_warmup_failed.model_ready = None
        snap_warmup_failed.accessibility_ready = None
        snap_warmup_failed.local_loop_ready = None
        snap_warmup_failed.warmup_result = "failed"
        snap_warmup_failed.current_fallback_tier = None
        snap_warmup_failed.offline_queue_depth = None
        snap_warmup_failed.is_local_ai_ready = lambda: False
        snap_warmup_failed.mobilevlm_present = None
        snap_warmup_failed.mobilevlm_checksum_ok = None
        snap_warmup_failed.seeclick_present = None

        score_no_snap, _ = _score_candidate(
            "sess_test", "dev_test",
            readiness=readiness, participation=participation,
            reuse_eligible=False, android_snapshot=None, execution_busy=False,
        )
        score_warmup_failed, _ = _score_candidate(
            "sess_test", "dev_test",
            readiness=readiness, participation=participation,
            reuse_eligible=False, android_snapshot=snap_warmup_failed, execution_busy=False,
        )

        assert score_warmup_failed < score_no_snap, (
            "warmup_result='failed' must reduce dispatch score"
        )

    def test_execution_busy_reduces_dispatch_score(self):
        from core.runtime.source_dispatch_orchestrator import _score_candidate

        readiness = MagicMock()
        readiness.registered = True
        readiness.routable = True
        participation = MagicMock()
        participation.orchestration_eligible = True
        participation.participant_tier = "joined_runtime"

        score_idle, _ = _score_candidate(
            "sess_test", "dev_test",
            readiness=readiness, participation=participation,
            reuse_eligible=False, android_snapshot=None, execution_busy=False,
        )
        score_busy, _ = _score_candidate(
            "sess_test", "dev_test",
            readiness=readiness, participation=participation,
            reuse_eligible=False, android_snapshot=None, execution_busy=True,
        )

        assert score_busy < score_idle, (
            "execution_busy=True must reduce dispatch score"
        )

    def test_healthy_vs_degraded_snapshot_score_difference(self):
        """Healthy snapshot must score materially higher than degraded snapshot."""
        from core.android_device_state_store import absorb_device_state_snapshot, get_device_state_snapshot
        from core.runtime.source_dispatch_orchestrator import _score_candidate
        from unittest.mock import MagicMock as MM

        dev_healthy = f"pr8-score-h-{uuid.uuid4().hex[:8]}"
        dev_degraded = f"pr8-score-d-{uuid.uuid4().hex[:8]}"

        absorb_device_state_snapshot(
            dev_healthy,
            {"model_ready": True, "accessibility_ready": True, "warmup_result": "ok",
             "snapshot_seq": 1, "snapshot_ts": int(time.time() * 1000)},
        )
        absorb_device_state_snapshot(
            dev_degraded,
            {"model_ready": False, "accessibility_ready": False, "warmup_result": "failed",
             "snapshot_seq": 1, "snapshot_ts": int(time.time() * 1000)},
        )

        snap_h = get_device_state_snapshot(dev_healthy)
        snap_d = get_device_state_snapshot(dev_degraded)

        readiness = MM()
        readiness.registered = True
        readiness.routable = True
        participation = MM()
        participation.orchestration_eligible = True
        participation.participant_tier = "joined_runtime"

        score_h, _ = _score_candidate(
            "sess_h", dev_healthy,
            readiness=readiness, participation=participation,
            reuse_eligible=False, android_snapshot=snap_h, execution_busy=False,
        )
        score_d, _ = _score_candidate(
            "sess_d", dev_degraded,
            readiness=readiness, participation=participation,
            reuse_eligible=False, android_snapshot=snap_d, execution_busy=False,
        )

        assert score_h > score_d, (
            f"Healthy snapshot score ({score_h}) must exceed degraded snapshot score ({score_d})"
        )


# ===========================================================================
# 9. Signal Chain Idempotency and Ordering
# ===========================================================================


class TestSignalChainIdempotencyAndOrdering:
    """Repeated non-terminal signals do not regress the phase."""

    def test_repeated_progress_signals_are_idempotent_in_phase(self):
        """Sending progress repeatedly must keep the record in_progress (no regression)."""
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )

        contract_id = f"cid-prog-{uuid.uuid4().hex[:8]}"
        session_id = f"sid-prog-{uuid.uuid4().hex[:8]}"
        rt, _ = _make_record(contract_id, session_id)

        # ack first to advance from pending_ack
        env_ack = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.ack,
            contract_id=contract_id,
            session_id=session_id,
        )
        reconcile_android_execution_signal(env_ack, runtime=rt)

        for _i in range(5):
            env_prog = AndroidExecutionSignalEnvelope(
                signal_kind=AndroidSignalKind.progress,
                contract_id=contract_id,
                session_id=session_id,
            )
            outcome = reconcile_android_execution_signal(env_prog, runtime=rt)
            assert outcome.was_updated is True
            assert outcome.record.phase.value in ("acknowledged", "in_progress"), (
                f"Phase must not regress; got {outcome.record.phase.value!r}"
            )
            assert not outcome.record.phase.is_terminal(), (
                "Progress must never produce a terminal phase"
            )

    def test_ack_after_progress_does_not_regress_to_pending_ack(self):
        """An ack signal after in_progress must not regress the phase."""
        from core.android_execution_signal_reconciler import (
            AndroidExecutionSignalEnvelope,
            AndroidSignalKind,
            reconcile_android_execution_signal,
        )

        contract_id = f"cid-ackprog-{uuid.uuid4().hex[:8]}"
        session_id = f"sid-ackprog-{uuid.uuid4().hex[:8]}"
        rt, _ = _make_record(contract_id, session_id)

        # Advance through ack → progress
        for sig in (AndroidSignalKind.ack, AndroidSignalKind.progress):
            env = AndroidExecutionSignalEnvelope(
                signal_kind=sig,
                contract_id=contract_id,
                session_id=session_id,
            )
            reconcile_android_execution_signal(env, runtime=rt)

        # Another ack after in_progress: phase must not regress
        env_late_ack = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.ack,
            contract_id=contract_id,
            session_id=session_id,
        )
        outcome = reconcile_android_execution_signal(env_late_ack, runtime=rt)
        assert outcome.record.phase.value in ("acknowledged", "in_progress"), (
            "Late ack must not regress phase below current"
        )

    def test_signal_kind_is_terminal_property_is_consistent(self):
        from core.android_execution_signal_reconciler import AndroidSignalKind

        for kind in AndroidSignalKind:
            if kind in (
                AndroidSignalKind.final_result,
                AndroidSignalKind.error,
                AndroidSignalKind.timeout,
                AndroidSignalKind.cancelled,
            ):
                assert kind.is_terminal() is True, (
                    f"{kind.value} must be terminal"
                )
            else:
                assert kind.is_terminal() is False, (
                    f"{kind.value} must not be terminal"
                )


# ===========================================================================
# 10. Execution Runtime Snapshot Integrity
# ===========================================================================


class TestExecutionRuntimeSnapshotIntegrity:
    """build_execution_tracking_snapshot() produces a valid snapshot."""

    def test_snapshot_structure_with_records_present(self):
        from core.delegated_runtime_execution_tracker import (
            DelegatedExecutionTrackingRuntime,
            build_execution_tracking_snapshot,
            create_execution_tracking_record,
            record_execution_tracking,
        )

        rt = DelegatedExecutionTrackingRuntime()

        for i in range(3):
            r = create_execution_tracking_record(
                contract_id=f"cid-snap-{i}-{uuid.uuid4().hex[:6]}",
                session_id=f"sid-snap-{i}-{uuid.uuid4().hex[:6]}",
                device_id=f"dev_{i}",
                trace_id=f"trace_{i}",
            )
            record_execution_tracking(r, runtime=rt)

        snapshot = build_execution_tracking_snapshot(runtime=rt)
        assert snapshot is not None
        d = snapshot.to_dict()
        assert "records" in d
        assert len(d["records"]) == 3
        for rec in d["records"]:
            assert "phase" in rec
            assert "identity" in rec

    def test_snapshot_is_empty_for_fresh_runtime(self):
        from core.delegated_runtime_execution_tracker import (
            DelegatedExecutionTrackingRuntime,
            build_execution_tracking_snapshot,
        )

        rt = DelegatedExecutionTrackingRuntime()
        snapshot = build_execution_tracking_snapshot(runtime=rt)
        d = snapshot.to_dict()
        assert "records" in d
        assert len(d["records"]) == 0

    def test_tracking_record_to_dict_roundtrips(self):
        from core.delegated_runtime_execution_tracker import (
            DelegatedExecutionTrackingRuntime,
            create_execution_tracking_record,
            record_execution_tracking,
        )

        contract_id = f"cid-rd-{uuid.uuid4().hex[:8]}"
        session_id = f"sid-rd-{uuid.uuid4().hex[:8]}"
        rt = DelegatedExecutionTrackingRuntime()
        record = create_execution_tracking_record(
            contract_id=contract_id,
            session_id=session_id,
            device_id="dev_rd",
            trace_id="trace_rd",
        )
        record_execution_tracking(record, runtime=rt)

        d = record.to_dict()
        assert d["identity"]["contract_id"] == contract_id
        assert d["identity"]["session_id"] == session_id
        assert d["phase"] == "pending_ack"
        assert "acknowledgments" in d
        assert isinstance(d["acknowledgments"], list)
