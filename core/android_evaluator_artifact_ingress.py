"""core/android_evaluator_artifact_ingress.py
================================================
PR-4V2-GOV: Android Evaluator Artifact Ingress and Canonical Projection.

Background
----------
Android-side runtime evaluators produce structured artifacts for four
assessment dimensions:

* **Readiness** — ``DelegatedRuntimeReadinessEvaluator`` →
  ``DeviceReadinessArtifact``
* **Acceptance** — ``DelegatedRuntimeAcceptanceEvaluator`` →
  ``DeviceAcceptanceArtifact``
* **Governance** — ``DelegatedRuntimePostGraduationGovernanceEvaluator`` →
  ``DeviceGovernanceArtifact``
* **Strategy** — ``DelegatedRuntimeStrategyEvaluator`` →
  ``DeviceStrategyArtifact``

Prior to this module, these artifacts could be transported via
``ReconciliationSignal`` to V2, but were only absorbed as advisory/local-only
truth (``readiness_assessment`` kind, ``local_only=True``).  They had no
first-class presence in V2 canonical readiness or governance gate evaluation.

This module closes that gap by providing:

1. :class:`AndroidEvaluatorArtifactKind` — canonical enum for the four
   evaluator dimensions.

2. :class:`AndroidEvaluatorArtifact` — typed, immutable carrier for an
   Android-originated evaluator artifact, capturing device identity, kind,
   and the opaque artifact payload.

3. :class:`AndroidEvaluatorArtifactRegistry` — in-process ring-buffer
   singleton storing the most-recent artifacts per device/kind.  Operator
   surfaces and readiness gates can inspect this registry without re-deriving
   it from raw signals.

4. :func:`ingest_android_evaluator_artifact` — canonical ingress entry-point
   that:

   a. Stores the artifact in :class:`AndroidEvaluatorArtifactRegistry`.
   b. Calls :func:`~core.android_participant_truth_ingress.ingest_android_participant_truth_message`
      with truth kind ``governance_artifact`` so that
      :func:`~core.flow_level_truth_ownership.align_and_record` writes a
      :class:`~core.flow_level_truth_ownership.FlowTruthDecisionArtifact` to
      :class:`~core.flow_level_truth_ownership.FlowTruthAlignmentRuntime`.
      This is what makes the artifact visible to
      :meth:`~core.delegated_flow_readiness_gate.DelegatedFlowReadinessGate._evaluate_truth_ownership`.

5. Policy sentinels documenting which evaluator kinds are canonical gate
   inputs versus observation-only evidence.

Authority / classification
--------------------------
+--------------------------+-----------------------+--------------------+
| Kind                     | V2 Gate Visibility    | Classification     |
+==========================+=======================+====================+
| ``governance``           | ✅ Canonical gate      | Authoritative      |
| ``readiness``            | ✅ Canonical gate      | Authoritative      |
| ``acceptance``           | ✅ Canonical gate      | Authoritative      |
| ``strategy``             | ✅ Canonical gate      | Authoritative      |
+--------------------------+-----------------------+--------------------+
| ``readiness_assessment`` | ❌ Advisory/local-only | Advisory           |
| (truth kind)             |                       |                    |
+--------------------------+-----------------------+--------------------+

Note: ``readiness_assessment`` (the pre-existing truth kind) remains
advisory per :data:`READINESS_ASSESSMENT_IS_ADVISORY_POLICY` in
:mod:`core.android_participant_truth_ingress`.  The new
``AndroidEvaluatorArtifact`` path is explicitly canonical.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Delegates to existing modules** — ingress calls
  :func:`~core.android_participant_truth_ingress.ingest_android_participant_truth_message`
  and :func:`~core.flow_level_truth_ownership.align_and_record`; does not
  re-implement reconciliation logic.
- **Non-raising** — all public functions are non-raising.
- **Audit-complete** — every ingested artifact is recorded to
  ReplayFoundation via the truth ingress path.

PR
--
PR-4V2-GOV: Wire Android evaluator artifacts into canonical readiness and
governance flow.  Companion Android repo: ``DannyFish-11/ufo-galaxy-android``.
"""

from __future__ import annotations

import threading as _threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Tuple

logger_name = "Galaxy.AndroidEvaluatorArtifactIngress"

try:
    import logging as _logging

    _logger = _logging.getLogger(logger_name)
