#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""core/degraded_operation_envelope.py — Degraded Operation Envelopes (PR-29)

**Unified-Subject Architecture — Provider Failover and Degraded Multimodal**
-----------------------------------------------------------------------------
This module introduces the **canonical degraded-operation framework**: a
normalized, serialisable representation of provider failover sequencing and
reduced-capability operation so the system can express, classify, and surface
degraded states explicitly and coherently.

Shell / core boundary
---------------------
- The **runtime shell** (``DesktopPresenceRuntime``) remains the authority for
  source/session facts and shell-facing status projection.
- **OpenClawd core** remains the authority for route selection, fallback
  sequencing, and degraded-operation policy — this module is its canonical
  vocabulary.
- **Execution/projection/diagnostics layers** consume the resulting envelope
  without inventing their own degradation semantics.

This module converts fallback from an *ad hoc* sequence of downgrade branches
into a **normalized degraded-operation framework**.

Public structures
-----------------
:class:`DegradedOperationLevel`
    Stable vocabulary of normalized degradation levels from full multimodal
    down to no-op/observe-only.

:class:`ProviderFailoverReason`
    Structured taxonomy of reasons that can trigger provider failover.

:class:`DegradedOperationSeverity`
    Operator-facing health/severity classification of the current operating
    envelope.

:class:`ProviderFailoverStep`
    One step in a provider failover sequence: the candidate tried, the outcome,
    and the reason it was selected or skipped.

:class:`ProviderFailoverChain`
    Ordered sequence of :class:`ProviderFailoverStep` entries representing the
    full failover sequence from the preferred provider down to the final result.

:class:`FallbackPolicyLadder`
    Normalized degradation ladder mapping each :class:`DegradedOperationLevel`
    to a policy-governed threshold and the reason it was entered.

:class:`DegradedOperationEnvelope`
    Top-level canonical envelope aggregating the current degradation level,
    failover chain, policy ladder, severity, and structured reasoning.  Fully
    serialisable and suitable for shell-facing projection and observability.

Public builders
---------------
:func:`build_provider_failover_step`
    Construct a :class:`ProviderFailoverStep` from raw routing decision data.

:func:`build_provider_failover_chain`
    Build a :class:`ProviderFailoverChain` from a multimodal route dict and
    an optional canonical model supply snapshot.

:func:`build_fallback_policy_ladder`
    Derive a :class:`FallbackPolicyLadder` from routing and execution state.

:func:`build_degraded_operation_envelope`
    Primary integration point for OpenClawd: build a
    :class:`DegradedOperationEnvelope` from a routing decision dict, optional
    supply state, and optional prior envelope for transition tracking.

:func:`envelope_summary`
    Produce a compact projection-safe summary dict from a
    :class:`DegradedOperationEnvelope`.

Serialisation
-------------
All public dataclasses expose ``to_dict()`` / ``from_dict()`` round-trip
methods.  All stored values are plain Python primitives so that
``json.dumps(obj.to_dict())`` always succeeds.

Design principles
-----------------
- **Fallback ladder is explicit** — the system knows not just that it degraded,
  but to which normalized level and why.
- **Provider failover is policy-governed** — failover is not an implicit retry
  chain with unclear semantics.
- **Projection/diagnostics compatibility** — the envelope is serialisable and
  suitable for shell-facing projection.
- **Do not duplicate authority** — OpenClawd remains the place where
  degraded-operation policy is determined; this module provides the vocabulary.
- **Additive only** — does not modify any existing module.
- **Graceful defaults** — all fields beyond the primary key are optional.

Usage::

    from core.degraded_operation_envelope import (
        DegradedOperationEnvelope,
        ProviderFailoverChain,
        FallbackPolicyLadder,
        DegradedOperationLevel,
        build_degraded_operation_envelope,
    )

    # From a multimodal route dict produced by OpenClawd._select_multimodal_route()
    route_dict = {
        "route_type": "text_only",
        "provider": "openai",
        "model": "gpt-4o",
        "fallback_reason": "native_mm_unavailable",
        "is_native_multimodal": False,
    }
    envelope = build_degraded_operation_envelope(route_dict)
    payload = envelope.to_dict()   # projection-safe

