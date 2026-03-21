"""
core/projection/assembly_governance.py
========================================
Projection Assembly Governance — PR-26.

This module introduces a **canonical governance-aware assembly layer** that
determines which runtime-governance and execution-governance signals are
selected, normalised, and assembled into projection-ready output.

It answers:
- Which execution-governance signals should be promoted into the outward projection?
- Which fields are safe and useful for read-only status surfaces?
- How should readiness, fallback, and execution-trace information be summarised?
- How can projection stay stable even when some internal governance objects are missing?

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **No breaking API changes** — fully backward-compatible with all existing
  :class:`~core.projection.runtime_projection.RuntimeProjection` consumers.
- **Fully serialisable** — all summary objects provide ``to_dict()`` and
  ``to_json()`` for stable, round-trippable JSON output.
- **Graceful degradation** — every helper returns a minimal safe summary when
  inputs are ``None`` or malformed; they never raise to callers.
- **No UI semantics** — contracts carry no widget, view, or rendering references.
- **Stable field names** — field names are fixed and will not be renamed without
  a new major contract version.

Public surface
--------------
Contracts:
    - :class:`ProjectionExecutionSummary`
    - :class:`ProjectionPolicySummary`
    - :class:`ProjectionTraceSummary`
    - :class:`ProjectionGovernanceSummary`

Assembly helpers:
    - :func:`summarize_intent_for_projection`
    - :func:`summarize_readiness_for_projection`
    - :func:`summarize_fallback_for_projection`
    - :func:`summarize_execution_trace_for_projection`
    - :func:`assemble_projection_governance`

Usage::

    from core.projection.assembly_governance import assemble_projection_governance

    governance = assemble_projection_governance(
        intent_profile=profile,
        readiness_result=readiness,
        fallback_trace=trace,
        execution_trace_envelope=envelope,
        state_continuum=continuum_dict,
    )
    payload = governance.to_dict()

See ``docs/PROJECTION_ASSEMBLY_GOVERNANCE.md`` for the full specification.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("Galaxy.Projection.AssemblyGovernance")


# ---------------------------------------------------------------------------
# ProjectionExecutionSummary
# ---------------------------------------------------------------------------


class ProjectionExecutionSummary(BaseModel):
    """Compact, projection-safe summary of execution intent.

    Derived from an :class:`~core.execution.intent_profile.ExecutionIntentProfile`
    (PR-22).  Raw internal intent objects are never surfaced here; only
    normalised, safe fields are included.

    Fields
    ------
    intent_id
        Unique ID of the originating intent profile.  ``None`` when unavailable.
    source
        Origin of the intent (``"chat"`` / ``"openclawd"`` / ``"runtime"`` /
        etc.).  Defaults to ``"unknown"``.
    action_level
        Graduated action level (``"observe"`` / ``"hint"`` / ``"assist"`` /
        ``"execute"``).  Defaults to ``"observe"``.
    intent_mode
        Normalised mode derived from action_level
        (``"advisory"`` / ``"assistive"`` / ``"direct"`` / ``"autonomous"``).
        Defaults to ``"advisory"``.
    target_type
        Category of the execution target (e.g. ``"app"``, ``"window"``).
        ``None`` when unresolved.
    target_ref
        Specific target reference.  ``None`` when unresolved.
    device_scope
        Scope of target devices (``"local"`` / ``"remote"`` / ``"multi-device"``).
        ``None`` when unresolved.
    runtime_domain
        Runtime domain at intent construction time.  ``None`` when unresolved.
    confidence
        Confidence score [0.0, 1.0].  ``None`` when unavailable.
    degrade_reason
        Non-``None`` when the intent was downgraded (e.g. ``"policy_blocked"``).
    available
        ``True`` when a real intent was summarised; ``False`` for empty default.
    """

    intent_id: Optional[str] = Field(default=None, description="Unique intent ID.")
    source: str = Field(default="unknown", description="Origin of the intent.")
    action_level: str = Field(default="observe", description="Graduated action level.")
    intent_mode: str = Field(default="advisory", description="Normalised intent mode.")
    target_type: Optional[str] = Field(default=None, description="Execution target category.")
    target_ref: Optional[str] = Field(default=None, description="Specific target reference.")
    device_scope: Optional[str] = Field(default=None, description="Target device scope.")
    runtime_domain: Optional[str] = Field(default=None, description="Runtime domain.")
    confidence: Optional[float] = Field(default=None, description="Confidence score [0, 1].")
    degrade_reason: Optional[str] = Field(default=None, description="Reason for intent downgrade.")
    available: bool = Field(
        default=False, description="True when a real intent profile was summarised."
    )

    model_config = {"from_attributes": True}

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string."""
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# ProjectionPolicySummary
# ---------------------------------------------------------------------------


