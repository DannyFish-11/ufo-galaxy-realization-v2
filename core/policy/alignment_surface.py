"""
core/policy/alignment_surface.py
===================================
Execution Policy Alignment Surface — PR-28.

This module introduces the canonical **Execution Policy Alignment Surface**: a
unified, serialisable object that answers, in one narrow read-only structure,
whether the current execution-policy signals are aligned or contradictory across
runtime, projection, governance, and cross-device/device-formation surfaces.

It answers:
- Are runtime policy, readiness policy, fallback posture, dispatch/handoff
  posture, and projection governance in agreement?
- If they are not aligned, where is the mismatch?
- Is the current posture local-preferred, local-then-expand, remote-required,
  blocked, degraded, or confirmation-gated?
- What policy hints should downstream status surfaces, debugging tools, and
  later mesh/session work consume?

This module is the "policy explanation" counterpart to the existing governance
chain:

- PR-25 standardised execution lifecycle trace.
- PR-26 standardised projection-safe governance assembly.
- PR-27 standardised the runtime-side governance posture snapshot.
- PR-28 (this module) standardises whether these policies and surfaces are
  aligned, and makes misalignment explicit.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **No breaking API changes** — fully backward-compatible with all existing
  consumers of :class:`~core.projection.runtime_projection.RuntimeProjection`,
  :class:`~core.projection.assembly_governance.ProjectionGovernanceSummary`,
  and :class:`~core.runtime_governance.snapshot.RuntimeGovernanceSnapshot`.
- **Fully serialisable** — all contracts provide ``to_dict()`` and ``to_json()``
  for stable, round-trippable JSON output.
- **Graceful degradation** — every helper and the top-level assembler return
  minimal safe values when inputs are ``None`` or malformed; they never raise
  to callers.
- **No UI semantics** — contracts carry no widget, view, or rendering
  references.
- **Stable field names** — field names are fixed and will not be renamed
  without a new major contract version.
- **Read-only** — this surface is purely descriptive; it does not change any
  policy, state, or routing.

Public surface
--------------
Contracts:
    - :class:`AlignmentMismatch`
    - :class:`AlignmentDimensionSummary`
    - :class:`ExecutionPolicyHints`
    - :class:`ExecutionPolicyAlignmentSummary`

Assembly helpers:
    - :func:`summarize_runtime_policy_alignment`
    - :func:`summarize_dispatch_policy_alignment`
    - :func:`summarize_projection_policy_alignment`
    - :func:`build_execution_policy_alignment_surface`

Usage::

    from core.policy.alignment_surface import build_execution_policy_alignment_surface

    alignment = build_execution_policy_alignment_surface(
        runtime_governance_snapshot=snapshot,
        projection_governance=gov_summary,
        intent_profile=profile,
        readiness_result=readiness,
        fallback_trace=trace,
        execution_trace_envelope=envelope,
        tri_state_phase="manifest",
        runtime_domain="local",
        trace_id="trace-abc",
        runtime_session_id="sess-xyz",
    )
    payload = alignment.to_dict()

See ``docs/EXECUTION_POLICY_ALIGNMENT_SURFACE.md`` for the full specification.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("Galaxy.Policy.AlignmentSurface")

# ---------------------------------------------------------------------------
# Policy posture constants
# ---------------------------------------------------------------------------

POSTURE_LOCAL_PREFERRED = "local_preferred"
POSTURE_LOCAL_THEN_EXPAND = "local_then_expand"
POSTURE_REMOTE_REQUIRED = "remote_required"
POSTURE_BLOCKED = "blocked"
POSTURE_DEGRADED = "degraded"
POSTURE_CONFIRMATION_GATED = "confirmation_gated"
POSTURE_UNKNOWN = "unknown"

_VALID_POSTURES = frozenset(
    {
        POSTURE_LOCAL_PREFERRED,
        POSTURE_LOCAL_THEN_EXPAND,
        POSTURE_REMOTE_REQUIRED,
        POSTURE_BLOCKED,
        POSTURE_DEGRADED,
        POSTURE_CONFIRMATION_GATED,
        POSTURE_UNKNOWN,
    }
)


# ---------------------------------------------------------------------------
# AlignmentMismatch
# ---------------------------------------------------------------------------


class AlignmentMismatch(BaseModel):
    """Describes a single detected policy mismatch between two dimensions.

    Fields
    ------
    dimension_a
        Name of the first policy dimension in the mismatch
        (e.g. ``"runtime_policy"``).
    dimension_b
        Name of the second policy dimension in the mismatch
        (e.g. ``"readiness_policy"``).
    field_a
        Field name on dimension_a that differs.  ``None`` when the mismatch
        is at the dimension level (e.g. availability discrepancy).
    field_b
        Field name on dimension_b that differs.  Equals ``field_a`` when the
        same logical field is compared across dimensions.
    value_a
        Observed value on dimension_a.  Always serialisable.
    value_b
        Observed value on dimension_b.  Always serialisable.
    severity
        Mismatch severity: ``"info"`` | ``"warning"`` | ``"critical"``.
        Defaults to ``"warning"``.
    description
        Human-readable explanation of why this is a mismatch.
    """

    dimension_a: str = Field(description="First dimension name.")
    dimension_b: str = Field(description="Second dimension name.")
    field_a: Optional[str] = Field(default=None, description="Field on dimension_a.")
    field_b: Optional[str] = Field(default=None, description="Field on dimension_b.")
    value_a: Optional[Any] = Field(default=None, description="Observed value on dimension_a.")
    value_b: Optional[Any] = Field(default=None, description="Observed value on dimension_b.")
    severity: str = Field(
        default="warning",
        description="Mismatch severity: 'info' | 'warning' | 'critical'.",
    )
    description: str = Field(default="", description="Human-readable mismatch explanation.")

    model_config = {"from_attributes": True}

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string."""
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# AlignmentDimensionSummary
# ---------------------------------------------------------------------------