"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class DegradedOperationLevel(str, Enum):
    """Stable vocabulary of normalized degradation levels.

    The ladder descends from full multimodal capability at the top to
    observe-only / no-op at the bottom.  Each level is a string value safe
    for serialisation, counter keys, and policy tuning.
    """

    FULL_NATIVE_MULTIMODAL = "full_native_multimodal"
    """Tier-1: native multimodal API active; all modalities supported."""

    PARTIAL_MULTIMODAL = "partial_multimodal"
    """Tier-2: native multimodal unavailable; text-capable provider handles
    fusion summary derived from multimodal input."""

    TEXT_SUMMARY_FALLBACK = "text_summary_fallback"
    """Tier-3: multimodal input cannot be routed; system summarises context and
    routes as pure text to any available provider."""

    OBSERVE_ONLY = "observe_only"
    """Tier-4: no actionable response produced; system observes and may log.
    Suitable for advisory / diagnostic modes."""

    NO_OP = "no_op"
    """Tier-5: no providers available; system is fully degraded.  Any response
    is a locally-generated advisory message."""

    UNKNOWN = "unknown"
    """Unclassified degradation state.  Used as a safe default."""

    @classmethod
    def from_route_type(cls, route_type: Optional[str]) -> "DegradedOperationLevel":
        """Derive a :class:`DegradedOperationLevel` from a raw ``route_type`` string.

        Maps the routing tier strings produced by
        :meth:`~core.openclawd.OpenClawd._select_multimodal_route` to the
        canonical degradation ladder.
        """
        _map = {
            "native_multimodal": cls.FULL_NATIVE_MULTIMODAL,
            "partial_multimodal": cls.PARTIAL_MULTIMODAL,
            "text_only": cls.TEXT_SUMMARY_FALLBACK,
            "advisory": cls.OBSERVE_ONLY,
            "none": cls.NO_OP,
        }
        if route_type is None:
            return cls.UNKNOWN
        return _map.get(str(route_type).lower(), cls.UNKNOWN)

    @classmethod
    def from_string(cls, value: Optional[str]) -> "DegradedOperationLevel":
        """Return a :class:`DegradedOperationLevel` from a string, falling back to
        ``UNKNOWN`` for unrecognised values."""
        if value is None:
            return cls.UNKNOWN
        try:
            return cls(value)
        except ValueError:
            return cls.UNKNOWN


class ProviderFailoverReason(str, Enum):
    """Structured taxonomy of reasons that can trigger provider failover.

    Values are lowercase strings safe for serialisation and policy analysis.
    """

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    """The preferred provider is down or unreachable."""

    PROVIDER_DEGRADED = "provider_degraded"
    """The preferred provider is reachable but health-status is degraded."""

    NATIVE_MULTIMODAL_UNSUPPORTED = "native_multimodal_unsupported"
    """The preferred provider does not support native multimodal API for the
    current active modalities."""

    CONFIDENCE_BELOW_THRESHOLD = "confidence_below_threshold"
    """Modality confidence is below the eligibility threshold for native
    multimodal routing (see :mod:`~core.multimodal.modality_confidence_policy`)."""

    ROUTER_UNAVAILABLE = "router_unavailable"
    """The router itself is unavailable or uninitialised."""

    ROUTING_ERROR = "routing_error"
    """An exception occurred during the routing decision."""

    NO_PROVIDERS_AVAILABLE = "no_providers_available"
    """No providers are configured or all are down."""

    CAPABILITY_MISMATCH = "capability_mismatch"
    """Provider does not meet the required capability for the current request."""

    POLICY_GOVERNED = "policy_governed"
    """Failover was explicitly directed by operator policy rather than a failure."""

    UNKNOWN = "unknown"
    """Reason could not be determined."""

    @classmethod
    def from_string(cls, value: Optional[str]) -> "ProviderFailoverReason":
        """Return a :class:`ProviderFailoverReason` from a string; falls back to
        ``UNKNOWN`` for unrecognised values."""
        if value is None:
            return cls.UNKNOWN
        # Normalise common raw reason strings from routing internals
        _normalise: Dict[str, ProviderFailoverReason] = {
            "router_unavailable": cls.ROUTER_UNAVAILABLE,
            "routing_error": cls.ROUTING_ERROR,
            "no_providers_available": cls.NO_PROVIDERS_AVAILABLE,
            "provider_unavailable": cls.PROVIDER_UNAVAILABLE,
            "confidence_below_threshold": cls.CONFIDENCE_BELOW_THRESHOLD,
        }
        v = str(value).lower()
        if v in _normalise:
            return _normalise[v]
        # Try direct enum lookup
        try:
            return cls(v)
        except ValueError:
            # Heuristic keyword matching for raw reason strings embedded in
            # multi-word reason phrases (e.g. "router_unavailable degraded_to=advisory")
            if "router_unavailable" in v:
                return cls.ROUTER_UNAVAILABLE
            if "no_providers" in v or "no_provider" in v:
                return cls.NO_PROVIDERS_AVAILABLE
            if "unavailable" in v:
                return cls.PROVIDER_UNAVAILABLE
            if "degraded" in v:
                return cls.PROVIDER_DEGRADED
            if "confidence" in v or "threshold" in v:
                return cls.CONFIDENCE_BELOW_THRESHOLD
            if "multimodal" in v or "native" in v:
                return cls.NATIVE_MULTIMODAL_UNSUPPORTED
            if "error" in v or "exception" in v:
                return cls.ROUTING_ERROR
            return cls.UNKNOWN