class ProjectionPolicySummary(BaseModel):
    """Compact, projection-safe readiness and policy posture summary.

    Derived from a :class:`~core.execution.readiness_gate.ReadinessResult`
    (PR-23) combined with continuum/domain signals.

    Fields
    ------
    ready
        ``True`` when execution is permitted.
    status
        Top-level readiness status (``"ready"`` / ``"confirm_required"`` /
        ``"blocked"`` / ``"observe_only"``).  Defaults to ``"blocked"``.
    reason
        Human-readable explanation.  Empty string when unavailable.
    requires_confirmation
        ``True`` when execution requires explicit human confirmation.
    action_level
        Graduated action level from the readiness evaluation.
        Defaults to ``"observe"``.
    policy_band
        Policy band from the execution-policy resolver.  ``None`` when
        the resolver was not consulted.
    blocked_by
        Primary block-cause code (``"none"`` when not blocked).
    runtime_domain
        Runtime domain at evaluation time.  ``None`` when unavailable.
    blocked
        Convenience flag — ``True`` when ``status`` is ``"blocked"``.
    degraded
        ``True`` when the posture represents a degraded/reduced mode.
    available
        ``True`` when a real readiness result was summarised.
    """

    ready: bool = Field(default=False, description="True when execution is permitted.")
    status: str = Field(default="blocked", description="Top-level readiness status.")
    reason: str = Field(default="", description="Human-readable reason.")
    requires_confirmation: bool = Field(
        default=False, description="True when confirmation is required."
    )
    action_level: str = Field(default="observe", description="Action level at evaluation time.")
    policy_band: Optional[str] = Field(default=None, description="Policy band string.")
    blocked_by: str = Field(default="none", description="Primary block-cause code.")
    runtime_domain: Optional[str] = Field(default=None, description="Runtime domain.")
    blocked: bool = Field(default=True, description="True when status is blocked.")
    degraded: bool = Field(default=False, description="True when posture is degraded/reduced.")
    available: bool = Field(
        default=False, description="True when a real readiness result was summarised."
    )

    model_config = {"from_attributes": True}

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string."""
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# ProjectionTraceSummary (fallback)
# ---------------------------------------------------------------------------


class ProjectionTraceSummary(BaseModel):
    """Compact, projection-safe fallback decision trace summary.

    Derived from a :class:`~core.execution.fallback_trace.FallbackDecisionTrace`
    (PR-24).

    Fields
    ------
    outcome
        Final outcome of the fallback decision
        (``"selected"`` / ``"blocked"`` / ``"noop"`` / ``"degraded"`` /
        ``"failed"``).  Defaults to ``"noop"``.
    decision_source
        Which component made the fallback decision.  Defaults to ``"unknown"``.
    fallback_path
        Description of the fallback path selected.  ``None`` when none was chosen.
    reason
        Human-readable explanation of the fallback selection.  ``None`` when
        unavailable.
    primary_path
        The execution path that was originally attempted.  ``None`` when
        unavailable.
    primary_block_reason
        Why the primary path was not taken.  ``None`` when not applicable.
    action_level
        Action level at fallback decision time.  Defaults to ``"observe"``.
    available
        ``True`` when a real fallback trace was summarised.
    """

    outcome: str = Field(default="noop", description="Final fallback outcome.")
    decision_source: str = Field(default="unknown", description="Decision-making component.")
    fallback_path: Optional[str] = Field(default=None, description="Selected fallback path.")
    reason: Optional[str] = Field(default=None, description="Fallback selection reason.")
    primary_path: Optional[str] = Field(default=None, description="Originally attempted path.")
    primary_block_reason: Optional[str] = Field(
        default=None, description="Why the primary path was not taken."
    )
    action_level: str = Field(default="observe", description="Action level at decision time.")
    available: bool = Field(
        default=False, description="True when a real fallback trace was summarised."
    )

    model_config = {"from_attributes": True}

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string."""
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# ProjectionExecutionTraceSummary (execution trace envelope)
# ---------------------------------------------------------------------------


