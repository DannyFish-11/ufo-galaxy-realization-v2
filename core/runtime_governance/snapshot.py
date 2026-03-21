"""
core/runtime_governance/snapshot.py
=====================================
Runtime Governance Snapshot — PR-27.

This module introduces the canonical **Runtime Governance Snapshot**: a
unified, serialisable object that assembles the current runtime posture into
one stable, narrow contract.

It answers, in one object:
- What tri-state phase is the system currently in?
- What runtime domain is active or intended?
- What is the current governance posture across intent / readiness / fallback /
  execution?
- What execution lifecycle summary is currently available?
- What projection-governance summary is currently available?
- Can downstream runtime, projection, status surfaces, and future
  mesh/session work consume one narrow snapshot instead of hand-rolling
  multiple summaries?

This module is the canonical runtime-side counterpart to PR-26's outward
projection governance layer:

- PR-25 standardised execution lifecycle trace.
- PR-26 standardised projection-safe governance assembly.
- PR-27 (this module) standardises the runtime-side governance posture as
  one unified snapshot.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **No breaking API changes** — fully backward-compatible with all existing
  consumers of :class:`~core.projection.runtime_projection.RuntimeProjection`,
  :class:`~core.projection.assembly_governance.ProjectionGovernanceSummary`,
  and :class:`~contracts.execution_trace.ExecutionTraceEnvelope`.
- **Fully serialisable** — all contracts provide ``to_dict()`` and ``to_json()``
  for stable, round-trippable JSON output.
- **Graceful degradation** — every helper and the top-level assembler return
  minimal safe summaries when inputs are ``None`` or malformed; they never
  raise to callers.
- **No UI semantics** — contracts carry no widget, view, or rendering
  references.
- **Stable field names** — field names are fixed and will not be renamed
  without a new major contract version.
- **Suitable for internal and outward use** — the snapshot is appropriate
  for both internal runtime consumption and read-only outward surfaces.

Public surface
--------------
Contracts:
    - :class:`RuntimeGovernanceExecutionSummary`
    - :class:`RuntimeGovernancePolicySummary`
    - :class:`RuntimeGovernanceTraceSummary`
    - :class:`RuntimeGovernanceProjectionSummary`
    - :class:`RuntimeGovernanceSnapshot`

Assembly helpers:
    - :func:`summarize_runtime_intent`
    - :func:`summarize_runtime_readiness`
    - :func:`summarize_runtime_fallback`
    - :func:`summarize_runtime_execution_trace`
    - :func:`summarize_projection_governance_for_runtime`
    - :func:`assemble_runtime_governance_snapshot`

Usage::

    from core.runtime_governance.snapshot import assemble_runtime_governance_snapshot

    snapshot = assemble_runtime_governance_snapshot(
        intent_profile=profile,
        readiness_result=readiness,
        fallback_trace=trace,
        execution_trace_envelope=envelope,
        projection_governance=gov_summary,
        tri_state_phase="manifest",
        runtime_domain="local",
        trace_id="trace-abc",
        runtime_session_id="sess-xyz",
    )
    payload = snapshot.to_dict()

See ``docs/RUNTIME_GOVERNANCE_SNAPSHOT.md`` for the full specification.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("Galaxy.RuntimeGovernance.Snapshot")


# ---------------------------------------------------------------------------
# RuntimeGovernanceExecutionSummary
# ---------------------------------------------------------------------------


class RuntimeGovernanceExecutionSummary(BaseModel):
    """Compact runtime-side summary of execution intent.

    Derived from an
    :class:`~core.execution.intent_profile.ExecutionIntentProfile` (PR-22).
    This mirrors the projection-layer
    :class:`~core.projection.assembly_governance.ProjectionExecutionSummary`
    but is positioned as the canonical runtime-side view — it may carry
    additional runtime-internal fields in future without touching the
    outward projection surface.

    Fields
    ------
    intent_id
        Unique ID of the originating intent profile.  ``None`` when
        unavailable.
    source
        Origin of the intent (e.g. ``"chat"``, ``"openclawd"``,
        ``"runtime"``).  Defaults to ``"unknown"``.
    action_level
        Graduated action level
        (``"observe"`` / ``"hint"`` / ``"assist"`` / ``"execute"``).
        Defaults to ``"observe"``.
    intent_mode
        Normalised mode derived from action_level
        (``"advisory"`` / ``"assistive"`` / ``"direct"`` / ``"autonomous"``).
        Defaults to ``"advisory"``.
    target_type
        Category of the execution target.  ``None`` when unresolved.
    target_ref
        Specific target reference.  ``None`` when unresolved.
    device_scope
        Scope of target devices
        (``"local"`` / ``"remote"`` / ``"multi-device"``).
        ``None`` when unresolved.
    runtime_domain
        Runtime domain at intent construction time.  ``None`` when
        unresolved.
    confidence
        Confidence score [0.0, 1.0].  ``None`` when unavailable.
    degrade_reason
        Non-``None`` when the intent was downgraded.
    available
        ``True`` when a real intent was summarised; ``False`` for the empty
        default.
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
    degrade_reason: Optional[str] = Field(
        default=None, description="Reason for intent downgrade."
    )
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
# RuntimeGovernancePolicySummary
# ---------------------------------------------------------------------------