class DegradedOperationSeverity(str, Enum):
    """Operator-facing health/severity classification of the current operating
    envelope.  Maps onto standard health severity vocabularies.
    """

    OK = "ok"
    """System is operating at full capability.  No degradation."""

    WARNING = "warning"
    """System is operating at reduced capability but still functional.
    Suitable for monitoring without immediate action."""

    DEGRADED = "degraded"
    """System capability is meaningfully reduced; some features unavailable.
    Operator should investigate."""

    CRITICAL = "critical"
    """System is operating in a severely reduced or observe-only mode.
    Immediate operator attention recommended."""

    UNKNOWN = "unknown"
    """Severity cannot be determined."""

    @classmethod
    def from_level(cls, level: DegradedOperationLevel) -> "DegradedOperationSeverity":
        """Derive a :class:`DegradedOperationSeverity` from a
        :class:`DegradedOperationLevel`."""
        _map: Dict[DegradedOperationLevel, DegradedOperationSeverity] = {
            DegradedOperationLevel.FULL_NATIVE_MULTIMODAL: cls.OK,
            DegradedOperationLevel.PARTIAL_MULTIMODAL: cls.WARNING,
            DegradedOperationLevel.TEXT_SUMMARY_FALLBACK: cls.DEGRADED,
            DegradedOperationLevel.OBSERVE_ONLY: cls.CRITICAL,
            DegradedOperationLevel.NO_OP: cls.CRITICAL,
            DegradedOperationLevel.UNKNOWN: cls.UNKNOWN,
        }
        return _map.get(level, cls.UNKNOWN)

    @classmethod
    def from_string(cls, value: Optional[str]) -> "DegradedOperationSeverity":
        if value is None:
            return cls.UNKNOWN
        try:
            return cls(str(value).lower())
        except ValueError:
            return cls.UNKNOWN


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ProviderFailoverStep:
    """One step in a provider failover sequence.

    Represents a single candidate that was tried (or skipped) during provider
    failover, capturing why it was selected or why the system moved on to the
    next candidate.
    """

    step_index: int = 0
    """Zero-based position in the failover sequence."""

    provider: str = "unknown"
    """Provider name at this failover step."""

    model: str = ""
    """Model selected at this step (empty string if unavailable)."""

    selected: bool = False
    """Whether this step's provider was ultimately used for the request."""

    skipped: bool = False
    """Whether this step was skipped without attempting (e.g. known-down)."""

    failover_reason: str = ProviderFailoverReason.UNKNOWN.value
    """Structured :class:`ProviderFailoverReason` value explaining why the
    system progressed past this step (if ``selected=False``)."""

    raw_reason: str = ""
    """Verbatim reason string from the routing internals, preserved for
    diagnostics."""

    health_status: str = "unknown"
    """Canonical health status of the provider at this step, e.g. ``healthy``,
    ``degraded``, ``down``."""

    is_native_multimodal: bool = False
    """Whether the provider at this step supports native multimodal API."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_index": self.step_index,
            "provider": self.provider,
            "model": self.model,
            "selected": self.selected,
            "skipped": self.skipped,
            "failover_reason": self.failover_reason,
            "raw_reason": self.raw_reason,
            "health_status": self.health_status,
            "is_native_multimodal": self.is_native_multimodal,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProviderFailoverStep":
        return cls(
            step_index=int(d.get("step_index") or 0),
            provider=str(d.get("provider") or "unknown"),
            model=str(d.get("model") or ""),
            selected=bool(d.get("selected", False)),
            skipped=bool(d.get("skipped", False)),
            failover_reason=str(
                d.get("failover_reason") or ProviderFailoverReason.UNKNOWN.value
            ),
            raw_reason=str(d.get("raw_reason") or ""),
            health_status=str(d.get("health_status") or "unknown"),
            is_native_multimodal=bool(d.get("is_native_multimodal", False)),
        )


@dataclass
class ProviderFailoverChain:
    """Ordered sequence of failover steps representing the full provider failover
    path from the preferred provider down to the final selected provider.

    This converts an *ad hoc* retry sequence into a canonical, policy-governed
    artifact that can be audited, serialised, and compared across requests.
    """

    chain_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this failover chain instance."""

    steps: List[ProviderFailoverStep] = field(default_factory=list)
    """Ordered list of failover steps.  The final step with ``selected=True``
    is the provider that will service the request."""

    final_provider: str = "unknown"
    """The provider ultimately selected (mirrors the last ``selected=True``
    step's provider)."""

    final_model: str = ""
    """The model ultimately selected."""

    total_steps: int = 0
    """Total number of candidates evaluated (including skipped steps)."""

    failover_occurred: bool = False
    """True if the preferred provider was not used; i.e. the chain has more
    than one step or the first step was not selected."""

    primary_failover_reason: str = ProviderFailoverReason.UNKNOWN.value
    """The most significant :class:`ProviderFailoverReason` across all steps."""

    timestamp: float = field(default_factory=time.time)
    """Unix timestamp when this chain was built."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "steps": [s.to_dict() for s in self.steps],
            "final_provider": self.final_provider,
            "final_model": self.final_model,
            "total_steps": self.total_steps,
            "failover_occurred": self.failover_occurred,
            "primary_failover_reason": self.primary_failover_reason,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ProviderFailoverChain":
        steps = [
            ProviderFailoverStep.from_dict(s) for s in (d.get("steps") or [])
        ]
        return cls(
            chain_id=str(d.get("chain_id") or str(uuid.uuid4())),
            steps=steps,
            final_provider=str(d.get("final_provider") or "unknown"),
            final_model=str(d.get("final_model") or ""),
            total_steps=int(d.get("total_steps") or len(steps)),
            failover_occurred=bool(d.get("failover_occurred", False)),
            primary_failover_reason=str(
                d.get("primary_failover_reason") or ProviderFailoverReason.UNKNOWN.value
            ),
            timestamp=float(d.get("timestamp") or time.time()),
        )


@dataclass
class FallbackLadderRung:
    """One rung on the :class:`FallbackPolicyLadder`.

    Captures whether a given degradation level is currently active, the reason
    it was entered, and the transition metadata.
    """

    level: str = DegradedOperationLevel.UNKNOWN.value
    """The :class:`DegradedOperationLevel` this rung represents."""

    active: bool = False
    """Whether the system is currently at this rung."""

    entry_reason: str = ""
    """Structured reason why the system entered this rung (if active)."""

    entered_at: Optional[float] = None
    """Unix timestamp when this rung was entered (if active)."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "active": self.active,
            "entry_reason": self.entry_reason,
            "entered_at": self.entered_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FallbackLadderRung":
        return cls(
            level=str(d.get("level") or DegradedOperationLevel.UNKNOWN.value),
            active=bool(d.get("active", False)),
            entry_reason=str(d.get("entry_reason") or ""),
            entered_at=float(d["entered_at"]) if d.get("entered_at") is not None else None,
        )


