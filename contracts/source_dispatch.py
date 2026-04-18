"""contracts/source_dispatch.py
=================================
Source Runtime Dispatch Contracts — PR-35.

This module defines the **canonical source-side dispatch contracts**: the
structured, serialisable representations of a source runtime's orchestration
decision and result when choosing whether to execute locally, delegate to a
target runtime, or coordinate a staged multi-device dispatch.

It answers the architectural question:

    *"What structured decision, plan, and result does the source runtime
    produce when it decides how to dispatch a task — local, remote handoff,
    or staged mesh?"*

These contracts are the source-side counterpart to:

- **PR-34** (:class:`~contracts.local_takeover_result.LocalTakeoverResult`) —
  the target-side result after adopting and executing a handoff.
- **PR-31** (:class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2`) —
  the handoff envelope sent to the target.
- **PR-33** (:class:`~contracts.mesh_session.MeshSession`) — the mesh session
  that staged dispatch may coordinate across.
- **PR-27** (``RuntimeGovernanceSnapshot``) — the governance posture consumed
  when making the dispatch decision.
- **PR-28** (``ExecutionPolicyAlignmentSurface``) — the policy alignment
  consumed when making the dispatch decision.
- **PR-25** (:class:`~contracts.execution_trace.ExecutionTraceEnvelope`) —
  the execution trace produced by local execution, when chosen.

This module formalises:
- the dispatch mode enum (``SourceDispatchMode``);
- the dispatch decision (``SourceDispatchDecision``);
- the dispatch target (``SourceDispatchTarget``);
- the dispatch plan (``SourceDispatchPlan``);
- the dispatch result (``SourceDispatchResult``);
- the dispatch summary (``SourceDispatchSummary``);
- builder / adapter functions for all contracts.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Fully serialisable** — all contracts produce stable, round-trippable JSON
  via ``to_dict`` / ``to_json``.
- **Graceful defaults** — all fields beyond ``dispatch_id`` and ``mode`` are
  optional; callers with partial context always produce a valid contract.
- **Stable field names** — downstream consumers can rely on all field names.
- **No UI semantics** — purely runtime/projection/coordinator use.

Usage::

    from contracts.source_dispatch import (
        SourceDispatchMode,
        SourceDispatchDecision,
        SourceDispatchResult,
        build_source_dispatch_decision,
        build_source_dispatch_result,
    )

    decision = build_source_dispatch_decision(
        trace_id="trace_abc",
        mode=SourceDispatchMode.local,
        decision_reason="local_preferred_by_policy",
    )
    result = build_source_dispatch_result(
        dispatch_id=decision.dispatch_id,
        trace_id=decision.trace_id,
        mode=decision.mode,
        success=True,
    )
    payload = result.to_dict()

See ``docs/SOURCE_RUNTIME_DISPATCH_ORCHESTRATOR.md`` for the full
specification.
"""

from __future__ import annotations

import json
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from contracts.source_posture_contract import _normalise_posture_hint


# ---------------------------------------------------------------------------
# SourceDispatchMode — canonical dispatch mode enum
# ---------------------------------------------------------------------------


class SourceDispatchMode(str, Enum):
    """Source-side dispatch mode selected by the orchestrator.

    local
        Execute the task locally on the source runtime.
    remote_handoff
        Delegate the task to a remote target runtime via a HandoffEnvelopeV2.
    staged_mesh
        Coordinate execution across multiple devices via a mesh session
        (PR-33).  A full Mesh Session Coordinator is out of scope for PR-35;
        this mode produces a plan summary but defers coordinator work to a
        future PR.
    blocked
        The task cannot be dispatched due to a hard policy / governance
        constraint.
    fallback_local
        A remote handoff was attempted but failed; execution fell back to the
        local runtime.
    unknown
        Mode could not be determined (degraded / incomplete context).
    """

    local = "local"
    remote_handoff = "remote_handoff"
    staged_mesh = "staged_mesh"
    blocked = "blocked"
    fallback_local = "fallback_local"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# SourceDispatchTarget — selected execution target (remote or local)
# ---------------------------------------------------------------------------