class RuntimeGovernancePolicySummary(BaseModel):
    """Compact runtime-side readiness and policy posture summary.

    Derived from a
    :class:`~core.execution.readiness_gate.ReadinessResult` (PR-23).

    Fields
    ------
    ready
        ``True`` when execution is permitted.
    status
        Top-level readiness status
        (``"ready"`` / ``"confirm_required"`` / ``"blocked"`` /
        ``"observe_only"``).  Defaults to ``"blocked"``.
    reason
        Human-readable explanation.  Empty string when unavailable.
    requires_confirmation
        ``True`` when execution requires explicit human confirmation.
    action_level
        Graduated action level from the readiness evaluation.
        Defaults to ``"observe"``.
    policy_band
        Policy band from the execution-policy resolver.  ``None`` when the
        resolver was not consulted.
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
# RuntimeGovernanceTraceSummary
# ---------------------------------------------------------------------------


class RuntimeGovernanceTraceSummary(BaseModel):
    """Compact runtime-side execution trace summary.

    Derived from an
    :class:`~contracts.execution_trace.ExecutionTraceEnvelope` (PR-25)
    or a compatible compact summary dict.

    Fields
    ------
    trace_id
        Shared trace ID for the execution lifecycle.  ``None`` when
        unavailable.
    intent_id
        Originating intent ID.  ``None`` when unavailable.
    runtime_session_id
        Active runtime session ID.  ``None`` when unavailable.
    final_status
        Aggregate final status across all trace events.  Defaults to
        ``"pending"``.
    stage_count
        Number of lifecycle stages recorded.  Defaults to 0.
    stages
        Ordered list of stage name strings.
    fallback_outcome
        Fallback decision outcome (``"selected"`` / ``"blocked"`` /
        ``"noop"`` / ``"degraded"`` / ``"failed"``).  ``None`` when no
        fallback trace is available.
    available
        ``True`` when a real envelope was summarised.
    """

    trace_id: Optional[str] = Field(default=None, description="Shared trace ID.")
    intent_id: Optional[str] = Field(default=None, description="Originating intent ID.")
    runtime_session_id: Optional[str] = Field(
        default=None, description="Active runtime session ID."
    )
    final_status: str = Field(
        default="pending", description="Aggregate final status across all events."
    )
    stage_count: int = Field(default=0, description="Number of lifecycle stages recorded.")
    stages: List[str] = Field(
        default_factory=list, description="Ordered list of stage names."
    )
    fallback_outcome: Optional[str] = Field(
        default=None, description="Fallback decision outcome."
    )
    available: bool = Field(
        default=False,
        description="True when a real execution trace envelope was summarised.",
    )

    model_config = {"from_attributes": True}

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string."""
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# RuntimeGovernanceProjectionSummary
# ---------------------------------------------------------------------------


