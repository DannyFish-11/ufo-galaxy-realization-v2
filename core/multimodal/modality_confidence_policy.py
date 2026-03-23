"""core/multimodal/modality_confidence_policy.py — Source-to-Routing Calibration (PR-27)

**Unified-Subject Architecture — OpenClawd Core Policy**
---------------------------------------------------------
This module implements the explicit policy layer that calibrates source health,
modality confidence, and perception readiness into routing eligibility.

Shell / core boundary
---------------------
- The **runtime shell** (``DesktopPresenceRuntime``) owns source quality/health
  facts via :class:`~core.multimodal.perception_source_registry.PerceptionSourceRegistry`.
- **OpenClawd core** decides what those facts mean for routing via the policy
  structures defined here.
- The **execution/projection layers** consume the resulting decisions.

Public structures
-----------------
:class:`ModalityPresence`
    Whether a modality is present and how strong the signal is.

:class:`SourceDegradationSeverity`
    Calibrated severity of source degradation.

:class:`ModalityConfidencePolicy`
    Per-modality confidence calibration — combines source quality, degradation
    severity, freshness, and presence signals into a confidence score.

:class:`RoutingEligibilityReason`
    Stable vocabulary of routing eligibility reasons.

:class:`RoutingEligibilityAssessment`
    Assessment of whether a route tier is eligible, with structured reasons.

:class:`PerceptionRoutingReadiness`
    Top-level readiness contract that bridges perception/source state and
    model routing decisions.

Public builders
---------------
:func:`assess_modality_confidence`
    Compute a :class:`ModalityConfidencePolicy` from a source registry snapshot.

:func:`assess_routing_eligibility`
    Decide route-tier eligibility from a :class:`PerceptionRoutingReadiness`.

:func:`build_perception_routing_readiness`
    Build the top-level readiness object from canonical perception state and
    an optional source registry snapshot.

Serialisation
-------------
All public dataclasses expose ``to_dict()`` / ``from_dict()`` round-trip
methods.  All stored values are plain Python primitives so that
``json.dumps(obj.to_dict())`` always succeeds.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ModalityPresence(str, Enum):
    """Presence level of a modality in the current perception context."""

    ABSENT = "absent"
    """No signal for this modality (not present in request or continuous)."""

    WEAK = "weak"
    """Signal present but at low confidence or quality (e.g. degraded source)."""

    MODERATE = "moderate"
    """Signal present with acceptable quality but some degradation or staleness."""

    STRONG = "strong"
    """Signal present at high quality; sufficient to drive native multimodal routing."""


class SourceDegradationSeverity(str, Enum):
    """How severely a source is degraded, from the shell's perspective."""

    NONE = "none"
    """Source is healthy — no degradation."""

    LOW = "low"
    """Minor degradation; source is still usable with minor confidence penalty."""

    MEDIUM = "medium"
    """Moderate degradation; confidence is meaningfully reduced."""

    HIGH = "high"
    """Severe degradation; source may be unreliable for routing decisions."""

    UNAVAILABLE = "unavailable"
    """Source is completely unavailable; modality contribution is zero."""


class ModalitySemantics(str, Enum):
    """Whether a modality is required or optional for the current request."""

    REQUIRED = "required"
    """Routing MUST use native multimodal; text fallback is not acceptable."""

    PREFERRED = "preferred"
    """Native multimodal is preferred; text fallback is acceptable if needed."""

    OPTIONAL = "optional"
    """Multimodal is a soft hint; text routing is equally acceptable."""

    CONTINUOUS_ONLY = "continuous_only"
    """Modality comes from continuous perception only (no request-bound signal)."""