class ProjectionExecutionTraceSummary(BaseModel):
    """Compact, projection-safe execution trace envelope summary.

    Derived from an
    :class:`~contracts.execution_trace.ExecutionTraceEnvelope` (PR-25).

    Fields
    ------
    trace_id
        Shared trace ID for the execution lifecycle.  ``None`` when unavailable.
    intent_id
        Originating intent ID.  ``None`` when unavailable.
    final_status
        Aggregate final status across all trace events.  Defaults to ``"pending"``.
    stage_count
        Number of lifecycle stages recorded.  Defaults to 0.
    stages
        Ordered list of stage name strings.
    available
        ``True`` when a real envelope was summarised.
    """

    trace_id: Optional[str] = Field(default=None, description="Shared trace ID.")
    intent_id: Optional[str] = Field(default=None, description="Originating intent ID.")
    final_status: str = Field(
        default="pending", description="Aggregate final status across all events."
    )
    stage_count: int = Field(default=0, description="Number of lifecycle stages recorded.")
    stages: List[str] = Field(
        default_factory=list, description="Ordered list of stage names."
    )
    available: bool = Field(
        default=False, description="True when a real execution trace envelope was summarised."
    )

    model_config = {"from_attributes": True}

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string."""
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# ProjectionGovernanceSummary — top-level aggregate
# ---------------------------------------------------------------------------


class ProjectionGovernanceSummary(BaseModel):
    """Unified governance-enriched projection summary.

    Aggregates all governance-relevant signals into a single, read-only,
    serialisable object suitable for inclusion in the projection payload.

    This is the canonical answer to "what governance state is the system in,
    from the projection's perspective?" — combining execution intent, policy
    posture, fallback trace, and execution trace data in one stable contract.

    Fields
    ------
    execution
        Compact summary of the current execution intent (PR-22).
    policy
        Compact summary of the readiness/policy posture (PR-23).
    fallback
        Compact summary of the last fallback decision (PR-24).
    execution_trace
        Compact summary of the execution lifecycle trace (PR-25).
    tri_state_phase
        The public tri-state phase at assembly time (``"silent"`` /
        ``"liminal"`` / ``"manifest"``).  ``None`` when unavailable.
    runtime_domain
        Runtime domain at assembly time.  ``None`` when unavailable.
    assembled_at
        Unix epoch timestamp when this summary was assembled.
    governance_available
        ``True`` when at least one real governance input was present.
    """

    execution: ProjectionExecutionSummary = Field(
        default_factory=ProjectionExecutionSummary,
        description="Compact execution intent summary (PR-22).",
    )
    policy: ProjectionPolicySummary = Field(
        default_factory=ProjectionPolicySummary,
        description="Compact readiness/policy posture summary (PR-23).",
    )
    fallback: ProjectionTraceSummary = Field(
        default_factory=ProjectionTraceSummary,
        description="Compact fallback decision trace summary (PR-24).",
    )
    execution_trace: ProjectionExecutionTraceSummary = Field(
        default_factory=ProjectionExecutionTraceSummary,
        description="Compact execution lifecycle trace summary (PR-25).",
    )
    tri_state_phase: Optional[str] = Field(
        default=None,
        description="Public tri-state phase at assembly time.",
    )
    runtime_domain: Optional[str] = Field(
        default=None,
        description="Runtime domain at assembly time.",
    )
    assembled_at: float = Field(
        default_factory=time.time,
        description="Unix epoch timestamp when this summary was assembled.",
    )
    governance_available: bool = Field(
        default=False,
        description="True when at least one real governance input was present.",
    )

    model_config = {"from_attributes": True}

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "execution": self.execution.to_dict(),
            "policy": self.policy.to_dict(),
            "fallback": self.fallback.to_dict(),
            "execution_trace": self.execution_trace.to_dict(),
            "tri_state_phase": self.tri_state_phase,
            "runtime_domain": self.runtime_domain,
            "assembled_at": self.assembled_at,
            "governance_available": self.governance_available,
        }

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string."""
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# Assembly helpers — summarize_* adapters
# ---------------------------------------------------------------------------


