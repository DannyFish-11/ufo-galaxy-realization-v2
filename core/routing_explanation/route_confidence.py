#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.routing_explanation.route_confidence
==========================================

PR-21 (V4) — Routing Explanation & Decision Surface

Defines :class:`RouteConfidence`, a serialisable confidence model that
summarises how certain the routing engine was about its decision, and the
:class:`ConfidenceBand` enum that buckets numeric scores into human-readable
quality bands.

Confidence is derived by aggregating :class:`~.decision_basis.DecisionBasis`
entries rather than rerunning routing logic — it is a **post-hoc read-only
summary**, not a routing signal.

Design rules
------------
- All models are **immutable** (frozen dataclasses).
- ``to_dict()`` output is JSON-serialisable and stable.
- :func:`compute_confidence` accepts an empty basis list and returns a
  safe ``UNDETERMINED`` confidence so assembly never raises.
"""

from __future__ import annotations

import dataclasses
import time
from enum import Enum
from typing import Any, Dict, List, Optional

from .decision_basis import DecisionBasis, DecisionFactor

__all__ = [
    "ConfidenceBand",
    "CONFIDENCE_BAND_DESCRIPTIONS",
    "RouteConfidence",
    "compute_confidence",
    "UNDETERMINED_CONFIDENCE",
]


# ---------------------------------------------------------------------------
# Confidence band enum
# ---------------------------------------------------------------------------


class ConfidenceBand(str, Enum):
    """Quality bands for routing confidence scores.

    String values are stable identifiers safe for serialisation and logging.
    """

    HIGH = "high"
    """Score ≥ 0.75 — strong signal alignment across multiple factors."""

    MEDIUM = "medium"
    """Score in [0.45, 0.75) — acceptable but not fully converged."""

    LOW = "low"
    """Score in [0.15, 0.45) — weak or conflicting signals."""

    UNDETERMINED = "undetermined"
    """Score < 0.15 or no basis entries — cannot derive meaningful confidence."""


CONFIDENCE_BAND_DESCRIPTIONS: Dict[str, str] = {
    ConfidenceBand.HIGH.value: (
        "Strong alignment across multiple decision factors.  The selected route "
        "was clearly preferred over alternatives by health, policy, and capability "
        "signals."
    ),
    ConfidenceBand.MEDIUM.value: (
        "Acceptable routing decision but with some uncertainty.  One or more "
        "factors may have been neutral or mildly conflicting."
    ),
    ConfidenceBand.LOW.value: (
        "Weak or conflicting signals.  The route was selected as the best "
        "available option but alternatives should be monitored."
    ),
    ConfidenceBand.UNDETERMINED.value: (
        "Insufficient signal data to derive meaningful confidence.  The system "
        "may be in an idle or initialising state."
    ),
}


def _band_from_score(score: float) -> ConfidenceBand:
    if score >= 0.75:
        return ConfidenceBand.HIGH
    if score >= 0.45:
        return ConfidenceBand.MEDIUM
    if score >= 0.15:
        return ConfidenceBand.LOW
    return ConfidenceBand.UNDETERMINED


# ---------------------------------------------------------------------------
# RouteConfidence dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RouteConfidence:
    """Confidence summary for a routing decision.

    Attributes
    ----------
    score:
        Numeric confidence in ``[0.0, 1.0]``.  Higher = more confident.
    band:
        :class:`ConfidenceBand` bucket for the score.
    basis_count:
        Number of :class:`~.decision_basis.DecisionBasis` entries that
        contributed to this confidence score.
    accepted_factor_count:
        Number of basis entries where ``accepted=True``.
    rejected_factor_count:
        Number of basis entries where ``accepted=False`` (constraints /
        fallbacks that were engaged).
    contributing_factors:
        List of :class:`~.decision_basis.DecisionFactor` values that
        participated in the score computation.
    computed_at:
        Unix timestamp of when this confidence was computed.
    reason:
        Human-readable explanation of the confidence score.
    """

    score: float = 0.0
    band: ConfidenceBand = ConfidenceBand.UNDETERMINED
    basis_count: int = 0
    accepted_factor_count: int = 0
    rejected_factor_count: int = 0
    contributing_factors: List[str] = dataclasses.field(default_factory=list)
    computed_at: float = dataclasses.field(default_factory=time.time)
    reason: str = "no basis entries — undetermined confidence"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "score": round(self.score, 4),
            "band": self.band.value,
            "basis_count": self.basis_count,
            "accepted_factor_count": self.accepted_factor_count,
            "rejected_factor_count": self.rejected_factor_count,
            "contributing_factors": list(self.contributing_factors),
            "computed_at": self.computed_at,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RouteConfidence":
        """Reconstruct a :class:`RouteConfidence` from a serialised dict.

        Unknown or missing fields are silently defaulted.
        """
        try:
            band = ConfidenceBand(data.get("band", ConfidenceBand.UNDETERMINED.value))
        except (ValueError, KeyError):
            band = ConfidenceBand.UNDETERMINED

        return cls(
            score=float(data.get("score", 0.0)),
            band=band,
            basis_count=int(data.get("basis_count", 0)),
            accepted_factor_count=int(data.get("accepted_factor_count", 0)),
            rejected_factor_count=int(data.get("rejected_factor_count", 0)),
            contributing_factors=list(data.get("contributing_factors", [])),
            computed_at=float(data.get("computed_at", time.time())),
            reason=str(data.get("reason", "")),
        )


# ---------------------------------------------------------------------------
# Pre-built sentinel
# ---------------------------------------------------------------------------

UNDETERMINED_CONFIDENCE: RouteConfidence = RouteConfidence(
    score=0.0,
    band=ConfidenceBand.UNDETERMINED,
    basis_count=0,
    accepted_factor_count=0,
    rejected_factor_count=0,
    contributing_factors=[],
    reason="no basis entries — undetermined confidence",
)
"""Pre-built :class:`RouteConfidence` for idle / no-data cases."""


# ---------------------------------------------------------------------------
# Confidence computation
# ---------------------------------------------------------------------------


def compute_confidence(bases: List[DecisionBasis]) -> RouteConfidence:
    """Compute a :class:`RouteConfidence` from a list of decision basis entries.

    Algorithm
    ---------
    1. For each :class:`~.decision_basis.DecisionBasis` entry:
       - If ``accepted=True``: contribute its ``weight`` (default 0.1) to a
         positive accumulator.
       - If ``accepted=False``: the factor was a constraint/fallback; subtract
         half its weight (fallback penalty).
    2. Normalise the raw score against the sum of all weights to produce a
       value in ``[0.0, 1.0]``.
    3. Map the score to a :class:`ConfidenceBand`.
    4. Assemble and return a frozen :class:`RouteConfidence`.

    The function always returns a valid :class:`RouteConfidence` — it never
    raises.

    Args:
        bases: List of :class:`~.decision_basis.DecisionBasis` entries from
            the routing explanation.  May be empty.

    Returns:
        A :class:`RouteConfidence` reflecting the aggregated signal quality.
    """
    try:
        return _compute_confidence_impl(bases)
    except Exception:
        return UNDETERMINED_CONFIDENCE


def _compute_confidence_impl(bases: List[DecisionBasis]) -> RouteConfidence:
    if not bases:
        return UNDETERMINED_CONFIDENCE

    total_weight = 0.0
    positive_weight = 0.0
    accepted_count = 0
    rejected_count = 0
    seen_factors: List[str] = []

    default_weight = 0.10

    for b in bases:
        w = b.weight if b.weight is not None else default_weight
        total_weight += w
        if b.accepted:
            positive_weight += w
            accepted_count += 1
        else:
            # Fallback/constraint entry: penalise
            positive_weight -= w * 0.5
            rejected_count += 1
        factor_str = b.factor.value
        if factor_str not in seen_factors:
            seen_factors.append(factor_str)

    if total_weight <= 0.0:
        return UNDETERMINED_CONFIDENCE

    raw_score = positive_weight / total_weight
    score = max(0.0, min(1.0, raw_score))
    band = _band_from_score(score)

    reason = (
        f"{accepted_count} accepted factor(s) / {rejected_count} constraint(s) "
        f"across {len(seen_factors)} distinct factor type(s) "
        f"→ confidence {score:.3f} ({band.value})"
    )

    return RouteConfidence(
        score=round(score, 4),
        band=band,
        basis_count=len(bases),
        accepted_factor_count=accepted_count,
        rejected_factor_count=rejected_count,
        contributing_factors=seen_factors,
        reason=reason,
    )