except Exception as exc:
    _logger.debug("Fallback triggered: %s", exc)
    _logger = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Optional dependency: truth ingress (for governance_artifact reconcile path)
# ---------------------------------------------------------------------------

try:
    from core.android_participant_truth_ingress import (
        AndroidParticipantReconcileOutcome as _ReconcileOutcome,
        ingest_android_participant_truth_message as _ingest_truth_message,
    )

    _TRUTH_INGRESS_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _TRUTH_INGRESS_AVAILABLE = False
    _ingest_truth_message = None  # type: ignore[assignment]
    _ReconcileOutcome = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Module authority sentinels
# ---------------------------------------------------------------------------

ANDROID_EVALUATOR_ARTIFACT_INGRESS_AUTHORITY: str = (
    "core.android_evaluator_artifact_ingress::PR4V2-GOV::"
    "android-evaluator-artifact-ingress-and-canonical-projection::"
    "wire-android-evaluator-artifacts-into-canonical-readiness-governance-flow"
)

ANDROID_EVALUATOR_ARTIFACT_INGRESS_SENTINEL: str = (
    "android_evaluator_artifact_ingress::package=PR4V2-GOV::"
    "pr=wire-android-evaluator-artifacts-into-canonical-readiness-governance-flow::"
    "authority=ANDROID_EVALUATOR_ARTIFACT_INGRESS_AUTHORITY"
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

EVALUATOR_ARTIFACT_IS_FIRST_CLASS_GATE_INPUT_POLICY: str = (
    "POLICY::EVALUATOR_ARTIFACT_IS_FIRST_CLASS_GATE_INPUT: "
    "Android-originated evaluator artifacts (governance, readiness, acceptance, "
    "strategy) inbound via AndroidEvaluatorArtifactKind are FIRST-CLASS canonical "
    "gate inputs.  They MUST be reconciled via ingest_android_evaluator_artifact() "
    "which calls ingest_android_participant_truth_message() with truth kind "
    "'governance_artifact'.  This triggers align_and_record() in "
    "core.flow_level_truth_ownership, writing a FlowTruthDecisionArtifact to "
    "FlowTruthAlignmentRuntime and making the artifact visible to "
    "DelegatedFlowReadinessGate.truth_ownership dimension evaluation.  "
    "PR-4V2-GOV."
)

CANONICAL_VS_ADVISORY_DISTINCTION_MUST_BE_EXPLICIT_POLICY: str = (
    "POLICY::CANONICAL_VS_ADVISORY_DISTINCTION_MUST_BE_EXPLICIT: "
    "The distinction between canonical participant evidence and advisory/"
    "observation-only evidence MUST remain explicit.  AndroidEvaluatorArtifact "
    "records (kind=governance/readiness/acceptance/strategy) are canonical.  "
    "readiness_assessment truth kind (from android_participant_truth_ingress) "
    "remains advisory/local-only per READINESS_ASSESSMENT_IS_ADVISORY_POLICY.  "
    "Do NOT conflate the two paths.  "
    "PR-4V2-GOV."
)

EVALUATOR_ARTIFACT_REGISTRY_IS_READ_ONLY_PROJECTION_POLICY: str = (
    "POLICY::EVALUATOR_ARTIFACT_REGISTRY_IS_READ_ONLY_PROJECTION: "
    "AndroidEvaluatorArtifactRegistry is a read-only projection layer for "
    "operator surfaces and gates.  It stores snapshots of the most-recent "
    "artifacts per device/kind.  Gates and surfaces MUST NOT write to the "
    "registry; they MUST use ingest_android_evaluator_artifact() as the "
    "canonical ingress path.  "
    "PR-4V2-GOV."
)

DEFERRED_TO_LATER_PRS_POLICY: str = (
    "POLICY::DEFERRED_TO_LATER_PRS: "
    "The following work is explicitly deferred to later PRs and is NOT in scope "
    "here: (1) CI/release blocking on governance artifact verdict; "
    "(2) full default-on release readiness based on governance artifacts; "
    "(3) Android-side dedicated message type for evaluator artifact upload "
    "(currently routed via ReconciliationSignal with governance_artifact kind); "
    "(4) multi-device governance verdict aggregation.  "
    "PR-4V2-GOV."
)

_ALL_POLICY_SENTINELS: Tuple[str, ...] = (
    EVALUATOR_ARTIFACT_IS_FIRST_CLASS_GATE_INPUT_POLICY,
    CANONICAL_VS_ADVISORY_DISTINCTION_MUST_BE_EXPLICIT_POLICY,
    EVALUATOR_ARTIFACT_REGISTRY_IS_READ_ONLY_PROJECTION_POLICY,
    DEFERRED_TO_LATER_PRS_POLICY,
)

# ---------------------------------------------------------------------------
# AndroidEvaluatorArtifactKind
# ---------------------------------------------------------------------------


class AndroidEvaluatorArtifactKind(str, Enum):
    """Canonical kind for Android-originated evaluator artifacts.

    Values
    ------
    governance
        Output of ``DelegatedRuntimePostGraduationGovernanceEvaluator``.
        Corresponds to ``DeviceGovernanceArtifact`` on the Android side.
    readiness
        Output of ``DelegatedRuntimeReadinessEvaluator``.
        Corresponds to ``DeviceReadinessArtifact`` on the Android side.
    acceptance
        Output of ``DelegatedRuntimeAcceptanceEvaluator``.
        Corresponds to ``DeviceAcceptanceArtifact`` on the Android side.
    strategy
        Output of ``DelegatedRuntimeStrategyEvaluator``.
        Corresponds to ``DeviceStrategyArtifact`` on the Android side.
    unknown
        Unrecognised evaluator kind.
    """

    governance = "governance"
    readiness = "readiness"
    acceptance = "acceptance"
    strategy = "strategy"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: Optional[str]) -> "AndroidEvaluatorArtifactKind":
        """Return the matching kind or ``unknown`` for unrecognised values."""
        if not value:
            return cls.unknown
        normalised = str(value).strip().lower()
        for member in cls:
            if member.value == normalised:
                return member
        return cls.unknown

    def is_canonical_gate_input(self) -> bool:
        """Return True iff this kind is a first-class V2 readiness gate input."""
        return self in (
            AndroidEvaluatorArtifactKind.governance,
            AndroidEvaluatorArtifactKind.readiness,
            AndroidEvaluatorArtifactKind.acceptance,
            AndroidEvaluatorArtifactKind.strategy,
        )