class SourceDispatchTarget(BaseModel):
    """Describes the execution target selected by the source dispatch decision.

    Fields
    ------
    target_device_id
        Identifier of the device selected as the execution target.  ``None``
        for local execution.
    target_runtime_id
        Identifier of the runtime on the target device.  ``None`` when
        unavailable or local.
    target_session_id
        Session identifier on the target side, if known at plan time.
    handoff_envelope_id
        Identifier of the :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2`
        built for remote handoff, if applicable.
    mesh_session_id
        Mesh-level session identifier (PR-33), if a staged mesh dispatch was
        selected.
    selection_reason
        Human-readable reason why this target was chosen.
    metadata
        Arbitrary extension metadata.
    """

    target_device_id: Optional[str] = Field(
        default=None,
        description="Selected target device ID.  None for local execution.",
    )
    target_runtime_id: Optional[str] = Field(
        default=None,
        description="Selected target runtime ID.  None when unavailable or local.",
    )
    target_session_id: Optional[str] = Field(
        default=None,
        description="Target-side session ID if known at plan time.",
    )
    handoff_envelope_id: Optional[str] = Field(
        default=None,
        description="Handoff envelope ID built for remote handoff, if applicable.",
    )
    mesh_session_id: Optional[str] = Field(
        default=None,
        description="Mesh session ID (PR-33) for staged mesh dispatch.",
    )
    selection_reason: Optional[str] = Field(
        default=None,
        description="Human-readable reason for target selection.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extension metadata.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# SourceDispatchDecision — the source-side dispatch decision record
# ---------------------------------------------------------------------------


class SourceDispatchDecision(BaseModel):
    """Canonical record of the source-side dispatch decision.

    This is the structured artefact produced when the source orchestrator
    evaluates the current execution context and decides *how* to dispatch a
    task.

    Fields
    ------
    dispatch_id
        Unique identifier for this dispatch decision (UUID4).
    trace_id
        Distributed trace identifier, forwarded from the upstream intent /
        task context.
    task_id
        Task identifier, if available.
    session_id
        Source-side session identifier, if available.
    source_device_id
        Identifier of the source device making the dispatch decision.
    source_runtime_id
        Identifier of the source runtime (e.g. OpenClawd instance ID).
    mode
        The :class:`SourceDispatchMode` selected (local / remote_handoff /
        staged_mesh / blocked / fallback_local / unknown).
    selected_target
        The :class:`SourceDispatchTarget` selected, when a remote or mesh
        target was chosen.  ``None`` for local execution.
    decision_reason
        Human-readable explanation of why this mode / target was selected.
    policy_alignment
        Serialised ``ExecutionPolicyAlignmentSurface`` dict (PR-28),
        if available when the decision was made.
    governance_snapshot
        Serialised ``RuntimeGovernanceSnapshot`` dict (PR-27), if available
        when the decision was made.
    mesh_session
        Serialised :class:`~contracts.mesh_session.MeshSession` dict (PR-33),
        if a mesh session is relevant to this decision.
    handoff_envelope
        Compact reference or serialised
        :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2` dict, if one
        was built for this dispatch.
    timestamp
        Unix timestamp when the decision was made.
    metadata
        Arbitrary extension metadata.
    """

    dispatch_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this dispatch decision (UUID4).",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Distributed trace identifier from the upstream task context.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Task identifier, if available.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Source-side session identifier, if available.",
    )
    source_device_id: Optional[str] = Field(
        default=None,
        description="Identifier of the source device making this dispatch decision.",
    )
    source_runtime_id: Optional[str] = Field(
        default=None,
        description="Identifier of the source runtime (e.g. OpenClawd instance ID).",
    )
    mode: SourceDispatchMode = Field(
        default=SourceDispatchMode.unknown,
        description="Selected dispatch mode.",
    )
    selected_target: Optional[SourceDispatchTarget] = Field(
        default=None,
        description="Selected execution target for remote/mesh dispatch.",
    )
    decision_reason: Optional[str] = Field(
        default=None,
        description="Human-readable explanation of why this mode/target was selected.",
    )
    policy_alignment: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialised ExecutionPolicyAlignmentSurface dict (PR-28).",
    )
    governance_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialised RuntimeGovernanceSnapshot dict (PR-27).",
    )
    mesh_session: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialised MeshSession dict (PR-33), if relevant.",
    )
    handoff_envelope: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Compact ref or serialised HandoffEnvelopeV2 dict, if built.",
    )
    source_runtime_posture: str = Field(
        default="control_only",
        description=(
            "Source-device runtime participation posture at dispatch time. "
            "Must be 'control_only' or 'join_runtime'. "
            "Canonical field name per SOURCE_POSTURE_CONTRACT_AUTHORITY."
        ),
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix timestamp when this decision was made.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extension metadata.",
    )

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable, JSON-safe dictionary representation."""
        return self.model_dump(mode="json")

    def to_json(self, *, indent: Optional[int] = None) -> str:
        """Return a stable JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourceDispatchDecision":
        """Construct from a dictionary.  Tolerates unknown extra fields."""
        return cls.model_validate(data)

    def to_compact_summary(self) -> Dict[str, Any]:
        """Return a compact human-readable summary dict."""
        return {
            "dispatch_id": self.dispatch_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "source_device_id": self.source_device_id,
            "source_runtime_posture": self.source_runtime_posture,
            "mode": self.mode.value if isinstance(self.mode, SourceDispatchMode) else str(self.mode),
            "decision_reason": self.decision_reason,
            "has_target": self.selected_target is not None,
            "has_policy_alignment": self.policy_alignment is not None,
            "has_governance_snapshot": self.governance_snapshot is not None,
            "has_mesh_session": self.mesh_session is not None,
            "has_handoff_envelope": self.handoff_envelope is not None,
            "timestamp": self.timestamp,
        }

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# SourceDispatchPlan — the planned dispatch, before execution begins
# ---------------------------------------------------------------------------