class AlignmentDimensionSummary(BaseModel):
    """Compact summary of a single policy dimension used in alignment evaluation.

    One instance of this class is produced per dimension (runtime, readiness,
    fallback, dispatch, projection).  Downstream consumers can inspect
    individual dimensions when a mismatch is detected.

    Fields
    ------
    dimension
        Canonical dimension name.  One of:
        ``"runtime_policy"`` / ``"readiness_policy"`` / ``"fallback_policy"`` /
        ``"dispatch_policy"`` / ``"projection_policy"``.
    available
        ``True`` when real data was available for this dimension.
    posture_signal
        The policy-posture signal extracted from this dimension.
        ``None`` when unavailable.
    blocked
        ``True`` when this dimension signals a hard block.
    degraded
        ``True`` when this dimension signals a degraded state.
    confirmation_required
        ``True`` when this dimension requires explicit confirmation.
    cross_device_allowed
        ``True`` when this dimension allows cross-device execution.
        ``None`` when the dimension does not carry this signal.
    runtime_domain
        Runtime domain signal from this dimension.  ``None`` when
        unavailable.
    action_level
        Action level from this dimension.  ``None`` when unavailable.
    summary_fields
        Any additional dimension-specific fields useful for mismatch
        explanations.  Always serialisable.
    """

    dimension: str = Field(description="Canonical dimension name.")
    available: bool = Field(default=False, description="True when real data was sourced.")
    posture_signal: Optional[str] = Field(
        default=None, description="Policy posture signal from this dimension."
    )
    blocked: bool = Field(default=False, description="True when this dimension signals a block.")
    degraded: bool = Field(
        default=False, description="True when this dimension signals degraded state."
    )
    confirmation_required: bool = Field(
        default=False, description="True when this dimension requires confirmation."
    )
    cross_device_allowed: Optional[bool] = Field(
        default=None,
        description="True when cross-device execution is allowed per this dimension.",
    )
    runtime_domain: Optional[str] = Field(
        default=None, description="Runtime domain from this dimension."
    )
    action_level: Optional[str] = Field(
        default=None, description="Action level from this dimension."
    )
    summary_fields: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional dimension-specific fields for mismatch context.",
    )

    model_config = {"from_attributes": True}

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string."""
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# ExecutionPolicyHints
# ---------------------------------------------------------------------------


class ExecutionPolicyHints(BaseModel):
    """Quick-access boolean/string hints derived from the alignment surface.

    These hints are intended for downstream consumers — status surfaces,
    debugging tools, and future mesh/session work — that need to act quickly
    on the current posture without unpacking the full alignment summary.

    Fields
    ------
    can_execute_locally
        ``True`` when local execution is currently permitted.
    can_expand_cross_device
        ``True`` when cross-device expansion is currently permitted by all
        aligned dimensions.
    is_confirmation_gated
        ``True`` when at least one aligned dimension requires confirmation.
    is_blocked
        ``True`` when any dimension signals a hard block.
    is_degraded
        ``True`` when the surface is operating in degraded mode (some
        dimensions unavailable or in conflict).
    preferred_domain
        Best-guess preferred runtime domain for the current posture.
        One of ``"local"`` / ``"cross_device"`` / ``"transition"`` /
        ``None``.
    effective_action_level
        The most conservative action level across all available dimensions.
        One of ``"observe"`` / ``"hint"`` / ``"assist"`` / ``"execute"``.
        Defaults to ``"observe"`` when unavailable.
    alignment_confidence
        A [0.0, 1.0] confidence score for the alignment assessment.  Higher
        values mean more dimensions were available and consistent.
    policy_posture
        The resolved policy posture string.
    hint_source
        Indicates whether hints were derived from ``"full"`` (all dimensions
        available), ``"partial"`` (some dimensions unavailable), or
        ``"empty"`` (no dimensions available) data.
    """

    can_execute_locally: bool = Field(
        default=False, description="True when local execution is currently permitted."
    )
    can_expand_cross_device: bool = Field(
        default=False, description="True when cross-device expansion is permitted."
    )
    is_confirmation_gated: bool = Field(
        default=False, description="True when confirmation is required by at least one dimension."
    )
    is_blocked: bool = Field(
        default=False, description="True when any dimension signals a hard block."
    )
    is_degraded: bool = Field(
        default=False, description="True when operating in degraded mode."
    )
    preferred_domain: Optional[str] = Field(
        default=None, description="Best-guess preferred runtime domain."
    )
    effective_action_level: str = Field(
        default="observe", description="Most conservative action level across dimensions."
    )
    alignment_confidence: float = Field(
        default=0.0, description="Alignment assessment confidence [0.0, 1.0]."
    )
    policy_posture: str = Field(
        default=POSTURE_UNKNOWN, description="Resolved policy posture string."
    )
    hint_source: str = Field(
        default="empty",
        description="Data completeness: 'full' | 'partial' | 'empty'.",
    )

    model_config = {"from_attributes": True}

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string."""
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# ExecutionPolicyAlignmentSummary — top-level canonical alignment surface
# ---------------------------------------------------------------------------