# ---------------------------------------------------------------------------
# AndroidEvaluatorArtifact dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AndroidEvaluatorArtifact:
    """Typed, immutable carrier for an Android-originated evaluator artifact.

    Attributes
    ----------
    artifact_id
        Unique identifier for this artifact (``aea_`` prefix + UUID4 hex).
    kind
        :class:`AndroidEvaluatorArtifactKind` identifying the evaluator
        dimension this artifact comes from.
    device_id
        Android device identifier.
    session_id
        Attached runtime session identifier (may be empty).
    contract_id
        Delegated execution contract identifier (may be empty).
    task_id
        Task identifier (may be empty).
    trace_id
        End-to-end trace identifier (may be empty).
    received_at
        Unix timestamp (float) when this artifact was ingested.
    payload
        Opaque snapshot of the raw artifact payload as received from Android.
    is_compliant
        Whether the evaluator found the system in a compliant/ready state.
        ``None`` when the artifact does not carry an explicit compliance flag.
    verdict_label
        Human-readable verdict label from the Android evaluator (may be empty).
    """

    artifact_id: str = field(default_factory=lambda: f"aea_{uuid.uuid4().hex[:12]}")
    kind: AndroidEvaluatorArtifactKind = AndroidEvaluatorArtifactKind.unknown
    device_id: str = ""
    session_id: str = ""
    contract_id: str = ""
    task_id: str = ""
    trace_id: str = ""
    received_at: float = field(default_factory=time.time)
    payload: Dict[str, Any] = field(default_factory=dict)
    is_compliant: Optional[bool] = None
    verdict_label: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind.value,
            "device_id": self.device_id,
            "session_id": self.session_id,
            "contract_id": self.contract_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "received_at": self.received_at,
            "payload": dict(self.payload),
            "is_compliant": self.is_compliant,
            "verdict_label": self.verdict_label,
        }


