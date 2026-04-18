"""contracts/dispatch_continuity.py
=====================================
Dispatch-to-Session Continuity and Recovery Context — PR-F.

This module defines the **canonical continuity and recovery contracts** for
multi-device runtime execution.  It answers the architectural question:

    *"How does the runtime preserve execution continuity across disconnects,
    handoffs, and recoverable runtime interruptions, and how does it
    distinguish recoverable interruptions from terminal failures?"*

These contracts complement the existing dispatch contracts:

- **PR-35** (:class:`~contracts.source_dispatch.SourceDispatchPlan`,
  :class:`~contracts.source_dispatch.SourceDispatchResult`) — the planned
  and completed dispatch records that now carry a ``continuity_context`` field.
- **PR-33** (:class:`~contracts.mesh_session.MeshSession`) — the mesh session
  that the continuity context links resumed execution back to.
- **PR-E** (:class:`~core.schemas.remote_execution.ExecutorTargetType`) —
  the explicit executor target typing that continuity records reference.

This module formalises:
- the continuity class enum (``DispatchContinuityClass``);
- the durable continuity context (``DispatchContinuityContext``);
- the interruption class enum (``ExecutionInterruptionClass``);
- the interruption record (``ExecutionInterruptionRecord``);
- builder / adapter functions for all contracts.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Fully serialisable** — all contracts produce stable, round-trippable JSON
  via ``to_dict`` / ``to_json``.
- **Graceful defaults** — all fields beyond ``continuity_id`` are optional;
  callers with partial context always produce a valid contract.
- **Backward compatible** — all fields are optional and have safe defaults.

Sentinels
---------
:data:`DISPATCH_CONTINUITY_CONTEXT_IS_DURABLE`
    Affirms that DispatchContinuityContext is the canonical durable
    continuity record for reconnect/handoff scenarios.
:data:`RECOVERABLE_INTERRUPTION_REQUIRES_CONTINUITY_CONTEXT_POLICY`
    Affirms that a recoverable interruption should carry a
    DispatchContinuityContext to allow resumed execution to be correlated
    with prior session and dispatch context.
:data:`TERMINAL_LOSS_IS_NON_RESUMABLE_POLICY`
    Affirms that a terminal interruption class means no resumed execution
    is possible and a new dispatch cycle is required.
:data:`CONTINUITY_CONTEXT_SURVIVES_RECONNECT_POLICY`
    Affirms that DispatchContinuityContext is designed to survive
    reconnect/handoff by carrying stable prior identity fields.

Usage::

    from contracts.dispatch_continuity import (
        DispatchContinuityContext,
        ExecutionInterruptionClass,
        ExecutionInterruptionRecord,
        build_dispatch_continuity_context,
        build_execution_interruption_record,
    )

    ctx = build_dispatch_continuity_context(
        prior_dispatch_id="dispatch_abc",
        prior_session_id="sess_001",
        prior_mesh_session_id="mesh_xyz",
        prior_task_id="task_001",
        prior_trace_id="trace_abc",
        originating_device_id="android_01",
    )

    record = build_execution_interruption_record(
        dispatch_id="dispatch_abc",
        interruption_class=ExecutionInterruptionClass.recoverable,
        interruption_reason="device_disconnect",
        continuity_context=ctx,
    )
"""

from __future__ import annotations

import json
import time
import uuid
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

DISPATCH_CONTINUITY_CONTEXT_IS_DURABLE: str = (
    "DISPATCH_CONTINUITY_CONTEXT_IS_DURABLE: "
    "contracts/dispatch_continuity.py:DispatchContinuityContext is the canonical "
    "durable continuity record for multi-device runtime execution.  It carries "
    "stable prior identity fields (dispatch_id, session_id, mesh_session_id, "
    "task_id, trace_id, originating_device_id) that survive reconnect and handoff "
    "scenarios and allow resumed execution to be correlated with prior context.  "
    "PR-F."
)

