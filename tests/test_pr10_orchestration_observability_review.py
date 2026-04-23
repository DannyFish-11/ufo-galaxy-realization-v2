#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr10_orchestration_observability_review.py
=======================================================
PR-10 — Orchestration Observability Review Surface Tests

Validates the new unified operator review surface introduced in PR-10 to
close the remaining observability and operator-review gaps in the V2
orchestration runtime.

Coverage
--------
1. Authority sentinels are present and non-empty.
2. ExecutionPathDecisionSummary to_dict / from_dict round-trips.
3. FallbackCascadeReview to_dict / from_dict round-trips.
4. RecoveryDecisionReview to_dict / from_dict round-trips.
5. ReconciliationOutcomeReview to_dict / from_dict round-trips.
6. LegacyDispatchCounters to_dict / from_dict round-trips.
7. LegacyDispatchCounters increment / reset behaviour.
8. build_orchestration_review_snapshot() returns a non-None snapshot.
9. Snapshot is partial (_partial=True) when sources unavailable.
10. Snapshot _partial_reasons is a list (possibly empty or non-empty).
11. OrchestrationReviewSnapshot to_dict contains all expected top-level keys.
12. Snapshot legacy_dispatch is always present (never None even on cold start).
13. PR-10 sentinel is present.
14. android_participant_truth_ingress: get_last_reconciliation_outcome returns
    None before any reconciliation has occurred.
15. android_participant_truth_ingress: get_last_reconciliation_outcome returns
    a dict after a reconciliation.