@dataclass
class FallbackPolicyLadder:
    """Normalized degradation ladder mapping each :class:`DegradedOperationLevel`
    to its activation state and the policy-governed reason for entering it.

    The ladder makes the entire degradation progression explicit and auditable.
    OpenClawd remains the authority for deciding which rung is active; this
    structure is the canonical vocabulary that captures the decision.
    """

    ladder_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this ladder snapshot."""

    rungs: List[FallbackLadderRung] = field(default_factory=list)
    """All ladder rungs in descending capability order.  Exactly one rung
    should have ``active=True`` at any time."""

    current_level: str = DegradedOperationLevel.UNKNOWN.value
    """The currently active :class:`DegradedOperationLevel` value."""

    prior_level: Optional[str] = None
    """The previous :class:`DegradedOperationLevel` value, if a transition
    occurred.  ``None`` if this is the first observed state."""

    transition_occurred: bool = False
    """True if ``current_level`` differs from ``prior_level``."""

    timestamp: float = field(default_factory=time.time)
    """Unix timestamp when this ladder snapshot was taken."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ladder_id": self.ladder_id,
            "rungs": [r.to_dict() for r in self.rungs],
            "current_level": self.current_level,
            "prior_level": self.prior_level,
            "transition_occurred": self.transition_occurred,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FallbackPolicyLadder":
        rungs = [FallbackLadderRung.from_dict(r) for r in (d.get("rungs") or [])]
        return cls(
            ladder_id=str(d.get("ladder_id") or str(uuid.uuid4())),
            rungs=rungs,
            current_level=str(
                d.get("current_level") or DegradedOperationLevel.UNKNOWN.value
            ),
            prior_level=str(d["prior_level"]) if d.get("prior_level") is not None else None,
            transition_occurred=bool(d.get("transition_occurred", False)),
            timestamp=float(d.get("timestamp") or time.time()),
        )