class RoutingEligibilityReason(str, Enum):
    """Stable vocabulary of reasons for routing eligibility decisions."""

    STRONG_MULTIMODAL_SIGNAL = "strong_multimodal_signal"
    """All active modalities have strong confidence — native MM eligible."""

    ADEQUATE_MULTIMODAL_SIGNAL = "adequate_multimodal_signal"
    """Confidence is acceptable (not degraded) — native MM eligible."""

    WEAK_SIGNAL_DEGRADED_ELIGIBILITY = "weak_signal_degraded_eligibility"
    """Modality confidence is low; native MM eligibility reduced."""

    SOURCE_DEGRADED = "source_degraded"
    """At least one source is degraded, reducing overall confidence."""

    SOURCE_UNAVAILABLE = "source_unavailable"
    """At least one required source is unavailable; eligibility blocked."""

    STALE_CONTINUOUS_PERCEPTION = "stale_continuous_perception"
    """Continuous perception data is stale; confidence penalty applied."""

    REQUEST_BOUND_OVERRIDE = "request_bound_override"
    """Request-bound multimodal context overrides missing continuous perception."""

    NO_MULTIMODAL_INPUT = "no_multimodal_input"
    """No multimodal input detected; native MM not warranted."""

    MODALITY_REQUIRED_BUT_ABSENT = "modality_required_but_absent"
    """A required modality is absent; routing cannot proceed to native MM."""

    CONFIDENCE_BELOW_THRESHOLD = "confidence_below_threshold"
    """Aggregate confidence is below the minimum threshold for native MM."""

    TEXT_ONLY_FALLBACK = "text_only_fallback"
    """System falls back to text-only routing."""


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

#: Minimum aggregate confidence required for native-multimodal eligibility.
NATIVE_MM_CONFIDENCE_THRESHOLD: float = 0.5

#: Maximum age in seconds before continuous perception is considered stale.
CONTINUOUS_PERCEPTION_STALENESS_THRESHOLD_S: float = 5.0

#: Confidence score assigned to a modality with no source information.
UNKNOWN_SOURCE_CONFIDENCE: float = 0.5


# ---------------------------------------------------------------------------
# ModalityConfidencePolicy
# ---------------------------------------------------------------------------


@dataclass
class ModalityConfidencePolicy:
    """Per-modality confidence calibration derived from shell source facts.

    Fields
    ------
    modality
        The sensory modality this policy applies to (e.g. ``"audio"``,
        ``"video"``, ``"image"``).
    presence
        Qualitative presence level for this modality.
    confidence_score
        Normalised confidence in the range ``[0.0, 1.0]``.  ``1.0`` means
        full confidence; ``0.0`` means the modality contributes nothing.
    source_quality_score
        Raw quality score reported by the source (may be ``None`` when
        unknown).
    degradation_severity
        Calibrated severity of the source degradation.
    is_stale
        ``True`` when the source data is older than the freshness threshold.
    staleness_age_s
        Age of the most recent source update in seconds.  ``None`` when
        unknown.
    semantics
        Whether this modality is required, preferred, optional, or continuous-
        only for the current routing context.
    contributing_source_ids
        Source IDs from the registry that contributed to this assessment.
    degradation_reasons
        Free-text reasons for any confidence reduction.
    """

    modality: str
    presence: ModalityPresence = ModalityPresence.ABSENT
    confidence_score: float = 0.0
    source_quality_score: Optional[float] = None
    degradation_severity: SourceDegradationSeverity = SourceDegradationSeverity.NONE
    is_stale: bool = False
    staleness_age_s: Optional[float] = None
    semantics: ModalitySemantics = ModalitySemantics.OPTIONAL
    contributing_source_ids: List[str] = field(default_factory=list)
    degradation_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "modality": self.modality,
            "presence": self.presence.value,
            "confidence_score": self.confidence_score,
            "source_quality_score": self.source_quality_score,
            "degradation_severity": self.degradation_severity.value,
            "is_stale": self.is_stale,
            "staleness_age_s": self.staleness_age_s,
            "semantics": self.semantics.value,
            "contributing_source_ids": list(self.contributing_source_ids),
            "degradation_reasons": list(self.degradation_reasons),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ModalityConfidencePolicy":
        return cls(
            modality=d.get("modality", ""),
            presence=ModalityPresence(d.get("presence", ModalityPresence.ABSENT.value)),
            confidence_score=float(d.get("confidence_score", 0.0)),
            source_quality_score=(
                float(d["source_quality_score"])
                if d.get("source_quality_score") is not None
                else None
            ),
            degradation_severity=SourceDegradationSeverity(
                d.get("degradation_severity", SourceDegradationSeverity.NONE.value)
            ),
            is_stale=bool(d.get("is_stale", False)),
            staleness_age_s=(
                float(d["staleness_age_s"])
                if d.get("staleness_age_s") is not None
                else None
            ),
            semantics=ModalitySemantics(
                d.get("semantics", ModalitySemantics.OPTIONAL.value)
            ),
            contributing_source_ids=list(d.get("contributing_source_ids", [])),
            degradation_reasons=list(d.get("degradation_reasons", [])),
        )


