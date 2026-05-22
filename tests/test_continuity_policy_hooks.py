from __future__ import annotations

import time

from core.continuity_adjudication import (
    ContinuityAdjudicationClassification,
    ContinuityPolicyDecision,
    adjudicate_continuity_legality_gate,
    adjudicate_duplicate_vs_first_accepted,
    adjudicate_stale_vs_current,
    decide_reconnect_pending_policy,
)


def test_continuity_policy_hooks_cover_key_adjudication_points() -> None:
    stale = adjudicate_stale_vs_current(
        is_stale=True,
        stale_classification="epoch_mismatch",
    )
    assert stale.classification == ContinuityAdjudicationClassification.stale_rejected.value
    assert stale.completion_disposition == "stale_rejected"

    duplicate = adjudicate_duplicate_vs_first_accepted(is_duplicate=True)
    assert duplicate.classification == ContinuityAdjudicationClassification.duplicate_ignored.value
    assert duplicate.completion_disposition == "duplicate_ignored"

    replay_required = adjudicate_continuity_legality_gate(
        should_block=True,
        verdict="require_review",
    )
    assert (
        replay_required.classification
        == ContinuityAdjudicationClassification.replay_reconciliation_required.value
    )

    reconnect = decide_reconnect_pending_policy(
        continuity_outcome="new_attachment",
        owner="routing",
        is_timed_out=False,
    )
    assert (
        reconnect.classification
        == ContinuityAdjudicationClassification.replay_reconciliation_required.value
    )
    assert reconnect.decision == "request_replay_reconciliation"


def test_unified_result_ingress_duplicate_decision_uses_policy_hook(monkeypatch) -> None:
    from core import unified_result_ingress as uri

    ingress = uri.UnifiedResultIngress()
    ingress._check_continuity_legality = lambda e, mode: "allow"  # type: ignore[method-assign]
    ingress._check_idempotency = lambda e: True  # type: ignore[method-assign]
    ingress._record_idempotency = lambda e: None  # type: ignore[method-assign]

    def _hook(*, is_duplicate: bool) -> ContinuityPolicyDecision:
        assert is_duplicate is True
        return ContinuityPolicyDecision(
            classification=ContinuityAdjudicationClassification.duplicate_ignored.value,
            triggering_reason="test_policy_hook_duplicate_reason",
            completion_disposition="duplicate_ignored",
        )

    monkeypatch.setattr(uri, "adjudicate_duplicate_vs_first_accepted", _hook)
    event = uri.NormalizedResultEvent(
        task_id="hook-dup-task",
        device_id="hook-dup-device",
        raw_message_type="goal_execution_result",
        normalized_result_kind="goal_execution_result",
        normalized_status="completed",
        source_channel=uri.ResultSourceChannel.CANONICAL_WS,
        payload={},
        idempotency_key="hook-dup-task",
    )
    outcome = ingress.process(event)
    assert outcome.continuity_adjudication_classification == "duplicate-ignored"
    assert (
        outcome.continuity_adjudication_evidence["triggering_reason"]
        == "test_policy_hook_duplicate_reason"
    )


def test_reconnect_pending_lifecycle_uses_policy_hook_and_exposes_evidence(monkeypatch) -> None:
    from core.task_envelope_lifecycle_registry import (
        LifecycleOwner,
        PendingEnvelopeRecord,
        get_lifecycle_registry,
        reset_lifecycle_registry,
    )
    from galaxy_gateway.android.handlers import registration

    reset_lifecycle_registry()
    registry = get_lifecycle_registry()
    registry._pending["hook-reconnect-task"] = PendingEnvelopeRecord(
        task_id="hook-reconnect-task",
        trace_id="trace-hook-reconnect-task",
        target_device_id="hook-device",
        tool_name="test_tool",
        owner=LifecycleOwner.DEVICE_DISPATCH,
        timeout=30.0,
        registered_at=time.time(),
        future=None,
        metadata={},
    )

    def _hook(*, continuity_outcome: str, owner: str, is_timed_out: bool) -> ContinuityPolicyDecision:
        assert continuity_outcome == "continuity_resume"
        assert owner == "device_dispatch"
        assert is_timed_out is False
        return ContinuityPolicyDecision(
            classification=ContinuityAdjudicationClassification.reconnect_recovery_required.value,
            triggering_reason="test_policy_hook_reconnect_reason",
            decision="resume_existing_execution",
            action="keep_pending_and_wait_for_result",
            should_fail=False,
        )

    monkeypatch.setattr(registration, "decide_reconnect_pending_policy", _hook)
    decisions = registration._apply_pending_lifecycle_reconnect_decisions(
        device_id="hook-device",
        continuity_outcome="continuity_resume",
        delivery_replay_scheduled=False,
    )
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision["continuity_adjudication_classification"] == "reconnect-recovery-required"
    assert decision["reason"] == "test_policy_hook_reconnect_reason"
    assert (
        decision["continuity_adjudication"]["triggering_reason"]
        == "test_policy_hook_reconnect_reason"
    )