@dataclass
class DegradedOperationEnvelope:
    """Top-level canonical envelope for degraded-operation state.

    Aggregates the current degradation level, provider failover chain, policy
    ladder, operator-facing severity, and structured reasoning into one
    serialisable artifact.

    This envelope is the primary integration point between:
    - **OpenClawd core** (which populates it from routing/fallback decisions);
    - **projection layers** (which surface it to the operator);
    - **diagnostics/telemetry** (which record it for observability).

    All downstream consumers should read the envelope rather than inventing
    their own degradation semantics.
    """

    envelope_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this envelope instance (UUID4)."""

    current_level: str = DegradedOperationLevel.UNKNOWN.value
    """The currently active :class:`DegradedOperationLevel` value.  This is the
    primary signal for downstream consumers."""

    severity: str = DegradedOperationSeverity.UNKNOWN.value
    """Operator-facing :class:`DegradedOperationSeverity` derived from
    ``current_level``."""

    failover_chain: Optional[Dict[str, Any]] = None
    """Serialised :class:`ProviderFailoverChain`, or ``None`` if not available."""

    fallback_ladder: Optional[Dict[str, Any]] = None
    """Serialised :class:`FallbackPolicyLadder`, or ``None`` if not available."""

    failover_reasons: List[str] = field(default_factory=list)
    """Ordered list of structured :class:`ProviderFailoverReason` values that
    drove the current degradation state.  Stable strings safe for aggregation."""

    degradation_summary: str = ""
    """Human-readable summary of the current degradation state, suitable for
    operator display."""

    is_degraded: bool = False
    """Convenience flag: ``True`` when ``current_level`` is not
    :attr:`DegradedOperationLevel.FULL_NATIVE_MULTIMODAL`."""

    is_observe_only: bool = False
    """Convenience flag: ``True`` when capability is advisory/observe-only or
    no-op."""

    provider: str = "unknown"
    """The provider ultimately selected for this request."""

    model: str = ""
    """The model ultimately selected."""

    prior_level: Optional[str] = None
    """Prior :class:`DegradedOperationLevel` before the most recent transition,
    useful for transition tracking across the control loop."""

    transition_occurred: bool = False
    """True if the degradation level changed from ``prior_level``."""

    trace_id: Optional[str] = None
    """Correlation trace ID for the request that produced this envelope."""

    timestamp: float = field(default_factory=time.time)
    """Unix timestamp when this envelope was created."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "envelope_id": self.envelope_id,
            "current_level": self.current_level,
            "severity": self.severity,
            "failover_chain": self.failover_chain,
            "fallback_ladder": self.fallback_ladder,
            "failover_reasons": list(self.failover_reasons),
            "degradation_summary": self.degradation_summary,
            "is_degraded": self.is_degraded,
            "is_observe_only": self.is_observe_only,
            "provider": self.provider,
            "model": self.model,
            "prior_level": self.prior_level,
            "transition_occurred": self.transition_occurred,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DegradedOperationEnvelope":
        return cls(
            envelope_id=str(d.get("envelope_id") or str(uuid.uuid4())),
            current_level=str(
                d.get("current_level") or DegradedOperationLevel.UNKNOWN.value
            ),
            severity=str(d.get("severity") or DegradedOperationSeverity.UNKNOWN.value),
            failover_chain=d.get("failover_chain"),
            fallback_ladder=d.get("fallback_ladder"),
            failover_reasons=list(d.get("failover_reasons") or []),
            degradation_summary=str(d.get("degradation_summary") or ""),
            is_degraded=bool(d.get("is_degraded", False)),
            is_observe_only=bool(d.get("is_observe_only", False)),
            provider=str(d.get("provider") or "unknown"),
            model=str(d.get("model") or ""),
            prior_level=str(d["prior_level"]) if d.get("prior_level") is not None else None,
            transition_occurred=bool(d.get("transition_occurred", False)),
            trace_id=str(d["trace_id"]) if d.get("trace_id") is not None else None,
            timestamp=float(d.get("timestamp") or time.time()),
        )


# ---------------------------------------------------------------------------
# Builder functions
# ---------------------------------------------------------------------------