def summarize_intent_for_projection(
    intent_profile: Optional[Any],
) -> ProjectionExecutionSummary:
    """Build a :class:`ProjectionExecutionSummary` from an intent profile.

    Parameters
    ----------
    intent_profile:
        An :class:`~core.execution.intent_profile.ExecutionIntentProfile`
        (PR-22) or any object with compatible attributes.  ``None`` and
        malformed objects are handled gracefully.

    Returns
    -------
    ProjectionExecutionSummary
        Always returns a valid summary; never raises.
    """
    if intent_profile is None:
        return ProjectionExecutionSummary(available=False)

    try:
        # Prefer compact_summary() if available
        if hasattr(intent_profile, "compact_summary"):
            summary = intent_profile.compact_summary()
            return ProjectionExecutionSummary(
                intent_id=summary.get("intent_id"),
                source=summary.get("source", "unknown"),
                action_level=summary.get("action_level", "observe"),
                intent_mode=summary.get("intent_mode", "advisory"),
                target_type=summary.get("target_type"),
                target_ref=summary.get("target_ref"),
                device_scope=summary.get("device_scope"),
                runtime_domain=summary.get("runtime_domain"),
                confidence=summary.get("confidence"),
                degrade_reason=summary.get("degrade_reason"),
                available=True,
            )

        # Fallback: read attributes directly
        return ProjectionExecutionSummary(
            intent_id=getattr(intent_profile, "intent_id", None),
            source=getattr(intent_profile, "source", "unknown"),
            action_level=getattr(intent_profile, "action_level", "observe"),
            intent_mode=getattr(intent_profile, "intent_mode", "advisory"),
            target_type=getattr(intent_profile, "target_type", None),
            target_ref=getattr(intent_profile, "target_ref", None),
            device_scope=getattr(intent_profile, "device_scope", None),
            runtime_domain=getattr(intent_profile, "runtime_domain", None),
            confidence=getattr(intent_profile, "confidence", None),
            degrade_reason=getattr(intent_profile, "degrade_reason", None),
            available=True,
        )
    except Exception as exc:
        logger.warning(
            "summarize_intent_for_projection: failed to summarise intent_profile "
            "(type=%s): %s",
            type(intent_profile).__name__,
            exc,
        )
        return ProjectionExecutionSummary(available=False)


def summarize_readiness_for_projection(
    readiness_result: Optional[Any],
) -> ProjectionPolicySummary:
    """Build a :class:`ProjectionPolicySummary` from a readiness result.

    Parameters
    ----------
    readiness_result:
        A :class:`~core.execution.readiness_gate.ReadinessResult` (PR-23)
        or any object with compatible attributes.  ``None`` and malformed
        objects are handled gracefully; the default summary represents a
        conservatively blocked posture.

    Returns
    -------
    ProjectionPolicySummary
        Always returns a valid summary; never raises.
    """
    if readiness_result is None:
        return ProjectionPolicySummary(available=False)

    try:
        ready = bool(getattr(readiness_result, "ready", False))
        status = str(getattr(readiness_result, "status", "blocked"))
        reason = str(getattr(readiness_result, "reason", ""))
        requires_confirmation = bool(
            getattr(readiness_result, "requires_confirmation", False)
        )
        action_level = str(getattr(readiness_result, "action_level", "observe"))
        policy_band = getattr(readiness_result, "policy_band", None)
        blocked_by = str(getattr(readiness_result, "blocked_by", "none"))
        runtime_domain = getattr(readiness_result, "runtime_domain", None)

        blocked = status == "blocked"
        degraded = status in ("observe_only",) or action_level in ("observe", "hint")

        return ProjectionPolicySummary(
            ready=ready,
            status=status,
            reason=reason,
            requires_confirmation=requires_confirmation,
            action_level=action_level,
            policy_band=policy_band,
            blocked_by=blocked_by,
            runtime_domain=str(runtime_domain) if runtime_domain else None,
            blocked=blocked,
            degraded=degraded,
            available=True,
        )
    except Exception as exc:
        logger.warning(
            "summarize_readiness_for_projection: failed to summarise readiness_result "
            "(type=%s): %s",
            type(readiness_result).__name__,
            exc,
        )
        return ProjectionPolicySummary(available=False)


