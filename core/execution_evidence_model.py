"""core/execution_evidence_model.py
====================================
PR-4: Canonical Execution Evidence Model — defines and integrates a real
runtime evidence model for execution outcomes in the center-distributed system.

Background
----------
Prior to this module, the system had no single canonical representation of
*where an execution stands* from an evidence perspective.  Result ingress paths
could accept a result as "completed" regardless of whether the evidence behind
it was strong (confirmed by device, full lifecycle, no conflicts), degraded
(partial, stale, or inferred only), or absent.  This made it impossible for
downstream consumers — operator surfaces, board projections, governance gates —
to distinguish:

- a task that genuinely completed with verified evidence, from
- a task that produced a result message but whose evidence chain is incomplete,
- a task whose result is stale or superseded,
- a task whose result is a duplicate replay,
- a task that was started but never completed.

This module closes that gap by defining:

1. :class:`ExecutionEvidenceState` — an enum of 13 named evidence states
   covering the full lifecycle from planned-not-started through all terminal
   conditions.

2. :class:`EvidenceTrustLevel` — a four-value enum classifying a result's
   trustworthiness for downstream consumers:
   ``trusted`` / ``provisional`` / ``quarantine`` / ``rejected``.

3. :class:`ExecutionEvidenceRecord` — a typed, immutable record capturing the
   evidence state, trust level, source channel, device provenance, and a
   machine-readable diagnosis list for every evaluated result.

4. :func:`classify_execution_evidence` — the canonical mapping function that
   derives an :class:`EvidenceTrustLevel` from an :class:`ExecutionEvidenceState`
   and optional proof-quality signals.  This function is **the enforcement
   point**: downstream callers that previously accepted any result
   unconditionally now obtain an explicit trust verdict they can act on.

5. :func:`build_execution_evidence_record` — convenience constructor for
   creating :class:`ExecutionEvidenceRecord` instances from result event data.

Design principles
-----------------
- **Non-raising** — all public functions catch and log, returning a degraded
  result rather than raising.
- **Additive** — does not modify any existing module; layers cleanly on top
  of :mod:`core.unified_result_ingress`, :mod:`core.task_result_canonical_truth_chain`,
  and :mod:`core.ownership_transfer_proof_quality`.
- **Actionable** — :class:`EvidenceTrustLevel` directly gates downstream
  acceptance behaviour: ``trusted`` → accept, ``provisional`` → accept with
  operator warning, ``quarantine`` → hold for review, ``rejected`` → discard.
- **Runtime-path integrated** — :func:`classify_execution_evidence` is called
  inside :class:`~core.unified_result_ingress.UnifiedResultIngress` so every
  result event acquires an evidence trust verdict before state propagation.

Authority sentinel
------------------
``EXECUTION_EVIDENCE_MODEL_POLICY`` — import to assert this module is the
canonical execution evidence model for the center-distributed runtime.

``EXECUTION_EVIDENCE_MODEL_CONTRACT_VERSION`` — semver string for the model
contract.  Consumers can check this to detect schema changes.

Android integration points
--------------------------
The evidence states and their V2-side classification rely on signals originating
from the Android runtime:

- ``android_delegated`` and ``completed_strong`` states require a corresponding
  confirmed takeover record (from :mod:`core.takeover_tracking`) AND a passing
  proof quality (:mod:`core.ownership_transfer_proof_quality`
  ``confirmed_strong``).
- ``completed_degraded`` is assigned when evidence is present but the
  :class:`~core.ownership_transfer_proof_quality.OwnershipTransferProofClass`
  returns anything other than ``confirmed_strong``.
- ``stale_result`` requires cross-checking the result timestamp against the
  :class:`~core.takeover_tracking.TakeoverTrackingRecord` ``recorded_at``
  field; Android-side must emit timestamps reliably.
- ``duplicate_result`` relies on the idempotency key chain
  (:mod:`core.durable_result_idempotency`) populated when Android sends
  offline-replay result messages.

The Android-repo counterpart integration points (cross-repo):
- ``agent/DelegatedRuntimeUnit.kt`` must include a ``proof_class`` field in its
  result report (``DELEGATED_RESULT_PROOF_CLASS_POLICY``).
- ``agent/AutonomousExecutionPipeline.kt`` must populate ``execution_source``
  (``"local"`` / ``"android_delegated"`` / ``"hybrid"``) in result messages.
- ``agent/DelegatedTakeoverExecutor.kt`` must set ``takeover_confirmed=true``
  and ``evidence_quality`` fields on accepted takeover results.

Public API
----------
Sentinels::

    EXECUTION_EVIDENCE_MODEL_POLICY
    EXECUTION_EVIDENCE_MODEL_CONTRACT_VERSION
    DELEGATED_RESULT_PROOF_CLASS_POLICY

Policy constants::

    STALE_RESULT_THRESHOLD_SECONDS
    DUPLICATE_EVIDENCE_REJECTION_POLICY

Enums::

    ExecutionEvidenceState
    EvidenceTrustLevel

Dataclass::

    ExecutionEvidenceRecord

Functions::

    classify_execution_evidence(state, *, proof_class, is_duplicate, is_stale, ...) -> EvidenceTrustLevel
    build_execution_evidence_record(task_id, device_id, state, *, ...) -> ExecutionEvidenceRecord
    infer_execution_evidence_state(normalized_status, *, source_channel, truth_chain_complete, ...) -> ExecutionEvidenceState
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ExecutionEvidenceModel")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

EXECUTION_EVIDENCE_MODEL_POLICY: str = (
    "EXECUTION_EVIDENCE_MODEL_V1: core/execution_evidence_model.py is the "
    "canonical execution evidence model for the center-distributed runtime.  "
    "ALL result ingress paths MUST classify their execution evidence using "
    "classify_execution_evidence() and surface the resulting EvidenceTrustLevel "
    "in their outcome objects.  A result MUST NOT be treated as canonically "
    "accepted (trusted) unless its EvidenceTrustLevel is 'trusted'.  "
    "Results with trust level 'provisional' MUST be flagged to operator surfaces.  "
    "Results with trust level 'quarantine' MUST be held for review and MUST NOT "
    "propagate to user-facing problem closure.  "
    "Results with trust level 'rejected' MUST be discarded."
)

EXECUTION_EVIDENCE_MODEL_CONTRACT_VERSION: str = "4.0.0"

DELEGATED_RESULT_PROOF_CLASS_POLICY: str = (
    "POLICY::DELEGATED_RESULT_PROOF_CLASS: "
    "Android-side result messages from DelegatedRuntimeUnit, "
    "AutonomousExecutionPipeline, and DelegatedTakeoverExecutor MUST include "
    "a 'proof_class' field ('confirmed_strong' / 'degraded_partial' / "
    "'degraded_stale' / 'degraded_conflicting' / 'incomplete') and an "
    "'execution_source' field ('local' / 'android_delegated' / 'hybrid').  "
    "V2 uses these fields to classify ExecutionEvidenceState and derive "
    "EvidenceTrustLevel.  Absence of these fields results in "
    "EvidenceTrustLevel.provisional with a diagnosis token of "
    "'android_proof_class_absent'."
)

DUPLICATE_EVIDENCE_REJECTION_POLICY: str = (
    "POLICY::DUPLICATE_EVIDENCE_REJECTION: "
    "A result whose idempotency key has already been processed MUST be classified "
    "as ExecutionEvidenceState.duplicate_result and MUST receive "
    "EvidenceTrustLevel.rejected.  Duplicate results MUST NOT advance canonical "
    "task lifecycle state or notify completion awaiters."
)

# Default staleness threshold: evidence older than this (seconds) is classified as stale.
# 5 minutes is chosen as a balance between accepting delayed Android result messages
# (common in offline/replay scenarios) and rejecting genuinely stale evidence.
# This threshold applies to ownership-transfer evidence age in TakeoverTrackingRecord.
STALE_RESULT_THRESHOLD_SECONDS: float = 300.0


# ---------------------------------------------------------------------------
# ExecutionEvidenceState
# ---------------------------------------------------------------------------


class ExecutionEvidenceState(str, Enum):
    """Canonical execution evidence states for center-distributed task outcomes.

    These states represent where in the execution and evidence lifecycle a task
    result stands.  They are not task-queue lifecycle states (QUEUED / RUNNING /
    DONE) — they are evidence-quality states that affect downstream acceptance.

    Values
    ------
    planned_not_started
        Task was dispatched / planned but no execution evidence has been
        received yet.
    started
        Execution start evidence received (in-progress signal from device or
        local executor).
    locally_executed
        Task was executed locally on the V2 host; no Android delegation.
    android_delegated
        Task was delegated to an Android device and execution evidence has been
        received from that device, but canonical proof quality has not yet been
        confirmed.
    partially_completed
        Execution began but only partial results were returned (e.g. a step
        result with no final closure).
    completed_strong
        Execution completed AND canonical proof quality is confirmed_strong.
        This is the only state that maps to EvidenceTrustLevel.trusted.
    completed_degraded
        Execution reported as completed, but evidence quality is degraded
        (partial, stale, conflicting, or inferred).
    stale_result
        Evidence was once present but is now older than the staleness threshold.
    duplicate_result
        This result has already been processed under the same idempotency key.
    superseded_result
        A newer authoritative result exists for this task_id; this result should
        be discarded.
    failed
        Execution reported as failed with evidence.
    aborted
        Execution was explicitly aborted by the system or operator.
    interrupted
        Execution was in progress but was interrupted (e.g. device disconnected,
        session broken, network loss).
    """

    planned_not_started = "planned_not_started"
    started = "started"
    locally_executed = "locally_executed"
    android_delegated = "android_delegated"
    partially_completed = "partially_completed"
    completed_strong = "completed_strong"
    completed_degraded = "completed_degraded"
    stale_result = "stale_result"
    duplicate_result = "duplicate_result"
    superseded_result = "superseded_result"
    failed = "failed"
    aborted = "aborted"
    interrupted = "interrupted"


# ---------------------------------------------------------------------------
# EvidenceTrustLevel
# ---------------------------------------------------------------------------


class EvidenceTrustLevel(str, Enum):
    """Downstream trust classification derived from :class:`ExecutionEvidenceState`.

    This classification is **the enforcement point**: result ingress and
    canonical completion paths must gate on this level before accepting a result.

    Values
    ------
    trusted
        Evidence is strong and result may be accepted as canonical truth.
        Only :attr:`ExecutionEvidenceState.completed_strong` maps here.
    provisional
        Evidence is present but not fully confirmed.  Result may be displayed
        with an operator-visible warning flag but should not be treated as
        canonical truth for governance decisions.
    quarantine
        Evidence quality is too low to display or propagate.  Result must be
        held for manual review or reprocessing.
    rejected
        Result must be discarded.  Covers duplicates, superseded results, and
        evidence that is structurally invalid.
    """

    trusted = "trusted"
    provisional = "provisional"
    quarantine = "quarantine"
    rejected = "rejected"


# ---------------------------------------------------------------------------
# ExecutionEvidenceRecord
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExecutionEvidenceRecord:
    """Typed, immutable execution evidence record for one result event.

    Attributes
    ----------
    task_id
        The canonical task identifier.
    device_id
        The device that produced the result (empty for local-only execution).
    evidence_state
        The canonical :class:`ExecutionEvidenceState`.
    trust_level
        The derived :class:`EvidenceTrustLevel` for downstream gating.
    source_channel
        The result ingress channel (e.g. ``"canonical_ws"``, ``"rest_callback"``).
    android_proof_class
        The raw Android-side proof class string (from ``DelegatedRuntimeUnit``
        result messages).  Empty if not provided.
    is_duplicate
        ``True`` iff this result was classified as a duplicate replay.
    is_stale
        ``True`` iff evidence age exceeded :data:`STALE_RESULT_THRESHOLD_SECONDS`.
    is_superseded
        ``True`` iff a newer authoritative result exists for this task_id.
    truth_chain_complete
        ``True`` iff the four-step truth chain completed successfully.
    diagnosis
        Machine-readable list of diagnostic tokens explaining the classification.
    classified_at
        Unix epoch float when this record was created.
    """

    task_id: str
    device_id: str
    evidence_state: ExecutionEvidenceState
    trust_level: EvidenceTrustLevel
    source_channel: str = ""
    android_proof_class: str = ""
    effective_android_proof_class: str = ""
    android_evidence_resolution: str = ""
    android_inferred_evidence_strength: str = ""
    android_evidence_runtime_context: Dict[str, Any] = field(default_factory=dict)
    is_duplicate: bool = False
    is_stale: bool = False
    is_superseded: bool = False
    truth_chain_complete: bool = False
    diagnosis: tuple = field(default_factory=tuple)
    classified_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable summary dict."""
        return {
            "task_id": self.task_id,
            "device_id": self.device_id,
            "evidence_state": self.evidence_state.value,
            "trust_level": self.trust_level.value,
            "source_channel": self.source_channel,
            "android_proof_class": self.android_proof_class,
            "effective_android_proof_class": self.effective_android_proof_class,
            "android_evidence_resolution": self.android_evidence_resolution,
            "android_inferred_evidence_strength": self.android_inferred_evidence_strength,
            "android_evidence_runtime_context": dict(self.android_evidence_runtime_context),
            "is_duplicate": self.is_duplicate,
            "is_stale": self.is_stale,
            "is_superseded": self.is_superseded,
            "truth_chain_complete": self.truth_chain_complete,
            "diagnosis": list(self.diagnosis),
            "classified_at": self.classified_at,
        }

    @property
    def is_accepted(self) -> bool:
        """True iff trust_level is trusted or provisional (displayable)."""
        return self.trust_level in (EvidenceTrustLevel.trusted, EvidenceTrustLevel.provisional)

    @property
    def is_canonical(self) -> bool:
        """True iff trust_level is trusted (canonical result truth)."""
        return self.trust_level == EvidenceTrustLevel.trusted