def build_provider_failover_step(
    step_index: int,
    provider: str,
    model: str,
    *,
    selected: bool = False,
    skipped: bool = False,
    failover_reason: Optional[str] = None,
    raw_reason: str = "",
    health_status: str = "unknown",
    is_native_multimodal: bool = False,
) -> ProviderFailoverStep:
    """Construct a :class:`ProviderFailoverStep` from raw routing decision data.

    Parameters
    ----------
    step_index:
        Zero-based position in the failover sequence.
    provider:
        Provider name at this step.
    model:
        Model selected at this step.
    selected:
        Whether this step's provider was used for the request.
    skipped:
        Whether this step was skipped without attempting.
    failover_reason:
        Structured :class:`ProviderFailoverReason` or raw string.  If raw,
        it will be normalised via :meth:`ProviderFailoverReason.from_string`.
    raw_reason:
        Verbatim reason string preserved for diagnostics.
    health_status:
        Health status string for the provider at this step.
    is_native_multimodal:
        Whether the provider supports native multimodal API.

    Returns
    -------
    ProviderFailoverStep
    """
    _reason = ProviderFailoverReason.from_string(failover_reason)
    return ProviderFailoverStep(
        step_index=step_index,
        provider=provider or "unknown",
        model=model or "",
        selected=selected,
        skipped=skipped,
        failover_reason=_reason.value,
        raw_reason=raw_reason or "",
        health_status=health_status or "unknown",
        is_native_multimodal=bool(is_native_multimodal),
    )


def build_provider_failover_chain(
    route_dict: Optional[Dict[str, Any]],
    supply_snapshot: Optional[Dict[str, Any]] = None,
) -> ProviderFailoverChain:
    """Build a :class:`ProviderFailoverChain` from a routing decision dict.

    Constructs a policy-governed failover chain artifact from the canonical
    multimodal route dict produced by
    :meth:`~core.openclawd.OpenClawd._select_multimodal_route`.

    Parameters
    ----------
    route_dict:
        The dict returned by ``_select_multimodal_route()``.  Expected keys
        include ``provider``, ``model``, ``route_type``, ``fallback_reason``,
        ``is_native_multimodal``.
    supply_snapshot:
        Optional canonical model supply state dict (from
        :class:`~core.model_topology.canonical_model_supply_state.CanonicalModelSupplyState`).
        When provided, skipped providers are derived from supply records.

    Returns
    -------
    ProviderFailoverChain
        Never raises; returns a safe minimal chain on any error.
    """
    try:
        if not route_dict:
            return ProviderFailoverChain()

        final_provider = str(route_dict.get("provider") or "unknown")
        final_model = str(route_dict.get("model") or "")
        route_type = str(route_dict.get("route_type") or "")
        raw_fallback_reason = str(route_dict.get("fallback_reason") or "")
        is_native_mm = bool(route_dict.get("is_native_multimodal", False))

        steps: List[ProviderFailoverStep] = []

        # ── Derive skipped / failed steps from supply snapshot ────────────────
        # If supply information is available, build a step per provider record
        # that was down or degraded (these were tried first and skipped).
        _skipped_providers: List[str] = []
        if supply_snapshot and isinstance(supply_snapshot, dict):
            supply_records = supply_snapshot.get("providers") or []
            for rec in supply_records:
                if not isinstance(rec, dict):
                    continue
                pname = str(rec.get("provider_name") or rec.get("provider") or "")
                pstatus = str(rec.get("health_status") or "unknown").lower()
                if pname and pname != final_provider and pstatus in ("down", "degraded"):
                    _skipped_providers.append(pname)
                    steps.append(
                        build_provider_failover_step(
                            step_index=len(steps),
                            provider=pname,
                            model=str(rec.get("default_model") or ""),
                            selected=False,
                            skipped=True,
                            failover_reason=ProviderFailoverReason.PROVIDER_UNAVAILABLE.value
                            if pstatus == "down"
                            else ProviderFailoverReason.PROVIDER_DEGRADED.value,
                            raw_reason=f"health_status={pstatus}",
                            health_status=pstatus,
                            is_native_multimodal=bool(
                                rec.get("native_multimodal_capability", {}).get(
                                    "has_native_multimodal", False
                                )
                                if isinstance(rec.get("native_multimodal_capability"), dict)
                                else False
                            ),
                        )
                    )

        # ── Final selected step ───────────────────────────────────────────────
        _primary_reason = ProviderFailoverReason.from_string(raw_fallback_reason)
        if final_provider != "none":
            steps.append(
                build_provider_failover_step(
                    step_index=len(steps),
                    provider=final_provider,
                    model=final_model,
                    selected=True,
                    skipped=False,
                    failover_reason=_primary_reason.value,
                    raw_reason=raw_fallback_reason,
                    health_status="healthy"
                    if route_type != "advisory"
                    else "unavailable",
                    is_native_multimodal=is_native_mm,
                )
            )
        else:
            # No provider available — advisory/no-op step
            steps.append(
                build_provider_failover_step(
                    step_index=len(steps),
                    provider="none",
                    model="none",
                    selected=True,
                    skipped=False,
                    failover_reason=ProviderFailoverReason.NO_PROVIDERS_AVAILABLE.value,
                    raw_reason=raw_fallback_reason or "no_providers_available",
                    health_status="unavailable",
                    is_native_multimodal=False,
                )
            )

        failover_occurred = len(steps) > 1 or bool(_skipped_providers) or bool(
            raw_fallback_reason
        )

        return ProviderFailoverChain(
            steps=steps,
            final_provider=final_provider,
            final_model=final_model,
            total_steps=len(steps),
            failover_occurred=failover_occurred,
            primary_failover_reason=_primary_reason.value,
        )
    except Exception as _exc:
        logger.debug("build_provider_failover_chain failed (swallowed): %s", _exc)
        return ProviderFailoverChain()