class SourceDispatchPlan(BaseModel):
    """Planned source dispatch, produced before execution begins.

    A plan captures the decision plus any pre-built artefacts (e.g. a
    HandoffEnvelopeV2 ref for remote handoff, or a mesh session summary for
    staged mesh dispatch).  Execution may then proceed or be deferred.

    Fields
    ------
    plan_id
        Unique identifier for this plan (UUID4).
    dispatch_id
        Identifier of the :class:`SourceDispatchDecision` this plan is based on.
    trace_id
        Distributed trace identifier.
    task_id
        Task identifier, if available.
    session_id
        Source-side session identifier, if available.
    mode
        The :class:`SourceDispatchMode` to be executed.
    selected_target
        The :class:`SourceDispatchTarget` selected, if remote/mesh.
    handoff_envelope
        Serialised :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2`
        dict, if one was pre-built for a remote handoff.
    mesh_session
        Serialised :class:`~contracts.mesh_session.MeshSession` dict, if a
        mesh session was prepared for a staged dispatch.
    policy_alignment
        Serialised policy alignment dict (PR-28), if available.
    governance_snapshot
        Serialised governance snapshot dict (PR-27), if available.
    ready
        ``True`` when the plan is ready for immediate execution.
    readiness_notes
        List of notes about plan readiness (warnings, missing inputs, etc.).
    timestamp
        Unix timestamp when the plan was built.
    metadata
        Arbitrary extension metadata.
    """

    plan_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this dispatch plan (UUID4).",
    )
    dispatch_id: Optional[str] = Field(
        default=None,
        description="Dispatch decision ID this plan is based on.",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Distributed trace identifier.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Task identifier, if available.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Source-side session identifier, if available.",
    )
    mode: SourceDispatchMode = Field(
        default=SourceDispatchMode.unknown,
        description="Dispatch mode to be executed.",
    )
    selected_target: Optional[SourceDispatchTarget] = Field(
        default=None,
        description="Selected execution target for remote/mesh dispatch.",
    )
    handoff_envelope: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Pre-built HandoffEnvelopeV2 dict for remote handoff.",
    )
    mesh_session: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Pre-built MeshSession dict for staged mesh dispatch.",
    )
    policy_alignment: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialised policy alignment (PR-28), if available.",
    )
    governance_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialised governance snapshot (PR-27), if available.",
    )
    source_runtime_posture: str = Field(
        default="control_only",
        description=(
            "Source-device runtime participation posture for this planned dispatch. "
            "Must be 'control_only' or 'join_runtime'. "
            "Canonical field name per SOURCE_POSTURE_CONTRACT_AUTHORITY."
        ),
    )
    ready: bool = Field(
        default=False,
        description="True when the plan is ready for immediate execution.",
    )
    readiness_notes: List[str] = Field(
        default_factory=list,
        description="Notes about plan readiness (warnings, missing inputs, etc.).",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix timestamp when the plan was built.",
    )
    continuity_context: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Durable continuity context (PR-F) carrying prior identity fields for "
            "reconnect/handoff correlation.  Serialised DispatchContinuityContext dict. "
            "None when not yet established (first dispatch attempt or ephemeral context). "
            "(PR-F)"
        ),
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extension metadata.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    def to_json(self, *, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourceDispatchPlan":
        return cls.model_validate(data)

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# SourceDispatchResult — the result of a completed source dispatch
# ---------------------------------------------------------------------------


class SourceDispatchResult(BaseModel):
    """Canonical result produced after a source dispatch has completed.

    This captures the outcome of executing a :class:`SourceDispatchPlan`:
    whether local execution succeeded, remote handoff completed, or staged mesh
    was prepared.

    Fields
    ------
    result_id
        Unique identifier for this result (UUID4).
    dispatch_id
        The dispatch decision ID this result corresponds to.
    trace_id
        Distributed trace identifier.
    task_id
        Task identifier, if available.
    session_id
        Source-side session identifier, if available.
    source_device_id
        Source device identifier.
    source_runtime_id
        Source runtime identifier.
    mode
        The :class:`SourceDispatchMode` that was executed.
    selected_target
        The :class:`SourceDispatchTarget` that was used, if remote/mesh.
    success
        ``True`` when dispatch completed successfully.
    result
        Raw execution result dict, as returned by the executor (local path) or
        remote bridge (handoff path).  ``None`` when unavailable.
    execution_trace
        Serialised :class:`~contracts.execution_trace.ExecutionTraceEnvelope`
        dict, if local execution produced one.
    takeover_result
        Serialised :class:`~contracts.local_takeover_result.LocalTakeoverResult`
        dict returned by the remote target, if a remote handoff was used.
    governance_snapshot
        Serialised ``RuntimeGovernanceSnapshot`` dict (PR-27), if available.
    policy_alignment
        Serialised ``ExecutionPolicyAlignmentSurface`` dict (PR-28), if
        available.
    mesh_session
        Serialised :class:`~contracts.mesh_session.MeshSession` dict (PR-33),
        if a mesh session was involved.
    errors
        List of error/warning strings.  Empty on clean success.
    decision_reason
        Human-readable reason for the dispatch mode that was selected.
    timestamp
        Unix timestamp when this result was produced.
    metadata
        Arbitrary extension metadata.
    """

    result_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this dispatch result (UUID4).",
    )
    dispatch_id: Optional[str] = Field(
        default=None,
        description="Dispatch decision ID this result corresponds to.",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Distributed trace identifier.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Task identifier, if available.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Source-side session identifier, if available.",
    )
    source_device_id: Optional[str] = Field(
        default=None,
        description="Source device identifier.",
    )
    source_runtime_id: Optional[str] = Field(
        default=None,
        description="Source runtime identifier.",
    )
    mode: SourceDispatchMode = Field(
        default=SourceDispatchMode.unknown,
        description="Dispatch mode that was executed.",
    )
    selected_target: Optional[SourceDispatchTarget] = Field(
        default=None,
        description="Execution target used for remote/mesh dispatch.",
    )
    success: bool = Field(
        default=False,
        description="True when dispatch completed successfully.",
    )
    result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Raw execution result dict.  None when unavailable.",
    )
    execution_trace: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialised ExecutionTraceEnvelope dict (PR-25), if available.",
    )
    takeover_result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialised LocalTakeoverResult from remote target, if handoff was used.",
    )
    governance_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialised RuntimeGovernanceSnapshot dict (PR-27), if available.",
    )
    policy_alignment: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialised ExecutionPolicyAlignmentSurface dict (PR-28), if available.",
    )
    mesh_session: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialised MeshSession dict (PR-33), if involved.",
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Error/warning strings.  Empty on clean success.",
    )
    decision_reason: Optional[str] = Field(
        default=None,
        description="Human-readable reason for the dispatch mode selected.",
    )
    source_runtime_posture: str = Field(
        default="control_only",
        description=(
            "Source-device runtime participation posture at result time. "
            "Must be 'control_only' or 'join_runtime'. "
            "Canonical field name per SOURCE_POSTURE_CONTRACT_AUTHORITY."
        ),
    )
    continuity_context: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Durable continuity context (PR-F) carrying prior identity fields for "
            "reconnect/handoff correlation.  Serialised DispatchContinuityContext dict. "
            "Populated when this result may be interrupted and resumed, or when it "
            "corresponds to a resumed execution.  None for clean terminal results. "
            "(PR-F)"
        ),
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix timestamp when this result was produced.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extension metadata.",
    )

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable, JSON-safe dictionary representation."""
        return self.model_dump(mode="json")

    def to_json(self, *, indent: Optional[int] = None) -> str:
        """Return a stable JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourceDispatchResult":
        """Construct from a dictionary.  Tolerates unknown extra fields."""
        return cls.model_validate(data)

    def to_compact_summary(self) -> Dict[str, Any]:
        """Return a compact human-readable summary dict."""
        return {
            "result_id": self.result_id,
            "dispatch_id": self.dispatch_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "source_device_id": self.source_device_id,
            "source_runtime_posture": self.source_runtime_posture,
            "mode": self.mode.value if isinstance(self.mode, SourceDispatchMode) else str(self.mode),
            "success": self.success,
            "decision_reason": self.decision_reason,
            "error_count": len(self.errors),
            "has_result": self.result is not None,
            "has_execution_trace": self.execution_trace is not None,
            "has_takeover_result": self.takeover_result is not None,
            "has_governance_snapshot": self.governance_snapshot is not None,
            "has_policy_alignment": self.policy_alignment is not None,
            "has_mesh_session": self.mesh_session is not None,
            "has_continuity_context": self.continuity_context is not None,
            "timestamp": self.timestamp,
        }

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# SourceDispatchSummary — lightweight read-only orchestration summary
# ---------------------------------------------------------------------------