class RuntimeGovernanceProjectionSummary(BaseModel):
    """Compact runtime-side summary of the projection governance layer.

    Derived from a
    :class:`~core.projection.assembly_governance.ProjectionGovernanceSummary`
    (PR-26).  This carries only the narrow set of fields that are
    meaningful to the runtime governance layer.

    Fields
    ------
    governance_available
        ``True`` when the projection governance layer reported at least one
        available governance input.
    action_level
        Action level extracted from the projection execution summary.
        Defaults to ``"observe"``.
    intent_mode
        Intent mode extracted from the projection execution summary.
        Defaults to ``"advisory"``.
    policy_status
        Policy status extracted from the projection policy summary.
        Defaults to ``"blocked"``.
    ready
        Whether execution is permitted according to the projection policy.
    blocked
        Convenience flag — ``True`` when the projection policy is blocked.
    degraded
        Convenience flag — ``True`` when the projection posture is degraded.
    fallback_outcome
        Fallback outcome from the projection fallback summary.
        Defaults to ``"noop"``.
    trace_final_status
        Final status from the projection execution trace summary.
        Defaults to ``"pending"``.
    tri_state_phase
        Tri-state phase captured in the projection governance summary.
        ``None`` when unavailable.
    runtime_domain
        Runtime domain captured in the projection governance summary.
        ``None`` when unavailable.
    assembled_at
        Unix epoch timestamp when the upstream governance summary was
        assembled.  ``None`` when unavailable.
    available
        ``True`` when a real projection governance summary was provided.
    """

    governance_available: bool = Field(
        default=False,
        description="True when the projection governance layer reported at least one input.",
    )
    action_level: str = Field(default="observe", description="Action level.")
    intent_mode: str = Field(default="advisory", description="Intent mode.")
    policy_status: str = Field(default="blocked", description="Policy status.")
    ready: bool = Field(default=False, description="True when execution is permitted.")
    blocked: bool = Field(default=True, description="True when policy is blocked.")
    degraded: bool = Field(default=False, description="True when posture is degraded.")
    fallback_outcome: str = Field(default="noop", description="Fallback decision outcome.")
    trace_final_status: str = Field(
        default="pending", description="Final trace status."
    )
    tri_state_phase: Optional[str] = Field(
        default=None, description="Tri-state phase from projection governance."
    )
    runtime_domain: Optional[str] = Field(
        default=None, description="Runtime domain from projection governance."
    )
    assembled_at: Optional[float] = Field(
        default=None,
        description="Unix epoch timestamp when upstream governance summary was assembled.",
    )
    available: bool = Field(
        default=False,
        description="True when a real projection governance summary was provided.",
    )

    model_config = {"from_attributes": True}

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string."""
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# RuntimeGovernanceSnapshot — top-level canonical snapshot
# ---------------------------------------------------------------------------


class RuntimeGovernanceSnapshot(BaseModel):
    """Unified runtime governance snapshot.

    The top-level canonical object that assembles the current runtime
    posture into one stable, serialisable contract.

    This is the answer to "what is the complete runtime governance posture
    right now?" — combining tri-state phase, runtime domain, execution intent,
    readiness/policy posture, fallback trace, execution lifecycle trace, and
    projection governance data in one stable object.

    Fields
    ------
    snapshot_id
        Unique identifier for this snapshot instance (UUID4).
    trace_id
        Shared trace ID from the current execution lifecycle.  ``None``
        when no active trace is available.
    runtime_session_id
        Active runtime / OpenClawd session ID.  ``None`` when unavailable.
    tri_state_phase
        The public three-state view of the system
        (``"silent"`` / ``"liminal"`` / ``"manifest"``).  ``None`` when
        the phase has not been resolved.
    runtime_domain
        Execution domain
        (``"local"`` / ``"cross_device"`` / ``"transition"``).  ``None``
        when undetermined.
    governance_available
        ``True`` when at least one real governance input was present.
    intent_summary
        Compact runtime-side summary of the current execution intent
        (PR-22).
    readiness_summary
        Compact runtime-side readiness and policy posture summary (PR-23).
    fallback_summary
        Compact runtime-side fallback trace summary, derived from PR-24
        trace data embedded in the execution trace (PR-25).
    execution_trace_summary
        Compact runtime-side execution lifecycle trace summary (PR-25).
    projection_governance_summary
        Compact runtime-side summary of the projection governance layer
        (PR-26).
    posture
        Top-level posture string derived from the combined governance
        signals.  One of: ``"execute"`` / ``"observe"`` / ``"blocked"`` /
        ``"degraded"`` / ``"unknown"``.
    blocked
        Convenience flag — ``True`` when the posture is ``"blocked"``.
    degraded
        Convenience flag — ``True`` when the posture is ``"degraded"``.
    timestamp
        Unix epoch seconds when this snapshot was assembled.
    """

    snapshot_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this snapshot instance.",
    )
    trace_id: Optional[str] = Field(
        default=None, description="Shared trace ID from the current execution lifecycle."
    )
    runtime_session_id: Optional[str] = Field(
        default=None, description="Active runtime / OpenClawd session ID."
    )
    tri_state_phase: Optional[str] = Field(
        default=None,
        description="Public three-state view of the system (silent / liminal / manifest).",
    )
    runtime_domain: Optional[str] = Field(
        default=None,
        description="Execution domain (local / cross_device / transition).",
    )
    governance_available: bool = Field(
        default=False,
        description="True when at least one real governance input was present.",
    )
    intent_summary: RuntimeGovernanceExecutionSummary = Field(
        default_factory=RuntimeGovernanceExecutionSummary,
        description="Compact runtime-side summary of the current execution intent (PR-22).",
    )
    readiness_summary: RuntimeGovernancePolicySummary = Field(
        default_factory=RuntimeGovernancePolicySummary,
        description="Compact runtime-side readiness and policy posture summary (PR-23).",
    )
    fallback_summary: RuntimeGovernanceTraceSummary = Field(
        default_factory=RuntimeGovernanceTraceSummary,
        description="Compact runtime-side fallback trace summary (derived from PR-24/25).",
    )
    execution_trace_summary: RuntimeGovernanceTraceSummary = Field(
        default_factory=RuntimeGovernanceTraceSummary,
        description="Compact runtime-side execution lifecycle trace summary (PR-25).",
    )
    projection_governance_summary: RuntimeGovernanceProjectionSummary = Field(
        default_factory=RuntimeGovernanceProjectionSummary,
        description="Compact runtime-side summary of the projection governance layer (PR-26).",
    )
    posture: str = Field(
        default="unknown",
        description=(
            "Top-level posture derived from governance signals. "
            "One of: execute / observe / blocked / degraded / unknown."
        ),
    )
    blocked: bool = Field(
        default=False, description="True when posture is blocked."
    )
    degraded: bool = Field(
        default=False, description="True when posture is degraded."
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds when this snapshot was assembled.",
    )

    model_config = {"from_attributes": True}

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict.

        Nested summary objects are recursively serialised via their own
        ``to_dict()`` methods.
        """
        return {
            "snapshot_id": self.snapshot_id,
            "trace_id": self.trace_id,
            "runtime_session_id": self.runtime_session_id,
            "tri_state_phase": self.tri_state_phase,
            "runtime_domain": self.runtime_domain,
            "governance_available": self.governance_available,
            "intent_summary": self.intent_summary.to_dict(),
            "readiness_summary": self.readiness_summary.to_dict(),
            "fallback_summary": self.fallback_summary.to_dict(),
            "execution_trace_summary": self.execution_trace_summary.to_dict(),
            "projection_governance_summary": self.projection_governance_summary.to_dict(),
            "posture": self.posture,
            "blocked": self.blocked,
            "degraded": self.degraded,
            "timestamp": self.timestamp,
        }

    def to_json(self, **kwargs: Any) -> str:
        """Return a compact JSON string."""
        return json.dumps(self.to_dict(), **kwargs)

    def __repr__(self) -> str:
        return (
            f"<RuntimeGovernanceSnapshot "
            f"phase={self.tri_state_phase!r} "
            f"domain={self.runtime_domain!r} "
            f"posture={self.posture!r} "
            f"blocked={self.blocked} "
            f"degraded={self.degraded}>"
        )


