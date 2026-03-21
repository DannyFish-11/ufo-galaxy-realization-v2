"""contracts/cross_runtime_result_merge.py
==========================================
Cross-Runtime Result Merge Contract — PR-36.

This module defines the **canonical Cross-Runtime Result Merge Contract**: the
structured, serialisable representation of how results from local execution,
remote handoff execution, and staged/multi-device execution are represented,
merged, and explained.

It answers the architectural question:

    *"When work is executed across one or more runtimes, what canonical
    contract describes the resulting outputs, their provenance, and how
    they are merged into one coherent result?"*

These contracts are the result-side foundation that builds on:

- **PR-25** (:class:`~contracts.execution_trace.ExecutionTraceEnvelope`) —
  execution trace envelopes that provide per-unit trace references.
- **PR-27** (``RuntimeGovernanceSnapshot``) — governance posture captured at
  execution time.
- **PR-28** (``ExecutionPolicyAlignmentSurface``) — policy alignment context.
- **PR-33** (:class:`~contracts.mesh_session.MeshSession`) — mesh session that
  may coordinate staged dispatch.
- **PR-34** (:class:`~contracts.local_takeover_result.LocalTakeoverResult`) —
  the target-side result after adopting and executing a handoff.
- **PR-35** (:class:`~contracts.source_dispatch.SourceDispatchResult`) —
  the source-side result of a completed dispatch decision.

This module formalises:
- the role enum for result units (``RuntimeResultRole``);
- the status enum for result units (``RuntimeResultStatus``);
- the merge policy enum (``ResultMergePolicy``);
- the per-unit provenance record (``RuntimeResultProvenance``);
- the result unit (``RuntimeResultUnit``);
- the merge input container (``ResultMergeInput``);
- the merged result output (``MergedRuntimeResult``);
- the lightweight read-only summary (``ResultMergeSummary``);
- builder / adapter functions for all contracts.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Fully serialisable** — all contracts produce stable, round-trippable JSON
  via ``to_dict`` / ``to_json``.
- **Graceful defaults** — all fields beyond ``merge_id`` are optional; callers
  with partial context always produce a valid contract.
- **Stable field names** — downstream consumers can rely on all field names.
- **No UI semantics** — purely runtime/projection/coordinator use.

Usage::

    from contracts.cross_runtime_result_merge import (
        RuntimeResultUnit,
        RuntimeResultRole,
        ResultMergePolicy,
        MergedRuntimeResult,
        build_merged_runtime_result,
        from_local_takeover_result,
        from_source_dispatch_result,
        merge_runtime_results,
    )

    # Build a single-unit local result
    unit = from_local_takeover_result(takeover_result_dict, role="primary")
    merged = merge_runtime_results(
        result_units=[unit],
        merge_policy=ResultMergePolicy.primary_wins,
        trace_id="trace_abc",
    )
    payload = merged.to_dict()

See ``docs/CROSS_RUNTIME_RESULT_MERGE_CONTRACT.md`` for the full
specification.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# RuntimeResultRole — role of a result unit within the merge
# ---------------------------------------------------------------------------


class RuntimeResultRole(str, Enum):
    """Role of a :class:`RuntimeResultUnit` within a cross-runtime merge.

    source
        The unit originates from the source runtime that initiated dispatch.
    target
        The unit originates from a remote target runtime (handoff path).
    primary
        Designated as the primary / authoritative result among all units.
    support
        A support / auxiliary result that supplements the primary.
    fallback
        A fallback result used when the preferred path failed.
    partial
        A partial result produced when full execution was not possible.
    unknown
        Role could not be determined.
    """

    source = "source"
    target = "target"
    primary = "primary"
    support = "support"
    fallback = "fallback"
    partial = "partial"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# RuntimeResultStatus — execution outcome of a result unit
# ---------------------------------------------------------------------------


class RuntimeResultStatus(str, Enum):
    """Execution outcome of a :class:`RuntimeResultUnit`.

    succeeded
        Execution completed successfully.
    failed
        Execution completed with a failure or error.
    partial
        Execution produced a partial result (incomplete or degraded).
    blocked
        Execution was blocked before it started.
    skipped
        This unit was not executed (e.g. superseded by another unit).
    timeout
        Execution timed out before completion.
    unknown
        Status could not be determined.
    """

    succeeded = "succeeded"
    failed = "failed"
    partial = "partial"
    blocked = "blocked"
    skipped = "skipped"
    timeout = "timeout"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# ResultMergePolicy — strategy for merging multiple result units
# ---------------------------------------------------------------------------


class ResultMergePolicy(str, Enum):
    """Strategy for merging multiple :class:`RuntimeResultUnit` objects.

    primary_wins
        The unit with ``role=primary`` (or the first succeeded unit) becomes
        the authoritative merged output.  Other units contribute provenance
        only.
    first_success
        The first succeeded unit becomes the merged output.
    last_success
        The last succeeded unit becomes the merged output.
    all_required
        All units must succeed; any failure marks the merge as failed.
    best_effort
        Collect all succeeded units; partial success is acceptable.
    fallback_chain
        Try units in order; use the first that succeeds.
    unknown
        Merge policy could not be determined.
    """

    primary_wins = "primary_wins"
    first_success = "first_success"
    last_success = "last_success"
    all_required = "all_required"
    best_effort = "best_effort"
    fallback_chain = "fallback_chain"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# RuntimeResultProvenance — provenance metadata for a single result unit
# ---------------------------------------------------------------------------


class RuntimeResultProvenance(BaseModel):
    """Per-unit provenance metadata for a :class:`RuntimeResultUnit`.

    Fields
    ------
    device_id
        Identifier of the device that produced this result unit.
    runtime_id
        Identifier of the runtime instance that produced this result unit.
    session_id
        Session identifier used during execution.
    trace_id
        Distributed trace identifier for this unit.
    task_id
        Task identifier for this unit.
    execution_path
        Human-readable description of the execution path used
        (e.g. ``"local"``, ``"remote_handoff"``, ``"staged_mesh"``).
    governance_snapshot_ref
        Reference identifier of the governance snapshot captured at execution
        time (PR-27).  ``None`` when not captured.
    policy_alignment_ref
        Reference identifier of the policy alignment surface (PR-28).
        ``None`` when not captured.
    execution_trace_ref
        Reference identifier of the execution trace envelope (PR-25).
        ``None`` when not produced.
    metadata
        Arbitrary extension metadata.
    """

    device_id: Optional[str] = Field(
        default=None,
        description="Device that produced this result unit.",
    )
    runtime_id: Optional[str] = Field(
        default=None,
        description="Runtime instance that produced this result unit.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session identifier used during execution.",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Distributed trace identifier for this unit.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Task identifier for this unit.",
    )
    execution_path: Optional[str] = Field(
        default=None,
        description="Human-readable execution path (local / remote_handoff / staged_mesh / etc.).",
    )
    governance_snapshot_ref: Optional[str] = Field(
        default=None,
        description="Reference ID of the governance snapshot (PR-27), if captured.",
    )
    policy_alignment_ref: Optional[str] = Field(
        default=None,
        description="Reference ID of the policy alignment surface (PR-28), if captured.",
    )
    execution_trace_ref: Optional[str] = Field(
        default=None,
        description="Reference ID of the execution trace envelope (PR-25), if produced.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extension metadata.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# RuntimeResultUnit — canonical result from a single runtime participant
# ---------------------------------------------------------------------------


class RuntimeResultUnit(BaseModel):
    """Canonical result unit produced by a single runtime participant.

    A result unit represents the output from one runtime (local, remote target,
    or mesh participant) within a cross-runtime execution.  One or more result
    units are collected into a :class:`ResultMergeInput` and merged into a
    :class:`MergedRuntimeResult`.

    Fields
    ------
    result_unit_id
        Unique identifier for this result unit (UUID4).
    device_id
        Identifier of the device that produced this result.  ``None`` for
        local-only results where device context is unavailable.
    runtime_id
        Identifier of the runtime instance.  ``None`` when unavailable.
    role
        The :class:`RuntimeResultRole` this unit plays within the merge.
    status
        The :class:`RuntimeResultStatus` of this unit's execution.
    output
        The raw execution output dict.  ``None`` when no output was produced.
    error
        Error description when execution failed.  ``None`` on success.
    reason
        Human-readable reason for the outcome (failure reason, skip reason,
        or success confirmation).  ``None`` when not applicable.
    trace_id
        Distributed trace identifier.
    task_id
        Task identifier.
    session_id
        Session identifier.
    mesh_session_id
        Mesh-level session identifier (PR-33), if applicable.
    execution_trace
        Serialised :class:`~contracts.execution_trace.ExecutionTraceEnvelope`
        dict (PR-25), if available.
    governance_snapshot
        Serialised ``RuntimeGovernanceSnapshot`` dict (PR-27), if available.
    policy_alignment
        Serialised ``ExecutionPolicyAlignmentSurface`` dict (PR-28), if
        available.
    provenance
        Structured :class:`RuntimeResultProvenance` record for this unit.
    timestamp
        Unix timestamp when this result unit was produced.
    metadata
        Arbitrary extension metadata.
    """

    result_unit_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this result unit (UUID4).",
    )
    device_id: Optional[str] = Field(
        default=None,
        description="Device that produced this result unit.",
    )
    runtime_id: Optional[str] = Field(
        default=None,
        description="Runtime instance identifier.",
    )
    role: RuntimeResultRole = Field(
        default=RuntimeResultRole.unknown,
        description="Role of this unit within the cross-runtime merge.",
    )
    status: RuntimeResultStatus = Field(
        default=RuntimeResultStatus.unknown,
        description="Execution outcome of this unit.",
    )
    output: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Raw execution output dict.  None when no output was produced.",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error description when execution failed.  None on success.",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Human-readable reason for the outcome.",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Distributed trace identifier.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Task identifier.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session identifier.",
    )
    mesh_session_id: Optional[str] = Field(
        default=None,
        description="Mesh-level session identifier (PR-33), if applicable.",
    )
    execution_trace: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialised ExecutionTraceEnvelope dict (PR-25), if available.",
    )
    governance_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialised RuntimeGovernanceSnapshot dict (PR-27), if available.",
    )
    policy_alignment: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialised ExecutionPolicyAlignmentSurface dict (PR-28), if available.",
    )
    provenance: Optional[RuntimeResultProvenance] = Field(
        default=None,
        description="Structured provenance record for this result unit.",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix timestamp when this result unit was produced.",
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
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeResultUnit":
        """Construct from a dictionary.  Tolerates unknown extra fields."""
        return cls.model_validate(data)

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# ResultMergeInput — container for units to be merged
# ---------------------------------------------------------------------------


class ResultMergeInput(BaseModel):
    """Container of :class:`RuntimeResultUnit` objects to be merged.

    Wraps the inputs required to produce a :class:`MergedRuntimeResult`.

    Fields
    ------
    merge_id
        Unique identifier for this merge operation (UUID4).
    trace_id
        Distributed trace identifier for the merge operation.
    task_id
        Task identifier.
    session_id
        Session identifier.
    mesh_session_id
        Mesh-level session identifier (PR-33), if applicable.
    result_units
        List of :class:`RuntimeResultUnit` objects to be merged.
    merge_policy
        The :class:`ResultMergePolicy` to apply.
    primary_result_unit_id
        Identifier of the unit designated as primary, if explicitly known.
        Used by ``primary_wins`` policy.
    execution_trace_refs
        Reference identifiers of execution trace envelopes (PR-25) involved
        in this merge.
    governance_snapshot_refs
        Reference identifiers of governance snapshots (PR-27) involved.
    policy_alignment_refs
        Reference identifiers of policy alignment surfaces (PR-28) involved.
    merge_reason
        Human-readable reason or context for this merge operation.
    metadata
        Arbitrary extension metadata.
    """

    merge_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this merge operation (UUID4).",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Distributed trace identifier for this merge.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Task identifier.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session identifier.",
    )
    mesh_session_id: Optional[str] = Field(
        default=None,
        description="Mesh-level session identifier (PR-33), if applicable.",
    )
    result_units: List[RuntimeResultUnit] = Field(
        default_factory=list,
        description="List of RuntimeResultUnit objects to merge.",
    )
    merge_policy: ResultMergePolicy = Field(
        default=ResultMergePolicy.primary_wins,
        description="Merge policy to apply when combining result units.",
    )
    primary_result_unit_id: Optional[str] = Field(
        default=None,
        description="Explicit primary unit ID for primary_wins policy.",
    )
    execution_trace_refs: List[str] = Field(
        default_factory=list,
        description="Execution trace envelope reference IDs (PR-25) for this merge.",
    )
    governance_snapshot_refs: List[str] = Field(
        default_factory=list,
        description="Governance snapshot reference IDs (PR-27) for this merge.",
    )
    policy_alignment_refs: List[str] = Field(
        default_factory=list,
        description="Policy alignment surface reference IDs (PR-28) for this merge.",
    )
    merge_reason: Optional[str] = Field(
        default=None,
        description="Human-readable reason or context for this merge.",
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
    def from_dict(cls, data: Dict[str, Any]) -> "ResultMergeInput":
        return cls.model_validate(data)

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# MergedRuntimeResult — canonical merged result from cross-runtime execution
# ---------------------------------------------------------------------------


class MergedRuntimeResult(BaseModel):
    """Canonical merged result from cross-runtime execution.

    This is the top-level contract produced after applying a
    :class:`ResultMergePolicy` to a set of :class:`RuntimeResultUnit` objects.
    It answers: *"What is the final, explainable output of a cross-runtime
    execution, and how were the individual runtime results combined?"*

    Fields
    ------
    merge_id
        Unique identifier for this merged result (UUID4).  Matches the
        :attr:`ResultMergeInput.merge_id` when built from an input.
    trace_id
        Distributed trace identifier for the merge.
    task_id
        Task identifier.
    session_id
        Session identifier.
    mesh_session_id
        Mesh-level session identifier (PR-33), if applicable.
    result_units
        List of :class:`RuntimeResultUnit` objects that were merged.
    primary_result_unit_id
        Identifier of the unit that was selected as the primary result.
        ``None`` when no primary could be selected.
    merge_policy
        The :class:`ResultMergePolicy` that was applied.
    merged_output
        The canonical merged output dict.  This is the authoritative result
        derived from the ``primary_result_unit_id`` or policy logic.  ``None``
        when no output could be determined.
    success
        ``True`` when the merge produced a usable result.
    partial
        ``True`` when the result is present but incomplete (e.g. some units
        failed but the policy accepted partial output).
    fallback_applied
        ``True`` when a fallback unit was used as the primary result because
        the preferred path failed.
    conflicts
        List of human-readable conflict descriptions when result units
        disagree (e.g. different outputs from parallel remote executions).
    execution_trace_refs
        Reference identifiers of execution trace envelopes (PR-25) involved.
    governance_snapshot_refs
        Reference identifiers of governance snapshots (PR-27) involved.
    policy_alignment_refs
        Reference identifiers of policy alignment surfaces (PR-28) involved.
    merge_reason
        Human-readable reason or context for this merge.
    errors
        List of error/warning strings.  Empty on clean success.
    timestamp
        Unix timestamp when this merged result was produced.
    metadata
        Arbitrary extension metadata.
    """

    merge_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this merged result (UUID4).",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Distributed trace identifier for the merge.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Task identifier.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session identifier.",
    )
    mesh_session_id: Optional[str] = Field(
        default=None,
        description="Mesh-level session identifier (PR-33), if applicable.",
    )
    result_units: List[RuntimeResultUnit] = Field(
        default_factory=list,
        description="Result units that were merged.",
    )
    primary_result_unit_id: Optional[str] = Field(
        default=None,
        description="Identifier of the unit selected as the primary result.",
    )
    merge_policy: ResultMergePolicy = Field(
        default=ResultMergePolicy.primary_wins,
        description="Merge policy that was applied.",
    )
    merged_output: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Canonical merged output dict.  None when no output could be determined.",
    )
    success: bool = Field(
        default=False,
        description="True when the merge produced a usable result.",
    )
    partial: bool = Field(
        default=False,
        description="True when the result is present but incomplete.",
    )
    fallback_applied: bool = Field(
        default=False,
        description="True when a fallback unit was used as the primary result.",
    )
    conflicts: List[str] = Field(
        default_factory=list,
        description="Human-readable conflict descriptions when units disagree.",
    )
    execution_trace_refs: List[str] = Field(
        default_factory=list,
        description="Execution trace reference IDs (PR-25) involved.",
    )
    governance_snapshot_refs: List[str] = Field(
        default_factory=list,
        description="Governance snapshot reference IDs (PR-27) involved.",
    )
    policy_alignment_refs: List[str] = Field(
        default_factory=list,
        description="Policy alignment reference IDs (PR-28) involved.",
    )
    merge_reason: Optional[str] = Field(
        default=None,
        description="Human-readable reason or context for this merge.",
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Error/warning strings.  Empty on clean success.",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix timestamp when this merged result was produced.",
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
    def from_dict(cls, data: Dict[str, Any]) -> "MergedRuntimeResult":
        """Construct from a dictionary.  Tolerates unknown extra fields."""
        return cls.model_validate(data)

    def to_compact_summary(self) -> Dict[str, Any]:
        """Return a compact human-readable summary dict."""
        return {
            "merge_id": self.merge_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "merge_policy": (
                self.merge_policy.value
                if isinstance(self.merge_policy, ResultMergePolicy)
                else str(self.merge_policy)
            ),
            "success": self.success,
            "partial": self.partial,
            "fallback_applied": self.fallback_applied,
            "unit_count": len(self.result_units),
            "primary_result_unit_id": self.primary_result_unit_id,
            "conflict_count": len(self.conflicts),
            "error_count": len(self.errors),
            "has_merged_output": self.merged_output is not None,
            "merge_reason": self.merge_reason,
            "timestamp": self.timestamp,
        }

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# ResultMergeSummary — lightweight read-only merge summary
# ---------------------------------------------------------------------------


class ResultMergeSummary(BaseModel):
    """Lightweight read-only summary of a cross-runtime merge result.

    Suitable for projection payloads, debug surfaces, and trace metadata.
    Omits large raw payloads; use :class:`MergedRuntimeResult` for the full
    structured record.

    Fields
    ------
    summary_id
        Unique identifier for this summary (UUID4).
    merge_id
        The merge operation identifier.
    trace_id
        Distributed trace identifier.
    task_id
        Task identifier.
    session_id
        Session identifier.
    merge_policy
        The :class:`ResultMergePolicy` that was applied.
    success
        ``True`` when the merge produced a usable result.
    partial
        ``True`` when the result is present but incomplete.
    fallback_applied
        ``True`` when a fallback unit was used.
    unit_count
        Total number of result units that were merged.
    succeeded_unit_count
        Number of units that reported success.
    failed_unit_count
        Number of units that reported failure.
    conflict_count
        Number of merge conflicts detected.
    error_count
        Number of error/warning strings collected.
    has_merged_output
        Whether a merged output dict was produced.
    merge_reason
        Human-readable reason for this merge.
    timestamp
        Unix timestamp of the merged result.
    metadata
        Arbitrary extension metadata.
    """

    summary_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this summary (UUID4).",
    )
    merge_id: Optional[str] = Field(
        default=None,
        description="Merge operation identifier.",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Distributed trace identifier.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Task identifier.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session identifier.",
    )
    merge_policy: ResultMergePolicy = Field(
        default=ResultMergePolicy.unknown,
        description="Merge policy that was applied.",
    )
    success: bool = Field(
        default=False,
        description="True when the merge produced a usable result.",
    )
    partial: bool = Field(
        default=False,
        description="True when the result is present but incomplete.",
    )
    fallback_applied: bool = Field(
        default=False,
        description="True when a fallback unit was used.",
    )
    unit_count: int = Field(
        default=0,
        description="Total number of result units merged.",
    )
    succeeded_unit_count: int = Field(
        default=0,
        description="Number of succeeded result units.",
    )
    failed_unit_count: int = Field(
        default=0,
        description="Number of failed result units.",
    )
    conflict_count: int = Field(
        default=0,
        description="Number of merge conflicts detected.",
    )
    error_count: int = Field(
        default=0,
        description="Number of error/warning strings.",
    )
    has_merged_output: bool = Field(
        default=False,
        description="Whether a merged output dict was produced.",
    )
    merge_reason: Optional[str] = Field(
        default=None,
        description="Human-readable reason for this merge.",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix timestamp of the merged result.",
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
    def from_dict(cls, data: Dict[str, Any]) -> "ResultMergeSummary":
        return cls.model_validate(data)

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# Adapter / builder functions
# ---------------------------------------------------------------------------


def from_local_takeover_result(
    takeover_result: Any,
    *,
    role: RuntimeResultRole = RuntimeResultRole.target,
    mesh_session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeResultUnit:
    """Build a :class:`RuntimeResultUnit` from a LocalTakeoverResult (PR-34).

    Normalises the result of a target-side takeover into the canonical
    result unit contract.

    Parameters
    ----------
    takeover_result:
        A :class:`~contracts.local_takeover_result.LocalTakeoverResult`
        instance, or a dict representation of one.
    role:
        The role to assign to this unit (defaults to ``target``).
    mesh_session_id:
        Optional mesh-level session identifier (PR-33).
    metadata:
        Additional metadata to attach to the unit.

    Returns
    -------
    RuntimeResultUnit
    """
    try:
        if hasattr(takeover_result, "to_dict"):
            d: Dict[str, Any] = takeover_result.to_dict()
        elif isinstance(takeover_result, dict):
            d = takeover_result
        else:
            d = {}

        _success = bool(d.get("success", False))
        _status_raw = d.get("status", "unknown")
        if _status_raw == "succeeded" or (_status_raw not in {s.value for s in RuntimeResultStatus} and _success):
            _status = RuntimeResultStatus.succeeded
        elif _status_raw in {s.value for s in RuntimeResultStatus}:
            _status = RuntimeResultStatus(_status_raw)
        else:
            _status = RuntimeResultStatus.failed if not _success else RuntimeResultStatus.succeeded

        _trace_id: Optional[str] = d.get("trace_id")
        _task_id: Optional[str] = d.get("task_id")
        _session_id: Optional[str] = d.get("session_id")
        _device_id: Optional[str] = (
            (d.get("metadata") or {}).get("device_id")
            or (d.get("session_context") or {}).get("device_id")
        )
        _runtime_id: Optional[str] = d.get("runtime_session_id")

        _exec_trace: Optional[Dict[str, Any]] = d.get("execution_trace")
        _gov: Optional[Dict[str, Any]] = d.get("governance_snapshot")
        _policy: Optional[Dict[str, Any]] = d.get("policy_alignment")

        _errors = list(d.get("errors") or [])
        _reason: Optional[str] = d.get("reason")

        _provenance = RuntimeResultProvenance(
            device_id=_device_id,
            runtime_id=_runtime_id,
            session_id=_session_id,
            trace_id=_trace_id,
            task_id=_task_id,
            execution_path="remote_handoff",
            governance_snapshot_ref=(
                str(_gov.get("snapshot_id", "")) if _gov and _gov.get("snapshot_id") else None
            ),
            policy_alignment_ref=(
                str(_policy.get("alignment_id", "")) if _policy and _policy.get("alignment_id") else None
            ),
            execution_trace_ref=(
                str(_exec_trace.get("trace_id", "")) if _exec_trace and _exec_trace.get("trace_id") else None
            ),
            metadata=dict(metadata) if metadata else {},
        )

        return RuntimeResultUnit(
            device_id=_device_id,
            runtime_id=_runtime_id,
            role=role,
            status=_status,
            output=d.get("result"),
            error=_errors[0] if _errors and not _success else None,
            reason=_reason,
            trace_id=_trace_id,
            task_id=_task_id,
            session_id=_session_id,
            mesh_session_id=mesh_session_id,
            execution_trace=_exec_trace,
            governance_snapshot=_gov,
            policy_alignment=_policy,
            provenance=_provenance,
            metadata=dict(metadata) if metadata else {},
        )
    except Exception as _e:  # noqa: BLE001
        _logger.debug("from_local_takeover_result: adapter error: %s", _e)
        return RuntimeResultUnit(
            role=role,
            status=RuntimeResultStatus.failed,
            error=f"from_local_takeover_result: {_e}",
            reason="adapter_error",
            metadata=dict(metadata) if metadata else {},
        )


def from_source_dispatch_result(
    dispatch_result: Any,
    *,
    role: RuntimeResultRole = RuntimeResultRole.source,
    mesh_session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeResultUnit:
    """Build a :class:`RuntimeResultUnit` from a SourceDispatchResult (PR-35).

    Normalises the result of a source-side dispatch into the canonical
    result unit contract.

    Parameters
    ----------
    dispatch_result:
        A :class:`~contracts.source_dispatch.SourceDispatchResult` instance,
        or a dict representation of one.
    role:
        The role to assign to this unit (defaults to ``source``).
    mesh_session_id:
        Optional mesh-level session identifier (PR-33).
    metadata:
        Additional metadata to attach to the unit.

    Returns
    -------
    RuntimeResultUnit
    """
    try:
        if hasattr(dispatch_result, "to_dict"):
            d: Dict[str, Any] = dispatch_result.to_dict()
        elif isinstance(dispatch_result, dict):
            d = dispatch_result
        else:
            d = {}

        _success = bool(d.get("success", False))
        _status = RuntimeResultStatus.succeeded if _success else RuntimeResultStatus.failed

        _mode = d.get("mode", "unknown")
        _trace_id: Optional[str] = d.get("trace_id")
        _task_id: Optional[str] = d.get("task_id")
        _session_id: Optional[str] = d.get("session_id")
        _device_id: Optional[str] = d.get("source_device_id")
        _runtime_id: Optional[str] = d.get("source_runtime_id")

        _exec_trace: Optional[Dict[str, Any]] = d.get("execution_trace")
        _gov: Optional[Dict[str, Any]] = d.get("governance_snapshot")
        _policy: Optional[Dict[str, Any]] = d.get("policy_alignment")

        _errors = list(d.get("errors") or [])
        _reason: Optional[str] = d.get("decision_reason")

        # If a takeover result is present, extract it as a nested reference
        _takeover: Optional[Dict[str, Any]] = d.get("takeover_result")
        _mesh_ref: Optional[str] = None
        if d.get("mesh_session"):
            _mesh_ref = (d["mesh_session"] or {}).get("session_id") or mesh_session_id
        _mesh_id = _mesh_ref or mesh_session_id

        _provenance = RuntimeResultProvenance(
            device_id=_device_id,
            runtime_id=_runtime_id,
            session_id=_session_id,
            trace_id=_trace_id,
            task_id=_task_id,
            execution_path=str(_mode),
            governance_snapshot_ref=(
                str(_gov.get("snapshot_id", "")) if _gov and _gov.get("snapshot_id") else None
            ),
            policy_alignment_ref=(
                str(_policy.get("alignment_id", "")) if _policy and _policy.get("alignment_id") else None
            ),
            execution_trace_ref=(
                str(_exec_trace.get("trace_id", "")) if _exec_trace and _exec_trace.get("trace_id") else None
            ),
            metadata=dict(metadata) if metadata else {},
        )

        # Build the unit output — prefer the nested takeover output if present
        _output: Optional[Dict[str, Any]] = d.get("result") or (_takeover or {}).get("result")

        return RuntimeResultUnit(
            device_id=_device_id,
            runtime_id=_runtime_id,
            role=role,
            status=_status,
            output=_output,
            error=_errors[0] if _errors and not _success else None,
            reason=_reason,
            trace_id=_trace_id,
            task_id=_task_id,
            session_id=_session_id,
            mesh_session_id=_mesh_id,
            execution_trace=_exec_trace,
            governance_snapshot=_gov,
            policy_alignment=_policy,
            provenance=_provenance,
            metadata=dict(metadata) if metadata else {},
        )
    except Exception as _e:  # noqa: BLE001
        _logger.debug("from_source_dispatch_result: adapter error: %s", _e)
        return RuntimeResultUnit(
            role=role,
            status=RuntimeResultStatus.failed,
            error=f"from_source_dispatch_result: {_e}",
            reason="adapter_error",
            metadata=dict(metadata) if metadata else {},
        )


def from_execution_output(
    execution_output: Optional[Dict[str, Any]],
    *,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    device_id: Optional[str] = None,
    runtime_id: Optional[str] = None,
    role: RuntimeResultRole = RuntimeResultRole.primary,
    governance_snapshot: Optional[Dict[str, Any]] = None,
    policy_alignment: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeResultUnit:
    """Build a :class:`RuntimeResultUnit` from raw execution output.

    Normalises the output dict returned by ``OpenClawd._run_execution()``-style
    callers into the canonical result unit contract.

    Parameters
    ----------
    execution_output:
        Dict returned by the local execution path; may be ``None``.
    trace_id:
        Distributed trace identifier.
    task_id:
        Task identifier.
    session_id:
        Session identifier.
    device_id:
        Device identifier for the executing runtime.
    runtime_id:
        Runtime instance identifier.
    role:
        The role to assign to this unit (defaults to ``primary``).
    governance_snapshot:
        Serialised RuntimeGovernanceSnapshot dict (PR-27), if available.
    policy_alignment:
        Serialised ExecutionPolicyAlignmentSurface dict (PR-28), if available.
    metadata:
        Additional metadata to attach to the unit.

    Returns
    -------
    RuntimeResultUnit
    """
    try:
        out = execution_output or {}
        _success = bool(out.get("success", False))
        _action = out.get("action_taken", "none")
        _skipped = out.get("skipped_reason")

        if _action == "error":
            _status = RuntimeResultStatus.failed
        elif _skipped and _skipped.startswith("readiness_gate"):
            _status = RuntimeResultStatus.blocked
        elif _skipped:
            _status = RuntimeResultStatus.skipped
        elif _success:
            _status = RuntimeResultStatus.succeeded
        else:
            _status = RuntimeResultStatus.failed

        _exec_trace: Optional[Dict[str, Any]] = None
        _raw_trace = out.get("execution_trace")
        if _raw_trace is not None:
            if hasattr(_raw_trace, "to_dict"):
                _exec_trace = _raw_trace.to_dict()
            elif isinstance(_raw_trace, dict):
                _exec_trace = _raw_trace

        _reason: Optional[str] = None if _success else (_skipped or "execution_failed")

        _provenance = RuntimeResultProvenance(
            device_id=device_id,
            runtime_id=runtime_id,
            session_id=session_id,
            trace_id=trace_id,
            task_id=task_id,
            execution_path="local",
            governance_snapshot_ref=(
                str((governance_snapshot or {}).get("snapshot_id", ""))
                if governance_snapshot and (governance_snapshot or {}).get("snapshot_id")
                else None
            ),
            policy_alignment_ref=(
                str((policy_alignment or {}).get("alignment_id", ""))
                if policy_alignment and (policy_alignment or {}).get("alignment_id")
                else None
            ),
            execution_trace_ref=(
                str(_exec_trace.get("trace_id", "")) if _exec_trace and _exec_trace.get("trace_id") else None
            ),
            metadata=dict(metadata) if metadata else {},
        )

        return RuntimeResultUnit(
            device_id=device_id,
            runtime_id=runtime_id,
            role=role,
            status=_status,
            output=out if out else None,
            error=_skipped if not _success else None,
            reason=_reason,
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            execution_trace=_exec_trace,
            governance_snapshot=governance_snapshot,
            policy_alignment=policy_alignment,
            provenance=_provenance,
            metadata=dict(metadata) if metadata else {},
        )
    except Exception as _e:  # noqa: BLE001
        _logger.debug("from_execution_output: adapter error: %s", _e)
        return RuntimeResultUnit(
            role=role,
            status=RuntimeResultStatus.failed,
            error=f"from_execution_output: {_e}",
            reason="adapter_error",
            metadata=dict(metadata) if metadata else {},
        )


def build_merged_runtime_result(
    *,
    result_units: Optional[List[RuntimeResultUnit]] = None,
    merge_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    mesh_session_id: Optional[str] = None,
    merge_policy: ResultMergePolicy = ResultMergePolicy.primary_wins,
    primary_result_unit_id: Optional[str] = None,
    merged_output: Optional[Dict[str, Any]] = None,
    success: bool = False,
    partial: bool = False,
    fallback_applied: bool = False,
    conflicts: Optional[List[str]] = None,
    execution_trace_refs: Optional[List[str]] = None,
    governance_snapshot_refs: Optional[List[str]] = None,
    policy_alignment_refs: Optional[List[str]] = None,
    merge_reason: Optional[str] = None,
    errors: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> MergedRuntimeResult:
    """Convenience factory for :class:`MergedRuntimeResult`.

    All parameters are optional; omitted fields fall back to safe defaults.
    This builder never raises.

    Parameters
    ----------
    result_units:
        List of :class:`RuntimeResultUnit` objects that were merged.
    merge_id:
        Override the merge identifier (UUID4 generated if not provided).
    trace_id, task_id, session_id, mesh_session_id:
        Correlation identifiers.
    merge_policy:
        The merge policy applied.
    primary_result_unit_id:
        The unit selected as primary.
    merged_output:
        The canonical merged output dict.
    success:
        Whether the merge produced a usable result.
    partial:
        Whether the result is incomplete.
    fallback_applied:
        Whether a fallback unit was used.
    conflicts:
        List of conflict descriptions.
    execution_trace_refs, governance_snapshot_refs, policy_alignment_refs:
        Reference IDs for cross-cutting concerns.
    merge_reason:
        Human-readable merge context.
    errors:
        Error/warning strings.
    metadata:
        Arbitrary extension metadata.

    Returns
    -------
    MergedRuntimeResult
    """
    try:
        return MergedRuntimeResult(
            merge_id=merge_id or str(uuid.uuid4()),
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            mesh_session_id=mesh_session_id,
            result_units=list(result_units) if result_units else [],
            primary_result_unit_id=primary_result_unit_id,
            merge_policy=merge_policy,
            merged_output=merged_output,
            success=success,
            partial=partial,
            fallback_applied=fallback_applied,
            conflicts=list(conflicts) if conflicts else [],
            execution_trace_refs=list(execution_trace_refs) if execution_trace_refs else [],
            governance_snapshot_refs=list(governance_snapshot_refs) if governance_snapshot_refs else [],
            policy_alignment_refs=list(policy_alignment_refs) if policy_alignment_refs else [],
            merge_reason=merge_reason,
            errors=list(errors) if errors else [],
            metadata=dict(metadata) if metadata else {},
        )
    except Exception as _e:  # noqa: BLE001
        _logger.debug("build_merged_runtime_result: construction error: %s", _e)
        return MergedRuntimeResult(
            merge_id=merge_id or str(uuid.uuid4()),
            trace_id=trace_id,
            success=False,
            errors=["build_merged_runtime_result: construction error"],
        )


def merge_runtime_results(
    result_units: Optional[List[RuntimeResultUnit]] = None,
    *,
    merge_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    mesh_session_id: Optional[str] = None,
    merge_policy: ResultMergePolicy = ResultMergePolicy.primary_wins,
    primary_result_unit_id: Optional[str] = None,
    merge_reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> MergedRuntimeResult:
    """Apply a merge policy to a list of result units and return a merged result.

    This is the canonical merge entry point.  It evaluates the given
    :class:`ResultMergePolicy` against the provided units and selects the
    primary output, marks partial/fallback states, and collects any conflicts.

    Parameters
    ----------
    result_units:
        List of :class:`RuntimeResultUnit` objects to merge.
    merge_id:
        Optional override for the merge identifier.
    trace_id, task_id, session_id, mesh_session_id:
        Correlation identifiers propagated from the merge context.
    merge_policy:
        The :class:`ResultMergePolicy` to apply.
    primary_result_unit_id:
        Explicit primary unit override for ``primary_wins`` policy.
    merge_reason:
        Human-readable context for the merge.
    metadata:
        Arbitrary extension metadata.

    Returns
    -------
    MergedRuntimeResult
    """
    try:
        units: List[RuntimeResultUnit] = list(result_units) if result_units else []
        _id = merge_id or str(uuid.uuid4())
        _errors: List[str] = []
        _conflicts: List[str] = []
        _fallback_applied = False
        _partial = False
        _success = False
        _primary_unit_id: Optional[str] = primary_result_unit_id
        _merged_output: Optional[Dict[str, Any]] = None

        # Collect refs from units
        _exec_trace_refs: List[str] = []
        _gov_refs: List[str] = []
        _policy_refs: List[str] = []
        for u in units:
            if u.provenance:
                if u.provenance.execution_trace_ref:
                    _exec_trace_refs.append(u.provenance.execution_trace_ref)
                if u.provenance.governance_snapshot_ref:
                    _gov_refs.append(u.provenance.governance_snapshot_ref)
                if u.provenance.policy_alignment_ref:
                    _policy_refs.append(u.provenance.policy_alignment_ref)

        succeeded_units = [u for u in units if u.status == RuntimeResultStatus.succeeded]
        failed_units = [u for u in units if u.status == RuntimeResultStatus.failed]
        fallback_units = [u for u in units if u.role == RuntimeResultRole.fallback]

        if not units:
            return build_merged_runtime_result(
                merge_id=_id,
                trace_id=trace_id,
                task_id=task_id,
                session_id=session_id,
                mesh_session_id=mesh_session_id,
                merge_policy=merge_policy,
                success=False,
                errors=["no_result_units_provided"],
                merge_reason=merge_reason or "empty_merge",
                metadata=metadata,
            )

        if merge_policy == ResultMergePolicy.primary_wins:
            # Find explicit primary unit or first succeeded primary/source unit
            _primary: Optional[RuntimeResultUnit] = None
            if _primary_unit_id:
                _primary = next((u for u in units if u.result_unit_id == _primary_unit_id), None)
            if _primary is None:
                _primary = next(
                    (u for u in succeeded_units if u.role in (RuntimeResultRole.primary, RuntimeResultRole.source)),
                    None,
                )
            if _primary is None:
                # Try non-fallback succeeded units before falling back
                non_fallback_succeeded = [
                    u for u in succeeded_units if u.role != RuntimeResultRole.fallback
                ]
                _primary = non_fallback_succeeded[0] if non_fallback_succeeded else None
            if _primary is None:
                # Use a succeeded fallback unit if available, and mark fallback_applied
                _primary = next(
                    (u for u in succeeded_units if u.role == RuntimeResultRole.fallback), None
                )
                if _primary:
                    _fallback_applied = True
            if _primary is None and fallback_units:
                _primary = next((u for u in fallback_units if u.status == RuntimeResultStatus.succeeded), None)
                if _primary:
                    _fallback_applied = True
            if _primary:
                _merged_output = _primary.output
                _success = True
                _primary_unit_id = _primary.result_unit_id
                if failed_units:
                    _partial = True
            else:
                _success = False
                _errors.append("no_succeeded_unit_found")

        elif merge_policy == ResultMergePolicy.first_success:
            _primary = succeeded_units[0] if succeeded_units else None
            if _primary:
                _merged_output = _primary.output
                _success = True
                _primary_unit_id = _primary.result_unit_id
                if len(failed_units) > 0:
                    _partial = True
            else:
                _success = False
                _errors.append("no_succeeded_unit_found")

        elif merge_policy == ResultMergePolicy.last_success:
            _primary = succeeded_units[-1] if succeeded_units else None
            if _primary:
                _merged_output = _primary.output
                _success = True
                _primary_unit_id = _primary.result_unit_id
                if len(failed_units) > 0:
                    _partial = True
            else:
                _success = False
                _errors.append("no_succeeded_unit_found")

        elif merge_policy == ResultMergePolicy.all_required:
            if failed_units:
                _success = False
                _errors.extend(
                    f"unit_failed:{u.result_unit_id}:{u.error or u.reason}" for u in failed_units
                )
            else:
                _success = True
                _primary = succeeded_units[0] if succeeded_units else None
                if _primary:
                    _merged_output = _primary.output
                    _primary_unit_id = _primary.result_unit_id

        elif merge_policy == ResultMergePolicy.best_effort:
            if succeeded_units:
                _primary = succeeded_units[0]
                _merged_output = _primary.output
                _success = True
                _primary_unit_id = _primary.result_unit_id
                if failed_units:
                    _partial = True
                    _errors.extend(
                        f"unit_failed:{u.result_unit_id}:{u.error or u.reason}" for u in failed_units
                    )
            else:
                _success = False
                _partial = True
                _errors.append("all_units_failed")

        elif merge_policy == ResultMergePolicy.fallback_chain:
            # Try units in order until one succeeds
            _primary = None
            for _u in units:
                if _u.status == RuntimeResultStatus.succeeded:
                    _primary = _u
                    break
                if _u.role == RuntimeResultRole.fallback and _u.status == RuntimeResultStatus.succeeded:
                    _primary = _u
                    _fallback_applied = True
                    break
            if _primary:
                _merged_output = _primary.output
                _success = True
                _primary_unit_id = _primary.result_unit_id
                if any(u != _primary for u in failed_units):
                    _partial = True
            else:
                # Attempt fallback units explicitly
                _primary = next(
                    (u for u in fallback_units if u.status == RuntimeResultStatus.succeeded), None
                )
                if _primary:
                    _merged_output = _primary.output
                    _success = True
                    _primary_unit_id = _primary.result_unit_id
                    _fallback_applied = True
                else:
                    _success = False
                    _errors.append("fallback_chain_exhausted")

        else:
            # unknown — default to first_success
            _primary = succeeded_units[0] if succeeded_units else None
            if _primary:
                _merged_output = _primary.output
                _success = True
                _primary_unit_id = _primary.result_unit_id
            else:
                _success = False
                _errors.append("unknown_policy_no_succeeded_unit")

        # Detect conflicts: multiple succeeded units with differing outputs.
        # Excluded policies:
        #   - all_required: expects all units to agree; divergence is a
        #     failure, not a conflict, and is captured in errors above.
        #   - best_effort: intentionally collects all outputs without
        #     expecting them to match; the caller handles diversity.
        # Note: JSON serialisation is used for comparison.  For very large
        # outputs or many units this may be expensive; consider hashing if
        # performance becomes a concern.
        if len(succeeded_units) > 1 and merge_policy not in (
            ResultMergePolicy.all_required, ResultMergePolicy.best_effort
        ):
            outputs = [
                json.dumps(u.output, sort_keys=True, default=str)
                for u in succeeded_units
                if u.output is not None
            ]
            unique_outputs = set(outputs)
            if len(unique_outputs) > 1:
                _conflicts.append(
                    f"conflicting_outputs_from_{len(succeeded_units)}_succeeded_units"
                )

        return build_merged_runtime_result(
            merge_id=_id,
            result_units=units,
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            mesh_session_id=mesh_session_id,
            merge_policy=merge_policy,
            primary_result_unit_id=_primary_unit_id,
            merged_output=_merged_output,
            success=_success,
            partial=_partial,
            fallback_applied=_fallback_applied,
            conflicts=_conflicts,
            execution_trace_refs=_exec_trace_refs,
            governance_snapshot_refs=_gov_refs,
            policy_alignment_refs=_policy_refs,
            merge_reason=merge_reason,
            errors=_errors,
            metadata=metadata,
        )
    except Exception as _e:  # noqa: BLE001
        _logger.debug("merge_runtime_results: internal error: %s", _e)
        return MergedRuntimeResult(
            merge_id=merge_id or str(uuid.uuid4()),
            trace_id=trace_id,
            success=False,
            errors=[f"merge_runtime_results: internal_error:{_e}"],
        )


def build_result_merge_summary(
    result: Optional[MergedRuntimeResult] = None,
    *,
    merge_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    merge_policy: Optional[ResultMergePolicy] = None,
    success: Optional[bool] = None,
    partial: Optional[bool] = None,
    fallback_applied: Optional[bool] = None,
    unit_count: Optional[int] = None,
    succeeded_unit_count: Optional[int] = None,
    failed_unit_count: Optional[int] = None,
    conflict_count: Optional[int] = None,
    error_count: Optional[int] = None,
    has_merged_output: Optional[bool] = None,
    merge_reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> ResultMergeSummary:
    """Convenience factory for :class:`ResultMergeSummary`.

    When ``result`` is provided its fields populate defaults.  Explicit
    keyword arguments take precedence.

    Parameters
    ----------
    result:
        Optional :class:`MergedRuntimeResult` to source default values from.
    All other parameters override ``result`` fields when provided.

    Returns
    -------
    ResultMergeSummary
    """
    try:
        _merge_id = merge_id if merge_id is not None else (result.merge_id if result else None)
        _trace = trace_id if trace_id is not None else (result.trace_id if result else None)
        _task = task_id if task_id is not None else (result.task_id if result else None)
        _session = session_id if session_id is not None else (result.session_id if result else None)
        _policy = merge_policy if merge_policy is not None else (
            result.merge_policy if result else ResultMergePolicy.unknown
        )
        _success = success if success is not None else (result.success if result else False)
        _partial = partial if partial is not None else (result.partial if result else False)
        _fallback = fallback_applied if fallback_applied is not None else (
            result.fallback_applied if result else False
        )
        _reason = merge_reason if merge_reason is not None else (result.merge_reason if result else None)

        if result:
            _units = result.result_units or []
            _unit_c = unit_count if unit_count is not None else len(_units)
            _succ_c = succeeded_unit_count if succeeded_unit_count is not None else sum(
                1 for u in _units if u.status == RuntimeResultStatus.succeeded
            )
            _fail_c = failed_unit_count if failed_unit_count is not None else sum(
                1 for u in _units if u.status == RuntimeResultStatus.failed
            )
            _conf_c = conflict_count if conflict_count is not None else len(result.conflicts)
            _err_c = error_count if error_count is not None else len(result.errors)
            _has_out = has_merged_output if has_merged_output is not None else (result.merged_output is not None)
        else:
            _unit_c = unit_count or 0
            _succ_c = succeeded_unit_count or 0
            _fail_c = failed_unit_count or 0
            _conf_c = conflict_count or 0
            _err_c = error_count or 0
            _has_out = has_merged_output or False

        return ResultMergeSummary(
            merge_id=_merge_id,
            trace_id=_trace,
            task_id=_task,
            session_id=_session,
            merge_policy=_policy,
            success=_success,
            partial=_partial,
            fallback_applied=_fallback,
            unit_count=_unit_c,
            succeeded_unit_count=_succ_c,
            failed_unit_count=_fail_c,
            conflict_count=_conf_c,
            error_count=_err_c,
            has_merged_output=_has_out,
            merge_reason=_reason,
            metadata=dict(metadata) if metadata else {},
        )
    except Exception as _e:  # noqa: BLE001
        _logger.debug("build_result_merge_summary: construction error: %s", _e)
        return ResultMergeSummary(
            merge_policy=ResultMergePolicy.unknown,
            success=False,
            merge_reason="build_result_merge_summary: construction error",
        )


__all__ = [
    # Enums
    "RuntimeResultRole",
    "RuntimeResultStatus",
    "ResultMergePolicy",
    # Sub-contracts
    "RuntimeResultProvenance",
    # Core contracts
    "RuntimeResultUnit",
    "ResultMergeInput",
    "MergedRuntimeResult",
    "ResultMergeSummary",
    # Builders / adapters
    "from_local_takeover_result",
    "from_source_dispatch_result",
    "from_execution_output",
    "build_merged_runtime_result",
    "merge_runtime_results",
    "build_result_merge_summary",
]