def build_fallback_policy_ladder(
    current_level: DegradedOperationLevel,
    prior_level: Optional[DegradedOperationLevel] = None,
    entry_reason: str = "",
) -> FallbackPolicyLadder:
    """Derive a :class:`FallbackPolicyLadder` from routing and execution state.

    Constructs a ladder with all canonical rungs populated, marking exactly one
    rung as active.

    Parameters
    ----------
    current_level:
        The currently active degradation level.
    prior_level:
        The previous degradation level, for transition tracking.
    entry_reason:
        Structured reason why the current rung was entered.

    Returns
    -------
    FallbackPolicyLadder
        Never raises; returns a safe default ladder on any error.
    """
    try:
        # Build all rungs in descending capability order
        _all_levels = [
            DegradedOperationLevel.FULL_NATIVE_MULTIMODAL,
            DegradedOperationLevel.PARTIAL_MULTIMODAL,
            DegradedOperationLevel.TEXT_SUMMARY_FALLBACK,
            DegradedOperationLevel.OBSERVE_ONLY,
            DegradedOperationLevel.NO_OP,
        ]
        rungs: List[FallbackLadderRung] = []
        now = time.time()
        for lvl in _all_levels:
            is_active = lvl == current_level
            rungs.append(
                FallbackLadderRung(
                    level=lvl.value,
                    active=is_active,
                    entry_reason=entry_reason if is_active else "",
                    entered_at=now if is_active else None,
                )
            )

        transition = (
            prior_level is not None
            and prior_level != current_level
            and prior_level != DegradedOperationLevel.UNKNOWN
        )

        return FallbackPolicyLadder(
            rungs=rungs,
            current_level=current_level.value,
            prior_level=prior_level.value if prior_level is not None else None,
            transition_occurred=transition,
        )
    except Exception as _exc:
        logger.debug("build_fallback_policy_ladder failed (swallowed): %s", _exc)
        return FallbackPolicyLadder()