# ---------------------------------------------------------------------------
# Assembly helpers — summarize_* adapters
# ---------------------------------------------------------------------------


def summarize_runtime_intent(
    intent_profile: Optional[Any],
) -> RuntimeGovernanceExecutionSummary:
    """Build a :class:`RuntimeGovernanceExecutionSummary` from an intent profile.

    Parameters
    ----------
    intent_profile:
        An :class:`~core.execution.intent_profile.ExecutionIntentProfile`
        (PR-22) or any object with compatible attributes.  ``None`` and
        malformed objects are handled gracefully.

    Returns
    -------
    RuntimeGovernanceExecutionSummary
        Always returns a valid summary; never raises.
    """
    if intent_profile is None:
        return RuntimeGovernanceExecutionSummary(available=False)

    try:
        if hasattr(intent_profile, "compact_summary"):
            summary = intent_profile.compact_summary()
            return RuntimeGovernanceExecutionSummary(
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

        return RuntimeGovernanceExecutionSummary(
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
            "summarize_runtime_intent: failed to summarise intent_profile "
            "(type=%s): %s",
            type(intent_profile).__name__,
            exc,
        )
        return RuntimeGovernanceExecutionSummary(available=False)


def summarize_runtime_readiness(
    readiness_result: Optional[Any],
) -> RuntimeGovernancePolicySummary:
    """Build a :class:`RuntimeGovernancePolicySummary` from a readiness result.

    Parameters
    ----------
    readiness_result:
        A :class:`~core.execution.readiness_gate.ReadinessResult` (PR-23)
        or any object with compatible attributes.  ``None`` and malformed
        objects are handled gracefully; the default summary represents a
        conservatively blocked posture.

    Returns
    -------
    RuntimeGovernancePolicySummary
        Always returns a valid summary; never raises.
    """
    if readiness_result is None:
        return RuntimeGovernancePolicySummary(available=False)

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

        return RuntimeGovernancePolicySummary(
            ready=ready,
            status=status,
            reason=reason,
            requires_confirmation=requires_confirmation,
            action_level=action_level,
            policy_band=policy_band,
            blocked_by=blocked_by,
            runtime_domain=str(runtime_domain) if runtime_domain is not None else None,
            blocked=blocked,
            degraded=degraded,
            available=True,
        )
    except Exception as exc:
        logger.warning(
            "summarize_runtime_readiness: failed to summarise readiness_result "
            "(type=%s): %s",
            type(readiness_result).__name__,
            exc,
        )
        return RuntimeGovernancePolicySummary(available=False)


def summarize_runtime_fallback(
    fallback_trace: Optional[Any],
) -> RuntimeGovernanceTraceSummary:
    """Build a :class:`RuntimeGovernanceTraceSummary` from a fallback decision trace.

    This helper populates only the fallback-relevant fields of the trace
    summary; ``stage_count`` and ``stages`` will reflect zero/empty because
    this object represents a fallback decision trace (PR-24), not the full
    execution lifecycle (PR-25).

    Parameters
    ----------
    fallback_trace:
        A :class:`~core.execution.fallback_trace.FallbackDecisionTrace`
        (PR-24) or any object with compatible attributes.  ``None`` and
        malformed objects are handled gracefully; the default summary
        represents a no-op posture.

    Returns
    -------
    RuntimeGovernanceTraceSummary
        Always returns a valid summary; never raises.
    """
    if fallback_trace is None:
        return RuntimeGovernanceTraceSummary(available=False)

    try:
        if hasattr(fallback_trace, "compact_summary"):
            cs = fallback_trace.compact_summary()
            outcome = cs.get("outcome", "noop")
            trace_id = cs.get("trace_id")
            intent_id = cs.get("intent_id")
            return RuntimeGovernanceTraceSummary(
                trace_id=trace_id,
                intent_id=intent_id,
                fallback_outcome=outcome,
                final_status="pending",
                stage_count=0,
                stages=[],
                available=True,
            )

        outcome = str(getattr(fallback_trace, "outcome", "noop"))
        return RuntimeGovernanceTraceSummary(
            trace_id=getattr(fallback_trace, "trace_id", None),
            intent_id=getattr(fallback_trace, "intent_id", None),
            fallback_outcome=outcome,
            final_status="pending",
            stage_count=0,
            stages=[],
            available=True,
        )
    except Exception as exc:
        logger.warning(
            "summarize_runtime_fallback: failed to summarise fallback_trace "
            "(type=%s): %s",
            type(fallback_trace).__name__,
            exc,
        )
        return RuntimeGovernanceTraceSummary(available=False)


def summarize_runtime_execution_trace(
    execution_trace_envelope: Optional[Any],
) -> RuntimeGovernanceTraceSummary:
    """Build a :class:`RuntimeGovernanceTraceSummary` from an execution trace envelope.

    Parameters
    ----------
    execution_trace_envelope:
        An :class:`~contracts.execution_trace.ExecutionTraceEnvelope`
        (PR-25) or any object with compatible attributes.  ``None`` and
        malformed objects are handled gracefully; the default summary has
        zero stages and a ``"pending"`` final_status.

    Returns
    -------
    RuntimeGovernanceTraceSummary
        Always returns a valid summary; never raises.
    """
    if execution_trace_envelope is None:
        return RuntimeGovernanceTraceSummary(available=False)

    try:
        if hasattr(execution_trace_envelope, "compact_summary"):
            cs = execution_trace_envelope.compact_summary()
            return RuntimeGovernanceTraceSummary(
                trace_id=cs.get("trace_id"),
                intent_id=cs.get("intent_id"),
                runtime_session_id=cs.get("runtime_session_id"),
                final_status=cs.get("final_status", "pending"),
                stage_count=int(cs.get("stage_count", 0)),
                stages=list(cs.get("stages", [])),
                available=True,
            )

        return RuntimeGovernanceTraceSummary(
            trace_id=getattr(execution_trace_envelope, "trace_id", None),
            intent_id=getattr(execution_trace_envelope, "intent_id", None),
            runtime_session_id=getattr(
                execution_trace_envelope, "runtime_session_id", None
            ),
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
            "summarize_runtime_execution_trace: failed to summarise envelope "
            "(type=%s): %s",
            type(execution_trace_envelope).__name__,
            exc,
        )
        return RuntimeGovernanceTraceSummary(available=False)


def summarize_projection_governance_for_runtime(
    projection_governance: Optional[Any],
) -> RuntimeGovernanceProjectionSummary:
    """Build a :class:`RuntimeGovernanceProjectionSummary` from a projection governance summary.

    Parameters
    ----------
    projection_governance:
        A :class:`~core.projection.assembly_governance.ProjectionGovernanceSummary`
        (PR-26) or any object / dict with compatible attributes.  ``None``
        and malformed objects are handled gracefully.

    Returns
    -------
    RuntimeGovernanceProjectionSummary
        Always returns a valid summary; never raises.
    """
    if projection_governance is None:
        return RuntimeGovernanceProjectionSummary(available=False)

    try:
        # Support both Pydantic object and plain dict
        if isinstance(projection_governance, dict):
            gov_available = bool(projection_governance.get("governance_available", False))
            execution = projection_governance.get("execution", {}) or {}
            policy = projection_governance.get("policy", {}) or {}
            fallback = projection_governance.get("fallback", {}) or {}
            exec_trace = projection_governance.get("execution_trace", {}) or {}
            return RuntimeGovernanceProjectionSummary(
                governance_available=gov_available,
                action_level=str(execution.get("action_level", "observe")),
                intent_mode=str(execution.get("intent_mode", "advisory")),
                policy_status=str(policy.get("status", "blocked")),
                ready=bool(policy.get("ready", False)),
                blocked=bool(policy.get("blocked", True)),
                degraded=bool(policy.get("degraded", False)),
                fallback_outcome=str(fallback.get("outcome", "noop")),
                trace_final_status=str(exec_trace.get("final_status", "pending")),
                tri_state_phase=projection_governance.get("tri_state_phase"),
                runtime_domain=projection_governance.get("runtime_domain"),
                assembled_at=projection_governance.get("assembled_at"),
                available=True,
            )

        # Pydantic model or attribute-bearing object
        gov_available = bool(
            getattr(projection_governance, "governance_available", False)
        )
        execution = getattr(projection_governance, "execution", None) or {}
        policy = getattr(projection_governance, "policy", None) or {}
        fallback = getattr(projection_governance, "fallback", None) or {}
        exec_trace = getattr(projection_governance, "execution_trace", None) or {}

        def _get(obj: Any, key: str, default: Any) -> Any:
            if isinstance(obj, dict):
                return obj.get(key, default)
            return getattr(obj, key, default)

        return RuntimeGovernanceProjectionSummary(
            governance_available=gov_available,
            action_level=str(_get(execution, "action_level", "observe")),
            intent_mode=str(_get(execution, "intent_mode", "advisory")),
            policy_status=str(_get(policy, "status", "blocked")),
            ready=bool(_get(policy, "ready", False)),
            blocked=bool(_get(policy, "blocked", True)),
            degraded=bool(_get(policy, "degraded", False)),
            fallback_outcome=str(_get(fallback, "outcome", "noop")),
            trace_final_status=str(_get(exec_trace, "final_status", "pending")),
            tri_state_phase=getattr(projection_governance, "tri_state_phase", None),
            runtime_domain=getattr(projection_governance, "runtime_domain", None),
            assembled_at=getattr(projection_governance, "assembled_at", None),
            available=True,
        )
    except Exception as exc:
        logger.warning(
            "summarize_projection_governance_for_runtime: failed to summarise "
            "projection_governance (type=%s): %s",
            type(projection_governance).__name__,
            exc,
        )
        return RuntimeGovernanceProjectionSummary(available=False)


# ---------------------------------------------------------------------------
# Posture derivation helper
# ---------------------------------------------------------------------------


def _derive_posture(
    intent_summary: RuntimeGovernanceExecutionSummary,
    readiness_summary: RuntimeGovernancePolicySummary,
    execution_trace_summary: RuntimeGovernanceTraceSummary,
) -> str:
    """Derive the top-level posture string from combined governance signals.

    Returns one of: ``"execute"`` / ``"observe"`` / ``"blocked"`` /
    ``"degraded"`` / ``"unknown"``.

    The derivation order is:
    1. blocked overrides everything
    2. degraded overrides non-execute postures
    3. execute when readiness confirms it
    4. observe when intent is advisory/observe only
    5. unknown when insufficient signals are available
    """
    # Not enough signals
    if (
        not intent_summary.available
        and not readiness_summary.available
        and not execution_trace_summary.available
    ):
        return "unknown"

    # Blocked trumps all
    if readiness_summary.available and readiness_summary.blocked:
        return "blocked"

    if execution_trace_summary.available and execution_trace_summary.final_status in (
        "blocked",
        "failed",
    ):
        return "blocked"

    # Degraded
    if readiness_summary.available and readiness_summary.degraded:
        return "degraded"

    # Execute
    if readiness_summary.available and readiness_summary.ready:
        return "execute"

    # Observe
    if intent_summary.available and intent_summary.action_level in ("observe", "hint"):
        return "observe"

    if readiness_summary.available and readiness_summary.action_level in ("observe", "hint"):
        return "observe"

    return "unknown"


# ---------------------------------------------------------------------------
# assemble_runtime_governance_snapshot — single canonical entry point
# ---------------------------------------------------------------------------


def assemble_runtime_governance_snapshot(
    *,
    intent_profile: Optional[Any] = None,
    readiness_result: Optional[Any] = None,
    fallback_trace: Optional[Any] = None,
    execution_trace_envelope: Optional[Any] = None,
    projection_governance: Optional[Any] = None,
    tri_state_phase: Optional[str] = None,
    runtime_domain: Optional[str] = None,
    trace_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
    snapshot_id: Optional[str] = None,
    timestamp: Optional[float] = None,
) -> RuntimeGovernanceSnapshot:
    """Assemble a unified :class:`RuntimeGovernanceSnapshot` from all governance inputs.

    This is the **single canonical entry point** for building the runtime
    governance snapshot.  Downstream code must not hand-roll runtime
    governance dicts; all runtime governance data should pass through here.

    Parameters
    ----------
    intent_profile:
        Optional :class:`~core.execution.intent_profile.ExecutionIntentProfile`
        (PR-22).
    readiness_result:
        Optional :class:`~core.execution.readiness_gate.ReadinessResult`
        (PR-23).
    fallback_trace:
        Optional :class:`~core.execution.fallback_trace.FallbackDecisionTrace`
        (PR-24).
    execution_trace_envelope:
        Optional :class:`~contracts.execution_trace.ExecutionTraceEnvelope`
        (PR-25).
    projection_governance:
        Optional
        :class:`~core.projection.assembly_governance.ProjectionGovernanceSummary`
        (PR-26) or its ``to_dict()`` representation.
    tri_state_phase:
        Optional tri-state phase string override
        (``"silent"`` / ``"liminal"`` / ``"manifest"``).  When ``None``
        the phase is resolved from available inputs.
    runtime_domain:
        Optional runtime domain string override
        (``"local"`` / ``"cross_device"`` / ``"transition"``).  When
        ``None`` the domain is resolved from available inputs.
    trace_id:
        Optional trace ID override.  When ``None`` the trace ID is
        resolved from the execution trace envelope (if available).
    runtime_session_id:
        Optional runtime session ID override.  When ``None`` the session
        ID is resolved from the execution trace envelope (if available).
    snapshot_id:
        Optional explicit snapshot ID.  A UUID4 is generated when ``None``.
    timestamp:
        Optional explicit Unix epoch timestamp.  Defaults to
        :func:`time.time`.

    Returns
    -------
    RuntimeGovernanceSnapshot
        Always returns a valid snapshot; never raises.  When all inputs
        are ``None`` the snapshot has ``governance_available=False``,
        ``posture="unknown"``, and all sub-summaries carry
        ``available=False``.
    """
    ts = timestamp if timestamp is not None else time.time()
    sid = snapshot_id or str(uuid.uuid4())

    try:
        intent_summary = summarize_runtime_intent(intent_profile)
        readiness_summary = summarize_runtime_readiness(readiness_result)
        fallback_summary = summarize_runtime_fallback(fallback_trace)
        trace_summary = summarize_runtime_execution_trace(execution_trace_envelope)
        proj_gov_summary = summarize_projection_governance_for_runtime(projection_governance)

        # Resolve tri_state_phase / runtime_domain from available signals
        resolved_phase = tri_state_phase
        resolved_domain = runtime_domain

        if resolved_phase is None and proj_gov_summary.available:
            resolved_phase = proj_gov_summary.tri_state_phase
        if resolved_domain is None and proj_gov_summary.available:
            resolved_domain = proj_gov_summary.runtime_domain
        if resolved_domain is None and intent_summary.available:
            resolved_domain = intent_summary.runtime_domain

        # Resolve trace_id / runtime_session_id from envelope when not explicit
        resolved_trace_id = trace_id
        resolved_session_id = runtime_session_id
        if resolved_trace_id is None and trace_summary.available:
            resolved_trace_id = trace_summary.trace_id
        if resolved_session_id is None and trace_summary.available:
            resolved_session_id = trace_summary.runtime_session_id

        governance_available = any(
            [
                intent_summary.available,
                readiness_summary.available,
                fallback_summary.available,
                trace_summary.available,
                proj_gov_summary.available,
            ]
        )

        posture = _derive_posture(intent_summary, readiness_summary, trace_summary)
        blocked = posture == "blocked"
        degraded = posture == "degraded"

        return RuntimeGovernanceSnapshot(
            snapshot_id=sid,
            trace_id=resolved_trace_id,
            runtime_session_id=resolved_session_id,
            tri_state_phase=resolved_phase,
            runtime_domain=resolved_domain,
            governance_available=governance_available,
            intent_summary=intent_summary,
            readiness_summary=readiness_summary,
            fallback_summary=fallback_summary,
            execution_trace_summary=trace_summary,
            projection_governance_summary=proj_gov_summary,
            posture=posture,
            blocked=blocked,
            degraded=degraded,
            timestamp=ts,
        )
    except Exception as exc:
        logger.warning(
            "assemble_runtime_governance_snapshot: assembly failed, "
            "returning minimal snapshot: %s",
            exc,
        )
        return RuntimeGovernanceSnapshot(
            snapshot_id=sid,
            governance_available=False,
            posture="unknown",
            blocked=False,
            degraded=False,
            timestamp=ts,
        )
