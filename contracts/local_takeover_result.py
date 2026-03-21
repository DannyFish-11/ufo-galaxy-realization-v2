"""contracts/local_takeover_result.py
======================================
Local Takeover Result Contract — PR-34.

This module defines the **canonical Local Takeover Result contract**: the
structured, serialisable response produced by the target runtime after it has
adopted a handoff envelope and executed locally.

It answers the architectural question:

    *"What structured result does the target runtime return after it accepts a
    handoff envelope, resolves a local session, and executes locally?"*

It is the target-side response contract, and the natural counterpart to:

- **PR-31** (:class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2`) — the
  inbound handoff envelope delivered to the target.
- **PR-25** (:class:`~contracts.execution_trace.ExecutionTraceEnvelope`) — the
  execution lifecycle trace that the local runtime produces.
- **PR-27** (``RuntimeGovernanceSnapshot``) — the governance posture captured at
  execution time.
- **PR-28** (``ExecutionPolicyAlignmentSurface``) — optional policy alignment
  context.

This contract formalises:
- whether the takeover succeeded (``success``);
- the trace correlation identifiers (``trace_id``, ``task_id``, ``session_id``,
  ``runtime_session_id``);
- the raw local execution output (``result``);
- the execution trace envelope (``execution_trace``);
- optional governance snapshot and policy alignment (``governance_snapshot``,
  ``policy_alignment``);
- structured error / reason fields (``errors``, ``reason``);
- arbitrary extension metadata (``metadata``).

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Fully serialisable** — :meth:`LocalTakeoverResult.to_dict` and
  :meth:`LocalTakeoverResult.to_json` produce stable, round-trippable JSON.
- **Graceful defaults** — all fields beyond ``trace_id`` and ``success`` are
  optional; callers with partial context always produce a valid result.
- **Stable field names** — downstream consumers can rely on the field names
  without fear of silent renaming.
- **No UI semantics** — purely runtime/projection/coordinator use.

Usage::

    from contracts.local_takeover_result import (
        LocalTakeoverResult,
        LocalTakeoverStatus,
        build_local_takeover_result,
        from_execution_output,
        failure_result,
    )

    # Build a successful result from raw execution output
    result = from_execution_output(
        trace_id="trace_abc",
        execution_output={"action_taken": "click", "success": True},
        session_id="sess_001",
    )
    payload = result.to_dict()

    # Build a minimal failure result
    err = failure_result(trace_id="trace_abc", reason="executor_unavailable")
    payload = err.to_dict()

See ``docs/TARGET_RUNTIME_LOCAL_TAKEOVER.md`` for the full specification.
"""

from __future__ import annotations

import json
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# LocalTakeoverStatus — lifecycle status of the takeover execution
# ---------------------------------------------------------------------------


class LocalTakeoverStatus(str, Enum):
    """Lifecycle status of the local takeover execution.

    pending
        The takeover has been received but not yet started.
    adopted
        The session context has been adopted / resolved; execution not yet run.
    executing
        Local execution is currently in progress.
    succeeded
        Execution completed successfully.
    failed
        Execution completed with a failure or error.
    blocked
        Execution was blocked before it started (policy, readiness gate, etc.).
    rejected
        The takeover was rejected (e.g. policy disallows, envelope invalid).
    """

    pending = "pending"
    adopted = "adopted"
    executing = "executing"
    succeeded = "succeeded"
    failed = "failed"
    blocked = "blocked"
    rejected = "rejected"


# ---------------------------------------------------------------------------
# LocalTakeoverSessionContext — local session resolution outcome
# ---------------------------------------------------------------------------