# ---------------------------------------------------------------------------
# RoutingEligibilityAssessment
# ---------------------------------------------------------------------------


@dataclass
class RoutingEligibilityAssessment:
    """Assessment of whether native multimodal routing is eligible.

    This is the *core policy output* — it encodes the routing tier decision
    together with structured, explainable reasons so the control loop can
    reason about eligibility without opaque boolean flags.

    Fields
    ------
    is_native_multimodal_eligible
        ``True`` when the confidence/readiness assessment supports using a
        native multimodal model.
    aggregate_confidence
        Aggregate confidence score across all active modalities ``[0.0, 1.0]``.
    primary_reason
        The dominant reason driving the eligibility decision (stable enum value).
    all_reasons
        All contributing reasons, ordered by significance.
    modality_policies
        Per-modality confidence policies that fed into this assessment.
    has_required_modality_absent
        ``True`` when any modality marked as ``REQUIRED`` is absent.
    is_degraded
        ``True`` when at least one contributing modality is degraded.
    degradation_severity
        Worst-case degradation severity across all modalities.
    eligibility_summary
        Concise human-readable summary for diagnostics/logging.
    """

    is_native_multimodal_eligible: bool = False
    aggregate_confidence: float = 0.0
    primary_reason: RoutingEligibilityReason = RoutingEligibilityReason.NO_MULTIMODAL_INPUT
    all_reasons: List[RoutingEligibilityReason] = field(default_factory=list)
    modality_policies: List[ModalityConfidencePolicy] = field(default_factory=list)
    has_required_modality_absent: bool = False
    is_degraded: bool = False
    degradation_severity: SourceDegradationSeverity = SourceDegradationSeverity.NONE
    eligibility_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_native_multimodal_eligible": self.is_native_multimodal_eligible,
            "aggregate_confidence": self.aggregate_confidence,
            "primary_reason": self.primary_reason.value,
            "all_reasons": [r.value for r in self.all_reasons],
            "modality_policies": [p.to_dict() for p in self.modality_policies],
            "has_required_modality_absent": self.has_required_modality_absent,
            "is_degraded": self.is_degraded,
            "degradation_severity": self.degradation_severity.value,
            "eligibility_summary": self.eligibility_summary,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RoutingEligibilityAssessment":
        return cls(
            is_native_multimodal_eligible=bool(
                d.get("is_native_multimodal_eligible", False)
            ),
            aggregate_confidence=float(d.get("aggregate_confidence", 0.0)),
            primary_reason=RoutingEligibilityReason(
                d.get("primary_reason", RoutingEligibilityReason.NO_MULTIMODAL_INPUT.value)
            ),
            all_reasons=[
                RoutingEligibilityReason(r)
                for r in d.get("all_reasons", [])
            ],
            modality_policies=[
                ModalityConfidencePolicy.from_dict(p)
                for p in d.get("modality_policies", [])
            ],
            has_required_modality_absent=bool(
                d.get("has_required_modality_absent", False)
            ),
            is_degraded=bool(d.get("is_degraded", False)),
            degradation_severity=SourceDegradationSeverity(
                d.get("degradation_severity", SourceDegradationSeverity.NONE.value)
            ),
            eligibility_summary=d.get("eligibility_summary", ""),
        )


# ---------------------------------------------------------------------------
# PerceptionRoutingReadiness
# ---------------------------------------------------------------------------