def summarize_fallback_for_projection(
    fallback_trace: Optional[Any],
) -> ProjectionTraceSummary:
    """Build a :class:`ProjectionTraceSummary` from a fallback decision trace.

    Parameters
    ----------
    fallback_trace:
        A :class:`~core.execution.fallback_trace.FallbackDecisionTrace` (PR-24)
        or any object with compatible attributes.  ``None`` and malformed
        objects are handled gracefully; the default summary represents a
        no-op posture.

    Returns
    -------
    ProjectionTraceSummary
        Always returns a valid summary; never raises.
    """
    if fallback_trace is None:
        return ProjectionTraceSummary(available=False)

    try:
        # Prefer compact_summary() if available
        if hasattr(fallback_trace, "compact_summary"):
            cs = fallback_trace.compact_summary()
            return ProjectionTraceSummary(
                outcome=cs.get("outcome", "noop"),
                decision_source=cs.get("decision_source", "unknown"),
                fallback_path=cs.get("fallback_path"),
                reason=cs.get("fallback_reason") or cs.get("reason"),
                primary_path=cs.get("primary_path"),
                primary_block_reason=cs.get("primary_block_reason"),
                action_level=cs.get("action_level", "observe"),
                available=True,
            )

        return ProjectionTraceSummary(
            outcome=str(getattr(fallback_trace, "outcome", "noop")),
            decision_source=str(getattr(fallback_trace, "decision_source", "unknown")),
            fallback_path=getattr(fallback_trace, "fallback_path", None),
            reason=getattr(fallback_trace, "fallback_reason", None)
            or getattr(fallback_trace, "reason", None),
            primary_path=getattr(fallback_trace, "primary_path", None),
            primary_block_reason=getattr(fallback_trace, "primary_block_reason", None),
            action_level=str(getattr(fallback_trace, "action_level", "observe")),
            available=True,
        )
    except Exception as exc:
        logger.warning(
            "summarize_fallback_for_projection: failed to summarise fallback_trace "
            "(type=%s): %s",
            type(fallback_trace).__name__,
            exc,
        )
        return ProjectionTraceSummary(available=False)


def summarize_execution_trace_for_projection(
    execution_trace_envelope: Optional[Any],
) -> ProjectionExecutionTraceSummary:
    """Build a :class:`ProjectionExecutionTraceSummary` from an execution trace envelope.

    Parameters
    ----------
    execution_trace_envelope:
        An :class:`~contracts.execution_trace.ExecutionTraceEnvelope` (PR-25)
        or any object with compatible attributes.  ``None`` and malformed
        objects are handled gracefully; the default summary has zero stages
        and a ``"pending"`` final_status.

    Returns
    -------
    ProjectionExecutionTraceSummary
        Always returns a valid summary; never raises.
    """
    if execution_trace_envelope is None:
        return ProjectionExecutionTraceSummary(available=False)

    try:
        # Prefer compact_summary() if available
        if hasattr(execution_trace_envelope, "compact_summary"):
            cs = execution_trace_envelope.compact_summary()
            return ProjectionExecutionTraceSummary(
                trace_id=cs.get("trace_id"),
                intent_id=cs.get("intent_id"),
                final_status=cs.get("final_status", "pending"),
                stage_count=int(cs.get("stage_count", 0)),
                stages=list(cs.get("stages", [])),
                available=True,
            )

        return ProjectionExecutionTraceSummary(
            trace_id=getattr(execution_trace_envelope, "trace_id", None),
            intent_id=getattr(execution_trace_envelope, "intent_id", None),
            final_status=str(
                getattr(execution_trace_envelope, "final_status", "pending")
            ),
            stage_count=len(getattr(execution_trace_envelope, "events", [])),
            stages=[
                getattr(e, "stage", str(e))
                for e in getattr(execution_trace_envelope, "events", [])
            ],
            available=True,
        )
    except Exception as exc:
        logger.warning(
            "summarize_execution_trace_for_projection: failed to summarise envelope "
            "(type=%s): %s",
            type(execution_trace_envelope).__name__,
            exc,
        )
        return ProjectionExecutionTraceSummary(available=False)