class LocalTakeoverSessionContext(BaseModel):
    """Describes the local session context adopted or created during takeover.

    Fields
    ------
    session_id
        The session identifier used locally.  Either adopted from the incoming
        envelope or freshly generated.
    runtime_session_id
        The local runtime's own session identifier (e.g. OpenClawd session ID).
        ``None`` when unavailable.
    task_id
        The task identifier forwarded from the envelope.  ``None`` when absent.
    trace_id
        The distributed trace identifier forwarded from the envelope.
    adopted
        ``True`` when an existing session was reused; ``False`` when a new
        local session was created.
    mesh_session_id
        The mesh-level session identifier, if one was available from
        PR-33 context.  ``None`` when mesh sessions are not active.
    metadata
        Arbitrary extension metadata.
    """

    session_id: Optional[str] = Field(
        default=None,
        description="Local session identifier (adopted or freshly generated).",
    )
    runtime_session_id: Optional[str] = Field(
        default=None,
        description="Runtime-internal session identifier (e.g. OpenClawd session).",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Task identifier forwarded from the handoff envelope.",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Distributed trace identifier forwarded from the handoff envelope.",
    )
    adopted: bool = Field(
        default=False,
        description="True when an existing local session was reused; False when created.",
    )
    mesh_session_id: Optional[str] = Field(
        default=None,
        description="Mesh-level session ID from PR-33 context, if available.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extension metadata.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# LocalTakeoverResult — canonical target-side takeover result
# ---------------------------------------------------------------------------


class LocalTakeoverResult(BaseModel):
    """Canonical result returned by the target runtime after local takeover.

    This is the structured response produced after the target runtime:
    1. receives and validates a handoff envelope (PR-31);
    2. resolves or creates a local session context;
    3. executes locally using existing execution facilities; and
    4. returns a stable, traceable result to the caller.

    Fields
    ------
    result_id
        Unique identifier for this takeover result (UUID4).
    trace_id
        Distributed trace identifier from the originating handoff envelope.
        ``None`` only when completely unavailable.
    task_id
        Task identifier from the handoff envelope.  ``None`` when absent.
    session_id
        Session identifier used during local execution.  ``None`` when absent.
    runtime_session_id
        The target runtime's own internal session identifier.  ``None`` when
        unavailable.
    success
        ``True`` when local execution completed without fatal error.
    status
        Structured :class:`LocalTakeoverStatus` lifecycle value.
    result
        The raw local execution output dict, as returned by the executor.
        ``None`` when execution did not produce output (e.g. blocked/rejected).
    execution_trace
        Serialised :class:`~contracts.execution_trace.ExecutionTraceEnvelope`
        dict, when available from the local execution path (PR-25).
    governance_snapshot
        Serialised ``RuntimeGovernanceSnapshot`` dict, when available (PR-27).
    policy_alignment
        Serialised ``ExecutionPolicyAlignmentSurface`` dict, when available
        (PR-28).
    session_context
        The resolved local session context object (adopted / created).
    errors
        List of error/warning strings.  Empty when no errors occurred.
    reason
        Human-readable reason string when ``success`` is ``False``.  ``None``
        on success.
    timestamp
        Unix timestamp (seconds) when this result was produced.
    metadata
        Arbitrary extension metadata (source device, target device, etc.).
    """

    result_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this takeover result (UUID4).",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Distributed trace identifier from the handoff envelope.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Task identifier from the handoff envelope.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session identifier used during local execution.",
    )
    runtime_session_id: Optional[str] = Field(
        default=None,
        description="Target runtime's internal session identifier.",
    )
    success: bool = Field(
        default=False,
        description="True when local execution completed without fatal error.",
    )
    status: LocalTakeoverStatus = Field(
        default=LocalTakeoverStatus.pending,
        description="Structured lifecycle status of the takeover.",
    )
    result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Raw local execution output dict, or None when not available.",
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
    session_context: Optional[LocalTakeoverSessionContext] = Field(
        default=None,
        description="Resolved local session context (adopted or created).",
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Error/warning strings. Empty on clean success.",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Human-readable reason when success is False. None on success.",
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
        """Return a stable, JSON-safe dictionary representation.

        All enum values are serialised as their string values.  Nested
        sub-contracts (session_context) are recursively expanded.
        """
        return self.model_dump(mode="json")

    def to_json(self, *, indent: Optional[int] = None) -> str:
        """Return a stable JSON string.

        Parameters
        ----------
        indent:
            Optional indentation level for pretty-printing.
        """
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocalTakeoverResult":
        """Construct a :class:`LocalTakeoverResult` from a dictionary.

        Tolerates unknown extra fields; missing optional fields fall back to
        their defaults.
        """
        return cls.model_validate(data)

    def to_compact_summary(self) -> Dict[str, Any]:
        """Return a compact human-readable summary dict.

        Suitable for logging, dashboard tiles, and trace metadata.
        """
        return {
            "result_id": self.result_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "runtime_session_id": self.runtime_session_id,
            "success": self.success,
            "status": self.status.value if isinstance(self.status, LocalTakeoverStatus) else str(self.status),
            "reason": self.reason,
            "error_count": len(self.errors),
            "has_execution_trace": self.execution_trace is not None,
            "has_governance_snapshot": self.governance_snapshot is not None,
            "has_policy_alignment": self.policy_alignment is not None,
            "timestamp": self.timestamp,
        }

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# Adapter / builder functions
# ---------------------------------------------------------------------------


def build_local_takeover_result(
    *,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
    success: bool = False,
    status: LocalTakeoverStatus = LocalTakeoverStatus.pending,
    result: Optional[Dict[str, Any]] = None,
    execution_trace: Optional[Dict[str, Any]] = None,
    governance_snapshot: Optional[Dict[str, Any]] = None,
    policy_alignment: Optional[Dict[str, Any]] = None,
    session_context: Optional[LocalTakeoverSessionContext] = None,
    errors: Optional[List[str]] = None,
    reason: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> LocalTakeoverResult:
    """Convenience factory for :class:`LocalTakeoverResult`.

    All parameters are optional; omitted fields fall back to safe defaults.
    This builder never raises — any error returns a minimal failed result.

    Parameters
    ----------
    trace_id:
        Distributed trace identifier from the handoff envelope.
    task_id:
        Task identifier from the handoff envelope.
    session_id:
        Session identifier used during local execution.
    runtime_session_id:
        Target runtime's internal session identifier.
    success:
        Whether local execution completed without fatal error.
    status:
        Structured lifecycle status.
    result:
        Raw local execution output dict.
    execution_trace:
        Serialised ExecutionTraceEnvelope dict (PR-25).
    governance_snapshot:
        Serialised RuntimeGovernanceSnapshot dict (PR-27).
    policy_alignment:
        Serialised ExecutionPolicyAlignmentSurface dict (PR-28).
    session_context:
        Resolved local session context.
    errors:
        List of error strings.
    reason:
        Human-readable failure reason.
    metadata:
        Arbitrary extension metadata.

    Returns
    -------
    LocalTakeoverResult
    """
    try:
        return LocalTakeoverResult(
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            runtime_session_id=runtime_session_id,
            success=success,
            status=status,
            result=result,
            execution_trace=execution_trace,
            governance_snapshot=governance_snapshot,
            policy_alignment=policy_alignment,
            session_context=session_context,
            errors=list(errors) if errors else [],
            reason=reason,
            metadata=dict(metadata) if metadata else {},
        )
    except Exception:  # noqa: BLE001
        return LocalTakeoverResult(
            trace_id=trace_id,
            success=False,
            status=LocalTakeoverStatus.failed,
            reason="internal_error:build_local_takeover_result",
        )


def from_execution_output(
    *,
    trace_id: Optional[str] = None,
    execution_output: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_context: Optional[LocalTakeoverSessionContext] = None,
    governance_snapshot: Optional[Dict[str, Any]] = None,
    policy_alignment: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> LocalTakeoverResult:
    """Build a :class:`LocalTakeoverResult` from raw execution output.

    Extracts the ``execution_trace``, ``success``, and error information
    from the output dict returned by ``OpenClawd._run_execution()``-style
    callers.

    This is the canonical adapter from the existing execution path (PR-4/25)
    to the takeover result contract.

    Parameters
    ----------
    trace_id:
        Distributed trace identifier.
    execution_output:
        Dict returned by ``_run_execution()``; may be ``None``.
    session_id:
        Session identifier used during this execution.
    runtime_session_id:
        Runtime's internal session ID.
    task_id:
        Task identifier.
    session_context:
        Resolved session context object.
    governance_snapshot:
        Serialised RuntimeGovernanceSnapshot dict, if available.
    policy_alignment:
        Serialised ExecutionPolicyAlignmentSurface dict, if available.
    metadata:
        Arbitrary extension metadata.

    Returns
    -------
    LocalTakeoverResult
    """
    try:
        out = execution_output or {}
        _success = bool(out.get("success", False))
        _action = out.get("action_taken", "none")
        _skipped = out.get("skipped_reason")

        # Derive status
        if _action == "error":
            _status = LocalTakeoverStatus.failed
        elif _skipped and _skipped.startswith("readiness_gate"):
            _status = LocalTakeoverStatus.blocked
        elif _success:
            _status = LocalTakeoverStatus.succeeded
        elif _skipped:
            _status = LocalTakeoverStatus.blocked
        else:
            _status = LocalTakeoverStatus.failed

        _reason: Optional[str] = None
        if not _success:
            _reason = _skipped or "execution_failed"

        _exec_trace: Optional[Dict[str, Any]] = None
        _raw_trace = out.get("execution_trace")
        if _raw_trace is not None:
            if hasattr(_raw_trace, "to_dict"):
                _exec_trace = _raw_trace.to_dict()
            elif isinstance(_raw_trace, dict):
                _exec_trace = _raw_trace

        _errors: List[str] = []
        if _skipped:
            _errors.append(_skipped)

        return LocalTakeoverResult(
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            runtime_session_id=runtime_session_id,
            success=_success,
            status=_status,
            result=out,
            execution_trace=_exec_trace,
            governance_snapshot=governance_snapshot,
            policy_alignment=policy_alignment,
            session_context=session_context,
            errors=_errors,
            reason=_reason,
            metadata=dict(metadata) if metadata else {},
        )
    except Exception as _e:  # noqa: BLE001
        return LocalTakeoverResult(
            trace_id=trace_id,
            task_id=task_id,
            session_id=session_id,
            success=False,
            status=LocalTakeoverStatus.failed,
            reason=f"internal_error:from_execution_output:{_e}",
            errors=[str(_e)],
        )


def failure_result(
    *,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    reason: str = "unknown",
    errors: Optional[List[str]] = None,
    status: LocalTakeoverStatus = LocalTakeoverStatus.failed,
    metadata: Optional[Dict[str, Any]] = None,
) -> LocalTakeoverResult:
    """Build a minimal failure :class:`LocalTakeoverResult`.

    Convenience constructor for error paths and rejection cases.

    Parameters
    ----------
    trace_id:
        Distributed trace identifier.
    task_id:
        Task identifier.
    session_id:
        Session identifier.
    reason:
        Human-readable failure reason.
    errors:
        List of error strings.
    status:
        Specific lifecycle status (defaults to :attr:`LocalTakeoverStatus.failed`).
    metadata:
        Arbitrary extension metadata.

    Returns
    -------
    LocalTakeoverResult
    """
    return LocalTakeoverResult(
        trace_id=trace_id,
        task_id=task_id,
        session_id=session_id,
        success=False,
        status=status,
        reason=reason,
        errors=list(errors) if errors else [],
        metadata=dict(metadata) if metadata else {},
    )


__all__ = [
    # Enumerations
    "LocalTakeoverStatus",
    # Sub-contracts
    "LocalTakeoverSessionContext",
    # Top-level result
    "LocalTakeoverResult",
    # Builders / adapters
    "build_local_takeover_result",
    "from_execution_output",
    "failure_result",
]
