from __future__ import annotations

import time
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


def build_continuity_adjudication_evidence(
    *,
    classification: ContinuityAdjudicationClassification | str,
    triggering_reason: str,
    epoch_session_basis: Optional[Dict[str, Any]] = None,
    related_identity: Optional[Dict[str, Any]] = None,
    decision_point: str = "",
) -> Dict[str, Any]:
    """Build structured continuity adjudication evidence for diagnostics/tests."""
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
