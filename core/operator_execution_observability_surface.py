"""core/operator_execution_observability_surface.py
====================================================
PR-4: Operator Execution Observability Surface — aggregates execution evidence
and canonical result truth state into a unified operator-facing snapshot.

Background
----------
Prior to this module, operator surfaces (dashboard, board, projection) had to
reconstruct execution state from multiple independent subsystem snapshots:

- Truth chain completion from :mod:`core.task_result_canonical_truth_chain`
- Takeover proof quality from :mod:`core.ownership_transfer_proof_quality`
- Governance audit from :mod:`core.execution_governance_audit_authority`
- Android evidence pipeline from :mod:`core.android_evidence_integration_pipeline`

Each subsystem exposed its own schema with no unified surface that answered the
operator question:

    "What actually executed, how trustworthy is the evidence, which result is
    canonical, and does the runtime-visible state reflect that truth consistently?"

This module closes that gap by providing:

1. :class:`OperatorExecutionEvidenceEntry` — a per-task execution evidence
   snapshot that surfaces the canonical evidence state, trust level, acceptance
   verdict, truth chain completeness, and operator-visible warnings.

2. :class:`OperatorExecutionObservabilitySnapshot` — the top-level snapshot
   aggregating the recent execution evidence ring buffer, acceptance summary
   (how many accepted vs provisional vs quarantine vs rejected), and
   cross-repo integration status.

3. :func:`build_operator_execution_observability_snapshot` — the primary
   builder that aggregates evidence from the incomplete-result ledger, recent
   result ingress outcomes, and takeover tracking into a unified snapshot.

4. :func:`get_latest_operator_evidence_entry_for_task` — lookup helper for a
   single task_id.

Design principles
-----------------
- **Operator-aligned** — the snapshot answers operator questions in operator
  language, not internal system vocabulary.
- **Read-only** — does not mutate any system state; safe to call at any time.
- **Non-raising** — all public functions catch and log, returning partial
  snapshots rather than raising.
- **Board/projection aligned** — the snapshot is designed to be consumed
  directly by operator board renderers and projection endpoints without
  further translation.

Android integration points
--------------------------
The operator surface identifies the Android-side evidence quality by reading:
- Takeover tracking records (:mod:`core.takeover_tracking`)
- Ownership transfer proof quality (:mod:`core.ownership_transfer_proof_quality`)
- The incomplete result ledger (:func:`~core.task_result_canonical_truth_chain.get_incomplete_result_ledger`)

For cross-repo completeness, the snapshot includes a ``cross_repo_integration``
block identifying whether Android-side proof class fields (from
``DelegatedRuntimeUnit.kt``) are being received.

Authority sentinel
------------------
``OPERATOR_EXECUTION_OBSERVABILITY_SENTINEL`` — import to assert this module
is the canonical operator execution observability surface.

Public API
----------
Sentinels::

    OPERATOR_EXECUTION_OBSERVABILITY_SENTINEL
    OPERATOR_EXECUTION_OBSERVABILITY_CONTRACT_VERSION

Dataclasses::

    OperatorExecutionEvidenceEntry
    OperatorExecutionObservabilitySnapshot

Functions::

    build_operator_execution_observability_snapshot(*, max_entries, device_id) -> OperatorExecutionObservabilitySnapshot
    get_latest_operator_evidence_entry_for_task(task_id) -> Optional[OperatorExecutionEvidenceEntry]
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.OperatorExecutionObservabilitySurface")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

OPERATOR_EXECUTION_OBSERVABILITY_SENTINEL: str = (
    "OPERATOR_EXECUTION_OBSERVABILITY_SURFACE_V1: "
    "core/operator_execution_observability_surface.py is the canonical operator "
    "execution observability surface.  Board renderers, projection endpoints, and "
    "operator dashboards MUST consume execution evidence state from "
    "build_operator_execution_observability_snapshot() rather than deriving it "
    "from multiple subsystem snapshots independently."
)

OPERATOR_EXECUTION_OBSERVABILITY_CONTRACT_VERSION: str = "4.0.0"


# ---------------------------------------------------------------------------
# OperatorExecutionEvidenceEntry
# ---------------------------------------------------------------------------

@dataclass
class OperatorExecutionEvidenceEntry:
    """Per-task execution evidence snapshot for operator consumption.

    Attributes
    ----------
    task_id
        The canonical task identifier.
    device_id
        The device that produced the result (empty for local-only).
    evidence_state
        Human-readable execution evidence state string (e.g. ``completed_strong``).
    trust_level
        Human-readable trust level (``trusted`` / ``provisional`` / ``quarantine``
        / ``rejected``).
    acceptance_verdict
        The acceptance gate decision (``accept`` / ``accept_provisional`` /
        ``quarantine`` / ``reject``).
    truth_chain_complete
        Whether the four-step truth chain completed for this task.
    operator_warning
        Whether an operator-visible warning flag should be displayed.
    android_proof_class
        The Android-side proof class from the result message (empty if absent).
    source_channel
        The result ingress channel name.
    diagnosis
        List of machine-readable diagnostic tokens.
    classified_at
        Unix epoch when the evidence was classified.
    """

    task_id: str = ""
    device_id: str = ""
    evidence_state: str = ""
    trust_level: str = ""
    acceptance_verdict: str = ""
    truth_chain_complete: bool = False
    operator_warning: bool = False
    android_proof_class: str = ""
    source_channel: str = ""
    diagnosis: List[str] = field(default_factory=list)
    classified_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "device_id": self.device_id,
            "evidence_state": self.evidence_state,
            "trust_level": self.trust_level,
            "acceptance_verdict": self.acceptance_verdict,
            "truth_chain_complete": self.truth_chain_complete,
            "operator_warning": self.operator_warning,
            "android_proof_class": self.android_proof_class,
            "source_channel": self.source_channel,
            "diagnosis": list(self.diagnosis),
            "classified_at": self.classified_at,
        }

    @property
    def is_canonical_truth(self) -> bool:
        """True iff this entry represents a canonically accepted result."""
        return self.acceptance_verdict == "accept"

    @property
    def requires_operator_attention(self) -> bool:
        """True iff operator intervention or review is indicated."""
        return self.operator_warning or self.acceptance_verdict in (
            "quarantine", "reject"
        )


# ---------------------------------------------------------------------------
# OperatorExecutionObservabilitySnapshot
# ---------------------------------------------------------------------------

@dataclass
class OperatorExecutionObservabilitySnapshot:
    """Top-level operator execution observability snapshot.

    Attributes
    ----------
    assembled_at
        Unix epoch when the snapshot was assembled.
    entries
        List of :class:`OperatorExecutionEvidenceEntry` for recent tasks,
        most recent first.
    acceptance_summary
        Dict with counts: ``accepted``, ``provisional``, ``quarantine``,
        ``rejected``, ``incomplete_truth_chain``.
    incomplete_result_count
        Number of tasks in the incomplete result ledger (truth chain not closed).
    cross_repo_integration
        Dict describing Android-side integration status and whether proof class
        fields are being received.
    schema_version
        Module contract version for consumer compatibility checks.
    """

    assembled_at: float = field(default_factory=time.time)
    entries: List[OperatorExecutionEvidenceEntry] = field(default_factory=list)
    acceptance_summary: Dict[str, int] = field(default_factory=dict)
    incomplete_result_count: int = 0
    cross_repo_integration: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = OPERATOR_EXECUTION_OBSERVABILITY_CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "assembled_at": self.assembled_at,
            "entries": [e.to_dict() for e in self.entries],
            "acceptance_summary": dict(self.acceptance_summary),
            "incomplete_result_count": self.incomplete_result_count,
            "cross_repo_integration": dict(self.cross_repo_integration),
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# Process-local evidence ring buffer
# ---------------------------------------------------------------------------

_EVIDENCE_RING_MAX = 200
_evidence_ring: List[OperatorExecutionEvidenceEntry] = []


def _push_to_evidence_ring(entry: OperatorExecutionEvidenceEntry) -> None:
    """Add an entry to the process-local evidence ring buffer."""
    global _evidence_ring
    _evidence_ring.append(entry)
    if len(_evidence_ring) > _EVIDENCE_RING_MAX:
        _evidence_ring = _evidence_ring[-_EVIDENCE_RING_MAX:]


def record_operator_evidence_entry(
    *,
    task_id: str,
    device_id: str = "",
    evidence_state: str = "",
    trust_level: str = "",
    acceptance_verdict: str = "",
    truth_chain_complete: bool = False,
    operator_warning: bool = False,
    android_proof_class: str = "",
    source_channel: str = "",
    diagnosis: Optional[List[str]] = None,
) -> OperatorExecutionEvidenceEntry:
    """Record an execution evidence entry to the process-local ring buffer.

    This is the write API called by :mod:`core.unified_result_ingress` after
    the evidence gate step completes.  Downstream consumers (board renderers,
    projection endpoints) read from this ring via
    :func:`build_operator_execution_observability_snapshot`.
    """
    entry = OperatorExecutionEvidenceEntry(
        task_id=task_id,
        device_id=device_id,
        evidence_state=evidence_state,
        trust_level=trust_level,
        acceptance_verdict=acceptance_verdict,
        truth_chain_complete=truth_chain_complete,
        operator_warning=operator_warning,
        android_proof_class=android_proof_class,
        source_channel=source_channel,
        diagnosis=list(diagnosis or []),
        classified_at=time.time(),
    )
    _push_to_evidence_ring(entry)
    return entry


# ---------------------------------------------------------------------------
# build_operator_execution_observability_snapshot
# ---------------------------------------------------------------------------

def build_operator_execution_observability_snapshot(
    *,
    max_entries: int = 50,
    device_id: Optional[str] = None,
) -> OperatorExecutionObservabilitySnapshot:
    """Build the operator execution observability snapshot.

    Aggregates:
    1. The process-local evidence ring buffer (from result ingress)
    2. The incomplete result ledger (from truth chain)
    3. Android-side integration health (proof class field presence)

    Parameters
    ----------
    max_entries:
        Maximum number of recent entries to include in the snapshot.
    device_id:
        Optional filter to include only entries for a specific device.

    Returns
    -------
    OperatorExecutionObservabilitySnapshot
    """
    try:
        # Filter entries
        entries = list(reversed(_evidence_ring))
        if device_id:
            entries = [e for e in entries if e.device_id == device_id]
        entries = entries[:max_entries]

        # Acceptance summary
        summary: Dict[str, int] = {
            "accepted": 0,
            "provisional": 0,
            "quarantine": 0,
            "rejected": 0,
            "incomplete_truth_chain": 0,
        }
        for e in entries:
            v = e.acceptance_verdict
            if v == "accept":
                summary["accepted"] += 1
            elif v == "accept_provisional":
                summary["provisional"] += 1
            elif v == "quarantine":
                summary["quarantine"] += 1
            elif v == "reject":
                summary["rejected"] += 1
            if not e.truth_chain_complete:
                summary["incomplete_truth_chain"] += 1

        # Incomplete result ledger count
        incomplete_count = _get_incomplete_result_count()

        # Cross-repo integration status
        cross_repo = _build_cross_repo_integration_status(entries)

        return OperatorExecutionObservabilitySnapshot(
            assembled_at=time.time(),
            entries=entries,
            acceptance_summary=summary,
            incomplete_result_count=incomplete_count,
            cross_repo_integration=cross_repo,
            schema_version=OPERATOR_EXECUTION_OBSERVABILITY_CONTRACT_VERSION,
        )

    except Exception as exc:
        logger.warning(
            "operator_execution_observability: build_snapshot failed: %s", exc
        )
        return OperatorExecutionObservabilitySnapshot(
            assembled_at=time.time(),
            cross_repo_integration={"error": str(exc)},
        )


# ---------------------------------------------------------------------------
# get_latest_operator_evidence_entry_for_task
# ---------------------------------------------------------------------------

def get_latest_operator_evidence_entry_for_task(
    task_id: str,
) -> Optional[OperatorExecutionEvidenceEntry]:
    """Return the most recent evidence entry for a given task_id, or None."""
    for entry in reversed(_evidence_ring):
        if entry.task_id == task_id:
            return entry
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_incomplete_result_count() -> int:
    """Return the count of incomplete results from the truth-chain ledger."""
    try:
        from core.task_result_canonical_truth_chain import get_incomplete_result_ledger
        ledger = get_incomplete_result_ledger()
        return len(ledger.snapshot())
    except Exception as exc:
        logger.debug(
            "operator_execution_observability: incomplete_result_ledger unavailable: %s",
            exc,
        )
        return 0


def _build_cross_repo_integration_status(
    entries: List[OperatorExecutionEvidenceEntry],
) -> Dict[str, Any]:
    """Build the cross-repo Android integration status block.

    Checks whether recent Android-originating entries have android_proof_class
    populated (indicating DelegatedRuntimeUnit.kt has been updated to include
    the proof_class field in result messages).
    """
    android_entries = [
        e for e in entries
        if e.source_channel in ("canonical_ws", "compat_ws", "delegated", "replay")
    ]

    proof_class_present_count = sum(
        1 for e in android_entries if e.android_proof_class
    )
    proof_class_absent_count = len(android_entries) - proof_class_present_count

    # Check takeover tracking integration
    takeover_integration = _check_takeover_tracking_integration()

    android_integration_status: str
    if not android_entries:
        android_integration_status = "no_android_results_observed"
    elif proof_class_absent_count == 0:
        android_integration_status = "proof_class_present_all"
    elif proof_class_present_count == 0:
        android_integration_status = "proof_class_absent_all"
    else:
        android_integration_status = "proof_class_partially_present"

    return {
        "android_result_entries_in_snapshot": len(android_entries),
        "proof_class_present_count": proof_class_present_count,
        "proof_class_absent_count": proof_class_absent_count,
        "android_integration_status": android_integration_status,
        "android_integration_note": (
            "DelegatedRuntimeUnit.kt must include 'proof_class' field in result "
            "messages for full evidence quality classification.  "
            "See DELEGATED_RESULT_PROOF_CLASS_POLICY in "
            "core/execution_evidence_model.py."
            if proof_class_absent_count > 0
            else "Android proof class fields received correctly."
        ),
        "takeover_tracking": takeover_integration,
        "android_repo_integration_points": [
            "agent/DelegatedRuntimeUnit.kt: add proof_class field to result messages",
            "agent/AutonomousExecutionPipeline.kt: add execution_source field",
            "agent/DelegatedTakeoverExecutor.kt: set takeover_confirmed and evidence_quality",
        ],
    }


def _check_takeover_tracking_integration() -> Dict[str, Any]:
    """Check whether takeover tracking is functional and has recent records."""
    try:
        from core.takeover_tracking import get_takeover_tracking_runtime
        runtime = get_takeover_tracking_runtime()
        records = runtime.snapshot()
        return {
            "available": True,
            "recent_record_count": len(records[:10]),
        }
    except Exception as exc:
        return {
            "available": False,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "OPERATOR_EXECUTION_OBSERVABILITY_SENTINEL",
    "OPERATOR_EXECUTION_OBSERVABILITY_CONTRACT_VERSION",
    # Dataclasses
    "OperatorExecutionEvidenceEntry",
    "OperatorExecutionObservabilitySnapshot",
    # Functions
    "build_operator_execution_observability_snapshot",
    "get_latest_operator_evidence_entry_for_task",
    "record_operator_evidence_entry",
]