class SourceDispatchSummary(BaseModel):
    """Lightweight read-only summary of a completed source dispatch cycle.

    This is suitable for projection payloads, dashboard tiles, and trace
    metadata.  It omits large raw payloads; use :class:`SourceDispatchResult`
    for the full structured record.

    Fields
    ------
    summary_id
        Unique identifier for this summary (UUID4).
    dispatch_id
        The dispatch decision ID.
    trace_id
        Distributed trace identifier.
    task_id
        Task identifier, if available.
    session_id
        Source-side session identifier, if available.
    source_device_id
        Source device identifier.
    mode
        The :class:`SourceDispatchMode` that was selected.
    success
        ``True`` when dispatch completed successfully.
    decision_reason
        Human-readable reason for the dispatch mode.
    target_device_id
        Target device identifier, if a remote or mesh target was used.
    error_count
        Number of errors / warnings collected.
    has_execution_trace
        Whether an execution trace was produced.
    has_takeover_result
        Whether a remote takeover result was received.
    has_mesh_session
        Whether a mesh session was involved.
    timestamp
        Unix timestamp of the source dispatch result.
    """

    summary_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this summary (UUID4).",
    )
    dispatch_id: Optional[str] = Field(
        default=None,
        description="Dispatch decision ID.",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Distributed trace identifier.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Task identifier, if available.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Source-side session identifier, if available.",
    )
    source_device_id: Optional[str] = Field(
        default=None,
        description="Source device identifier.",
    )
    mode: SourceDispatchMode = Field(
        default=SourceDispatchMode.unknown,
        description="Dispatch mode that was selected.",
    )
    success: bool = Field(
        default=False,
        description="True when dispatch completed successfully.",
    )
    decision_reason: Optional[str] = Field(
        default=None,
        description="Human-readable reason for the dispatch mode.",
    )
    target_device_id: Optional[str] = Field(
        default=None,
        description="Target device ID used, if remote or mesh dispatch.",
    )
    error_count: int = Field(
        default=0,
        description="Number of errors/warnings collected.",
    )
    has_execution_trace: bool = Field(
        default=False,
        description="Whether an execution trace was produced.",
    )
    has_takeover_result: bool = Field(
        default=False,
        description="Whether a remote takeover result was received.",
    )
    has_mesh_session: bool = Field(
        default=False,
        description="Whether a mesh session was involved.",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix timestamp of the dispatch result.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extension metadata.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    def to_json(self, *, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SourceDispatchSummary":
        return cls.model_validate(data)

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# Builder / adapter functions
# ---------------------------------------------------------------------------


def build_source_dispatch_decision(
    *,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    source_device_id: Optional[str] = None,
    source_runtime_id: Optional[str] = None,
    source_runtime_posture: Optional[str] = None,
    mode: SourceDispatchMode = SourceDispatchMode.unknown,
    selected_target: Optional[SourceDispatchTarget] = None,
    decision_reason: Optional[str] = None,
    policy_alignment: Optional[Dict[str, Any]] = None,
    governance_snapshot: Optional[Dict[str, Any]] = None,
    mesh_session: Optional[Dict[str, Any]] = None,
    handoff_envelope: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> SourceDispatchDecision:
    """Convenience factory for :class:`SourceDispatchDecision`.

    All parameters are optional; omitted fields fall back to safe defaults.
    This builder never raises.

    Parameters
    ----------
    trace_id:
        Distributed trace identifier from the upstream task context.
    task_id:
        Task identifier, if available.
    session_id:
        Source-side session identifier.
    source_device_id:
        Source device identifier.
    source_runtime_id:
        Source runtime identifier.
    source_runtime_posture:
        Source-device runtime participation posture: 'control_only' or
        'join_runtime'.  Defaults to 'control_only'.
    mode:
        Selected dispatch mode.
    selected_target:
        Selected execution target (for remote/mesh dispatch).
    decision_reason:
        Human-readable reason for mode selection.
    policy_alignment:
        Serialised policy alignment dict (PR-28).
    governance_snapshot:
        Serialised governance snapshot dict (PR-27).
    mesh_session:
        Serialised mesh session dict (PR-33).
    handoff_envelope:
        Compact ref or serialised handoff envelope dict.
    metadata:
        Arbitrary extension metadata.
    """
    _posture = _normalise_posture_hint(source_runtime_posture)
    try:
        return SourceDispatchDecision(
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            source_device_id=source_device_id,
            source_runtime_id=source_runtime_id,
            source_runtime_posture=_posture,
            mode=mode,
            selected_target=selected_target,
            decision_reason=decision_reason,
            policy_alignment=policy_alignment,
            governance_snapshot=governance_snapshot,
            mesh_session=mesh_session,
            handoff_envelope=handoff_envelope,
            metadata=metadata or {},
        )
    except Exception:
        return SourceDispatchDecision(
            mode=SourceDispatchMode.unknown,
            decision_reason="build_source_dispatch_decision: construction error",
        )


def build_source_dispatch_plan(
    *,
    decision: Optional[SourceDispatchDecision] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    source_runtime_posture: Optional[str] = None,
    mode: Optional[SourceDispatchMode] = None,
    selected_target: Optional[SourceDispatchTarget] = None,
    handoff_envelope: Optional[Dict[str, Any]] = None,
    mesh_session: Optional[Dict[str, Any]] = None,
    policy_alignment: Optional[Dict[str, Any]] = None,
    governance_snapshot: Optional[Dict[str, Any]] = None,
    ready: bool = False,
    readiness_notes: Optional[List[str]] = None,
    continuity_context: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> SourceDispatchPlan:
    """Convenience factory for :class:`SourceDispatchPlan`.

    When ``decision`` is provided its fields populate defaults for other
    parameters.

    Parameters
    ----------
    decision:
        Optional :class:`SourceDispatchDecision` to source default values from.
    trace_id, task_id, session_id, mode, selected_target, handoff_envelope,
    mesh_session, policy_alignment, governance_snapshot, ready,
    readiness_notes, metadata:
        Override fields (take precedence over ``decision`` fields when
        provided).
    source_runtime_posture:
        Source-device runtime participation posture.  Falls back to the
        decision's posture when not provided explicitly.
    continuity_context:
        Serialised :class:`~contracts.dispatch_continuity.DispatchContinuityContext`
        dict (PR-F) for reconnect/handoff correlation.  ``None`` for first
        dispatch attempts or ephemeral contexts.
    """
    try:
        d_trace = trace_id if trace_id is not None else (decision.trace_id if decision else None)
        d_task = task_id if task_id is not None else (decision.task_id if decision else None)
        d_session = session_id if session_id is not None else (decision.session_id if decision else None)
        d_mode = mode if mode is not None else (decision.mode if decision else SourceDispatchMode.unknown)
        d_target = selected_target if selected_target is not None else (decision.selected_target if decision else None)
        d_envelope = handoff_envelope if handoff_envelope is not None else (decision.handoff_envelope if decision else None)
        d_mesh = mesh_session if mesh_session is not None else (decision.mesh_session if decision else None)
        d_policy = policy_alignment if policy_alignment is not None else (decision.policy_alignment if decision else None)
        d_gov = governance_snapshot if governance_snapshot is not None else (decision.governance_snapshot if decision else None)
        d_dispatch_id = decision.dispatch_id if decision else None
        # posture: explicit override > decision's posture > default "control_only"
        _decision_posture = getattr(decision, "source_runtime_posture", "control_only") if decision else "control_only"
        d_posture = _normalise_posture_hint(source_runtime_posture) if source_runtime_posture is not None else _decision_posture
        return SourceDispatchPlan(
            dispatch_id=d_dispatch_id,
            trace_id=d_trace,
            task_id=d_task,
            session_id=d_session,
            source_runtime_posture=d_posture,
            mode=d_mode,
            selected_target=d_target,
            handoff_envelope=d_envelope,
            mesh_session=d_mesh,
            policy_alignment=d_policy,
            governance_snapshot=d_gov,
            ready=ready,
            readiness_notes=readiness_notes or [],
            continuity_context=continuity_context,
            metadata=metadata or {},
        )
    except Exception:
        return SourceDispatchPlan(
            mode=SourceDispatchMode.unknown,
            readiness_notes=["build_source_dispatch_plan: construction error"],
        )


def build_source_dispatch_result(
    *,
    dispatch_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    source_device_id: Optional[str] = None,
    source_runtime_id: Optional[str] = None,
    source_runtime_posture: Optional[str] = None,
    mode: SourceDispatchMode = SourceDispatchMode.unknown,
    selected_target: Optional[SourceDispatchTarget] = None,
    success: bool = False,
    result: Optional[Dict[str, Any]] = None,
    execution_trace: Optional[Dict[str, Any]] = None,
    takeover_result: Optional[Dict[str, Any]] = None,
    governance_snapshot: Optional[Dict[str, Any]] = None,
    policy_alignment: Optional[Dict[str, Any]] = None,
    mesh_session: Optional[Dict[str, Any]] = None,
    errors: Optional[List[str]] = None,
    decision_reason: Optional[str] = None,
    continuity_context: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> SourceDispatchResult:
    """Convenience factory for :class:`SourceDispatchResult`.

    All parameters are optional.  Never raises; construction errors produce a
    minimal failed result.

    Parameters
    ----------
    continuity_context:
        Serialised :class:`~contracts.dispatch_continuity.DispatchContinuityContext`
        dict (PR-F) for reconnect/handoff correlation.  ``None`` for clean
        terminal results or when continuity context is not applicable.
    """
    _posture = _normalise_posture_hint(source_runtime_posture)
    try:
        return SourceDispatchResult(
            dispatch_id=dispatch_id,
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            source_device_id=source_device_id,
            source_runtime_id=source_runtime_id,
            source_runtime_posture=_posture,
            mode=mode,
            selected_target=selected_target,
            success=success,
            result=result,
            execution_trace=execution_trace,
            takeover_result=takeover_result,
            governance_snapshot=governance_snapshot,
            policy_alignment=policy_alignment,
            mesh_session=mesh_session,
            errors=errors or [],
            decision_reason=decision_reason,
            continuity_context=continuity_context,
            metadata=metadata or {},
        )
    except Exception:
        return SourceDispatchResult(
            dispatch_id=dispatch_id,
            trace_id=trace_id,
            success=False,
            errors=["build_source_dispatch_result: construction error"],
        )


def build_source_dispatch_summary(
    *,
    result: Optional[SourceDispatchResult] = None,
    dispatch_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    source_device_id: Optional[str] = None,
    mode: Optional[SourceDispatchMode] = None,
    success: bool = False,
    decision_reason: Optional[str] = None,
    target_device_id: Optional[str] = None,
    error_count: int = 0,
    has_execution_trace: bool = False,
    has_takeover_result: bool = False,
    has_mesh_session: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
) -> SourceDispatchSummary:
    """Convenience factory for :class:`SourceDispatchSummary`.

    When ``result`` is provided its fields are used to populate defaults.
    Explicit keyword arguments take precedence over ``result`` fields.
    """
    try:
        r_dispatch_id = dispatch_id if dispatch_id is not None else (result.dispatch_id if result else None)
        r_trace = trace_id if trace_id is not None else (result.trace_id if result else None)
        r_task = task_id if task_id is not None else (result.task_id if result else None)
        r_session = session_id if session_id is not None else (result.session_id if result else None)
        r_src_device = source_device_id if source_device_id is not None else (result.source_device_id if result else None)
        r_mode = mode if mode is not None else (result.mode if result else SourceDispatchMode.unknown)
        r_success = success if result is None else result.success
        r_reason = decision_reason if decision_reason is not None else (result.decision_reason if result else None)
        r_target = target_device_id if target_device_id is not None else (
            result.selected_target.target_device_id if (result and result.selected_target) else None
        )
        r_err_count = error_count if result is None else len(result.errors)
        r_has_trace = has_execution_trace if result is None else (result.execution_trace is not None)
        r_has_takeover = has_takeover_result if result is None else (result.takeover_result is not None)
        r_has_mesh = has_mesh_session if result is None else (result.mesh_session is not None)
        r_ts = result.timestamp if result else time.time()
        return SourceDispatchSummary(
            dispatch_id=r_dispatch_id,
            trace_id=r_trace,
            task_id=r_task,
            session_id=r_session,
            source_device_id=r_src_device,
            mode=r_mode,
            success=r_success,
            decision_reason=r_reason,
            target_device_id=r_target,
            error_count=r_err_count,
            has_execution_trace=r_has_trace,
            has_takeover_result=r_has_takeover,
            has_mesh_session=r_has_mesh,
            timestamp=r_ts,
            metadata=metadata or {},
        )
    except Exception:
        return SourceDispatchSummary(
            mode=SourceDispatchMode.unknown,
            success=False,
        )


def failure_dispatch_result(
    *,
    dispatch_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    mode: SourceDispatchMode = SourceDispatchMode.unknown,
    reason: str = "dispatch_failed",
    metadata: Optional[Dict[str, Any]] = None,
) -> SourceDispatchResult:
    """Return a minimal failed :class:`SourceDispatchResult`.

    Convenience helper for error paths that need to return a valid result
    without populating any execution artefacts.
    """
    return SourceDispatchResult(
        dispatch_id=dispatch_id,
        trace_id=trace_id,
        task_id=task_id,
        session_id=session_id,
        mode=mode,
        success=False,
        errors=[reason],
        decision_reason=reason,
        metadata=metadata or {},
    )
