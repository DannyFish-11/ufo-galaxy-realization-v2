"""core/ownership_transfer_proof_quality.py
============================================
PR-16 — Canonical ownership-transfer proof quality and failure semantics.

Background
----------
Prior to this module, ``adjudicate_takeover_ownership_convergence()`` could
return ``resumed_v2_ownership_confirmed`` with ``evidence_quality='strong'``
for any non-conflicting, non-missing takeover record, regardless of whether
the underlying evidence was stale, partial, or otherwise insufficient.  This
made it possible for callers to mistake degraded evidence for confirmed
ownership-transfer closure.

This module closes that gap by providing:

1. :class:`OwnershipTransferProofClass` — an explicit six-value enum
   classifying ownership-transfer evidence into:

   * ``confirmed_strong`` — the only class sufficient for closure.
   * ``degraded_partial`` — evidence present but structurally incomplete.
   * ``degraded_stale`` — evidence present but too old to trust.
   * ``degraded_conflicting`` — contradictory evidence (accepted + rejected).
   * ``degraded_unresolved`` — no convergence yet reached.
   * ``incomplete`` — missing or unclassifiable evidence.

2. :class:`OwnershipTransferProofQualityResult` — a typed result that
   carries ``proof_class``, ``is_sufficient_for_closure``, the raw
   ``ownership_state`` and ``evidence_quality`` from the underlying verdict,
   and a ``diagnosis`` list for operator/audit surfaces.

3. :func:`classify_ownership_transfer_proof_quality` — maps any
   :class:`~core.takeover_tracking.TakeoverOwnershipConvergenceVerdict` (or
   its ``to_dict()`` representation) to an
   :class:`OwnershipTransferProofQualityResult`.  Returns a degraded result
   rather than raising on any error.

4. :func:`get_latest_ownership_transfer_proof_quality_for_device` — a
   convenience wrapper that looks up the most recent takeover record for a
   device from the process-local ring buffer, adjudicates it, and classifies
   the proof quality in one call.

Design principles
-----------------
- **Non-raising** — all public functions catch and log exceptions, returning
  a degraded ``OwnershipTransferProofQualityResult``.
- **Explicit over implicit** — every non-``confirmed_strong`` result is
  labelled with a machine-readable diagnosis token.
- **Additive** — does not modify any existing module; it layers on top of
  ``core.takeover_tracking``.

Authority sentinel
------------------
``OWNERSHIP_TRANSFER_PROOF_QUALITY_SENTINEL`` — import this to assert that
this module is the canonical proof-quality classifier for ownership transfer.

Public API
----------
Sentinels::

    OWNERSHIP_TRANSFER_PROOF_QUALITY_SENTINEL
    OWNERSHIP_TRANSFER_PROOF_QUALITY_CONTRACT_VERSION

Policy constants::

    RESUMED_OWNERSHIP_TRANSFER_REQUIRES_PROOF_POLICY
    OWNERSHIP_TRANSFER_PROOF_QUALITY_POLICY
    STALE_OWNERSHIP_EVIDENCE_THRESHOLD_SECONDS

Enum::

    OwnershipTransferProofClass

Dataclass::

    OwnershipTransferProofQualityResult

Functions::

    classify_ownership_transfer_proof_quality(verdict, *, now, stale_threshold_seconds)
        -> OwnershipTransferProofQualityResult
    get_latest_ownership_transfer_proof_quality_for_device(device_id, ...)
        -> OwnershipTransferProofQualityResult
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.OwnershipTransferProofQuality")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

OWNERSHIP_TRANSFER_PROOF_QUALITY_SENTINEL: str = (
    "OWNERSHIP_TRANSFER_PROOF_QUALITY_SENTINEL::"
    "core.ownership_transfer_proof_quality (PR16_V2) is the canonical "
    "authority for ownership-transfer proof-quality classification.  "
    "Resumed ownership transfer MUST NOT be treated as confirmed closure "
    "unless classify_ownership_transfer_proof_quality() returns "
    "proof_class='confirmed_strong'.  All other proof classes are non-passing "
    "and MUST be surfaced as degraded states in canonical truth, diagnostics, "
    "and audit."
)

OWNERSHIP_TRANSFER_PROOF_QUALITY_CONTRACT_VERSION: str = "16.0.0"

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

RESUMED_OWNERSHIP_TRANSFER_REQUIRES_PROOF_POLICY: str = (
    "POLICY::RESUMED_OWNERSHIP_TRANSFER_REQUIRES_PROOF: "
    "A resumed V2 ownership-transfer state MUST be backed by strong, fresh, "
    "non-conflicting evidence before it is treated as closure.  "
    "Insufficient evidence (partial, stale, conflicting, missing, or unresolved) "
    "MUST produce a degraded proof class, not a confirmed state.  "
    "Callers MUST check OwnershipTransferProofQualityResult.is_sufficient_for_closure "
    "before treating any ownership-transfer verdict as finalised.  "
    "It is a regression to accept ownership-transfer closure on anything other "
    "than proof_class='confirmed_strong'."
)

OWNERSHIP_TRANSFER_PROOF_QUALITY_POLICY: str = (
    "POLICY::OWNERSHIP_TRANSFER_PROOF_QUALITY: "
    "classify_ownership_transfer_proof_quality() maps a "
    "TakeoverOwnershipConvergenceVerdict to an explicit OwnershipTransferProofClass.  "
    "Only 'confirmed_strong' is a passing classification for closure eligibility.  "
    "All other classes ('degraded_partial', 'degraded_stale', "
    "'degraded_conflicting', 'degraded_unresolved', 'incomplete') are non-passing "
    "and MUST surface as canonical degraded states in governance readiness, "
    "decision_causality, diagnostics panels, and audit outputs."
)

# Default staleness threshold (seconds).  Evidence older than this is
# classified as ``degraded_stale`` even if structurally complete.
STALE_OWNERSHIP_EVIDENCE_THRESHOLD_SECONDS: float = 300.0

# ---------------------------------------------------------------------------
# OwnershipTransferProofClass enum
# ---------------------------------------------------------------------------


class OwnershipTransferProofClass(str, Enum):
    """Proof-quality class for a canonical ownership-transfer verdict.

    Only :attr:`confirmed_strong` meets the bar for closure eligibility.
    All other classes are degraded and MUST NOT be treated as confirmed.

    Values
    ------
    confirmed_strong
        Evidence is fresh, non-conflicting, and structurally complete.
        ``is_sufficient_for_closure`` is ``True`` only for this class.
    degraded_partial
        Evidence is present but structurally incomplete (partial quality).
    degraded_stale
        Evidence was once complete but is now older than the staleness threshold.
    degraded_conflicting
        Contradictory evidence exists (both accepted and rejected decisions).
    degraded_unresolved
        No convergence has been reached; ownership state is still unknown.
    incomplete
        Evidence is missing or classification could not be determined.
    """

    confirmed_strong = "confirmed_strong"
    degraded_partial = "degraded_partial"
    degraded_stale = "degraded_stale"
    degraded_conflicting = "degraded_conflicting"
    degraded_unresolved = "degraded_unresolved"
    incomplete = "incomplete"


# ---------------------------------------------------------------------------
# OwnershipTransferProofQualityResult dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OwnershipTransferProofQualityResult:
    """Result of ownership-transfer proof-quality classification.

    Attributes
    ----------
    proof_class
        The assigned :class:`OwnershipTransferProofClass`.
    is_sufficient_for_closure
        ``True`` only when ``proof_class == confirmed_strong``.
    ownership_state
        The raw ownership-state string from the underlying verdict.
    evidence_quality
        The raw evidence-quality string from the underlying verdict.
    diagnosis
        List of machine-readable diagnostic tokens explaining the classification.
    degraded
        ``True`` when ``proof_class`` is not ``confirmed_strong``.
    """

    proof_class: OwnershipTransferProofClass = OwnershipTransferProofClass.incomplete
    is_sufficient_for_closure: bool = False
    ownership_state: str = ""
    evidence_quality: str = ""
    diagnosis: List[str] = field(default_factory=list)
    degraded: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "proof_class": self.proof_class.value,
            "is_sufficient_for_closure": self.is_sufficient_for_closure,
            "ownership_state": self.ownership_state,
            "evidence_quality": self.evidence_quality,
            "diagnosis": list(self.diagnosis),
            "degraded": self.degraded,
            "_policy": OWNERSHIP_TRANSFER_PROOF_QUALITY_POLICY,
            "_sentinel": OWNERSHIP_TRANSFER_PROOF_QUALITY_SENTINEL,
        }


# ---------------------------------------------------------------------------
# classify_ownership_transfer_proof_quality
# ---------------------------------------------------------------------------


def classify_ownership_transfer_proof_quality(
    verdict: Any,
    *,
    now: Optional[float] = None,
    stale_threshold_seconds: float = STALE_OWNERSHIP_EVIDENCE_THRESHOLD_SECONDS,
) -> OwnershipTransferProofQualityResult:
    """Classify the proof quality of an ownership-transfer convergence verdict.

    Accepts either a
    :class:`~core.takeover_tracking.TakeoverOwnershipConvergenceVerdict`
    instance or its ``to_dict()`` representation (a plain ``dict``).

    Classification rules (applied in priority order)
    -------------------------------------------------
    1. **Conflicting** — ``evidence_quality`` is ``'conflicting'`` or
       ``ownership_state`` is ``'degraded_conflicting_evidence'`` or
       ``'conflicting_takeover_decisions'`` appears in ``diagnosis``.
    2. **Incomplete / partial** — ``evidence_quality`` is ``'missing'`` or
       ``ownership_state`` is ``'degraded_incomplete_evidence'``.
       Evidence quality ``'partial'`` maps to ``degraded_partial``.
    3. **Stale** — ``evidence_quality`` is ``'stale'``,
       ``ownership_state`` is ``'degraded_stale_evidence'``, or
       ``latest_record_at`` is set and older than *stale_threshold_seconds*.
    4. **Unresolved** — ``is_converged`` is ``False`` and the state is not
       already classified above.
    5. **Confirmed strong** — ``is_converged`` is ``True``,
       ``evidence_quality`` is ``'strong'``, and ``ownership_state`` is one
       of the two confirmed states.
    6. **Incomplete** (fallback) — anything not matching rules 1–5.

    Parameters
    ----------
    verdict
        Verdict to classify.  May be a typed dataclass instance or a dict.
    now
        Current wall-clock timestamp (``time.time()``).  Defaults to the
        actual current time.  Pass an explicit value in tests.
    stale_threshold_seconds
        Maximum age (seconds) for evidence to be considered fresh.

    Returns
    -------
    OwnershipTransferProofQualityResult
        Always returns a typed result; never raises.
    """
    try:
        _now = now if now is not None else time.time()

        # Normalise verdict into flat field access
        if isinstance(verdict, dict):
            ownership_state = str(verdict.get("ownership_state") or "")
            evidence_quality = str(verdict.get("evidence_quality") or "")
            is_converged = bool(verdict.get("is_converged", False))
            degraded_in = bool(verdict.get("degraded", True))
            diagnosis_in: List[str] = list(verdict.get("diagnosis") or [])
            latest_record_at = float(verdict.get("latest_record_at") or 0.0)
        else:
            _os = getattr(verdict, "ownership_state", "")
            ownership_state = _os.value if hasattr(_os, "value") else str(_os)
            _eq = getattr(verdict, "evidence_quality", "")
            evidence_quality = _eq.value if hasattr(_eq, "value") else str(_eq)
            is_converged = bool(getattr(verdict, "is_converged", False))
            degraded_in = bool(getattr(verdict, "degraded", True))
            diagnosis_in = list(getattr(verdict, "diagnosis") or [])
            latest_record_at = float(getattr(verdict, "latest_record_at", 0.0) or 0.0)

        diagnosis: List[str] = list(diagnosis_in)

        # ── Rule 1: Conflicting evidence ─────────────────────────────────────
        if (
            evidence_quality == "conflicting"
            or ownership_state == "degraded_conflicting_evidence"
            or "conflicting_takeover_decisions" in diagnosis_in
        ):
            diagnosis.append("ownership_transfer_proof_class:degraded_conflicting")
            return OwnershipTransferProofQualityResult(
                proof_class=OwnershipTransferProofClass.degraded_conflicting,
                is_sufficient_for_closure=False,
                ownership_state=ownership_state,
                evidence_quality=evidence_quality,
                diagnosis=diagnosis,
                degraded=True,
            )

        # ── Rule 2: Missing / incomplete / partial evidence ───────────────────
        if (
            evidence_quality == "missing"
            or ownership_state == "degraded_incomplete_evidence"
        ):
            diagnosis.append("ownership_transfer_proof_class:incomplete")
            return OwnershipTransferProofQualityResult(
                proof_class=OwnershipTransferProofClass.incomplete,
                is_sufficient_for_closure=False,
                ownership_state=ownership_state,
                evidence_quality=evidence_quality,
                diagnosis=diagnosis,
                degraded=True,
            )

        if evidence_quality == "partial":
            diagnosis.append("ownership_transfer_proof_class:degraded_partial")
            return OwnershipTransferProofQualityResult(
                proof_class=OwnershipTransferProofClass.degraded_partial,
                is_sufficient_for_closure=False,
                ownership_state=ownership_state,
                evidence_quality=evidence_quality,
                diagnosis=diagnosis,
                degraded=True,
            )

        # ── Rule 3: Stale evidence ────────────────────────────────────────────
        evidence_is_stale = (
            evidence_quality == "stale"
            or ownership_state == "degraded_stale_evidence"
            or (
                stale_threshold_seconds > 0
                and latest_record_at > 0.0
                and (_now - latest_record_at) > stale_threshold_seconds
            )
        )
        if evidence_is_stale:
            age_s = (_now - latest_record_at) if latest_record_at > 0.0 else None
            token = (
                f"ownership_transfer_proof_class:degraded_stale:age_s={age_s:.1f}"
                if age_s is not None
                else "ownership_transfer_proof_class:degraded_stale"
            )
            diagnosis.append(token)
            return OwnershipTransferProofQualityResult(
                proof_class=OwnershipTransferProofClass.degraded_stale,
                is_sufficient_for_closure=False,
                ownership_state=ownership_state,
                evidence_quality=evidence_quality,
                diagnosis=diagnosis,
                degraded=True,
            )

        # ── Rule 4: Unresolved ────────────────────────────────────────────────
        _confirmed_states = {
            "delegated_takeover_confirmed",
            "resumed_v2_ownership_confirmed",
        }
        if not is_converged and ownership_state not in _confirmed_states:
            diagnosis.append("ownership_transfer_proof_class:degraded_unresolved")
            return OwnershipTransferProofQualityResult(
                proof_class=OwnershipTransferProofClass.degraded_unresolved,
                is_sufficient_for_closure=False,
                ownership_state=ownership_state,
                evidence_quality=evidence_quality,
                diagnosis=diagnosis,
                degraded=True,
            )

        # ── Rule 5: Confirmed strong ──────────────────────────────────────────
        if (
            is_converged
            and evidence_quality == "strong"
            and ownership_state in _confirmed_states
            and not degraded_in
        ):
            diagnosis.append("ownership_transfer_proof_class:confirmed_strong")
            return OwnershipTransferProofQualityResult(
                proof_class=OwnershipTransferProofClass.confirmed_strong,
                is_sufficient_for_closure=True,
                ownership_state=ownership_state,
                evidence_quality=evidence_quality,
                diagnosis=diagnosis,
                degraded=False,
            )

        # ── Rule 6: Fallback — incomplete ─────────────────────────────────────
        diagnosis.append("ownership_transfer_proof_class:incomplete_fallback")
        return OwnershipTransferProofQualityResult(
            proof_class=OwnershipTransferProofClass.incomplete,
            is_sufficient_for_closure=False,
            ownership_state=ownership_state,
            evidence_quality=evidence_quality,
            diagnosis=diagnosis,
            degraded=True,
        )

    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "classify_ownership_transfer_proof_quality failed (non-fatal): %s", exc
        )
        return OwnershipTransferProofQualityResult(
            proof_class=OwnershipTransferProofClass.incomplete,
            is_sufficient_for_closure=False,
            ownership_state="",
            evidence_quality="",
            diagnosis=[f"classification_error:{type(exc).__name__}"],
            degraded=True,
        )


# ---------------------------------------------------------------------------
# get_latest_ownership_transfer_proof_quality_for_device
# ---------------------------------------------------------------------------


def get_latest_ownership_transfer_proof_quality_for_device(
    device_id: str,
    *,
    session_id: str = "",
    now: Optional[float] = None,
    stale_threshold_seconds: float = STALE_OWNERSHIP_EVIDENCE_THRESHOLD_SECONDS,
) -> OwnershipTransferProofQualityResult:
    """Return the ownership-transfer proof quality for the most recent
    takeover record associated with *device_id*.

    This is a convenience wrapper that:

    1. Queries the process-local tracking ring buffer for the most recent
       :class:`~core.takeover_tracking.TakeoverTrackingRecord` for
       *device_id*.
    2. Runs :func:`~core.takeover_tracking.adjudicate_takeover_ownership_convergence`
       on that record's ``takeover_id``.
    3. Classifies the resulting verdict with
       :func:`classify_ownership_transfer_proof_quality`.

    Parameters
    ----------
    device_id
        Android device identifier.
    session_id
        Optional session identifier for richer adjudication.
    now
        Current wall-clock timestamp.  Defaults to ``time.time()``.
    stale_threshold_seconds
        Staleness threshold forwarded to both adjudication and classification.

    Returns
    -------
    OwnershipTransferProofQualityResult
        Always returns a typed result; never raises.  Returns
        ``proof_class='incomplete'`` when no tracking records are found.
    """
    try:
        from core.takeover_tracking import (
            adjudicate_takeover_ownership_convergence,
            get_takeover_tracking_runtime,
        )

        _now = now if now is not None else time.time()
        rt = get_takeover_tracking_runtime()
        snap = rt.snapshot()

        # Find the most recent record for this device_id.
        latest_record = None
        for rec in snap.records:
            if rec.device_id == device_id:
                latest_record = rec
                break

        if latest_record is None:
            return OwnershipTransferProofQualityResult(
                proof_class=OwnershipTransferProofClass.incomplete,
                is_sufficient_for_closure=False,
                ownership_state="",
                evidence_quality="",
                diagnosis=["no_takeover_record_for_device"],
                degraded=True,
            )

        verdict = adjudicate_takeover_ownership_convergence(
            takeover_id=latest_record.takeover_id,
            session_id=session_id or latest_record.session_id,
            device_id=device_id,
            stale_threshold_seconds=stale_threshold_seconds,
            now=_now,
        )
        return classify_ownership_transfer_proof_quality(
            verdict,
            now=_now,
            stale_threshold_seconds=stale_threshold_seconds,
        )

    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "get_latest_ownership_transfer_proof_quality_for_device failed "
            "(non-fatal): device_id=%r exc=%s",
            device_id,
            exc,
        )
        return OwnershipTransferProofQualityResult(
            proof_class=OwnershipTransferProofClass.incomplete,
            is_sufficient_for_closure=False,
            ownership_state="",
            evidence_quality="",
            diagnosis=[
                "proof_quality_lookup_error",
                f"error_type:{type(exc).__name__}",
            ],
            degraded=True,
        )


__all__ = [
    "OWNERSHIP_TRANSFER_PROOF_QUALITY_SENTINEL",
    "OWNERSHIP_TRANSFER_PROOF_QUALITY_CONTRACT_VERSION",
    "RESUMED_OWNERSHIP_TRANSFER_REQUIRES_PROOF_POLICY",
    "OWNERSHIP_TRANSFER_PROOF_QUALITY_POLICY",
    "STALE_OWNERSHIP_EVIDENCE_THRESHOLD_SECONDS",
    "OwnershipTransferProofClass",
    "OwnershipTransferProofQualityResult",
    "classify_ownership_transfer_proof_quality",
    "get_latest_ownership_transfer_proof_quality_for_device",
]