# ---------------------------------------------------------------------------
# AndroidEvaluatorArtifactIngestOutcome dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AndroidEvaluatorArtifactIngestOutcome:
    """Typed result of an Android evaluator artifact ingestion attempt.

    Attributes
    ----------
    artifact
        The :class:`AndroidEvaluatorArtifact` that was processed.
    was_stored
        True iff the artifact was stored in the registry.
    truth_reconcile_outcome
        The :class:`~core.android_participant_truth_ingress.AndroidParticipantReconcileOutcome`
        from the downstream truth ingress call, or ``None`` if unavailable.
    canonical_update
        Human-readable description of what V2 canonical state was updated.
    reject_reason
        Non-empty when ingestion was rejected or degraded.
    """

    artifact: Optional[AndroidEvaluatorArtifact] = None
    was_stored: bool = False
    truth_reconcile_outcome: Optional[Any] = None
    canonical_update: str = ""
    reject_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "was_stored": self.was_stored,
            "canonical_update": self.canonical_update,
            "reject_reason": self.reject_reason,
            "artifact": self.artifact.to_dict() if self.artifact else None,
            "truth_reconcile": (
                self.truth_reconcile_outcome.to_dict()
                if self.truth_reconcile_outcome is not None
                and hasattr(self.truth_reconcile_outcome, "to_dict")
                else None
            ),
        }


# ---------------------------------------------------------------------------
# AndroidEvaluatorArtifactRegistry
# ---------------------------------------------------------------------------

_REGISTRY_CAPACITY: int = 128
"""Default ring-buffer capacity for the artifact registry."""


class AndroidEvaluatorArtifactRegistry:
    """In-process ring-buffer storing recent Android evaluator artifacts.

    Artifacts are appended newest-first.  The registry retains up to
    ``capacity`` entries.  Callers can inspect the history via
    :meth:`list_recent` or retrieve the latest artifact for a given
    ``(device_id, kind)`` pair via :meth:`get_latest_for_device_kind`.

    Policy: :data:`EVALUATOR_ARTIFACT_REGISTRY_IS_READ_ONLY_PROJECTION_POLICY`
    """

    def __init__(self, capacity: int = _REGISTRY_CAPACITY) -> None:
        self._capacity = capacity
        self._ring: Deque[AndroidEvaluatorArtifact] = deque(maxlen=capacity)
        self._total: int = 0
        self._lock: _threading.Lock = _threading.Lock()

    def record(self, artifact: AndroidEvaluatorArtifact) -> None:
        """Append *artifact* to the ring buffer."""
        with self._lock:
            self._ring.appendleft(artifact)
            self._total += 1

    def list_recent(self, n: int = 20) -> List[AndroidEvaluatorArtifact]:
        """Return up to *n* most-recent artifacts (newest-first)."""
        with self._lock:
            return list(self._ring)[:n]

    def get_latest_for_device_kind(
        self,
        device_id: str,
        kind: AndroidEvaluatorArtifactKind,
    ) -> Optional[AndroidEvaluatorArtifact]:
        """Return the most-recent artifact for ``(device_id, kind)``, or ``None``."""
        with self._lock:
            for art in self._ring:
                if art.device_id == device_id and art.kind == kind:
                    return art
        return None

    def get_by_artifact_id(self, artifact_id: str) -> Optional[AndroidEvaluatorArtifact]:
        """Return the artifact matching *artifact_id*, or ``None``."""
        with self._lock:
            for art in self._ring:
                if art.artifact_id == artifact_id:
                    return art
        return None

    def count(self) -> int:
        """Return the total number of artifacts recorded since startup."""
        with self._lock:
            return self._total

    def list_for_kind(
        self, kind: AndroidEvaluatorArtifactKind, n: int = 20
    ) -> List[AndroidEvaluatorArtifact]:
        """Return up to *n* most-recent artifacts of the given *kind*."""
        with self._lock:
            return [a for a in self._ring if a.kind == kind][:n]

    def build_snapshot(self) -> Dict[str, Any]:
        """Return a serialisable summary snapshot for gate/operator consumption."""
        with self._lock:
            ring_copy = list(self._ring)
            total = self._total

        counts: Dict[str, int] = {}
        for art in ring_copy:
            counts[art.kind.value] = counts.get(art.kind.value, 0) + 1

        latest_by_kind: Dict[str, Optional[Dict[str, Any]]] = {}
        seen: set = set()
        for art in ring_copy:
            if art.kind.value not in seen:
                seen.add(art.kind.value)
                latest_by_kind[art.kind.value] = art.to_dict()

        return {
            "total_artifacts": total,
            "artifact_counts_by_kind": counts,
            "latest_by_kind": latest_by_kind,
            "canonical_gate_input_kinds": [
                k.value
                for k in AndroidEvaluatorArtifactKind
                if k.is_canonical_gate_input()
            ],
        }


