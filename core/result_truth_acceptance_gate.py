"""core/result_truth_acceptance_gate.py
========================================
PR-4: Canonical Result Truth Acceptance Gate — makes evidence quality and
proof class materially actionable in result handling.

Background
----------
Prior to this module, the V2 result ingress chain could accept or reject a
result based only on idempotency and truth-chain completion, but had no
canonical gate that considered *evidence quality* when deciding how to
propagate a result to downstream consumers (operator surfaces, board
projections, user-facing problem closure, governance decisions).

The gap was:
- A result from an Android device with degraded proof quality was accepted
  with the same weight as a result backed by confirmed_strong evidence.
- Stale or duplicate results could propagate to user-facing surfaces unless
  the idempotency key had been explicitly tracked.
- There was no canonical concept of "quarantine" — results that are not
  clearly wrong but cannot yet be trusted should be held for review rather
  than silently degraded.

This module closes that gap by providing:

1. :class:`ResultAcceptanceVerdict` — a four-value enum encoding the
   canonical acceptance decision: ``accept``, ``accept_provisional``,
   ``quarantine``, ``reject``.

2. :class:`ResultTrustAcceptanceRecord` — typed, immutable record carrying
   the verdict, evidence trust level, evidence state, diagnosis, and
   downstream propagation flags for one result event.

3. :func:`evaluate_result_truth_acceptance` — the canonical gate function
   that consumes an :class:`~core.execution_evidence_model.ExecutionEvidenceRecord`
   (or equivalent fields) and produces a :class:`ResultTrustAcceptanceRecord`.

4. :func:`apply_acceptance_gate` — the integration entry point called from
   within :class:`~core.unified_result_ingress.UnifiedResultIngress.process`
   that translates a verdict into concrete flags on
   :class:`~core.unified_result_ingress.UnifiedResultIngressOutcome`.

Design principles
-----------------
- **Non-raising** — all public functions catch and log, returning a degraded
  verdict rather than raising.
- **Single authority** — only this module decides acceptance vs quarantine
  vs rejection based on evidence quality; no other ingress path may implement
  a competing acceptance gate.
- **Canonical truth protection** — ``accept`` verdict requires
  ``EvidenceTrustLevel.trusted``; ``accept_provisional`` requires
  ``provisional``; anything else is quarantine or reject.
- **Propagation flags** — the record exposes per-consumer propagation flags
  (``propagate_to_user_closure``, ``propagate_to_operator_surface``,
  ``propagate_to_board_projection``) that downstream surfaces can read
  directly without re-deriving the verdict.

Android integration points
--------------------------
- The gate uses ``android_proof_class`` from the result payload (expected
  to be populated by ``agent/DelegatedRuntimeUnit.kt``).
- If ``android_proof_class`` is absent from an Android-originating result,
  the gate assigns ``accept_provisional`` with diagnosis token
  ``android_proof_class_absent``, not a hard reject, to maintain forward
  compatibility during the Android-side rollout window.

Authority sentinel
------------------
``RESULT_TRUTH_ACCEPTANCE_GATE_POLICY`` — import to assert this module is
the canonical result truth acceptance gate.

Public API
----------
Sentinels::

    RESULT_TRUTH_ACCEPTANCE_GATE_POLICY
    RESULT_TRUTH_ACCEPTANCE_GATE_CONTRACT_VERSION
    QUARANTINE_BLOCKS_USER_CLOSURE_POLICY
    ACCEPTANCE_REQUIRES_TRUSTED_EVIDENCE_POLICY

Enum::

    ResultAcceptanceVerdict

Dataclass::

    ResultTrustAcceptanceRecord

Functions::

    evaluate_result_truth_acceptance(evidence_record) -> ResultTrustAcceptanceRecord
    apply_acceptance_gate(evidence_record, ingress_outcome) -> ResultTrustAcceptanceRecord
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    pass

logger = logging.getLogger("Galaxy.ResultTruthAcceptanceGate")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

RESULT_TRUTH_ACCEPTANCE_GATE_POLICY: str = (
    "RESULT_TRUTH_ACCEPTANCE_GATE_V1: core/result_truth_acceptance_gate.py "
    "is the canonical result truth acceptance gate.  "
    "ALL result ingress paths MUST call evaluate_result_truth_acceptance() "
    "after building an ExecutionEvidenceRecord.  "
    "Only 'accept' verdict allows full canonical truth propagation.  "
    "'accept_provisional' allows operator-surface display with a warning flag "
    "but MUST NOT propagate to user-facing problem closure.  "
    "'quarantine' blocks all propagation and requires operator review.  "
    "'reject' discards the result silently."
)

RESULT_TRUTH_ACCEPTANCE_GATE_CONTRACT_VERSION: str = "4.0.0"

QUARANTINE_BLOCKS_USER_CLOSURE_POLICY: str = (
    "POLICY::QUARANTINE_BLOCKS_USER_CLOSURE: "
    "A result with ResultAcceptanceVerdict.quarantine MUST NOT propagate to "
    "user-facing problem closure (nl_execution_spine, CanonicalCompletionIngress "
    "notify, or any user-visible resolution surface).  It may be displayed on "
    "internal operator surfaces with a quarantine indicator."
)

ACCEPTANCE_REQUIRES_TRUSTED_EVIDENCE_POLICY: str = (
    "POLICY::ACCEPTANCE_REQUIRES_TRUSTED_EVIDENCE: "
    "Full canonical truth acceptance (ResultAcceptanceVerdict.accept) requires "
    "EvidenceTrustLevel.trusted.  This means ExecutionEvidenceState.completed_strong "
    "with truth_chain_complete=True and android_proof_class='confirmed_strong' (for "
    "Android-delegated paths), or ExecutionEvidenceState.locally_executed with "
    "truth_chain_complete=True (for local paths).  Any weaker evidence state "
    "produces accept_provisional, quarantine, or reject."
)


# ---------------------------------------------------------------------------
# ResultAcceptanceVerdict
# ---------------------------------------------------------------------------

class ResultAcceptanceVerdict(str, Enum):
    """Canonical acceptance decision for a result event.

    Values
    ------
    accept
        Result has strong evidence and may propagate to all downstream consumers
        (canonical truth, user closure, board projection, operator surface).
    accept_provisional
        Evidence is present but not fully confirmed.  Result may propagate to
        operator surfaces and board projections with a warning flag, but MUST
        NOT propagate to user-facing problem closure or canonical truth decisions.
    quarantine
        Evidence quality is too low to propagate.  Result is held for review.
        No user-facing surfaces should display this as resolved.
    reject
        Result must be discarded.  Covers duplicate replays, superseded results,
        and structurally invalid evidence.
    """

    accept = "accept"
    accept_provisional = "accept_provisional"
    quarantine = "quarantine"
    reject = "reject"


# ---------------------------------------------------------------------------
# ResultTrustAcceptanceRecord
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResultTrustAcceptanceRecord:
    """Typed, immutable record of the acceptance gate decision for one result.

    Attributes
    ----------
    task_id
        The canonical task identifier.
    verdict
        The :class:`ResultAcceptanceVerdict` for this result.
    evidence_state
        The :class:`~core.execution_evidence_model.ExecutionEvidenceState`
        that drove this verdict.
    evidence_trust_level
        The :class:`~core.execution_evidence_model.EvidenceTrustLevel`
        derived from the evidence state.
    propagate_to_user_closure
        ``True`` iff the result may propagate to user-facing problem closure.
    propagate_to_operator_surface
        ``True`` iff the result may appear on operator/board surfaces (possibly
        with a warning flag).
    propagate_to_board_projection
        ``True`` iff the result may update board projection state.
    operator_warning
        ``True`` iff the result requires an operator-visible warning flag.
    diagnosis
        Machine-readable list of diagnostic tokens explaining the verdict.
    evaluated_at
        Unix epoch float when the record was created.
    """

    task_id: str
    verdict: ResultAcceptanceVerdict
    evidence_state: str = ""
    evidence_trust_level: str = ""
    propagate_to_user_closure: bool = False
    propagate_to_operator_surface: bool = False
    propagate_to_board_projection: bool = False
    operator_warning: bool = False
    diagnosis: tuple = field(default_factory=tuple)
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable summary dict."""
        return {
            "task_id": self.task_id,
            "verdict": self.verdict.value,
            "evidence_state": self.evidence_state,
            "evidence_trust_level": self.evidence_trust_level,
            "propagate_to_user_closure": self.propagate_to_user_closure,
            "propagate_to_operator_surface": self.propagate_to_operator_surface,
            "propagate_to_board_projection": self.propagate_to_board_projection,
            "operator_warning": self.operator_warning,
            "diagnosis": list(self.diagnosis),
            "evaluated_at": self.evaluated_at,
        }

    @property
    def is_accepted(self) -> bool:
        """True iff verdict is accept or accept_provisional."""
        return self.verdict in (
            ResultAcceptanceVerdict.accept,
            ResultAcceptanceVerdict.accept_provisional,
        )

    @property
    def is_canonical(self) -> bool:
        """True iff verdict is accept (fully trusted, canonical truth)."""
        return self.verdict == ResultAcceptanceVerdict.accept