# ---------------------------------------------------------------------------
# classify_execution_evidence
# ---------------------------------------------------------------------------


def classify_execution_evidence(
    state: ExecutionEvidenceState,
    *,
    proof_class: str = "",
    android_inferred_evidence_strength: str = "",
    is_duplicate: bool = False,
    is_stale: bool = False,
    is_superseded: bool = False,
    truth_chain_complete: bool = False,
) -> EvidenceTrustLevel:
    """Derive an :class:`EvidenceTrustLevel` from an :class:`ExecutionEvidenceState`.

    This is **the canonical enforcement function**.  Callers that previously
    accepted any result unconditionally must now call this function and act on
    the returned trust level.

    Classification rules (in precedence order):

    1. ``duplicate_result`` or ``is_duplicate`` → ``rejected``
    2. ``superseded_result`` or ``is_superseded`` → ``rejected``
    3. ``stale_result`` or ``is_stale`` → ``quarantine``
    4. ``completed_strong`` with ``truth_chain_complete=True`` and
       ``proof_class='confirmed_strong'`` → ``trusted``
    5. ``completed_strong`` without full confirmation → ``provisional``
    6. ``locally_executed`` with ``truth_chain_complete=True`` → ``trusted``
    7. ``locally_executed`` without full truth chain → ``provisional``
    8. ``failed`` / ``aborted`` / ``interrupted`` → ``provisional``
       (these are terminal states with evidence, just not "success" evidence)
    9. ``completed_degraded`` → ``quarantine``
    10. ``android_delegated`` (evidence received, proof not yet confirmed) → ``provisional``
    11. ``partially_completed`` → ``quarantine``
    12. ``started`` / ``planned_not_started`` → ``quarantine``

    Parameters
    ----------
    state:
        The :class:`ExecutionEvidenceState` for this result.
    proof_class:
        The Android-side proof class string (``"confirmed_strong"`` etc.).
    is_duplicate:
        Whether the idempotency key was already recorded.
    is_stale:
        Whether the evidence age exceeded the staleness threshold.
    is_superseded:
        Whether a newer authoritative result exists.
    truth_chain_complete:
        Whether the four-step truth chain completed successfully.

    Returns
    -------
    EvidenceTrustLevel
    """
    try:
        # Rule 1: duplicates are always rejected
        if is_duplicate or state == ExecutionEvidenceState.duplicate_result:
            return EvidenceTrustLevel.rejected

        # Rule 2: superseded results are always rejected
        if is_superseded or state == ExecutionEvidenceState.superseded_result:
            return EvidenceTrustLevel.rejected

        # Rule 3: stale evidence goes to quarantine
        if is_stale or state == ExecutionEvidenceState.stale_result:
            return EvidenceTrustLevel.quarantine

        # Rule 4: completed_strong with full confirmation → trusted
        if state == ExecutionEvidenceState.completed_strong:
            if truth_chain_complete and (
                proof_class in {"confirmed_strong", "inferred_strong"} or android_inferred_evidence_strength == "strong"
            ):
                return EvidenceTrustLevel.trusted
            # Rule 5: completed_strong but missing proof confirmation → provisional
            return EvidenceTrustLevel.provisional

        # Rule 6: locally_executed with complete truth chain → trusted
        if state == ExecutionEvidenceState.locally_executed:
            if truth_chain_complete:
                return EvidenceTrustLevel.trusted
            # Rule 7: local execution without truth chain → provisional
            return EvidenceTrustLevel.provisional

        # Rule 8: terminal failure states → provisional
        if state in (
            ExecutionEvidenceState.failed,
            ExecutionEvidenceState.aborted,
            ExecutionEvidenceState.interrupted,
        ):
            return EvidenceTrustLevel.provisional

        # Rule 9: degraded completion → quarantine
        if state == ExecutionEvidenceState.completed_degraded:
            return EvidenceTrustLevel.quarantine

        # Rule 10: android delegated, proof not yet confirmed → provisional
        if state == ExecutionEvidenceState.android_delegated:
            return EvidenceTrustLevel.provisional

        # Rule 11: partial completion → quarantine
        if state == ExecutionEvidenceState.partially_completed:
            return EvidenceTrustLevel.quarantine

        # Rule 12: not yet completed states → quarantine
        return EvidenceTrustLevel.quarantine

    except Exception as exc:
        logger.warning(
            "execution_evidence_model: classify_execution_evidence failed " "(returning quarantine): state=%r exc=%s",
            state,
            exc,
        )
        return EvidenceTrustLevel.quarantine