class ExecutionPolicyAlignmentSummary(BaseModel):
    """Canonical Execution Policy Alignment Surface (PR-28).

    The single narrow contract that answers whether the current execution-policy
    signals are aligned or contradictory across runtime, projection, governance,
    and cross-device/device-formation surfaces.

    This is the "policy explanation" layer that sits above existing governance
    summaries and answers *why* the system chose a particular route/posture.

    Fields
    ------
    alignment_id
        Unique ID of this alignment assessment (UUID4).
    trace_id
        Execution trace ID from the originating trace envelope.  ``None``
        when unavailable.
    runtime_session_id
        Runtime session ID.  ``None`` when unavailable.
    runtime_domain
        Resolved runtime domain at alignment time.  ``None`` when
        unresolvable.
    tri_state_phase
        Tri-state phase at alignment time.  ``None`` when unresolvable.
    aligned
        ``True`` when all available policy dimensions are in agreement.
    blocked
        ``True`` when any dimension signals a hard block.
    degraded
        ``True`` when the surface is in degraded mode (partial inputs or
        dimension conflicts).
    confirmation_required
        ``True`` when at least one dimension requires explicit confirmation.
    policy_posture
        The resolved policy posture.  One of:
        ``"local_preferred"`` / ``"local_then_expand"`` /
        ``"remote_required"`` / ``"blocked"`` / ``"degraded"`` /
        ``"confirmation_gated"`` / ``"unknown"``.
    runtime_policy_summary
        Alignment dimension summary for the runtime policy dimension.
    readiness_policy_summary
        Alignment dimension summary for the readiness/gate dimension.
    fallback_policy_summary
        Alignment dimension summary for the fallback posture dimension.
    dispatch_policy_summary
        Alignment dimension summary for the dispatch/handoff dimension.
    projection_policy_summary
        Alignment dimension summary for the projection governance dimension.
    mismatches
        Ordered list of detected policy mismatches.  Empty when aligned.
    alignment_hints
        Quick-access hints for downstream consumers.
    timestamp
        Unix epoch seconds when this alignment was assembled.
    """

    alignment_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique ID of this alignment assessment.",
    )
    trace_id: Optional[str] = Field(default=None, description="Execution trace ID.")
    runtime_session_id: Optional[str] = Field(default=None, description="Runtime session ID.")
    runtime_domain: Optional[str] = Field(
        default=None, description="Resolved runtime domain."
    )
    tri_state_phase: Optional[str] = Field(
        default=None, description="Tri-state phase at alignment time."
    )
    aligned: bool = Field(
        default=False, description="True when all available dimensions are in agreement."
    )
    blocked: bool = Field(
        default=False, description="True when any dimension signals a hard block."
    )
    degraded: bool = Field(
        default=False, description="True when operating in degraded/partial mode."
    )
    confirmation_required: bool = Field(
        default=False, description="True when confirmation is required."
    )
    policy_posture: str = Field(
        default=POSTURE_UNKNOWN, description="Resolved policy posture."
    )
    runtime_policy_summary: AlignmentDimensionSummary = Field(
        default_factory=lambda: AlignmentDimensionSummary(dimension="runtime_policy"),
        description="Dimension summary for runtime policy.",
    )
    readiness_policy_summary: AlignmentDimensionSummary = Field(
        default_factory=lambda: AlignmentDimensionSummary(dimension="readiness_policy"),
        description="Dimension summary for readiness/gate policy.",
    )
    fallback_policy_summary: AlignmentDimensionSummary = Field(
        default_factory=lambda: AlignmentDimensionSummary(dimension="fallback_policy"),
        description="Dimension summary for fallback posture.",
    )
    dispatch_policy_summary: AlignmentDimensionSummary = Field(
        default_factory=lambda: AlignmentDimensionSummary(dimension="dispatch_policy"),
        description="Dimension summary for dispatch/handoff policy.",
    )
    projection_policy_summary: AlignmentDimensionSummary = Field(
        default_factory=lambda: AlignmentDimensionSummary(dimension="projection_policy"),
        description="Dimension summary for projection governance.",
    )
    mismatches: List[AlignmentMismatch] = Field(
        default_factory=list,
        description="Ordered list of detected policy mismatches.",
    )
    alignment_hints: ExecutionPolicyHints = Field(
        default_factory=ExecutionPolicyHints,
        description="Quick-access hints for downstream consumers.",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds when this alignment was assembled.",
    )

    model_config = {"from_attributes": True}

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        d = self.model_dump()
        # Ensure nested models are dicts (pydantic v2 model_dump already does this)
        return d

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string."""
        return json.dumps(self.to_dict(), **kwargs)

    def __repr__(self) -> str:
        return (
            f"<ExecutionPolicyAlignmentSummary "
            f"alignment_id={self.alignment_id!r} "
            f"phase={self.tri_state_phase!r} "
            f"posture={self.policy_posture!r} "
            f"aligned={self.aligned} "
            f"mismatches={len(self.mismatches)}>"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_str(val: Any, default: str = "") -> str:
    """Return a safe string from any value."""
    if val is None:
        return default
    if isinstance(val, str):
        return val
    if hasattr(val, "value"):
        return str(val.value)
    return str(val)


def _safe_bool(val: Any, default: bool = False) -> bool:
    """Return a safe bool from any value."""
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return bool(val)
    if isinstance(val, str):
        return val.lower() in {"true", "1", "yes"}
    return default


def _safe_float(val: Any, default: float = 0.0) -> float:
    """Return a safe float from any value."""
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _action_level_rank(action_level: Optional[str]) -> int:
    """Return numeric rank for an action level (lower = more conservative)."""
    _ranks = {"observe": 0, "hint": 1, "assist": 2, "execute": 3}
    return _ranks.get(_safe_str(action_level, "observe"), 0)


def _most_conservative_action_level(levels: List[Optional[str]]) -> str:
    """Return the most conservative (lowest rank) action level."""
    valid = [al for al in levels if al is not None]
    if not valid:
        return "observe"
    return min(valid, key=_action_level_rank)


def _detect_mismatches(
    dimensions: List[AlignmentDimensionSummary],
) -> List[AlignmentMismatch]:
    """Detect policy mismatches between available dimension pairs.

    Returns a list of :class:`AlignmentMismatch` objects (may be empty).
    Never raises.
    """
    mismatches: List[AlignmentMismatch] = []
    try:
        available = [d for d in dimensions if d.available]
        if len(available) < 2:
            return mismatches

        for i, da in enumerate(available):
            for db in available[i + 1 :]:
                # Check blocked mismatch
                if da.blocked != db.blocked:
                    mismatches.append(
                        AlignmentMismatch(
                            dimension_a=da.dimension,
                            dimension_b=db.dimension,
                            field_a="blocked",
                            field_b="blocked",
                            value_a=da.blocked,
                            value_b=db.blocked,
                            severity="critical",
                            description=(
                                f"{da.dimension} blocked={da.blocked} conflicts with "
                                f"{db.dimension} blocked={db.blocked}"
                            ),
                        )
                    )

                # Check confirmation_required mismatch
                if da.confirmation_required != db.confirmation_required:
                    mismatches.append(
                        AlignmentMismatch(
                            dimension_a=da.dimension,
                            dimension_b=db.dimension,
                            field_a="confirmation_required",
                            field_b="confirmation_required",
                            value_a=da.confirmation_required,
                            value_b=db.confirmation_required,
                            severity="warning",
                            description=(
                                f"{da.dimension} confirmation_required="
                                f"{da.confirmation_required} conflicts with "
                                f"{db.dimension} confirmation_required="
                                f"{db.confirmation_required}"
                            ),
                        )
                    )

                # Check cross_device_allowed mismatch (only when both signals present)
                if (
                    da.cross_device_allowed is not None
                    and db.cross_device_allowed is not None
                    and da.cross_device_allowed != db.cross_device_allowed
                ):
                    mismatches.append(
                        AlignmentMismatch(
                            dimension_a=da.dimension,
                            dimension_b=db.dimension,
                            field_a="cross_device_allowed",
                            field_b="cross_device_allowed",
                            value_a=da.cross_device_allowed,
                            value_b=db.cross_device_allowed,
                            severity="warning",
                            description=(
                                f"{da.dimension} cross_device_allowed="
                                f"{da.cross_device_allowed} conflicts with "
                                f"{db.dimension} cross_device_allowed="
                                f"{db.cross_device_allowed}"
                            ),
                        )
                    )

                # Check runtime_domain mismatch (only when both signals present)
                if (
                    da.runtime_domain is not None
                    and db.runtime_domain is not None
                    and da.runtime_domain != db.runtime_domain
                ):
                    mismatches.append(
                        AlignmentMismatch(
                            dimension_a=da.dimension,
                            dimension_b=db.dimension,
                            field_a="runtime_domain",
                            field_b="runtime_domain",
                            value_a=da.runtime_domain,
                            value_b=db.runtime_domain,
                            severity="info",
                            description=(
                                f"{da.dimension} runtime_domain={da.runtime_domain!r} "
                                f"differs from {db.dimension} runtime_domain="
                                f"{db.runtime_domain!r}"
                            ),
                        )
                    )

    except Exception as exc:
        logger.warning("_detect_mismatches: unexpected error: %s", exc)
    return mismatches


def _derive_posture(
    dimensions: List[AlignmentDimensionSummary],
    mismatches: List[AlignmentMismatch],
    tri_state_phase: Optional[str],
    runtime_domain: Optional[str],
) -> str:
    """Derive the policy posture from all available dimensions.

    Returns one of the POSTURE_* constants.  Never raises.
    """
    try:
        available = [d for d in dimensions if d.available]

        # Hard block wins
        if any(d.blocked for d in available):
            return POSTURE_BLOCKED

        # No available dimensions → unknown
        if not available:
            return POSTURE_UNKNOWN

        # Degraded: critical mismatches or multiple available dimensions degraded
        has_critical_mismatch = any(m.severity == "critical" for m in mismatches)
        if has_critical_mismatch:
            return POSTURE_DEGRADED

        degraded_count = sum(1 for d in available if d.degraded)
        if degraded_count >= 2 or (len(available) == 1 and available[0].degraded):
            return POSTURE_DEGRADED

        # Confirmation gated
        if any(d.confirmation_required for d in available):
            return POSTURE_CONFIRMATION_GATED

        # Cross-device routing
        cross_device_signals = [d.cross_device_allowed for d in available if d.cross_device_allowed is not None]
        if cross_device_signals:
            all_cross = all(s is True for s in cross_device_signals)
            any_cross = any(s is True for s in cross_device_signals)
            domain = _safe_str(runtime_domain)
            if all_cross or domain == "cross_device":
                return POSTURE_REMOTE_REQUIRED
            if any_cross:
                return POSTURE_LOCAL_THEN_EXPAND

        # Domain-based fallback
        domain = _safe_str(runtime_domain)
        if domain == "cross_device":
            return POSTURE_REMOTE_REQUIRED
        if domain in ("local", ""):
            return POSTURE_LOCAL_PREFERRED

        return POSTURE_LOCAL_PREFERRED

    except Exception as exc:
        logger.warning("_derive_posture: unexpected error: %s", exc)
        return POSTURE_UNKNOWN


def _build_hints(
    dimensions: List[AlignmentDimensionSummary],
    posture: str,
    mismatches: List[AlignmentMismatch],
    runtime_domain: Optional[str],
) -> ExecutionPolicyHints:
    """Build quick-access hints from all alignment inputs.

    Never raises.
    """
    try:
        available = [d for d in dimensions if d.available]
        available_count = len(available)
        total_count = len(dimensions)

        is_blocked = posture == POSTURE_BLOCKED or any(d.blocked for d in available)
        is_degraded = posture == POSTURE_DEGRADED or any(d.degraded for d in available)
        is_confirmation_gated = any(d.confirmation_required for d in available)

        # Cross-device: only allowed when all available dimensions explicitly allow it
        cross_signals = [d.cross_device_allowed for d in available if d.cross_device_allowed is not None]
        can_expand_cross_device = bool(cross_signals) and all(s is True for s in cross_signals)

        can_execute_locally = (
            not is_blocked
            and posture not in (POSTURE_BLOCKED, POSTURE_REMOTE_REQUIRED)
        )

        # Preferred domain
        preferred_domain: Optional[str] = runtime_domain
        if preferred_domain is None:
            domain_signals = [d.runtime_domain for d in available if d.runtime_domain]
            if domain_signals:
                preferred_domain = domain_signals[0]

        # Effective action level — most conservative across available dimensions
        action_levels = [d.action_level for d in available if d.action_level is not None]
        effective_action_level = _most_conservative_action_level(action_levels)

        # Confidence: fraction of dimensions that are available and no critical mismatches
        critical_count = sum(1 for m in mismatches if m.severity == "critical")
        raw_confidence = (available_count / total_count) if total_count > 0 else 0.0
        penalty = min(critical_count * 0.2, 0.5)
        alignment_confidence = max(0.0, min(1.0, raw_confidence - penalty))

        if available_count == 0:
            hint_source = "empty"
        elif available_count < total_count:
            hint_source = "partial"
        else:
            hint_source = "full"

        return ExecutionPolicyHints(
            can_execute_locally=can_execute_locally,
            can_expand_cross_device=can_expand_cross_device,
            is_confirmation_gated=is_confirmation_gated,
            is_blocked=is_blocked,
            is_degraded=is_degraded,
            preferred_domain=preferred_domain,
            effective_action_level=effective_action_level,
            alignment_confidence=alignment_confidence,
            policy_posture=posture,
            hint_source=hint_source,
        )
    except Exception as exc:
        logger.warning("_build_hints: unexpected error: %s", exc)
        return ExecutionPolicyHints(policy_posture=posture)


# ---------------------------------------------------------------------------
# Assembly helpers — summarize_* adapters
# ---------------------------------------------------------------------------


def summarize_runtime_policy_alignment(
    runtime_governance_snapshot: Optional[Any] = None,
) -> AlignmentDimensionSummary:
    """Build the runtime-policy dimension summary from a RuntimeGovernanceSnapshot.

    Extracts intent, readiness, and execution posture from the snapshot.
    Always returns a valid :class:`AlignmentDimensionSummary`; never raises.

    Parameters
    ----------
    runtime_governance_snapshot:
        Optional :class:`~core.runtime_governance.snapshot.RuntimeGovernanceSnapshot`
        (PR-27) or compatible dict/object.
    """
    try:
        if runtime_governance_snapshot is None:
            return AlignmentDimensionSummary(dimension="runtime_policy")

        # Handle dict
        if isinstance(runtime_governance_snapshot, dict):
            gov_available = _safe_bool(runtime_governance_snapshot.get("governance_available"))
            if not gov_available:
                return AlignmentDimensionSummary(dimension="runtime_policy", available=False)

            readiness = runtime_governance_snapshot.get("readiness_summary", {}) or {}
            intent_s = runtime_governance_snapshot.get("intent_summary", {}) or {}
            posture = _safe_str(runtime_governance_snapshot.get("posture"), "unknown")
            blocked = _safe_bool(runtime_governance_snapshot.get("blocked")) or _safe_bool(readiness.get("blocked"))
            degraded = _safe_bool(runtime_governance_snapshot.get("degraded")) or _safe_bool(readiness.get("degraded"))
            confirmation_required = _safe_bool(readiness.get("requires_confirmation"))
            runtime_domain = (
                _safe_str(runtime_governance_snapshot.get("runtime_domain")) or
                _safe_str(intent_s.get("runtime_domain")) or None
            )
            action_level = _safe_str(intent_s.get("action_level"), "observe") or "observe"
            return AlignmentDimensionSummary(
                dimension="runtime_policy",
                available=True,
                posture_signal=posture,
                blocked=blocked,
                degraded=degraded,
                confirmation_required=confirmation_required,
                runtime_domain=runtime_domain if runtime_domain else None,
                action_level=action_level,
                summary_fields={
                    "readiness_status": _safe_str(readiness.get("status")),
                    "intent_mode": _safe_str(intent_s.get("intent_mode")),
                },
            )

        # Handle pydantic-like object
        gov_available = _safe_bool(getattr(runtime_governance_snapshot, "governance_available", False))
        if not gov_available:
            return AlignmentDimensionSummary(dimension="runtime_policy", available=False)

        posture = _safe_str(getattr(runtime_governance_snapshot, "posture", "unknown"), "unknown")
        blocked = _safe_bool(getattr(runtime_governance_snapshot, "blocked", False))
        degraded = _safe_bool(getattr(runtime_governance_snapshot, "degraded", False))

        readiness_s = getattr(runtime_governance_snapshot, "readiness_summary", None)
        confirmation_required = False
        readiness_status = ""
        if readiness_s is not None:
            confirmation_required = _safe_bool(
                getattr(readiness_s, "requires_confirmation", None)
                or (readiness_s.get("requires_confirmation") if isinstance(readiness_s, dict) else None)
            )
            readiness_status = _safe_str(
                getattr(readiness_s, "status", None)
                or (readiness_s.get("status") if isinstance(readiness_s, dict) else None)
            )

        intent_s = getattr(runtime_governance_snapshot, "intent_summary", None)
        runtime_domain = None
        action_level = "observe"
        intent_mode = ""
        if intent_s is not None:
            runtime_domain = _safe_str(
                getattr(intent_s, "runtime_domain", None)
                or (intent_s.get("runtime_domain") if isinstance(intent_s, dict) else None)
            ) or None
            action_level = (
                _safe_str(
                    getattr(intent_s, "action_level", None)
                    or (intent_s.get("action_level") if isinstance(intent_s, dict) else None)
                ) or "observe"
            )
            intent_mode = _safe_str(
                getattr(intent_s, "intent_mode", None)
                or (intent_s.get("intent_mode") if isinstance(intent_s, dict) else None)
            )

        domain_attr = getattr(runtime_governance_snapshot, "runtime_domain", None)
        if domain_attr is not None:
            runtime_domain = _safe_str(domain_attr) or runtime_domain

        return AlignmentDimensionSummary(
            dimension="runtime_policy",
            available=True,
            posture_signal=posture,
            blocked=blocked,
            degraded=degraded,
            confirmation_required=confirmation_required,
            runtime_domain=runtime_domain,
            action_level=action_level,
            summary_fields={
                "readiness_status": readiness_status,
                "intent_mode": intent_mode,
            },
        )
    except Exception as exc:
        logger.warning("summarize_runtime_policy_alignment: unexpected error: %s", exc)
        return AlignmentDimensionSummary(dimension="runtime_policy")


def summarize_dispatch_policy_alignment(
    dispatch_summary: Optional[Any] = None,
    handoff_policy: Optional[Any] = None,
) -> AlignmentDimensionSummary:
    """Build the dispatch/handoff-policy dimension summary.

    Extracts posture signals from a DispatchSummary and HandoffPolicy.
    Always returns a valid :class:`AlignmentDimensionSummary`; never raises.

    Parameters
    ----------
    dispatch_summary:
        Optional :class:`~core.agent_governance.dispatch_summary.DispatchSummary`
        (PR-18) or compatible dict/object.
    handoff_policy:
        Optional :class:`~core.agent_governance.handoff_policy.HandoffPolicy`
        (PR-18) or compatible dict/object.
    """
    try:
        if dispatch_summary is None and handoff_policy is None:
            return AlignmentDimensionSummary(dimension="dispatch_policy")

        ack_required = False
        recovery_permitted = True
        max_handoff_depth = 5
        confirmation_required = False
        blocked = False
        dispatch_status = "unknown"
        cross_device_allowed: Optional[bool] = None

        # HandoffPolicy extraction
        if handoff_policy is not None:
            if isinstance(handoff_policy, dict):
                ack_required = _safe_bool(handoff_policy.get("ack_required"))
                recovery_permitted = _safe_bool(handoff_policy.get("recovery_permitted"), True)
                depth_val = handoff_policy.get("max_handoff_depth")
                max_handoff_depth = int(depth_val) if depth_val is not None else 5
                blocked = max_handoff_depth == 0
            else:
                ack_required = _safe_bool(getattr(handoff_policy, "ack_required", False))
                recovery_permitted = _safe_bool(
                    getattr(handoff_policy, "recovery_permitted", True), True
                )
                max_handoff_depth = int(getattr(handoff_policy, "max_handoff_depth", 5) or 5)
                blocked = max_handoff_depth == 0

        confirmation_required = ack_required

        # DispatchSummary extraction
        if dispatch_summary is not None:
            if isinstance(dispatch_summary, dict):
                dispatch_status = _safe_str(dispatch_summary.get("status", "unknown"), "unknown")
                if dispatch_status in ("failed", "blocked"):
                    blocked = True
            else:
                dispatch_status = _safe_str(
                    getattr(dispatch_summary, "status", "unknown"), "unknown"
                )
                if dispatch_status in ("failed", "blocked"):
                    blocked = True

        available = handoff_policy is not None or dispatch_summary is not None

        return AlignmentDimensionSummary(
            dimension="dispatch_policy",
            available=available,
            posture_signal="blocked" if blocked else "dispatch_ok",
            blocked=blocked,
            degraded=False,
            confirmation_required=confirmation_required,
            cross_device_allowed=cross_device_allowed,
            summary_fields={
                "ack_required": ack_required,
                "recovery_permitted": recovery_permitted,
                "max_handoff_depth": max_handoff_depth,
                "dispatch_status": dispatch_status,
            },
        )
    except Exception as exc:
        logger.warning("summarize_dispatch_policy_alignment: unexpected error: %s", exc)
        return AlignmentDimensionSummary(dimension="dispatch_policy")


def summarize_projection_policy_alignment(
    projection_governance: Optional[Any] = None,
) -> AlignmentDimensionSummary:
    """Build the projection-governance dimension summary.

    Extracts posture signals from a ProjectionGovernanceSummary (PR-26).
    Always returns a valid :class:`AlignmentDimensionSummary`; never raises.

    Parameters
    ----------
    projection_governance:
        Optional :class:`~core.projection.assembly_governance.ProjectionGovernanceSummary`
        (PR-26) or compatible dict/object.
    """
    try:
        if projection_governance is None:
            return AlignmentDimensionSummary(dimension="projection_policy")

        if isinstance(projection_governance, dict):
            gov_available = _safe_bool(projection_governance.get("governance_available"))
            if not gov_available:
                return AlignmentDimensionSummary(
                    dimension="projection_policy", available=False
                )

            policy_s = projection_governance.get("policy", {}) or {}
            exec_s = projection_governance.get("execution", {}) or {}
            tri_phase = (
                _safe_str(projection_governance.get("tri_state_phase")) or None
            )
            runtime_domain = (
                _safe_str(projection_governance.get("runtime_domain")) or None
            )
            blocked = _safe_bool(policy_s.get("blocked"))
            degraded = _safe_bool(policy_s.get("degraded"))
            confirmation_required = _safe_bool(policy_s.get("requires_confirmation"))
            action_level = _safe_str(exec_s.get("action_level"), "observe") or "observe"

            return AlignmentDimensionSummary(
                dimension="projection_policy",
                available=True,
                posture_signal="blocked" if blocked else ("degraded" if degraded else "projection_ok"),
                blocked=blocked,
                degraded=degraded,
                confirmation_required=confirmation_required,
                runtime_domain=runtime_domain,
                action_level=action_level,
                summary_fields={
                    "tri_state_phase": tri_phase,
                    "policy_status": _safe_str(policy_s.get("status")),
                },
            )

        # Pydantic-like object
        gov_available = _safe_bool(getattr(projection_governance, "governance_available", False))
        if not gov_available:
            return AlignmentDimensionSummary(dimension="projection_policy", available=False)

        policy_s = getattr(projection_governance, "policy", None)
        exec_s = getattr(projection_governance, "execution", None)

        def _get(obj: Any, key: str, default: Any = None) -> Any:
            if obj is None:
                return default
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        blocked = _safe_bool(_get(policy_s, "blocked"))
        degraded = _safe_bool(_get(policy_s, "degraded"))
        confirmation_required = _safe_bool(_get(policy_s, "requires_confirmation"))
        action_level = _safe_str(_get(exec_s, "action_level"), "observe") or "observe"
        tri_phase = _safe_str(getattr(projection_governance, "tri_state_phase", None)) or None
        runtime_domain = (
            _safe_str(getattr(projection_governance, "runtime_domain", None)) or None
        )

        return AlignmentDimensionSummary(
            dimension="projection_policy",
            available=True,
            posture_signal="blocked" if blocked else ("degraded" if degraded else "projection_ok"),
            blocked=blocked,
            degraded=degraded,
            confirmation_required=confirmation_required,
            runtime_domain=runtime_domain,
            action_level=action_level,
            summary_fields={
                "tri_state_phase": tri_phase,
                "policy_status": _safe_str(_get(policy_s, "status")),
            },
        )
    except Exception as exc:
        logger.warning("summarize_projection_policy_alignment: unexpected error: %s", exc)
        return AlignmentDimensionSummary(dimension="projection_policy")


def _summarize_readiness_dimension(readiness_result: Optional[Any]) -> AlignmentDimensionSummary:
    """Build the readiness-policy dimension summary from a ReadinessResult."""
    try:
        if readiness_result is None:
            return AlignmentDimensionSummary(dimension="readiness_policy")

        if isinstance(readiness_result, dict):
            ready = _safe_bool(readiness_result.get("ready"))
            status = _safe_str(readiness_result.get("status"), "blocked")
            reason = _safe_str(readiness_result.get("reason"))
            requires_confirmation = _safe_bool(readiness_result.get("requires_confirmation"))
            action_level = _safe_str(readiness_result.get("action_level"), "observe")
            blocked = not ready or status == "blocked"
            degraded = action_level == "observe" and not blocked
            cross_device_allowed = readiness_result.get("cross_device_allowed")
            return AlignmentDimensionSummary(
                dimension="readiness_policy",
                available=True,
                posture_signal=status,
                blocked=blocked,
                degraded=degraded,
                confirmation_required=requires_confirmation,
                cross_device_allowed=_safe_bool(cross_device_allowed) if cross_device_allowed is not None else None,
                action_level=action_level,
                summary_fields={"reason": reason, "ready": ready},
            )

        ready = _safe_bool(getattr(readiness_result, "ready", False))
        status = _safe_str(getattr(readiness_result, "status", "blocked"), "blocked")
        reason = _safe_str(getattr(readiness_result, "reason", ""))
        requires_confirmation = _safe_bool(
            getattr(readiness_result, "requires_confirmation", False)
        )
        action_level = _safe_str(getattr(readiness_result, "action_level", "observe"), "observe")
        blocked = not ready or status == "blocked"
        degraded = action_level == "observe" and not blocked
        cross_device_attr = getattr(readiness_result, "cross_device_allowed", None)

        return AlignmentDimensionSummary(
            dimension="readiness_policy",
            available=True,
            posture_signal=status,
            blocked=blocked,
            degraded=degraded,
            confirmation_required=requires_confirmation,
            cross_device_allowed=_safe_bool(cross_device_attr) if cross_device_attr is not None else None,
            action_level=action_level,
            summary_fields={"reason": reason, "ready": ready},
        )
    except Exception as exc:
        logger.warning("_summarize_readiness_dimension: unexpected error: %s", exc)
        return AlignmentDimensionSummary(dimension="readiness_policy")


def _summarize_fallback_dimension(fallback_trace: Optional[Any]) -> AlignmentDimensionSummary:
    """Build the fallback-policy dimension summary from a FallbackDecisionTrace."""
    try:
        if fallback_trace is None:
            return AlignmentDimensionSummary(dimension="fallback_policy")

        def _compact(obj: Any) -> Dict[str, Any]:
            if hasattr(obj, "compact_summary"):
                try:
                    return obj.compact_summary() or {}
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)
            if isinstance(obj, dict):
                return obj
            return {}

        compact = _compact(fallback_trace)
        final_status = _safe_str(
            compact.get("final_status") or getattr(fallback_trace, "final_status", "pending"),
            "pending",
        )
        outcome = _safe_str(
            compact.get("outcome") or getattr(fallback_trace, "outcome", "noop"),
            "noop",
        )
        blocked = final_status in ("failed", "blocked")
        degraded = outcome in ("degraded", "partial")

        return AlignmentDimensionSummary(
            dimension="fallback_policy",
            available=True,
            posture_signal=outcome,
            blocked=blocked,
            degraded=degraded,
            confirmation_required=False,
            summary_fields={"final_status": final_status, "outcome": outcome},
        )
    except Exception as exc:
        logger.warning("_summarize_fallback_dimension: unexpected error: %s", exc)
        return AlignmentDimensionSummary(dimension="fallback_policy")


# ---------------------------------------------------------------------------
# Top-level assembly entry point
# ---------------------------------------------------------------------------


def build_execution_policy_alignment_surface(
    *,
    runtime_governance_snapshot: Optional[Any] = None,
    projection_governance: Optional[Any] = None,
    intent_profile: Optional[Any] = None,
    readiness_result: Optional[Any] = None,
    fallback_trace: Optional[Any] = None,
    execution_trace_envelope: Optional[Any] = None,
    dispatch_summary: Optional[Any] = None,
    handoff_policy: Optional[Any] = None,
    tri_state_phase: Optional[str] = None,
    runtime_domain: Optional[str] = None,
    trace_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
    alignment_id: Optional[str] = None,
    timestamp: Optional[float] = None,
) -> ExecutionPolicyAlignmentSummary:
    """Assemble the canonical :class:`ExecutionPolicyAlignmentSummary`.

    This is the **single canonical entry point** for building the execution
    policy alignment surface.  Downstream code must not hand-roll policy
    mismatch dicts; all alignment logic should pass through here.

    Parameters
    ----------
    runtime_governance_snapshot:
        Optional :class:`~core.runtime_governance.snapshot.RuntimeGovernanceSnapshot`
        (PR-27) or compatible dict/object.
    projection_governance:
        Optional :class:`~core.projection.assembly_governance.ProjectionGovernanceSummary`
        (PR-26) or compatible dict/object.
    intent_profile:
        Optional :class:`~core.execution.intent_profile.ExecutionIntentProfile`
        (PR-22).
    readiness_result:
        Optional :class:`~core.execution.readiness_gate.ReadinessResult` (PR-23).
    fallback_trace:
        Optional :class:`~core.execution.fallback_trace.FallbackDecisionTrace`
        (PR-24).
    execution_trace_envelope:
        Optional :class:`~contracts.execution_trace.ExecutionTraceEnvelope` (PR-25).
    dispatch_summary:
        Optional :class:`~core.agent_governance.dispatch_summary.DispatchSummary`
        (PR-18).
    handoff_policy:
        Optional :class:`~core.agent_governance.handoff_policy.HandoffPolicy`
        (PR-18).
    tri_state_phase:
        Optional tri-state phase override.
    runtime_domain:
        Optional runtime domain override.
    trace_id:
        Optional trace ID override.
    runtime_session_id:
        Optional runtime session ID override.
    alignment_id:
        Optional explicit alignment ID (UUID4 generated when ``None``).
    timestamp:
        Optional explicit Unix epoch timestamp.

    Returns
    -------
    ExecutionPolicyAlignmentSummary
        Always returns a valid summary; never raises.  When all inputs are
        ``None`` the summary has ``aligned=False``, ``policy_posture="unknown"``,
        and all dimension summaries carry ``available=False``.
    """
    ts = timestamp if timestamp is not None else time.time()
    aid = alignment_id or str(uuid.uuid4())

    try:
        # 1. Build per-dimension summaries
        runtime_dim = summarize_runtime_policy_alignment(runtime_governance_snapshot)
        readiness_dim = _summarize_readiness_dimension(readiness_result)
        fallback_dim = _summarize_fallback_dimension(fallback_trace)
        dispatch_dim = summarize_dispatch_policy_alignment(dispatch_summary, handoff_policy)
        projection_dim = summarize_projection_policy_alignment(projection_governance)

        dimensions = [runtime_dim, readiness_dim, fallback_dim, dispatch_dim, projection_dim]

        # 2. Resolve trace_id / runtime_session_id from execution trace envelope
        resolved_trace_id = trace_id
        resolved_session_id = runtime_session_id
        if execution_trace_envelope is not None:
            try:
                if isinstance(execution_trace_envelope, dict):
                    resolved_trace_id = resolved_trace_id or _safe_str(
                        execution_trace_envelope.get("trace_id")
                    ) or None
                    resolved_session_id = resolved_session_id or _safe_str(
                        execution_trace_envelope.get("runtime_session_id")
                    ) or None
                else:
                    resolved_trace_id = resolved_trace_id or _safe_str(
                        getattr(execution_trace_envelope, "trace_id", None)
                    ) or None
                    resolved_session_id = resolved_session_id or _safe_str(
                        getattr(execution_trace_envelope, "runtime_session_id", None)
                    ) or None
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

        # 3. Resolve runtime_domain / tri_state_phase from available sources
        resolved_domain = runtime_domain
        resolved_phase = tri_state_phase

        for dim in [runtime_dim, projection_dim]:
            if resolved_domain is None and dim.runtime_domain:
                resolved_domain = dim.runtime_domain
        if resolved_phase is None:
            for dim in dimensions:
                phase_hint = dim.summary_fields.get("tri_state_phase")
                if phase_hint:
                    resolved_phase = phase_hint
                    break

        # 4. Detect mismatches
        mismatches = _detect_mismatches(dimensions)

        # 5. Derive posture
        posture = _derive_posture(dimensions, mismatches, resolved_phase, resolved_domain)

        # 6. Derive top-level flags
        available_dims = [d for d in dimensions if d.available]
        blocked = posture == POSTURE_BLOCKED or any(d.blocked for d in available_dims)
        degraded = posture == POSTURE_DEGRADED or any(d.degraded for d in available_dims)
        confirmation_required = any(d.confirmation_required for d in available_dims)
        aligned = (
            len(available_dims) >= 2
            and not mismatches
            and not blocked
            and not degraded
        )

        # 7. Build hints
        alignment_hints = _build_hints(dimensions, posture, mismatches, resolved_domain)

        return ExecutionPolicyAlignmentSummary(
            alignment_id=aid,
            trace_id=resolved_trace_id,
            runtime_session_id=resolved_session_id,
            runtime_domain=resolved_domain,
            tri_state_phase=resolved_phase,
            aligned=aligned,
            blocked=blocked,
            degraded=degraded,
            confirmation_required=confirmation_required,
            policy_posture=posture,
            runtime_policy_summary=runtime_dim,
            readiness_policy_summary=readiness_dim,
            fallback_policy_summary=fallback_dim,
            dispatch_policy_summary=dispatch_dim,
            projection_policy_summary=projection_dim,
            mismatches=mismatches,
            alignment_hints=alignment_hints,
            timestamp=ts,
        )

    except Exception as exc:
        logger.warning(
            "build_execution_policy_alignment_surface: assembly failed, "
            "returning minimal summary: %s",
            exc,
        )
        return ExecutionPolicyAlignmentSummary(
            alignment_id=aid,
            aligned=False,
            blocked=False,
            degraded=True,
            confirmation_required=False,
            policy_posture=POSTURE_UNKNOWN,
            mismatches=[],
            timestamp=ts,
        )