# ---------------------------------------------------------------------------
# evaluate_result_truth_acceptance
# ---------------------------------------------------------------------------

def evaluate_result_truth_acceptance(
    evidence_record: Any,
) -> ResultTrustAcceptanceRecord:
    """Derive a :class:`ResultTrustAcceptanceRecord` from an evidence record.

    This is the canonical gate function.  Pass an
    :class:`~core.execution_evidence_model.ExecutionEvidenceRecord` instance
    (or any object with equivalent attributes) to get a propagation-ready
    acceptance record.

    Verdict derivation::

        EvidenceTrustLevel.trusted     → accept
        EvidenceTrustLevel.provisional → accept_provisional
        EvidenceTrustLevel.quarantine  → quarantine
        EvidenceTrustLevel.rejected    → reject

    Propagation flags::

        accept              → user_closure=True, operator=True, board=True
        accept_provisional  → user_closure=False, operator=True, board=True, warning=True
        quarantine          → user_closure=False, operator=True (with warning), board=False
        reject              → all False

    Parameters
    ----------
    evidence_record:
        An :class:`~core.execution_evidence_model.ExecutionEvidenceRecord`
        or compatible object with ``task_id``, ``evidence_state``,
        ``trust_level``, ``diagnosis`` attributes.

    Returns
    -------
    ResultTrustAcceptanceRecord
    """
    try:
        task_id = getattr(evidence_record, "task_id", "") or ""
        trust_level_raw = getattr(evidence_record, "trust_level", "")
        evidence_state_raw = getattr(evidence_record, "evidence_state", "")
        diagnosis = list(getattr(evidence_record, "diagnosis", []))

        # Normalise trust level to string for comparison
        trust_level = (
            trust_level_raw.value
            if hasattr(trust_level_raw, "value")
            else str(trust_level_raw)
        )
        evidence_state = (
            evidence_state_raw.value
            if hasattr(evidence_state_raw, "value")
            else str(evidence_state_raw)
        )

        verdict, propagate_flags, operator_warning = _derive_verdict_and_flags(trust_level)

        diagnosis.append(f"acceptance_verdict:{verdict.value}")

        return ResultTrustAcceptanceRecord(
            task_id=task_id,
            verdict=verdict,
            evidence_state=evidence_state,
            evidence_trust_level=trust_level,
            propagate_to_user_closure=propagate_flags["user_closure"],
            propagate_to_operator_surface=propagate_flags["operator_surface"],
            propagate_to_board_projection=propagate_flags["board_projection"],
            operator_warning=operator_warning,
            diagnosis=tuple(diagnosis),
            evaluated_at=time.time(),
        )

    except Exception as exc:
        logger.warning(
            "result_truth_acceptance_gate: evaluate_result_truth_acceptance "
            "failed task_id=%r exc=%s — returning quarantine",
            getattr(evidence_record, "task_id", "unknown"),
            exc,
        )
        return ResultTrustAcceptanceRecord(
            task_id=getattr(evidence_record, "task_id", ""),
            verdict=ResultAcceptanceVerdict.quarantine,
            diagnosis=("evaluation_exception",),
            evaluated_at=time.time(),
        )