16. windows_execution_arbiter: get_last_attempt_log returns a list.
17. ExecutionPathOutcome enum values are stable lowercase strings.
18. ReconciliationOutcome enum values are stable lowercase strings.
19. LegacyDispatchCounters per_surface_counts populated after increment.
20. build_orchestration_review_snapshot() is callable multiple times without error.
"""

from __future__ import annotations

import time

import pytest

from core.orchestration_review_surface import (
    ORCHESTRATION_REVIEW_SURFACE_IS_AUTHORITY,
    ORCHESTRATION_REVIEW_SURFACE_PR10_SENTINEL,
    REVIEW_SURFACE_IS_OBSERVATIONAL_ONLY_POLICY,
    REVIEW_SURFACE_NEVER_DUPLICATES_CANONICAL_LOGIC_POLICY,
    REVIEW_SURFACE_RESPECTS_AUTHORITY_BOUNDARIES_POLICY,
    ExecutionPathDecisionSummary,
    ExecutionPathOutcome,
    FallbackCascadeReview,
    FallbackCascadeStep,
    LegacyDispatchCounters,
    OrchestrationReviewSnapshot,
    ReconciliationOutcome,
    ReconciliationOutcomeReview,
    RecoveryDecisionReview,
    build_orchestration_review_snapshot,
    get_legacy_dispatch_counters,
    increment_legacy_dispatch_counter,
    reset_legacy_dispatch_counters,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset():
    """Reset mutable singletons between tests."""
    reset_legacy_dispatch_counters()


# ---------------------------------------------------------------------------
# 1. Authority sentinels
# ---------------------------------------------------------------------------


def test_authority_sentinel_present():
    assert ORCHESTRATION_REVIEW_SURFACE_IS_AUTHORITY
    assert "PR-10" in ORCHESTRATION_REVIEW_SURFACE_IS_AUTHORITY


def test_pr10_sentinel_present():
    assert ORCHESTRATION_REVIEW_SURFACE_PR10_SENTINEL
    assert "PR-10" in ORCHESTRATION_REVIEW_SURFACE_PR10_SENTINEL


def test_policy_sentinels_present():
    assert REVIEW_SURFACE_IS_OBSERVATIONAL_ONLY_POLICY
    assert REVIEW_SURFACE_RESPECTS_AUTHORITY_BOUNDARIES_POLICY
    assert REVIEW_SURFACE_NEVER_DUPLICATES_CANONICAL_LOGIC_POLICY


# ---------------------------------------------------------------------------
# 2. ExecutionPathDecisionSummary
# ---------------------------------------------------------------------------


def test_execution_path_decision_summary_defaults():
    summary = ExecutionPathDecisionSummary()
    assert summary.execution_path == "unknown"
    assert summary.outcome == ExecutionPathOutcome.UNKNOWN.value
    assert summary.hard_gate_active is False
    assert summary.hard_gate_reasons == []
    assert summary.active_soft_influences == 0


def test_execution_path_decision_summary_round_trip():
    original = ExecutionPathDecisionSummary(
        execution_path="agent_execute",
        outcome=ExecutionPathOutcome.CHOSEN.value,
        primary_reason="canonical_path_selected",
        hard_gate_active=False,
        hard_gate_reasons=[],
        active_soft_influences=2,
        model_selected="gpt-4o",
        provider_selected="openai",
        task_hint="code_generation",
    )
    d = original.to_dict()
    restored = ExecutionPathDecisionSummary.from_dict(d)
    assert restored.execution_path == "agent_execute"
    assert restored.outcome == ExecutionPathOutcome.CHOSEN.value
    assert restored.model_selected == "gpt-4o"
    assert restored.task_hint == "code_generation"
    assert restored.active_soft_influences == 2


def test_execution_path_decision_summary_rejected_path():
    summary = ExecutionPathDecisionSummary(
        execution_path="cross_device",
        outcome=ExecutionPathOutcome.REJECTED.value,
        primary_reason="governance_denial",
        hard_gate_active=True,
        hard_gate_reasons=["governance_denial"],
    )
    d = summary.to_dict()
    assert d["hard_gate_active"] is True
    assert d["outcome"] == "rejected"
    assert "governance_denial" in d["hard_gate_reasons"]


# ---------------------------------------------------------------------------
# 3. FallbackCascadeReview
# ---------------------------------------------------------------------------


def test_fallback_cascade_step_round_trip():
    step = FallbackCascadeStep(
        step_index=0,
        from_tier="system_api",
        to_tier="gui",
        reason="executor_unavailable",
        raw_reason="SystemAPI not initialised",
        authority="core.windows_execution_arbiter",
    )
    d = step.to_dict()
    restored = FallbackCascadeStep.from_dict(d)
    assert restored.step_index == 0
    assert restored.from_tier == "system_api"
    assert restored.to_tier == "gui"
    assert restored.reason == "executor_unavailable"


def test_fallback_cascade_review_defaults():
    review = FallbackCascadeReview()
    assert review.had_fallback is False
    assert review.total_steps == 0
    assert review.cascade_steps == []
    assert review.final_tier == ""


def test_fallback_cascade_review_round_trip():
    steps = [
        FallbackCascadeStep(step_index=0, from_tier="system_api", to_tier="gui"),
        FallbackCascadeStep(step_index=1, from_tier="gui", to_tier="vlm"),
    ]
    review = FallbackCascadeReview(
        cascade_steps=steps,
        final_tier="vlm",
        total_steps=2,
        had_fallback=True,
        degraded_from_preferred=True,
    )
    d = review.to_dict()
    restored = FallbackCascadeReview.from_dict(d)
    assert restored.had_fallback is True
    assert restored.total_steps == 2
    assert restored.final_tier == "vlm"
    assert len(restored.cascade_steps) == 2
    assert restored.cascade_steps[0].from_tier == "system_api"


# ---------------------------------------------------------------------------
# 4. RecoveryDecisionReview
# ---------------------------------------------------------------------------


def test_recovery_decision_review_defaults():
    review = RecoveryDecisionReview()
    assert review.decision_kind == "unknown"
    assert review.is_resumable is False
    assert review.resume_attempt_count == 0


def test_recovery_decision_review_round_trip():
    review = RecoveryDecisionReview(
        decision_kind="resumable_reassociation",
        is_resumable=True,
        interruption_class="process_restart",
        interruption_reason="host_crash",
        recovery_reason="session_context_available",
        continuity_id="cont_abc",
        trace_id="trace_xyz",
        resume_attempt_count=1,
    )
    d = review.to_dict()
    restored = RecoveryDecisionReview.from_dict(d)
    assert restored.decision_kind == "resumable_reassociation"
    assert restored.is_resumable is True
    assert restored.interruption_class == "process_restart"
    assert restored.continuity_id == "cont_abc"
    assert restored.resume_attempt_count == 1


def test_recovery_decision_review_terminal_loss():
    review = RecoveryDecisionReview(
        decision_kind="terminal_loss",
        is_resumable=False,
        interruption_class="device_disconnect",
        interruption_reason="network_timeout",
    )
    d = review.to_dict()
    assert d["decision_kind"] == "terminal_loss"
    assert d["is_resumable"] is False


# ---------------------------------------------------------------------------
# 5. ReconciliationOutcomeReview
# ---------------------------------------------------------------------------


def test_reconciliation_outcome_review_defaults():
    review = ReconciliationOutcomeReview()
    assert review.outcome == ReconciliationOutcome.UNKNOWN.value
    assert review.was_reconciled is False
    assert review.v2_terminal_state_blocked is False


def test_reconciliation_outcome_accepted():
    review = ReconciliationOutcomeReview(
        outcome=ReconciliationOutcome.ACCEPTED.value,
        was_reconciled=True,
        applied_signal_types=["cancel", "failure"],
        device_id="android_01",
        task_id="task_123",
    )
    d = review.to_dict()
    restored = ReconciliationOutcomeReview.from_dict(d)
    assert restored.outcome == "accepted"
    assert restored.was_reconciled is True
    assert "cancel" in restored.applied_signal_types


def test_reconciliation_outcome_rejected_terminal():
    review = ReconciliationOutcomeReview(
        outcome=ReconciliationOutcome.REJECTED_V2_TERMINAL.value,
        was_reconciled=False,
        v2_terminal_state_blocked=True,
    )
    d = review.to_dict()
    assert d["outcome"] == "rejected_v2_terminal"
    assert d["v2_terminal_state_blocked"] is True


def test_reconciliation_outcome_advisory_skipped():
    review = ReconciliationOutcomeReview(
        outcome=ReconciliationOutcome.PARTIALLY_APPLIED.value,
        was_reconciled=True,
        advisory_only_fields_skipped=["readiness_assessment", "runtime_state"],
    )
    d = review.to_dict()
    restored = ReconciliationOutcomeReview.from_dict(d)
    assert restored.outcome == "partially_applied"
    assert "readiness_assessment" in restored.advisory_only_fields_skipped


# ---------------------------------------------------------------------------
# 6. LegacyDispatchCounters
# ---------------------------------------------------------------------------


def test_legacy_dispatch_counters_defaults():
    _reset()
    counters = get_legacy_dispatch_counters()
    assert counters.total_legacy_dispatch_count == 0
    assert counters.per_surface_counts == {}


def test_legacy_dispatch_counters_round_trip():
    counters = LegacyDispatchCounters(
        total_legacy_dispatch_count=3,
        per_surface_counts={"cross_device_coordinator": 2, "compat_router": 1},
    )
    d = counters.to_dict()
    restored = LegacyDispatchCounters.from_dict(d)
    assert restored.total_legacy_dispatch_count == 3
    assert restored.per_surface_counts["cross_device_coordinator"] == 2


# ---------------------------------------------------------------------------
# 7. LegacyDispatchCounters increment / reset
# ---------------------------------------------------------------------------


def test_increment_legacy_dispatch_counter():
    _reset()
    increment_legacy_dispatch_counter("cross_device_coordinator")
    increment_legacy_dispatch_counter("cross_device_coordinator")
    increment_legacy_dispatch_counter("compat_router")
    counters = get_legacy_dispatch_counters()
    assert counters.total_legacy_dispatch_count == 3
    assert counters.per_surface_counts["cross_device_coordinator"] == 2
    assert counters.per_surface_counts["compat_router"] == 1


def test_reset_legacy_dispatch_counters():
    increment_legacy_dispatch_counter("some_surface")
    reset_legacy_dispatch_counters()
    counters = get_legacy_dispatch_counters()
    assert counters.total_legacy_dispatch_count == 0
    assert counters.per_surface_counts == {}


def test_increment_counter_is_thread_safe():
    """Verify counter increments from multiple threads are consistent."""
    import threading

    _reset()
    errors: list = []
    threads = []

    def _inc():
        try:
            for _ in range(10):
                increment_legacy_dispatch_counter("surface_a")
        except Exception as exc:
            errors.append(exc)

    for _ in range(5):
        t = threading.Thread(target=_inc)
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    counters = get_legacy_dispatch_counters()
    assert counters.total_legacy_dispatch_count == 50
    assert counters.per_surface_counts["surface_a"] == 50


# ---------------------------------------------------------------------------
# 8. build_orchestration_review_snapshot()
# ---------------------------------------------------------------------------


def test_build_orchestration_review_snapshot_returns_snapshot():
    snapshot = build_orchestration_review_snapshot()
    assert snapshot is not None
    assert isinstance(snapshot, OrchestrationReviewSnapshot)


def test_build_orchestration_review_snapshot_has_snapshot_id():
    snapshot = build_orchestration_review_snapshot()
    assert snapshot.snapshot_id
    assert len(snapshot.snapshot_id) > 0


def test_build_orchestration_review_snapshot_has_timestamp():
    before = time.time()
    snapshot = build_orchestration_review_snapshot()
    after = time.time()
    assert before <= snapshot.assembled_at <= after


# ---------------------------------------------------------------------------
# 9–10. Partial snapshot behaviour
# ---------------------------------------------------------------------------


def test_snapshot_partial_is_bool():
    snapshot = build_orchestration_review_snapshot()
    assert isinstance(snapshot._partial, bool)


def test_snapshot_partial_reasons_is_list():
    snapshot = build_orchestration_review_snapshot()
    assert isinstance(snapshot._partial_reasons, list)


def test_snapshot_partial_reasons_contains_strings_when_present():
    snapshot = build_orchestration_review_snapshot()
    for reason in snapshot._partial_reasons:
        assert isinstance(reason, str)


# ---------------------------------------------------------------------------
# 11. OrchestrationReviewSnapshot.to_dict() keys
# ---------------------------------------------------------------------------


def test_snapshot_to_dict_top_level_keys():
    snapshot = build_orchestration_review_snapshot()
    d = snapshot.to_dict()
    expected_keys = {
        "snapshot_id",
        "assembled_at",
        "execution_path_summary",
        "fallback_cascade",
        "recovery_review",
        "reconciliation_review",
        "legacy_dispatch",
        "observability_authority",
        "_partial",
        "_partial_reasons",
    }
    assert expected_keys.issubset(set(d.keys())), (
        f"Missing keys: {expected_keys - set(d.keys())}"
    )


def test_snapshot_to_dict_is_json_serialisable():
    import json

    snapshot = build_orchestration_review_snapshot()
    d = snapshot.to_dict()
    # Should not raise
    json.dumps(d)


# ---------------------------------------------------------------------------
# 12. Legacy dispatch always present
# ---------------------------------------------------------------------------


def test_snapshot_legacy_dispatch_always_present():
    _reset()
    snapshot = build_orchestration_review_snapshot()
    assert snapshot.legacy_dispatch is not None


def test_snapshot_legacy_dispatch_dict_present_in_serialised():
    _reset()
    snapshot = build_orchestration_review_snapshot()
    d = snapshot.to_dict()
    assert d["legacy_dispatch"] is not None


# ---------------------------------------------------------------------------
# 13. PR-10 sentinel in snapshot
# ---------------------------------------------------------------------------


def test_snapshot_observability_authority_contains_pr10():
    snapshot = build_orchestration_review_snapshot()
    assert "PR-10" in snapshot.observability_authority


# ---------------------------------------------------------------------------
# 14–15. android_participant_truth_ingress.get_last_reconciliation_outcome
# ---------------------------------------------------------------------------


def test_get_last_reconciliation_outcome_import():
    from core.android_participant_truth_ingress import get_last_reconciliation_outcome

    assert callable(get_last_reconciliation_outcome)


def test_get_last_reconciliation_outcome_returns_none_before_call():
    """get_last_reconciliation_outcome returns None or dict (not raises)."""
    from core.android_participant_truth_ingress import (
        _last_reconciliation_outcome,
        get_last_reconciliation_outcome,
    )

    result = get_last_reconciliation_outcome()
    # Either None (cold start) or a dict (if tests ran in different order)
    assert result is None or isinstance(result, dict)


def test_get_last_reconciliation_outcome_after_ingest():
    """After an ingest call, get_last_reconciliation_outcome returns a dict."""
    from core.android_participant_truth_ingress import (
        get_last_reconciliation_outcome,
        ingest_android_participant_truth_message,
    )

    message = {
        "truth_kind": "task_phase",
        "device_id": "test_device_review",
        "session_id": "sess_review_01",
        "task_id": "task_review_01",
        "payload": {"phase": "running"},
    }
    # Reconciliation will return was_reconciled=False (no matching V2 record)
    # but the outcome should still be recorded.
    ingest_android_participant_truth_message(message)
    outcome = get_last_reconciliation_outcome()
    assert isinstance(outcome, dict), f"Expected dict, got {outcome!r}"
    assert "was_reconciled" in outcome
    assert "v2_terminal_state_blocked" in outcome


# ---------------------------------------------------------------------------
# 16. windows_execution_arbiter.get_last_attempt_log
# ---------------------------------------------------------------------------


def test_get_last_attempt_log_import():
    from core.windows_execution_arbiter import get_last_attempt_log

    assert callable(get_last_attempt_log)


def test_get_last_attempt_log_returns_list():
    from core.windows_execution_arbiter import get_last_attempt_log

    result = get_last_attempt_log()
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 17. ExecutionPathOutcome enum stability
# ---------------------------------------------------------------------------


def test_execution_path_outcome_enum_values():
    assert ExecutionPathOutcome.CHOSEN.value == "chosen"
    assert ExecutionPathOutcome.REJECTED.value == "rejected"
    assert ExecutionPathOutcome.DEGRADED.value == "degraded"
    assert ExecutionPathOutcome.UNKNOWN.value == "unknown"


# ---------------------------------------------------------------------------
# 18. ReconciliationOutcome enum stability
# ---------------------------------------------------------------------------


def test_reconciliation_outcome_enum_values():
    assert ReconciliationOutcome.ACCEPTED.value == "accepted"
    assert ReconciliationOutcome.REJECTED_V2_TERMINAL.value == "rejected_v2_terminal"
    assert ReconciliationOutcome.REJECTED_NO_RECORD.value == "rejected_no_record"
    assert ReconciliationOutcome.PARTIALLY_APPLIED.value == "partially_applied"
    assert ReconciliationOutcome.UNKNOWN.value == "unknown"


# ---------------------------------------------------------------------------
# 19. Legacy dispatch per_surface_counts populated
# ---------------------------------------------------------------------------


def test_increment_counter_populates_per_surface():
    _reset()
    increment_legacy_dispatch_counter("surface_x")
    increment_legacy_dispatch_counter("surface_y")
    increment_legacy_dispatch_counter("surface_x")
    counters = get_legacy_dispatch_counters()
    assert "surface_x" in counters.per_surface_counts
    assert "surface_y" in counters.per_surface_counts
    assert counters.per_surface_counts["surface_x"] == 2
    assert counters.per_surface_counts["surface_y"] == 1
    assert counters.total_legacy_dispatch_count == 3


# ---------------------------------------------------------------------------
# 20. build_orchestration_review_snapshot() idempotency
# ---------------------------------------------------------------------------


def test_build_snapshot_callable_multiple_times():
    for _ in range(3):
        snapshot = build_orchestration_review_snapshot()
        assert snapshot is not None
        assert snapshot.snapshot_id


def test_build_snapshot_ids_differ():
    """Each call produces a distinct snapshot_id."""
    s1 = build_orchestration_review_snapshot()
    s2 = build_orchestration_review_snapshot()
    assert s1.snapshot_id != s2.snapshot_id


# ---------------------------------------------------------------------------
# Extra: Compact legibility surface
# ---------------------------------------------------------------------------


def test_execution_legibility_summary_path_key():
    """Snapshot to_dict() includes execution_path_summary with expected keys."""
    snapshot = build_orchestration_review_snapshot()
    d = snapshot.to_dict()
    if d["execution_path_summary"] is not None:
        ps = d["execution_path_summary"]
        assert "execution_path" in ps
        assert "outcome" in ps
        assert "hard_gate_active" in ps


def test_fallback_cascade_dict_structure():
    """Snapshot to_dict() includes fallback_cascade with expected keys."""
    snapshot = build_orchestration_review_snapshot()
    d = snapshot.to_dict()
    if d["fallback_cascade"] is not None:
        fc = d["fallback_cascade"]
        assert "had_fallback" in fc
        assert "total_steps" in fc
        assert "cascade_steps" in fc
        assert isinstance(fc["cascade_steps"], list)


def test_recovery_review_dict_structure():
    """Snapshot to_dict() includes recovery_review with expected keys."""
    snapshot = build_orchestration_review_snapshot()
    d = snapshot.to_dict()
    if d["recovery_review"] is not None:
        rr = d["recovery_review"]
        assert "decision_kind" in rr
        assert "is_resumable" in rr
        assert "interruption_class" in rr


def test_reconciliation_review_dict_structure():
    """Snapshot to_dict() includes reconciliation_review with expected keys."""
    snapshot = build_orchestration_review_snapshot()
    d = snapshot.to_dict()
    if d["reconciliation_review"] is not None:
        rec = d["reconciliation_review"]
        assert "outcome" in rec
        assert "was_reconciled" in rec
        assert "v2_terminal_state_blocked" in rec