RECOVERABLE_INTERRUPTION_REQUIRES_CONTINUITY_CONTEXT_POLICY: str = (
    "POLICY::RECOVERABLE_INTERRUPTION_REQUIRES_CONTINUITY_CONTEXT_PR-F: "
    "A recoverable execution interruption SHOULD carry a DispatchContinuityContext "
    "that references the prior dispatch_id, session_id, and mesh_session_id.  "
    "Without this context, the resumed execution cannot be correlated with the "
    "prior session or dispatch decision.  The continuity context is optional for "
    "backward compatibility, but its absence in a recoverable interruption is "
    "logged as a gap."
)

TERMINAL_LOSS_IS_NON_RESUMABLE_POLICY: str = (
    "POLICY::TERMINAL_LOSS_IS_NON_RESUMABLE_PR-F: "
    "An ExecutionInterruptionRecord with interruption_class=terminal represents a "
    "non-recoverable loss of execution state.  A new dispatch cycle (new "
    "SourceDispatchDecision, new session if required) is the only valid recovery "
    "path.  Callers MUST NOT attempt to resume from a terminal interruption record. "
    "The recommended_action for terminal records is 'terminal_abort'.  PR-F."
)

CONTINUITY_CONTEXT_SURVIVES_RECONNECT_POLICY: str = (
    "POLICY::CONTINUITY_CONTEXT_SURVIVES_RECONNECT_PR-F: "
    "DispatchContinuityContext is designed to survive reconnect/handoff scenarios. "
    "Its identity fields (prior_dispatch_id, prior_session_id, prior_mesh_session_id, "
    "prior_task_id, prior_trace_id) are stable references that a restored runtime "
    "can use to re-associate resumed execution with the correct active mesh session "
    "and dispatch context.  resume_attempt_count tracks how many resume attempts "
    "have been made so that the runtime can bound retry behaviour.  PR-F."
)


# ---------------------------------------------------------------------------
# DispatchContinuityClass — how execution continuity should be reasoned about
# ---------------------------------------------------------------------------


class DispatchContinuityClass(str, Enum):
    """How dispatch-to-session execution continuity should be classified.

    persistent
        The dispatch context persists across individual requests and transport
        reconnections.  A reconnect does not create a new dispatch context;
        resumed execution can be correlated with the prior session.

    request_scoped
        The dispatch context is scoped to a single request lifecycle.  A new
        request creates a new continuity context; resumed execution is not
        possible across request boundaries.

    transfer_scoped
        The dispatch context is scoped to one transfer / handoff lifecycle.
        It is non-resumable once a terminal state is reached; a new handshake
        is required.

    ephemeral
        The dispatch context is not intended to survive any interruption.
        This is used for fire-and-forget local executions that do not require
        continuity tracking.
    """

    persistent = "persistent"
    request_scoped = "request_scoped"
    transfer_scoped = "transfer_scoped"
    ephemeral = "ephemeral"


# ---------------------------------------------------------------------------
# DispatchContinuityContext — durable continuity metadata
# ---------------------------------------------------------------------------