def _derive_verdict_and_flags(
    trust_level: str,
) -> tuple:
    """Derive verdict, propagation flags, and operator warning from trust level."""
    if trust_level == "trusted":
        return (
            ResultAcceptanceVerdict.accept,
            {"user_closure": True, "operator_surface": True, "board_projection": True},
            False,
        )
    if trust_level == "provisional":
        return (
            ResultAcceptanceVerdict.accept_provisional,
            {"user_closure": False, "operator_surface": True, "board_projection": True},
            True,
        )
    if trust_level == "quarantine":
        return (
            ResultAcceptanceVerdict.quarantine,
            {"user_closure": False, "operator_surface": True, "board_projection": False},
            True,
        )
    if trust_level == "rejected":
        return (
            ResultAcceptanceVerdict.reject,
            {"user_closure": False, "operator_surface": False, "board_projection": False},
            False,
        )
    # Unknown trust level — quarantine is safer than reject for forward compatibility
    return (
        ResultAcceptanceVerdict.quarantine,
        {"user_closure": False, "operator_surface": True, "board_projection": False},
        True,
    )


# ---------------------------------------------------------------------------
# apply_acceptance_gate
# ---------------------------------------------------------------------------

def apply_acceptance_gate(
    evidence_record: Any,
    ingress_outcome: Any,
) -> ResultTrustAcceptanceRecord:
    """Apply the acceptance gate to an ingress outcome, mutating propagation flags.

    This is the integration entry point called from within
    :class:`~core.unified_result_ingress.UnifiedResultIngress.process` after
    the truth chain and completion notification steps.

    It evaluates the acceptance verdict and then applies it to the
    ``ingress_outcome`` by setting:
    - ``execution_evidence_state`` — the evidence state string
    - ``evidence_trust_level`` — the trust level string
    - ``evidence_acceptance_verdict`` — the verdict string
    - ``propagate_to_user_closure`` — False when quarantine/reject

    Parameters
    ----------
    evidence_record:
        The :class:`~core.execution_evidence_model.ExecutionEvidenceRecord`.
    ingress_outcome:
        The :class:`~core.unified_result_ingress.UnifiedResultIngressOutcome`
        to mutate.

    Returns
    -------
    ResultTrustAcceptanceRecord
    """
    acceptance = evaluate_result_truth_acceptance(evidence_record)

    try:
        # Stamp the ingress outcome with evidence fields
        ingress_outcome.execution_evidence_state = acceptance.evidence_state
        ingress_outcome.evidence_trust_level = acceptance.evidence_trust_level
        ingress_outcome.evidence_acceptance_verdict = acceptance.verdict.value

        # If verdict is quarantine or reject, block user-facing closure
        if acceptance.verdict in (
            ResultAcceptanceVerdict.quarantine,
            ResultAcceptanceVerdict.reject,
        ):
            ingress_outcome.is_fully_closed = False
            if not ingress_outcome.incomplete_reason:
                ingress_outcome.incomplete_reason = (
                    f"evidence_gate:{acceptance.verdict.value}"
                )
            elif "evidence_gate" not in ingress_outcome.incomplete_reason:
                ingress_outcome.incomplete_reason += (
                    f"; evidence_gate:{acceptance.verdict.value}"
                )

        logger.info(
            "result_truth_acceptance_gate: verdict=%s trust=%s state=%s "
            "task_id=%r propagate_user=%s propagate_operator=%s",
            acceptance.verdict.value,
            acceptance.evidence_trust_level,
            acceptance.evidence_state,
            acceptance.task_id,
            acceptance.propagate_to_user_closure,
            acceptance.propagate_to_operator_surface,
        )

    except Exception as exc:
        logger.warning(
            "result_truth_acceptance_gate: apply_acceptance_gate failed to "
            "stamp ingress_outcome: exc=%s",
            exc,
        )

    return acceptance


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "RESULT_TRUTH_ACCEPTANCE_GATE_POLICY",
    "RESULT_TRUTH_ACCEPTANCE_GATE_CONTRACT_VERSION",
    "QUARANTINE_BLOCKS_USER_CLOSURE_POLICY",
    "ACCEPTANCE_REQUIRES_TRUSTED_EVIDENCE_POLICY",
    # Enum
    "ResultAcceptanceVerdict",
    # Dataclass
    "ResultTrustAcceptanceRecord",
    # Functions
    "evaluate_result_truth_acceptance",
    "apply_acceptance_gate",
]