# Module-level singleton
_REGISTRY: Optional[AndroidEvaluatorArtifactRegistry] = None
_REGISTRY_LOCK: _threading.Lock = _threading.Lock()


def get_evaluator_artifact_registry() -> AndroidEvaluatorArtifactRegistry:
    """Return the module-level :class:`AndroidEvaluatorArtifactRegistry` singleton."""
    global _REGISTRY  # noqa: PLW0603
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = AndroidEvaluatorArtifactRegistry()
    return _REGISTRY


def reset_evaluator_artifact_registry() -> None:
    """Reset the singleton (test isolation only)."""
    global _REGISTRY  # noqa: PLW0603
    with _REGISTRY_LOCK:
        _REGISTRY = None


# ---------------------------------------------------------------------------
# Extraction helper
# ---------------------------------------------------------------------------


def extract_evaluator_artifact(
    message: Dict[str, Any],
) -> AndroidEvaluatorArtifact:
    """Extract an :class:`AndroidEvaluatorArtifact` from a raw message dict.

    Identity field extraction rules
    --------------------------------
    * ``device_id``, ``task_id`` — top-level first, then ``payload`` sub-dict.
    * ``contract_id``, ``session_id``, ``trace_id`` — ``payload`` sub-dict
      first, then top-level.
    * ``evaluator_kind`` / ``artifact_kind`` / ``kind`` — checked in order.
    * ``is_compliant`` — ``payload.compliant`` or ``payload.is_compliant``.
    * ``verdict_label`` — ``payload.verdict`` or ``payload.verdict_label``.
    """
    if not isinstance(message, dict):
        message = {}

    payload: Dict[str, Any] = message.get("payload", {}) or {}

    # evaluator kind — check multiple aliases
    raw_kind: str = ""
    for alias in ("evaluator_kind", "artifact_kind", "kind", "evaluator_type"):
        v = message.get(alias) or payload.get(alias)
        if v and isinstance(v, str):
            raw_kind = v
            break
    kind = AndroidEvaluatorArtifactKind.from_string(raw_kind)

    # identity fields
    device_id = str(message.get("device_id") or payload.get("device_id") or "")
    task_id = str(message.get("task_id") or payload.get("task_id") or "")
    contract_id = str(payload.get("contract_id") or message.get("contract_id") or "")
    session_id = str(payload.get("session_id") or message.get("session_id") or "")
    trace_id = str(payload.get("trace_id") or message.get("trace_id") or "")

    # compliance flag
    raw_compliant = payload.get("is_compliant")
    if raw_compliant is None:
        raw_compliant = payload.get("compliant")
    is_compliant: Optional[bool] = None
    if isinstance(raw_compliant, bool):
        is_compliant = raw_compliant

    # verdict label
    verdict_label = str(
        payload.get("verdict_label") or payload.get("verdict") or ""
    )

    return AndroidEvaluatorArtifact(
        kind=kind,
        device_id=device_id,
        session_id=session_id,
        contract_id=contract_id,
        task_id=task_id,
        trace_id=trace_id,
        payload=dict(payload),
        is_compliant=is_compliant,
        verdict_label=verdict_label,
    )


# ---------------------------------------------------------------------------
# ingest_android_evaluator_artifact — canonical ingress entry-point
# ---------------------------------------------------------------------------