class DispatchContinuityContext(BaseModel):
    """Durable continuity metadata connecting dispatch decisions, executor
    targets, and mesh session state.

    A ``DispatchContinuityContext`` is attached to a
    :class:`~contracts.source_dispatch.SourceDispatchPlan`,
    :class:`~contracts.source_dispatch.SourceDispatchResult`, and
    :class:`~core.schemas.task_envelope.TaskEnvelope`.  It carries the prior
    identity fields needed to correlate a resumed execution with the session
    and dispatch context that was interrupted.

    Fields
    ------
    continuity_id
        Unique identifier for this continuity context (UUID4).
    prior_dispatch_id
        The ``dispatch_id`` of the :class:`~contracts.source_dispatch.SourceDispatchDecision`
        that initiated the execution being continued.  ``None`` for the first
        attempt of a dispatch cycle.
    prior_session_id
        The source-side session identifier from the prior dispatch context.
    prior_mesh_session_id
        The mesh session identifier (PR-33) from the prior dispatch context,
        if the prior execution involved a staged mesh dispatch.
    prior_task_id
        The task identifier being continued.
    prior_trace_id
        The distributed trace identifier from the prior execution context.
        Should be forwarded unchanged to maintain trace continuity.
    originating_device_id
        The device that initiated the original dispatch cycle.
    resume_attempt_count
        Number of times resumption has been attempted for this continuity
        context.  Bounded by upstream policy.
    continuity_class
        How execution continuity should be classified for this context.
        Drives policy decisions about whether to attempt resumption.
    last_checkpoint_at
        Unix timestamp of the last known-good execution checkpoint, if any.
        ``None`` when no checkpoint has been recorded.
    created_at
        Unix timestamp when this continuity context was first created.
    metadata
        Arbitrary extension metadata.
    """

    continuity_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this continuity context (UUID4).",
    )
    prior_dispatch_id: Optional[str] = Field(
        default=None,
        description="Dispatch ID of the prior execution attempt.",
    )
    prior_session_id: Optional[str] = Field(
        default=None,
        description="Source-side session ID from the prior dispatch context.",
    )
    prior_mesh_session_id: Optional[str] = Field(
        default=None,
        description="Mesh session ID (PR-33) from the prior dispatch context.",
    )
    prior_task_id: Optional[str] = Field(
        default=None,
        description="Task ID being continued.",
    )
    prior_trace_id: Optional[str] = Field(
        default=None,
        description="Distributed trace ID from the prior execution context.",
    )
    originating_device_id: Optional[str] = Field(
        default=None,
        description="Device that initiated the original dispatch cycle.",
    )
    resume_attempt_count: int = Field(
        default=0,
        description="Number of resume attempts made for this continuity context.",
    )
    continuity_class: DispatchContinuityClass = Field(
        default=DispatchContinuityClass.persistent,
        description="How execution continuity is classified for this context.",
    )
    last_checkpoint_at: Optional[float] = Field(
        default=None,
        description="Unix timestamp of the last known-good execution checkpoint.",
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Unix timestamp when this continuity context was created.",
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
    def from_dict(cls, data: Dict[str, Any]) -> "DispatchContinuityContext":
        """Construct from a dictionary.  Tolerates unknown extra fields."""
        return cls.model_validate(data)

    def is_resumable(self) -> bool:
        """Return True if this continuity class supports resumed execution."""
        return self.continuity_class in (
            DispatchContinuityClass.persistent,
            DispatchContinuityClass.transfer_scoped,
        )

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# ExecutionInterruptionClass — recoverable vs terminal
# ---------------------------------------------------------------------------


class ExecutionInterruptionClass(str, Enum):
    """Classification of an execution interruption.

    recoverable
        The interruption can be recovered from.  The execution context is
        preserved (or can be re-associated from the durable continuity
        context), and a resume path is available.  Examples: network
        disconnect, device handoff, transient resource unavailability.

    terminal
        The interruption is terminal and the execution context is lost.
        A new dispatch cycle (new session, new dispatch decision) is
        required.  Examples: device permanently offline, unrecoverable
        executor crash, policy-blocked execution with no fallback.
    """

    recoverable = "recoverable"
    terminal = "terminal"


# ---------------------------------------------------------------------------
# ExecutionInterruptionRecord — structured record of an interruption
# ---------------------------------------------------------------------------

_RECOVERABLE_ACTIONS = frozenset(
    {"resume_local", "resume_on_target", "fallback_local", "reassociate_session"}
)
_TERMINAL_ACTIONS = frozenset({"terminal_abort"})


class ExecutionInterruptionRecord(BaseModel):
    """Structured record of a runtime execution interruption.

    Captures when and why an execution was interrupted and whether it can
    be resumed.  The ``interruption_class`` field is the canonical signal
    for distinguishing recoverable interruption from terminal failure.

    A ``recoverable`` record SHOULD carry a ``continuity_context`` that
    allows the resumed execution to be correlated with the prior session
    and dispatch context.

    A ``terminal`` record means no resume is possible and a new dispatch
    cycle is required.

    Fields
    ------
    interruption_id
        Unique identifier for this interruption record (UUID4).
    dispatch_id
        The ``dispatch_id`` of the interrupted dispatch, if known.
    session_id
        Source-side session identifier at the time of interruption.
    mesh_session_id
        Mesh session identifier at the time of interruption, if applicable.
    task_id
        Task identifier that was executing when interrupted.
    trace_id
        Distributed trace identifier from the interrupted execution.
    interruption_class
        Whether this interruption is ``recoverable`` or ``terminal``.
    interruption_reason
        Human-readable reason for the interruption.
    is_resumable
        Convenience flag: ``True`` when ``interruption_class`` is
        ``recoverable``.
    continuity_context
        Durable continuity context carrying prior identity fields for
        re-association.  ``None`` for terminal interruptions or when
        continuity context is unavailable.
    recommended_action
        Suggested action for the caller:
        ``resume_local`` — attempt to resume on the local runtime;
        ``resume_on_target`` — attempt to resume on the executor target;
        ``fallback_local`` — fall back to local execution;
        ``reassociate_session`` — re-associate execution with the mesh session;
        ``terminal_abort`` — abort and start a new dispatch cycle.
    executor_target_device_id
        Device ID of the executor target that was executing when interrupted,
        if applicable.
    timestamp
        Unix timestamp when this record was created.
    metadata
        Arbitrary extension metadata.
    """

    interruption_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this interruption record (UUID4).",
    )
    dispatch_id: Optional[str] = Field(
        default=None,
        description="Dispatch ID of the interrupted dispatch.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Source-side session identifier at interruption time.",
    )
    mesh_session_id: Optional[str] = Field(
        default=None,
        description="Mesh session identifier at interruption time.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Task identifier that was executing when interrupted.",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Distributed trace identifier from the interrupted execution.",
    )
    interruption_class: ExecutionInterruptionClass = Field(
        default=ExecutionInterruptionClass.recoverable,
        description="Whether this interruption is recoverable or terminal.",
    )
    interruption_reason: str = Field(
        default="unknown",
        description="Human-readable reason for the interruption.",
    )
    is_resumable: bool = Field(
        default=True,
        description="True when interruption_class is recoverable.",
    )
    continuity_context: Optional[DispatchContinuityContext] = Field(
        default=None,
        description=(
            "Durable continuity context for re-association.  "
            "None for terminal interruptions or when unavailable."
        ),
    )
    recommended_action: str = Field(
        default="resume_local",
        description=(
            "Suggested action: resume_local, resume_on_target, "
            "fallback_local, reassociate_session, or terminal_abort."
        ),
    )
    executor_target_device_id: Optional[str] = Field(
        default=None,
        description="Device ID of the executor target at interruption time.",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix timestamp when this record was created.",
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
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionInterruptionRecord":
        """Construct from a dictionary.  Tolerates unknown extra fields."""
        return cls.model_validate(data)

    model_config = {"extra": "allow", "populate_by_name": True}


# ---------------------------------------------------------------------------
# Builder / adapter functions
# ---------------------------------------------------------------------------


def build_dispatch_continuity_context(
    *,
    prior_dispatch_id: Optional[str] = None,
    prior_session_id: Optional[str] = None,
    prior_mesh_session_id: Optional[str] = None,
    prior_task_id: Optional[str] = None,
    prior_trace_id: Optional[str] = None,
    originating_device_id: Optional[str] = None,
    resume_attempt_count: int = 0,
    continuity_class: DispatchContinuityClass = DispatchContinuityClass.persistent,
    last_checkpoint_at: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> DispatchContinuityContext:
    """Convenience factory for :class:`DispatchContinuityContext`.

    All parameters are optional; omitted fields fall back to safe defaults.
    This builder never raises.

    Parameters
    ----------
    prior_dispatch_id:
        The dispatch ID of the prior execution attempt.
    prior_session_id:
        Source-side session ID from the prior dispatch context.
    prior_mesh_session_id:
        Mesh session ID (PR-33) from the prior dispatch context.
    prior_task_id:
        Task ID being continued.
    prior_trace_id:
        Distributed trace ID from the prior execution context.
    originating_device_id:
        Device that initiated the original dispatch cycle.
    resume_attempt_count:
        Number of resume attempts already made.
    continuity_class:
        How execution continuity is classified.
    last_checkpoint_at:
        Unix timestamp of the last known-good checkpoint, if any.
    metadata:
        Arbitrary extension metadata.
    """
    try:
        return DispatchContinuityContext(
            prior_dispatch_id=prior_dispatch_id,
            prior_session_id=prior_session_id,
            prior_mesh_session_id=prior_mesh_session_id,
            prior_task_id=prior_task_id,
            prior_trace_id=prior_trace_id,
            originating_device_id=originating_device_id,
            resume_attempt_count=resume_attempt_count,
            continuity_class=continuity_class,
            last_checkpoint_at=last_checkpoint_at,
            metadata=metadata or {},
        )
    except Exception:
        return DispatchContinuityContext(
            continuity_class=DispatchContinuityClass.ephemeral,
            metadata={"build_error": "build_dispatch_continuity_context: construction error"},
        )


def build_execution_interruption_record(
    *,
    dispatch_id: Optional[str] = None,
    session_id: Optional[str] = None,
    mesh_session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    interruption_class: ExecutionInterruptionClass = ExecutionInterruptionClass.recoverable,
    interruption_reason: str = "unknown",
    continuity_context: Optional[DispatchContinuityContext] = None,
    recommended_action: Optional[str] = None,
    executor_target_device_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> ExecutionInterruptionRecord:
    """Convenience factory for :class:`ExecutionInterruptionRecord`.

    All parameters are optional.  ``is_resumable`` and ``recommended_action``
    are derived from ``interruption_class`` when not explicitly provided.

    Parameters
    ----------
    dispatch_id:
        Dispatch ID of the interrupted dispatch.
    session_id:
        Source-side session identifier at interruption time.
    mesh_session_id:
        Mesh session identifier at interruption time.
    task_id:
        Task identifier that was executing when interrupted.
    trace_id:
        Distributed trace identifier from the interrupted execution.
    interruption_class:
        Whether this interruption is recoverable or terminal.
    interruption_reason:
        Human-readable reason for the interruption.
    continuity_context:
        Durable continuity context for re-association.  Recommended for
        recoverable interruptions.
    recommended_action:
        Suggested action.  When ``None``, derived from ``interruption_class``:
        ``recoverable`` → ``'resume_local'``;
        ``terminal`` → ``'terminal_abort'``.
    executor_target_device_id:
        Device ID of the executor target at interruption time.
    metadata:
        Arbitrary extension metadata.
    """
    is_recoverable = interruption_class == ExecutionInterruptionClass.recoverable
    if recommended_action is None:
        recommended_action = "resume_local" if is_recoverable else "terminal_abort"
    try:
        return ExecutionInterruptionRecord(
            dispatch_id=dispatch_id,
            session_id=session_id,
            mesh_session_id=mesh_session_id,
            task_id=task_id,
            trace_id=trace_id,
            interruption_class=interruption_class,
            interruption_reason=interruption_reason,
            is_resumable=is_recoverable,
            continuity_context=continuity_context,
            recommended_action=recommended_action,
            executor_target_device_id=executor_target_device_id,
            metadata=metadata or {},
        )
    except Exception:
        return ExecutionInterruptionRecord(
            interruption_class=ExecutionInterruptionClass.terminal,
            interruption_reason="build_execution_interruption_record: construction error",
            is_resumable=False,
            recommended_action="terminal_abort",
        )