def build_degraded_operation_envelope(
    route_dict: Optional[Dict[str, Any]],
    supply_snapshot: Optional[Dict[str, Any]] = None,
    prior_envelope: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> DegradedOperationEnvelope:
    """Primary builder for :class:`DegradedOperationEnvelope`.

    This is the main integration point for
    :meth:`~core.openclawd.OpenClawd._build_degraded_operation_envelope`.
    Derives a complete, serialisable envelope from the canonical routing
    decision dict, optional supply state, and an optional prior envelope for
    transition tracking.

    Parameters
    ----------
    route_dict:
        The dict returned by ``_select_multimodal_route()``.
    supply_snapshot:
        Optional :class:`~core.model_topology.canonical_model_supply_state.CanonicalModelSupplyState`
        dict for deriving skipped provider steps.
    prior_envelope:
        Optional prior :class:`DegradedOperationEnvelope` dict for tracking
        level transitions across the control loop.
    trace_id:
        Correlation trace ID for the request.

    Returns
    -------
    DegradedOperationEnvelope
        Never raises; returns a safe minimal envelope on any error.
    """
    try:
        if not route_dict:
            return DegradedOperationEnvelope(trace_id=trace_id)

        route_type = str(route_dict.get("route_type") or "")
        raw_fallback_reason = str(route_dict.get("fallback_reason") or "")
        final_provider = str(route_dict.get("provider") or "unknown")
        final_model = str(route_dict.get("model") or "")

        # ── Determine current degradation level ───────────────────────────────
        current_level = DegradedOperationLevel.from_route_type(route_type)

        # ── Extract prior level for transition tracking ───────────────────────
        prior_level: Optional[DegradedOperationLevel] = None
        if prior_envelope and isinstance(prior_envelope, dict):
            _prior_str = prior_envelope.get("current_level")
            if _prior_str:
                prior_level = DegradedOperationLevel.from_string(str(_prior_str))

        # ── Derive severity ───────────────────────────────────────────────────
        severity = DegradedOperationSeverity.from_level(current_level)

        # ── Collect structured failover reasons ───────────────────────────────
        reasons: List[str] = []
        if raw_fallback_reason:
            _r = ProviderFailoverReason.from_string(raw_fallback_reason)
            if _r != ProviderFailoverReason.UNKNOWN:
                reasons.append(_r.value)
            else:
                # Preserve the raw reason as-is for diagnostics
                reasons.append(raw_fallback_reason)

        # ── Build failover chain ──────────────────────────────────────────────
        chain = build_provider_failover_chain(route_dict, supply_snapshot)
        # Merge any additional failover reasons from skipped steps
        for step in chain.steps:
            if step.skipped and step.failover_reason:
                _fr = step.failover_reason
                if _fr not in reasons:
                    reasons.append(_fr)

        # ── Build fallback ladder ─────────────────────────────────────────────
        ladder = build_fallback_policy_ladder(
            current_level=current_level,
            prior_level=prior_level,
            entry_reason=raw_fallback_reason,
        )

        # ── Convenience flags ─────────────────────────────────────────────────
        is_degraded = current_level != DegradedOperationLevel.FULL_NATIVE_MULTIMODAL
        is_observe_only = current_level in (
            DegradedOperationLevel.OBSERVE_ONLY,
            DegradedOperationLevel.NO_OP,
        )

        # ── Degradation summary ───────────────────────────────────────────────
        _summary_parts: List[str] = [f"level={current_level.value}"]
        if raw_fallback_reason:
            _summary_parts.append(f"reason={raw_fallback_reason[:80]}")
        if chain.failover_occurred:
            _summary_parts.append(f"failover=true steps={chain.total_steps}")
        degradation_summary = " ".join(_summary_parts)

        # ── Transition detection ──────────────────────────────────────────────
        transition_occurred = (
            prior_level is not None
            and prior_level != current_level
            and prior_level != DegradedOperationLevel.UNKNOWN
        )

        return DegradedOperationEnvelope(
            current_level=current_level.value,
            severity=severity.value,
            failover_chain=chain.to_dict(),
            fallback_ladder=ladder.to_dict(),
            failover_reasons=reasons,
            degradation_summary=degradation_summary,
            is_degraded=is_degraded,
            is_observe_only=is_observe_only,
            provider=final_provider,
            model=final_model,
            prior_level=prior_level.value if prior_level is not None else None,
            transition_occurred=transition_occurred,
            trace_id=trace_id,
        )
    except Exception as _exc:
        logger.debug("build_degraded_operation_envelope failed (swallowed): %s", _exc)
        return DegradedOperationEnvelope(trace_id=trace_id)


def envelope_summary(envelope: DegradedOperationEnvelope) -> Dict[str, Any]:
    """Produce a compact, projection-safe summary dict from a
    :class:`DegradedOperationEnvelope`.

    Suitable for embedding in desktop status projection and observability
    payloads without the full nested chain/ladder details.

    Parameters
    ----------
    envelope:
        A populated :class:`DegradedOperationEnvelope`.

    Returns
    -------
    dict
        Compact summary with stable keys.
    """
    try:
        return {
            "envelope_id": envelope.envelope_id,
            "current_level": envelope.current_level,
            "severity": envelope.severity,
            "is_degraded": envelope.is_degraded,
            "is_observe_only": envelope.is_observe_only,
            "provider": envelope.provider,
            "model": envelope.model,
            "failover_occurred": (
                envelope.failover_chain.get("failover_occurred", False)
                if isinstance(envelope.failover_chain, dict)
                else False
            ),
            "failover_reasons": list(envelope.failover_reasons),
            "degradation_summary": envelope.degradation_summary,
            "transition_occurred": envelope.transition_occurred,
            "prior_level": envelope.prior_level,
            "trace_id": envelope.trace_id,
            "timestamp": envelope.timestamp,
        }
    except Exception as _exc:
        logger.debug("envelope_summary failed (swallowed): %s", _exc)
        return {
            "envelope_id": getattr(envelope, "envelope_id", ""),
            "current_level": DegradedOperationLevel.UNKNOWN.value,
            "severity": DegradedOperationSeverity.UNKNOWN.value,
            "is_degraded": True,
            "is_observe_only": False,
        }