def ingest_android_evaluator_artifact(
    message: Dict[str, Any],
    *,
    registry: Optional[AndroidEvaluatorArtifactRegistry] = None,
) -> AndroidEvaluatorArtifactIngestOutcome:
    """Canonical ingress entry-point for Android evaluator artifacts.

    This function:

    1. Extracts an :class:`AndroidEvaluatorArtifact` from the raw message.
    2. Stores it in :class:`AndroidEvaluatorArtifactRegistry`.
    3. Calls :func:`~core.android_participant_truth_ingress.ingest_android_participant_truth_message`
       with truth kind ``governance_artifact`` so that
       :func:`~core.flow_level_truth_ownership.align_and_record` writes a
       :class:`~core.flow_level_truth_ownership.FlowTruthDecisionArtifact` to
       :class:`~core.flow_level_truth_ownership.FlowTruthAlignmentRuntime`.

    This pipeline ensures Android evaluator artifacts are:

    * Stored/projected in a dedicated registry (gate-readable projection).
    * Consumed as first-class inputs to V2 readiness/governance gates via the
      ``truth_ownership`` dimension of
      :class:`~core.delegated_flow_readiness_gate.DelegatedFlowReadinessGate`.

    Parameters
    ----------
    message:
        Raw inbound message dict from Android.  Expected fields:
        ``device_id``, ``payload`` (containing ``evaluator_kind``,
        ``is_compliant``, ``verdict``, etc.).
    registry:
        Optional :class:`AndroidEvaluatorArtifactRegistry` instance for
        dependency injection / test isolation.  If ``None``, the global
        singleton is used.

    Returns
    -------
    AndroidEvaluatorArtifactIngestOutcome
        Typed outcome with ``was_stored`` flag, truth reconcile result, and
        canonical update description.
    """
    try:
        artifact = extract_evaluator_artifact(message)
    except Exception as exc:  # noqa: BLE001
        return AndroidEvaluatorArtifactIngestOutcome(
            was_stored=False,
            reject_reason=f"artifact_extraction_error:{exc}",
        )

    # Store in registry
    _registry = registry if registry is not None else get_evaluator_artifact_registry()
    was_stored = False
    try:
        _registry.record(artifact)
        was_stored = True
    except Exception as exc:  # noqa: BLE001
        if _logger:
            _logger.warning("AndroidEvaluatorArtifactRegistry.record failed: %s", exc)

    # Build governance_artifact truth message for the canonical truth ingress path.
    # This calls align_and_record() internally via _reconcile_governance_artifact()
    # in android_participant_truth_ingress, writing to FlowTruthAlignmentRuntime.
    truth_reconcile_outcome: Optional[Any] = None
    canonical_update = ""
    reject_reason = ""

    if _TRUTH_INGRESS_AVAILABLE and _ingest_truth_message is not None:
        truth_message: Dict[str, Any] = {
            "type": "governance_artifact",
            "truth_kind": "governance_artifact",
            "device_id": artifact.device_id,
            "task_id": artifact.task_id,
            "payload": {
                "evaluator_kind": artifact.kind.value,
                "session_id": artifact.session_id,
                "contract_id": artifact.contract_id,
                "trace_id": artifact.trace_id,
                "is_compliant": artifact.is_compliant,
                "verdict_label": artifact.verdict_label,
                **dict(artifact.payload),
            },
        }
        try:
            truth_reconcile_outcome = _ingest_truth_message(truth_message)
            if truth_reconcile_outcome is not None:
                canonical_update = (
                    f"evaluator_artifact_ingested:"
                    f"kind={artifact.kind.value}"
                    f" device_id={artifact.device_id}"
                    f" was_reconciled={truth_reconcile_outcome.was_reconciled}"
                )
        except Exception as exc:  # noqa: BLE001
            _logger.debug("Fallback triggered: %s", exc)
            reject_reason = f"truth_ingress_error:{exc}"
            if _logger:
                _logger.warning(
                    "ingest_android_evaluator_artifact truth ingress failed: %s", exc
                )
    else:
        reject_reason = "truth_ingress_unavailable"

    return AndroidEvaluatorArtifactIngestOutcome(
        artifact=artifact,
        was_stored=was_stored,
        truth_reconcile_outcome=truth_reconcile_outcome,
        canonical_update=canonical_update,
        reject_reason=reject_reason,
    )


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Authority sentinels
    "ANDROID_EVALUATOR_ARTIFACT_INGRESS_AUTHORITY",
    "ANDROID_EVALUATOR_ARTIFACT_INGRESS_SENTINEL",
    # Policy sentinels
    "EVALUATOR_ARTIFACT_IS_FIRST_CLASS_GATE_INPUT_POLICY",
    "CANONICAL_VS_ADVISORY_DISTINCTION_MUST_BE_EXPLICIT_POLICY",
    "EVALUATOR_ARTIFACT_REGISTRY_IS_READ_ONLY_PROJECTION_POLICY",
    "DEFERRED_TO_LATER_PRS_POLICY",
    # Enum
    "AndroidEvaluatorArtifactKind",
    # Dataclasses
    "AndroidEvaluatorArtifact",
    "AndroidEvaluatorArtifactIngestOutcome",
    # Registry class and accessors
    "AndroidEvaluatorArtifactRegistry",
    "get_evaluator_artifact_registry",
    "reset_evaluator_artifact_registry",
    # Functions
    "extract_evaluator_artifact",
    "ingest_android_evaluator_artifact",
]