@dataclass
class PerceptionRoutingReadiness:
    """Top-level readiness contract bridging perception/source state and routing.

    This object is the primary artifact produced by the policy layer.  It
    combines:
    - the ``RoutingEligibilityAssessment`` (core policy output), and
    - metadata about both request-bound and continuous perception signals.

    The runtime shell populates source facts; OpenClawd evaluates them into
    readiness; the execution/projection layers consume the resulting
    eligibility decisions.

    Fields
    ------
    eligibility
        The routing eligibility assessment computed by OpenClawd policy.
    has_request_multimodal
        ``True`` when the current request carries explicit multimodal context
        (images, audio clips, etc.).
    has_continuous_perception
        ``True`` when the continuous ingress bus has active perception data.
    request_bound_modalities
        Modalities present in the request-bound context.
    continuous_modalities
        Modalities present in the continuous perception stream.
    continuous_perception_age_s
        Age of the most recent continuous perception snapshot in seconds, or
        ``None`` when unavailable.
    is_continuous_perception_stale
        ``True`` when continuous perception data is older than the freshness
        threshold.
    request_overrides_continuous
        ``True`` when request-bound multimodal context is sufficient to
        override missing or stale continuous perception.
    assessed_at
        Wall-clock timestamp when this readiness was assessed (``time.time()``).
    """

    eligibility: RoutingEligibilityAssessment = field(
        default_factory=RoutingEligibilityAssessment
    )
    has_request_multimodal: bool = False
    has_continuous_perception: bool = False
    request_bound_modalities: List[str] = field(default_factory=list)
    continuous_modalities: List[str] = field(default_factory=list)
    continuous_perception_age_s: Optional[float] = None
    is_continuous_perception_stale: bool = False
    request_overrides_continuous: bool = False
    assessed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "eligibility": self.eligibility.to_dict(),
            "has_request_multimodal": self.has_request_multimodal,
            "has_continuous_perception": self.has_continuous_perception,
            "request_bound_modalities": list(self.request_bound_modalities),
            "continuous_modalities": list(self.continuous_modalities),
            "continuous_perception_age_s": self.continuous_perception_age_s,
            "is_continuous_perception_stale": self.is_continuous_perception_stale,
            "request_overrides_continuous": self.request_overrides_continuous,
            "assessed_at": self.assessed_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PerceptionRoutingReadiness":
        eligibility_data = d.get("eligibility", {})
        return cls(
            eligibility=RoutingEligibilityAssessment.from_dict(eligibility_data)
            if eligibility_data
            else RoutingEligibilityAssessment(),
            has_request_multimodal=bool(d.get("has_request_multimodal", False)),
            has_continuous_perception=bool(d.get("has_continuous_perception", False)),
            request_bound_modalities=list(d.get("request_bound_modalities", [])),
            continuous_modalities=list(d.get("continuous_modalities", [])),
            continuous_perception_age_s=(
                float(d["continuous_perception_age_s"])
                if d.get("continuous_perception_age_s") is not None
                else None
            ),
            is_continuous_perception_stale=bool(
                d.get("is_continuous_perception_stale", False)
            ),
            request_overrides_continuous=bool(
                d.get("request_overrides_continuous", False)
            ),
            assessed_at=float(d.get("assessed_at", time.time())),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _severity_from_health(health_value: str) -> SourceDegradationSeverity:
    """Map a SourceHealthStatus string to SourceDegradationSeverity."""
    mapping = {
        "healthy": SourceDegradationSeverity.NONE,
        "degraded": SourceDegradationSeverity.MEDIUM,
        "unavailable": SourceDegradationSeverity.UNAVAILABLE,
        "unknown": SourceDegradationSeverity.LOW,
    }
    return mapping.get(health_value, SourceDegradationSeverity.LOW)


def _confidence_from_quality_and_severity(
    quality_score: Optional[float],
    severity: SourceDegradationSeverity,
    is_stale: bool,
) -> float:
    """Compute a normalised confidence score from quality and degradation facts."""
    # Base confidence
    if quality_score is not None:
        base = max(0.0, min(1.0, quality_score))
    else:
        base = UNKNOWN_SOURCE_CONFIDENCE

    # Degradation penalty
    penalty_map = {
        SourceDegradationSeverity.NONE: 0.0,
        SourceDegradationSeverity.LOW: 0.1,
        SourceDegradationSeverity.MEDIUM: 0.35,
        SourceDegradationSeverity.HIGH: 0.6,
        SourceDegradationSeverity.UNAVAILABLE: 1.0,
    }
    penalty = penalty_map.get(severity, 0.1)

    # Staleness penalty
    stale_penalty = 0.15 if is_stale else 0.0

    return max(0.0, base - penalty - stale_penalty)


def _presence_from_confidence(confidence: float) -> ModalityPresence:
    """Derive qualitative presence from confidence score."""
    if confidence <= 0.0:
        return ModalityPresence.ABSENT
    if confidence < 0.3:
        return ModalityPresence.WEAK
    if confidence < 0.65:
        return ModalityPresence.MODERATE
    return ModalityPresence.STRONG


def _worst_severity(
    severities: List[SourceDegradationSeverity],
) -> SourceDegradationSeverity:
    """Return the most severe degradation level from a list."""
    _order = [
        SourceDegradationSeverity.NONE,
        SourceDegradationSeverity.LOW,
        SourceDegradationSeverity.MEDIUM,
        SourceDegradationSeverity.HIGH,
        SourceDegradationSeverity.UNAVAILABLE,
    ]
    if not severities:
        return SourceDegradationSeverity.NONE
    return max(severities, key=lambda s: _order.index(s) if s in _order else 0)


# ---------------------------------------------------------------------------
# Public builder: assess_modality_confidence
# ---------------------------------------------------------------------------


def assess_modality_confidence(
    *,
    modality: str,
    source_records: Optional[List[Dict[str, Any]]] = None,
    semantics: ModalitySemantics = ModalitySemantics.OPTIONAL,
    now: Optional[float] = None,
) -> ModalityConfidencePolicy:
    """Compute a :class:`ModalityConfidencePolicy` from source registry facts.

    Parameters
    ----------
    modality:
        The modality label to assess (e.g. ``"audio"``, ``"video"``).
    source_records:
        A list of source record dicts from
        :meth:`~core.multimodal.perception_source_registry.PerceptionSourceRecord.to_dict`.
        If ``None`` or empty, returns an ABSENT policy with no confidence.
    semantics:
        Whether this modality is required/preferred/optional for routing.
    now:
        Current time (``time.time()``); injectable for tests.

    Returns
    -------
    ModalityConfidencePolicy
    """
    _now = now if now is not None else time.time()

    if not source_records:
        return ModalityConfidencePolicy(
            modality=modality,
            presence=ModalityPresence.ABSENT,
            confidence_score=0.0,
            degradation_severity=SourceDegradationSeverity.UNAVAILABLE,
            semantics=semantics,
        )

    contributing_ids: List[str] = []
    degradation_reasons: List[str] = []
    severities: List[SourceDegradationSeverity] = []
    scores: List[float] = []
    source_quality_scores: List[float] = []

    for rec in source_records:
        src_id = rec.get("source_id", "")
        health = rec.get("health", "unknown")
        quality = rec.get("quality_score")
        last_seen = rec.get("last_seen_at")
        deg_reasons: List[str] = rec.get("degradation_reasons") or []
        is_active = bool(rec.get("is_active", False))

        # Staleness
        is_stale = False
        staleness_age_s: Optional[float] = None
        if last_seen is not None:
            staleness_age_s = _now - float(last_seen)
            is_stale = staleness_age_s > CONTINUOUS_PERCEPTION_STALENESS_THRESHOLD_S

        severity = _severity_from_health(health)

        # An inactive source that the registry marks as "healthy" still warrants
        # a LOW confidence penalty: the source exists and was healthy last time
        # it was checked, but it is not currently delivering signal, so we cannot
        # be fully confident about its contribution.  LOW (rather than MEDIUM/HIGH)
        # reflects that the source is dormant, not broken.
        if not is_active and severity == SourceDegradationSeverity.NONE:
            severity = SourceDegradationSeverity.LOW

        score = _confidence_from_quality_and_severity(quality, severity, is_stale)

        contributing_ids.append(src_id)
        severities.append(severity)
        scores.append(score)
        degradation_reasons.extend(deg_reasons)
        if quality is not None:
            source_quality_scores.append(float(quality))

    # Aggregate: use best-source score when multiple sources exist
    aggregate_score = max(scores) if scores else 0.0
    worst_sev = _worst_severity(severities)
    avg_quality = (
        sum(source_quality_scores) / len(source_quality_scores)
        if source_quality_scores
        else None
    )

    # Recompute staleness for summary (use first record for simplicity)
    first_rec = source_records[0]
    last_seen_ts = first_rec.get("last_seen_at")
    is_stale_summary = False
    age_s: Optional[float] = None
    if last_seen_ts is not None:
        age_s = _now - float(last_seen_ts)
        is_stale_summary = age_s > CONTINUOUS_PERCEPTION_STALENESS_THRESHOLD_S

    presence = _presence_from_confidence(aggregate_score)

    return ModalityConfidencePolicy(
        modality=modality,
        presence=presence,
        confidence_score=round(aggregate_score, 4),
        source_quality_score=round(avg_quality, 4) if avg_quality is not None else None,
        degradation_severity=worst_sev,
        is_stale=is_stale_summary,
        staleness_age_s=round(age_s, 2) if age_s is not None else None,
        semantics=semantics,
        contributing_source_ids=contributing_ids,
        degradation_reasons=list(dict.fromkeys(degradation_reasons)),
    )


# ---------------------------------------------------------------------------
# Public builder: assess_routing_eligibility
# ---------------------------------------------------------------------------


def assess_routing_eligibility(
    modality_policies: List[ModalityConfidencePolicy],
    *,
    confidence_threshold: float = NATIVE_MM_CONFIDENCE_THRESHOLD,
) -> RoutingEligibilityAssessment:
    """Decide native multimodal route eligibility from modality confidence policies.

    Parameters
    ----------
    modality_policies:
        List of per-modality confidence policies.
    confidence_threshold:
        Minimum aggregate confidence required for native MM eligibility.

    Returns
    -------
    RoutingEligibilityAssessment
    """
    if not modality_policies:
        return RoutingEligibilityAssessment(
            is_native_multimodal_eligible=False,
            aggregate_confidence=0.0,
            primary_reason=RoutingEligibilityReason.NO_MULTIMODAL_INPUT,
            all_reasons=[RoutingEligibilityReason.NO_MULTIMODAL_INPUT],
            eligibility_summary="no_modality_policies — native MM not warranted",
        )

    reasons: List[RoutingEligibilityReason] = []
    worst_severity = SourceDegradationSeverity.NONE
    _sev_order = [
        SourceDegradationSeverity.NONE,
        SourceDegradationSeverity.LOW,
        SourceDegradationSeverity.MEDIUM,
        SourceDegradationSeverity.HIGH,
        SourceDegradationSeverity.UNAVAILABLE,
    ]

    has_required_absent = False
    is_degraded = False

    # Collect confidence scores (only from non-absent modalities)
    active_scores: List[float] = []

    for policy in modality_policies:
        if (
            policy.semantics == ModalitySemantics.REQUIRED
            and policy.presence == ModalityPresence.ABSENT
        ):
            has_required_absent = True
            reasons.append(RoutingEligibilityReason.MODALITY_REQUIRED_BUT_ABSENT)
            continue

        if policy.presence == ModalityPresence.ABSENT:
            continue

        active_scores.append(policy.confidence_score)

        if policy.degradation_severity not in (
            SourceDegradationSeverity.NONE,
            SourceDegradationSeverity.LOW,
        ):
            is_degraded = True
            reasons.append(RoutingEligibilityReason.SOURCE_DEGRADED)

        if policy.degradation_severity == SourceDegradationSeverity.UNAVAILABLE:
            reasons.append(RoutingEligibilityReason.SOURCE_UNAVAILABLE)

        if policy.is_stale:
            reasons.append(RoutingEligibilityReason.STALE_CONTINUOUS_PERCEPTION)

        # Track worst severity across all policies
        if _sev_order.index(policy.degradation_severity) > _sev_order.index(worst_severity):
            worst_severity = policy.degradation_severity

    # Compute aggregate confidence
    if not active_scores:
        aggregate = 0.0
    else:
        aggregate = sum(active_scores) / len(active_scores)

    # Eligibility decision
    if has_required_absent:
        primary = RoutingEligibilityReason.MODALITY_REQUIRED_BUT_ABSENT
        eligible = False
        summary = "required_modality_absent — native MM blocked"
    elif aggregate <= 0.0:
        primary = RoutingEligibilityReason.NO_MULTIMODAL_INPUT
        eligible = False
        summary = "no_active_modalities — native MM not warranted"
    elif aggregate < confidence_threshold:
        primary = RoutingEligibilityReason.CONFIDENCE_BELOW_THRESHOLD
        if is_degraded:
            reasons.insert(0, RoutingEligibilityReason.WEAK_SIGNAL_DEGRADED_ELIGIBILITY)
            primary = RoutingEligibilityReason.WEAK_SIGNAL_DEGRADED_ELIGIBILITY
        eligible = False
        summary = (
            f"confidence={aggregate:.3f} below threshold={confidence_threshold:.3f} "
            "— native MM eligibility reduced"
        )
    else:
        # Eligible
        if aggregate >= 0.8 and not is_degraded:
            primary = RoutingEligibilityReason.STRONG_MULTIMODAL_SIGNAL
        else:
            primary = RoutingEligibilityReason.ADEQUATE_MULTIMODAL_SIGNAL
        eligible = True
        summary = (
            f"confidence={aggregate:.3f} >= threshold={confidence_threshold:.3f} "
            "— native MM eligible"
        )

    # Deduplicate reasons, keep primary first
    seen: set = set()
    deduped: List[RoutingEligibilityReason] = []
    if primary not in seen:
        deduped.append(primary)
        seen.add(primary)
    for r in reasons:
        if r not in seen:
            deduped.append(r)
            seen.add(r)

    return RoutingEligibilityAssessment(
        is_native_multimodal_eligible=eligible,
        aggregate_confidence=round(aggregate, 4),
        primary_reason=primary,
        all_reasons=deduped,
        modality_policies=list(modality_policies),
        has_required_modality_absent=has_required_absent,
        is_degraded=is_degraded,
        degradation_severity=worst_severity,
        eligibility_summary=summary,
    )


# ---------------------------------------------------------------------------
# Public builder: build_perception_routing_readiness
# ---------------------------------------------------------------------------


def build_perception_routing_readiness(
    *,
    canonical_perception: Optional[Dict[str, Any]] = None,
    source_registry_snapshot: Optional[Dict[str, Any]] = None,
    confidence_threshold: float = NATIVE_MM_CONFIDENCE_THRESHOLD,
    now: Optional[float] = None,
) -> PerceptionRoutingReadiness:
    """Build the top-level :class:`PerceptionRoutingReadiness` from canonical state.

    This is the primary integration point: OpenClawd calls this function with
    the canonical perception state dict and the source registry snapshot to
    obtain an explicit, explainable readiness assessment.

    Parameters
    ----------
    canonical_perception:
        Serialised :class:`~core.perception.canonical_perception_state.CanonicalPerceptionState`
        dict.  May be ``None`` for text-only requests.
    source_registry_snapshot:
        Serialised snapshot from
        :meth:`~core.multimodal.perception_source_registry.PerceptionSourceRegistry.snapshot`.
        May be ``None`` when no registry data is available.
    confidence_threshold:
        Minimum aggregate confidence required for native MM eligibility.
    now:
        Current time (``time.time()``); injectable for tests.

    Returns
    -------
    PerceptionRoutingReadiness
    """
    _now = now if now is not None else time.time()

    # Defaults for text-only / empty input
    if not canonical_perception:
        eligibility = RoutingEligibilityAssessment(
            is_native_multimodal_eligible=False,
            aggregate_confidence=0.0,
            primary_reason=RoutingEligibilityReason.NO_MULTIMODAL_INPUT,
            all_reasons=[RoutingEligibilityReason.NO_MULTIMODAL_INPUT],
            eligibility_summary="no_canonical_perception — text_only",
        )
        return PerceptionRoutingReadiness(
            eligibility=eligibility,
            assessed_at=_now,
        )

    has_request_mm = bool(canonical_perception.get("has_request_multimodal", False))
    has_continuous = bool(canonical_perception.get("has_continuous_perception", False))
    active_modalities: List[str] = list(
        canonical_perception.get("active_modalities") or []
    )
    requires_native = bool(canonical_perception.get("requires_native_multimodal", False))
    continuous_wall_clock: Optional[float] = canonical_perception.get(
        "continuous_wall_clock"
    )

    # When requires_native_multimodal=True but has_request_multimodal is not
    # explicitly set (e.g. minimal/legacy perception dicts), treat the native-
    # multimodal requirement as evidence of request-bound content.
    has_any_multimodal = has_request_mm or has_continuous or (
        requires_native and bool(active_modalities)
    )

    # Staleness of continuous perception
    continuous_age_s: Optional[float] = None
    is_continuous_stale = False
    if continuous_wall_clock is not None:
        continuous_age_s = _now - float(continuous_wall_clock)
        is_continuous_stale = (
            continuous_age_s > CONTINUOUS_PERCEPTION_STALENESS_THRESHOLD_S
        )

    # Separate request-bound vs continuous modalities
    request_bound_modalities = list(active_modalities) if has_request_mm else []
    continuous_modalities = list(active_modalities) if has_continuous else []

    # Request-bound override: request multimodal input can compensate for
    # missing or stale continuous perception.
    request_overrides_continuous = has_request_mm and (
        not has_continuous or is_continuous_stale
    )

    # Build per-modality confidence policies
    modality_policies: List[ModalityConfidencePolicy] = []

    # Index source registry records by modality for fast lookup
    registry_sources_by_modality: Dict[str, List[Dict[str, Any]]] = {}
    if source_registry_snapshot:
        sources_list = source_registry_snapshot.get("sources") or []
        for src in sources_list:
            mod = src.get("modality", "")
            registry_sources_by_modality.setdefault(mod, []).append(src)

    # Determine semantics for each active modality.
    # When requires_native_multimodal=True, the perception state has already
    # determined that native MM is needed; use REQUIRED semantics so the
    # eligibility assessment correctly blocks routing if the modality is absent.
    modality_semantics = (
        ModalitySemantics.REQUIRED if requires_native else ModalitySemantics.PREFERRED
    )

    for mod in active_modalities:
        # Find registry records for this modality (also check "multi")
        rec_list = (
            registry_sources_by_modality.get(mod, [])
            + registry_sources_by_modality.get("multi", [])
        )

        # If no registry data but there is multimodal context (request-bound,
        # continuous, or implied by requires_native_multimodal), synthesise a
        # moderately confident record to reflect the available signal.
        if not rec_list and has_any_multimodal:
            # Modality is signalled by the canonical perception state but has
            # no live source registration.  Treat as moderately confident.
            pol = ModalityConfidencePolicy(
                modality=mod,
                presence=ModalityPresence.MODERATE,
                confidence_score=0.7,
                degradation_severity=SourceDegradationSeverity.NONE,
                is_stale=False,
                semantics=modality_semantics,
            )
            modality_policies.append(pol)
            continue

        pol = assess_modality_confidence(
            modality=mod,
            source_records=rec_list,
            semantics=modality_semantics,
            now=_now,
        )

        # Request-bound override: if request carries this modality, boost
        # confidence when continuous source is stale/absent.
        if request_overrides_continuous and mod in request_bound_modalities:
            if pol.presence == ModalityPresence.ABSENT:
                pol.presence = ModalityPresence.MODERATE
                pol.confidence_score = max(pol.confidence_score, 0.6)
                pol.degradation_reasons.append("request_bound_override_applied")

        modality_policies.append(pol)

    # Assess eligibility from all modality policies
    eligibility = assess_routing_eligibility(
        modality_policies,
        confidence_threshold=confidence_threshold,
    )

    # Add request_bound_override reason if applicable
    if request_overrides_continuous and eligibility.is_native_multimodal_eligible:
        if RoutingEligibilityReason.REQUEST_BOUND_OVERRIDE not in eligibility.all_reasons:
            eligibility.all_reasons.append(
                RoutingEligibilityReason.REQUEST_BOUND_OVERRIDE
            )

    return PerceptionRoutingReadiness(
        eligibility=eligibility,
        has_request_multimodal=has_request_mm,
        has_continuous_perception=has_continuous,
        request_bound_modalities=request_bound_modalities,
        continuous_modalities=continuous_modalities,
        continuous_perception_age_s=(
            round(continuous_age_s, 2) if continuous_age_s is not None else None
        ),
        is_continuous_perception_stale=is_continuous_stale,
        request_overrides_continuous=request_overrides_continuous,
        assessed_at=_now,
    )