def assemble_projection_governance(
    intent_profile: Optional[Any] = None,
    readiness_result: Optional[Any] = None,
    fallback_trace: Optional[Any] = None,
    execution_trace_envelope: Optional[Any] = None,
    state_continuum: Optional[Any] = None,
    *,
    timestamp: Optional[float] = None,
) -> ProjectionGovernanceSummary:
    """Assemble a unified :class:`ProjectionGovernanceSummary` from all governance inputs.

    This is the **single narrow entry-point** for building governance-aware
    projection data.  Downstream projection code should not hand-roll summary
    dicts; all governance data entering projection should pass through here.

    Parameters
    ----------
    intent_profile:
        Optional :class:`~core.execution.intent_profile.ExecutionIntentProfile`
        (PR-22).
    readiness_result:
        Optional :class:`~core.execution.readiness_gate.ReadinessResult` (PR-23).
    fallback_trace:
        Optional :class:`~core.execution.fallback_trace.FallbackDecisionTrace`
        (PR-24).
    execution_trace_envelope:
        Optional :class:`~contracts.execution_trace.ExecutionTraceEnvelope`
        (PR-25).
    state_continuum:
        Optional live continuum state — either a
        :class:`~core.continuum.types.ContinuumState` object or a dict with
        ``"tri_state_phase"`` / ``"runtime_domain"`` keys.  Used to populate
        the top-level phase/domain fields of the governance summary.
    timestamp:
        Optional explicit Unix epoch timestamp.  Defaults to :func:`time.time`.

    Returns
    -------
    ProjectionGovernanceSummary
        Always returns a valid summary; never raises.  When all inputs are
        ``None`` the summary has ``governance_available=False`` and all
        sub-summaries carry ``available=False``.
    """
    ts = timestamp if timestamp is not None else time.time()

    try:
        execution_summary = summarize_intent_for_projection(intent_profile)
        policy_summary = summarize_readiness_for_projection(readiness_result)
        fallback_summary = summarize_fallback_for_projection(fallback_trace)
        trace_summary = summarize_execution_trace_for_projection(execution_trace_envelope)

        # Extract phase/domain from continuum state
        tri_state_phase: Optional[str] = None
        runtime_domain: Optional[str] = None
        if state_continuum is not None:
            try:
                if isinstance(state_continuum, dict):
                    tri_state_phase = state_continuum.get("tri_state_phase")
                    runtime_domain = state_continuum.get("runtime_domain")
                else:
                    phase = getattr(state_continuum, "tri_state_phase", None)
                    domain = getattr(state_continuum, "runtime_domain", None)
                    if phase is not None:
                        tri_state_phase = (
                            phase.value if hasattr(phase, "value") else str(phase)
                        )
                    if domain is not None:
                        runtime_domain = (
                            domain.value if hasattr(domain, "value") else str(domain)
                        )
            except Exception as _exc:
                logger.warning(
                    "assemble_projection_governance: failed to extract phase/domain "
                    "from state_continuum (type=%s): %s",
                    type(state_continuum).__name__,
                    _exc,
                )

        governance_available = any(
            [
                execution_summary.available,
                policy_summary.available,
                fallback_summary.available,
                trace_summary.available,
            ]
        )

        return ProjectionGovernanceSummary(
            execution=execution_summary,
            policy=policy_summary,
            fallback=fallback_summary,
            execution_trace=trace_summary,
            tri_state_phase=tri_state_phase,
            runtime_domain=runtime_domain,
            assembled_at=ts,
            governance_available=governance_available,
        )
    except Exception as exc:
        logger.warning(
            "assemble_projection_governance: assembly failed, returning empty summary: %s",
            exc,
        )
        return ProjectionGovernanceSummary(assembled_at=ts, governance_available=False)
