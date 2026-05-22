from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional


class ContinuityAdjudicationClassification(str, Enum):
    """Unified continuity adjudication vocabulary shared across runtime paths."""

    current_accepted = "current-accepted"
    stale_rejected = "stale-rejected"
    duplicate_ignored = "duplicate-ignored"
    reconnect_recovery_required = "reconnect-recovery-required"
    replay_reconciliation_required = "replay-reconciliation-required"
    abandoned_or_superseded = "abandoned-or-superseded"


@dataclass(frozen=True)
class ContinuityPolicyDecision:
    """Minimal control-plane policy decision contract shared by runtime paths."""

    classification: str
    triggering_reason: str
    completion_disposition: str = ""
    decision: str = ""
    action: str = ""
    should_fail: bool = False


_RECONNECT_PENDING_DECISION_CLASSIFICATION = {
    "resume_existing_execution": ContinuityAdjudicationClassification.reconnect_recovery_required.value,
    "request_replay_reconciliation": ContinuityAdjudicationClassification.replay_reconciliation_required.value,
    "trigger_failover": ContinuityAdjudicationClassification.abandoned_or_superseded.value,
    "closure_already_decided": ContinuityAdjudicationClassification.abandoned_or_superseded.value,
    "mark_abandoned_stale": ContinuityAdjudicationClassification.abandoned_or_superseded.value,
}


def adjudicate_continuity_legality_gate(
    *,
    should_block: bool,
    verdict: str,
) -> ContinuityPolicyDecision:
    if should_block:
        return ContinuityPolicyDecision(
            classification=ContinuityAdjudicationClassification.replay_reconciliation_required.value,
            triggering_reason=f"continuity_legality_verdict:{verdict}",
        )
    return ContinuityPolicyDecision(
        classification=ContinuityAdjudicationClassification.current_accepted.value,
        triggering_reason="continuity_legality_gate_passed",
    )


def adjudicate_stale_vs_current(
    *,
    is_stale: bool,
    stale_classification: str = "",
    stale_reason: str = "",
) -> ContinuityPolicyDecision:
    if is_stale:
        reason = str(stale_reason or "").strip() or f"stale_classification:{stale_classification}"
        return ContinuityPolicyDecision(
            classification=ContinuityAdjudicationClassification.stale_rejected.value,
            triggering_reason=reason,
            completion_disposition="stale_rejected",
        )
    return ContinuityPolicyDecision(
        classification=ContinuityAdjudicationClassification.current_accepted.value,
        triggering_reason="stale_gate_passed",
        completion_disposition="first_accepted",
    )


def adjudicate_duplicate_vs_first_accepted(
    *,
    is_duplicate: bool,
) -> ContinuityPolicyDecision:
    if is_duplicate:
        return ContinuityPolicyDecision(
            classification=ContinuityAdjudicationClassification.duplicate_ignored.value,
            triggering_reason="joint_idempotency_duplicate",
            completion_disposition="duplicate_ignored",
        )
    return ContinuityPolicyDecision(
        classification=ContinuityAdjudicationClassification.current_accepted.value,
        triggering_reason="passed_continuity_stale_idempotency_gates",
        completion_disposition="first_accepted",
    )


def decide_reconnect_pending_policy(
    *,
    continuity_outcome: str,
    owner: str,
    is_timed_out: bool,
) -> ContinuityPolicyDecision:
    normalized_owner = str(owner or "").strip().lower()
    normalized_outcome = str(continuity_outcome or "").strip().lower()
    decision = "resume_existing_execution"
    action = "keep_pending_and_wait_for_result"
    reason = "continuity_resume_for_existing_execution"
    should_fail = False

    if is_timed_out:
        decision = "mark_abandoned_stale"
        action = "abandon_pending_envelope"
        reason = "pending_envelope_timed_out_before_reconnect_decision"
        should_fail = True
    elif normalized_owner == "result_completion":
        decision = "closure_already_decided"
        action = "abandon_pending_envelope"
        reason = "pending_record_already_at_result_completion_owner"
        should_fail = True
    elif normalized_outcome != "continuity_resume":
        if normalized_owner == "routing":
            decision = "request_replay_reconciliation"
            action = "fail_pending_for_replay"
            reason = "new_attachment_blocks_routing_stage_resume"
        else:
            decision = "trigger_failover"
            action = "fail_pending_for_failover"
            reason = f"new_attachment_blocks_{normalized_owner}_resume"
        should_fail = True
    elif normalized_owner == "routing":
        decision = "request_replay_reconciliation"
        action = "fail_pending_for_replay"
        reason = "reconnect_requires_routing_replay"
        should_fail = True
    elif normalized_owner == "gateway_ingress":
        decision = "trigger_failover"
        action = "fail_pending_for_failover"
        reason = "reconnect_requires_gateway_reissue_or_failover"
        should_fail = True

    classification = _RECONNECT_PENDING_DECISION_CLASSIFICATION.get(
        decision,
        ContinuityAdjudicationClassification.abandoned_or_superseded.value,
    )
    return ContinuityPolicyDecision(
        classification=classification,
        triggering_reason=reason,
        decision=decision,
        action=action,
        should_fail=should_fail,
    )


def build_continuity_adjudication_evidence(
    *,
    classification: ContinuityAdjudicationClassification | str,
    triggering_reason: str,
    epoch_session_basis: Optional[Dict[str, Any]] = None,
    related_identity: Optional[Dict[str, Any]] = None,
    decision_point: str = "",
) -> Dict[str, Any]:
    """Build structured continuity adjudication evidence for diagnostics/tests.

    Parameters
    ----------
    classification:
        Unified continuity adjudication state (or equivalent string).
    triggering_reason:
        Human-readable reason that caused this classification.
    epoch_session_basis:
        Relevant session/epoch basis used during adjudication
        (for example ``session_epoch`` or reconnect continuity outcome).
    related_identity:
        Minimal task/envelope/result identity involved in this decision.
    decision_point:
        Runtime decision point identifier (for example ingress stale gate).
    """
    normalized_classification = (
        classification.value
        if isinstance(classification, ContinuityAdjudicationClassification)
        else str(classification)
    )
    return {
        "classification": normalized_classification,
        "triggering_reason": str(triggering_reason or ""),
        "epoch_session_basis": dict(epoch_session_basis or {}),
        "related_identity": dict(related_identity or {}),
        "decision_point": str(decision_point or ""),
        "adjudicated_at": time.time(),
    }