# ---------------------------------------------------------------------------
# infer_execution_evidence_state
# ---------------------------------------------------------------------------


def infer_execution_evidence_state(
    normalized_status: str,
    *,
    source_channel: str = "",
    truth_chain_complete: bool = False,
    android_proof_class: str = "",
    android_inferred_evidence_strength: str = "",
    is_duplicate: bool = False,
    is_stale: bool = False,
    is_superseded: bool = False,
    payload: Optional[Dict[str, Any]] = None,
) -> ExecutionEvidenceState:
    """Infer the :class:`ExecutionEvidenceState` from result event fields.

    This function bridges from the existing result ingress schema (which uses
    ``normalized_status`` and channel-level flags) to the richer evidence state
    vocabulary.

    Inference rules (in precedence order):

    1. ``is_duplicate`` → ``duplicate_result``
    2. ``is_superseded`` → ``superseded_result``
    3. ``is_stale`` → ``stale_result``
    4. ``normalized_status == "failed"`` → ``failed``
    5. ``normalized_status == "cancelled"`` → ``aborted``
    6. ``normalized_status == "degraded"`` → ``completed_degraded``
    7. ``normalized_status == "completed"`` and source is Android delegated:
       - ``android_proof_class == "confirmed_strong"`` and
         ``truth_chain_complete`` → ``completed_strong``
       - otherwise → ``android_delegated`` (awaiting confirmation)
    8. ``normalized_status == "completed"`` and local source → ``locally_executed``
       if ``truth_chain_complete``, else ``completed_degraded``
    9. Fallback → ``completed_degraded``

    Parameters
    ----------
    normalized_status:
        V2 canonical status string (``"completed"``, ``"failed"``, etc.).
    source_channel:
        The result ingress channel (e.g. ``"canonical_ws"``, ``"delegated"``).
    truth_chain_complete:
        Whether the four-step truth chain completed successfully.
    android_proof_class:
        The Android-side proof class from the result message.
    is_duplicate:
        Whether this result is a replay duplicate.
    is_stale:
        Whether evidence is stale by age threshold.
    is_superseded:
        Whether a newer result supersedes this one.
    payload:
        The raw result payload dict (may contain additional hints).

    Returns
    -------
    ExecutionEvidenceState
    """
    try:
        payload = payload or {}

        if is_duplicate:
            return ExecutionEvidenceState.duplicate_result
        if is_superseded:
            return ExecutionEvidenceState.superseded_result
        if is_stale:
            return ExecutionEvidenceState.stale_result

        status = (normalized_status or "").lower().strip()

        if status == "failed":
            return ExecutionEvidenceState.failed
        if status == "cancelled":
            return ExecutionEvidenceState.aborted
        if status == "degraded":
            return ExecutionEvidenceState.completed_degraded

        # Completed path — determine execution provenance
        if status == "completed":
            # Android-delegated channels
            _android_channels = {"canonical_ws", "compat_ws", "delegated", "replay"}
            execution_source = payload.get("execution_source", "")
            is_android_path = (
                source_channel in _android_channels
                or execution_source in ("android_delegated", "hybrid")
                or payload.get("device_id", "") != ""
            )

            if is_android_path:
                if truth_chain_complete and (
                    android_proof_class in {"confirmed_strong", "inferred_strong"}
                    or android_inferred_evidence_strength == "strong"
                ):
                    return ExecutionEvidenceState.completed_strong
                if android_inferred_evidence_strength == "weak":
                    return ExecutionEvidenceState.completed_degraded
                return ExecutionEvidenceState.android_delegated

            # Local execution path
            if truth_chain_complete:
                return ExecutionEvidenceState.locally_executed
            return ExecutionEvidenceState.completed_degraded

        # Interrupted or unrecognised status
        if status in ("interrupted", "partial"):
            return ExecutionEvidenceState.interrupted

        # Fallback
        return ExecutionEvidenceState.completed_degraded

    except Exception as exc:
        logger.warning(
            "execution_evidence_model: infer_execution_evidence_state failed "
            "(returning completed_degraded): status=%r exc=%s",
            normalized_status,
            exc,
        )
        return ExecutionEvidenceState.completed_degraded


# ---------------------------------------------------------------------------
# build_execution_evidence_record
# ---------------------------------------------------------------------------


def build_execution_evidence_record(
    task_id: str,
    device_id: str,
    normalized_status: str,
    *,
    source_channel: str = "",
    truth_chain_complete: bool = False,
    android_proof_class: str = "",
    android_runtime_truth_context: Optional[Dict[str, Any]] = None,
    is_duplicate: bool = False,
    is_stale: bool = False,
    is_superseded: bool = False,
    payload: Optional[Dict[str, Any]] = None,
) -> ExecutionEvidenceRecord:
    """Build a complete :class:`ExecutionEvidenceRecord` from result event fields.

    This is the primary factory function for creating execution evidence records
    from within the result ingress chain.  It:

    1. Infers the :class:`ExecutionEvidenceState` via :func:`infer_execution_evidence_state`.
    2. Derives the :class:`EvidenceTrustLevel` via :func:`classify_execution_evidence`.
    3. Assembles a machine-readable ``diagnosis`` list explaining the classification.

    Parameters
    ----------
    task_id:
        Canonical task identifier.
    device_id:
        Device that produced the result.
    normalized_status:
        V2 canonical status string.
    source_channel:
        Result ingress channel name.
    truth_chain_complete:
        Whether the four-step truth chain completed.
    android_proof_class:
        Android-side proof class from result message.
    is_duplicate:
        Whether this is a replay duplicate.
    is_stale:
        Whether evidence is stale.
    is_superseded:
        Whether a newer result supersedes this one.
    payload:
        Raw result payload dict.

    Returns
    -------
    ExecutionEvidenceRecord
    """
    try:
        payload = payload or {}
        android_resolution = _resolve_android_evidence_resolution(
            device_id=device_id,
            source_channel=source_channel,
            payload=payload,
            android_proof_class=android_proof_class,
            android_runtime_truth_context=android_runtime_truth_context,
            truth_chain_complete=truth_chain_complete,
        )
        effective_android_proof_class = android_resolution["effective_android_proof_class"]
        android_evidence_resolution = android_resolution["android_evidence_resolution"]
        android_inferred_evidence_strength = android_resolution["android_inferred_evidence_strength"]
        android_evidence_runtime_context = android_resolution["android_evidence_runtime_context"]

        state = infer_execution_evidence_state(
            normalized_status,
            source_channel=source_channel,
            truth_chain_complete=truth_chain_complete,
            android_proof_class=effective_android_proof_class,
            android_inferred_evidence_strength=android_inferred_evidence_strength,
            is_duplicate=is_duplicate,
            is_stale=is_stale,
            is_superseded=is_superseded,
            payload=payload,
        )

        trust_level = classify_execution_evidence(
            state,
            proof_class=effective_android_proof_class,
            android_inferred_evidence_strength=android_inferred_evidence_strength,
            is_duplicate=is_duplicate,
            is_stale=is_stale,
            is_superseded=is_superseded,
            truth_chain_complete=truth_chain_complete,
        )

        diagnosis = _build_diagnosis(
            state=state,
            trust_level=trust_level,
            android_proof_class=android_proof_class,
            effective_android_proof_class=effective_android_proof_class,
            android_evidence_resolution=android_evidence_resolution,
            android_inferred_evidence_strength=android_inferred_evidence_strength,
            android_evidence_runtime_context=android_evidence_runtime_context,
            truth_chain_complete=truth_chain_complete,
            is_duplicate=is_duplicate,
            is_stale=is_stale,
            is_superseded=is_superseded,
            source_channel=source_channel,
        )

        return ExecutionEvidenceRecord(
            task_id=task_id,
            device_id=device_id,
            evidence_state=state,
            trust_level=trust_level,
            source_channel=source_channel,
            android_proof_class=android_proof_class,
            effective_android_proof_class=effective_android_proof_class,
            android_evidence_resolution=android_evidence_resolution,
            android_inferred_evidence_strength=android_inferred_evidence_strength,
            android_evidence_runtime_context=android_evidence_runtime_context,
            is_duplicate=is_duplicate,
            is_stale=is_stale,
            is_superseded=is_superseded,
            truth_chain_complete=truth_chain_complete,
            diagnosis=tuple(diagnosis),
            classified_at=time.time(),
        )

    except Exception as exc:
        logger.warning(
            "execution_evidence_model: build_execution_evidence_record failed "
            "task_id=%r device_id=%r exc=%s — returning degraded record",
            task_id,
            device_id,
            exc,
        )
        return ExecutionEvidenceRecord(
            task_id=task_id,
            device_id=device_id,
            evidence_state=ExecutionEvidenceState.completed_degraded,
            trust_level=EvidenceTrustLevel.quarantine,
            source_channel=source_channel,
            diagnosis=("build_record_exception",),
            classified_at=time.time(),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_diagnosis(
    *,
    state: ExecutionEvidenceState,
    trust_level: EvidenceTrustLevel,
    android_proof_class: str,
    effective_android_proof_class: str,
    android_evidence_resolution: str,
    android_inferred_evidence_strength: str,
    android_evidence_runtime_context: Dict[str, Any],
    truth_chain_complete: bool,
    is_duplicate: bool,
    is_stale: bool,
    is_superseded: bool,
    source_channel: str,
) -> List[str]:
    """Build machine-readable diagnosis tokens for an evidence classification."""
    tokens: List[str] = []

    tokens.append(f"evidence_state:{state.value}")
    tokens.append(f"trust_level:{trust_level.value}")

    if not truth_chain_complete:
        tokens.append("truth_chain_incomplete")

    if android_evidence_resolution:
        tokens.append(f"android_evidence_resolution:{android_evidence_resolution}")
    if android_inferred_evidence_strength:
        tokens.append(f"android_inferred_evidence_strength:{android_inferred_evidence_strength}")
    if effective_android_proof_class:
        tokens.append(f"effective_android_proof_class:{effective_android_proof_class}")

    if not android_proof_class:
        _android_channels = {"canonical_ws", "compat_ws", "delegated", "replay"}
        if source_channel in _android_channels:
            tokens.append("android_proof_class_absent")
    elif android_proof_class != "confirmed_strong":
        tokens.append(f"android_proof_class_degraded:{android_proof_class}")

    if is_duplicate:
        tokens.append("is_duplicate_replay")
    if is_stale:
        tokens.append("is_stale_evidence")
    if is_superseded:
        tokens.append("is_superseded_result")

    context_sources = android_evidence_runtime_context.get("context_sources", [])
    for source in context_sources:
        tokens.append(f"android_runtime_context_source:{source}")
    if source_channel in {"canonical_ws", "compat_ws", "delegated", "replay"} and not android_evidence_runtime_context:
        tokens.append("android_runtime_truth_context_absent")

    if trust_level == EvidenceTrustLevel.quarantine:
        tokens.append("requires_operator_review")
    elif trust_level == EvidenceTrustLevel.provisional:
        tokens.append("operator_warning_flagged")

    return tokens


_ANDROID_RESULT_CHANNELS = frozenset({"canonical_ws", "compat_ws", "delegated", "replay"})
_ANDROID_PARTICIPATION_TIER_ORDER = (
    "local_only",
    "control_only",
    "cross_device_capable",
    "cross_device_enabled",
    "fully_attached",
    "dispatch_eligible",
    "distributed_participant",
)


def _resolve_android_evidence_resolution(
    *,
    device_id: str,
    source_channel: str,
    payload: Dict[str, Any],
    android_proof_class: str,
    android_runtime_truth_context: Optional[Dict[str, Any]],
    truth_chain_complete: bool,
) -> Dict[str, Any]:
    runtime_truth_context = android_runtime_truth_context or {}
    is_android_path = (
        source_channel in _ANDROID_RESULT_CHANNELS
        or str(payload.get("execution_source", "")).strip() in {"android_delegated", "hybrid"}
        or bool(device_id or payload.get("device_id"))
    )
    if not is_android_path:
        return {
            "effective_android_proof_class": android_proof_class or "",
            "android_evidence_resolution": "non_android_path",
            "android_inferred_evidence_strength": "",
            "android_evidence_runtime_context": {},
        }

    merged_context = _build_android_evidence_runtime_context(
        payload=payload,
        runtime_truth_context=runtime_truth_context,
    )
    if android_proof_class:
        return {
            "effective_android_proof_class": android_proof_class,
            "android_evidence_resolution": "explicit_proof_class",
            "android_inferred_evidence_strength": "",
            "android_evidence_runtime_context": merged_context,
        }

    tier = _coerce_optional_str(merged_context.get("participation_tier"))
    dispatch_eligible = _coerce_optional_bool(merged_context.get("dispatch_eligible"))
    runtime_constrained = _coerce_optional_bool(merged_context.get("runtime_constrained"))
    local_mode_active = _coerce_optional_bool(merged_context.get("local_mode_active"))
    local_loop_ready = _coerce_optional_bool(merged_context.get("local_loop_ready"))

    tier_is_strong = _participation_tier_rank(tier) >= _participation_tier_rank("dispatch_eligible")
    inferred_strong = (
        truth_chain_complete
        and tier_is_strong
        and dispatch_eligible is not False
        and runtime_constrained is False
        and local_mode_active is not True
        and (local_loop_ready is True or dispatch_eligible is True)
    )
    inferred_weak = (
        runtime_constrained is True
        or local_mode_active is True
        or dispatch_eligible is False
        or (tier is not None and not tier_is_strong)
        or local_loop_ready is False
    )

    if inferred_strong:
        return {
            "effective_android_proof_class": "inferred_strong",
            "android_evidence_resolution": "inferred_runtime_context",
            "android_inferred_evidence_strength": "strong",
            "android_evidence_runtime_context": merged_context,
        }
    if inferred_weak:
        return {
            "effective_android_proof_class": "inferred_weak",
            "android_evidence_resolution": "inferred_runtime_context",
            "android_inferred_evidence_strength": "weak",
            "android_evidence_runtime_context": merged_context,
        }
    if merged_context:
        return {
            "effective_android_proof_class": "inferred_indeterminate",
            "android_evidence_resolution": "inferred_runtime_context",
            "android_inferred_evidence_strength": "indeterminate",
            "android_evidence_runtime_context": merged_context,
        }
    return {
        "effective_android_proof_class": "",
        "android_evidence_resolution": "android_proof_missing",
        "android_inferred_evidence_strength": "",
        "android_evidence_runtime_context": {},
    }


def _build_android_evidence_runtime_context(
    *,
    payload: Dict[str, Any],
    runtime_truth_context: Dict[str, Any],
) -> Dict[str, Any]:
    context_sources: List[str] = []
    context: Dict[str, Any] = {}
    for field in (
        "participation_tier",
        "dispatch_eligible",
        "runtime_constrained",
        "local_mode_active",
        "local_loop_ready",
    ):
        value = _pick_context_value(
            field,
            payload=payload,
            runtime_truth_context=runtime_truth_context,
            context_sources=context_sources,
        )
        if value is not None:
            context[field] = value
    if context_sources:
        context["context_sources"] = list(context_sources)
    return context


def _pick_context_value(
    field: str,
    *,
    payload: Dict[str, Any],
    runtime_truth_context: Dict[str, Any],
    context_sources: List[str],
) -> Any:
    payload_value = payload.get(field)
    if payload_value not in (None, ""):
        context_sources.append(f"payload:{field}")
        return payload_value

    runtime_truth_value = runtime_truth_context.get(field)
    if runtime_truth_value not in (None, ""):
        context_sources.append(f"runtime_truth:{field}")
        return runtime_truth_value
    return None


def _coerce_optional_bool(value: Any) -> Optional[bool]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    return None


def _coerce_optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _participation_tier_rank(value: Optional[str]) -> int:
    if value is None:
        return -1
    try:
        return _ANDROID_PARTICIPATION_TIER_ORDER.index(str(value).strip())
    except ValueError:
        return -1


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "EXECUTION_EVIDENCE_MODEL_POLICY",
    "EXECUTION_EVIDENCE_MODEL_CONTRACT_VERSION",
    "DELEGATED_RESULT_PROOF_CLASS_POLICY",
    "DUPLICATE_EVIDENCE_REJECTION_POLICY",
    # Policy constants
    "STALE_RESULT_THRESHOLD_SECONDS",
    # Enums
    "ExecutionEvidenceState",
    "EvidenceTrustLevel",
    # Dataclass
    "ExecutionEvidenceRecord",
    # Functions
    "classify_execution_evidence",
    "infer_execution_evidence_state",
    "build_execution_evidence_record",
]
