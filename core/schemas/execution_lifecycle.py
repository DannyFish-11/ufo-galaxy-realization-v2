#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.schemas.execution_lifecycle — Canonical Execution Lifecycle Model
======================================================================

PR-12 — Unified Execution Lifecycle

Defines a single, stable vocabulary for **where execution currently is**
across all execution flow types: local manifestation, remote command
dispatch, remote agent dispatch, and multi-device orchestration.

After PR-11 introduced :class:`~core.schemas.execution_plan.ExecutionPlan`
to represent *execution intent*, PR-12 adds the complementary runtime
language for *execution progress* — so that plans, substrate dispatch,
and result handling all share one lifecycle vocabulary.

Architectural role
------------------
The lifecycle state sits at the *runtime observation* layer.  It is
orthogonal to the plan structure: a plan describes *what* will run and
*where*; lifecycle state describes *how far along* that plan is::

    ExecutionPlan (intent)
        └─ ExecutionStep  ← has lifecycle_state (per-step progress)
                            ↕
    ExecutionLifecycleState (runtime progress vocabulary)
                            ↕
    execution result dict   ← carries lifecycle_state and lifecycle_trail

Main concepts
-------------
:class:`ExecutionLifecycleState`
    Canonical enum of all stable states.  Values are lowercase strings
    safe for serialisation, logging, and API responses.

:class:`LifecycleTransition`
    A timestamped record of a single state transition.  Used to build an
    audit trail of how execution progressed.

:func:`initial_state_for_step_type`
    Map an :class:`~core.schemas.execution_plan.ExecutionStepType` to the
    initial lifecycle state it typically enters first.

:func:`terminal_states`
    Return the set of states from which no further transition is expected.

:func:`is_terminal`
    Return ``True`` when the given state is terminal (no further progress
    expected).

:func:`lifecycle_summary`
    Produce a compact, JSON-safe dict summarising the lifecycle state of a
    plan or step.

:func:`advance_lifecycle`
    Return the next canonical state given the current state and an outcome
    indicator.  Does *not* mutate anything; the caller decides whether to
    apply the transition.

Backward compatibility
----------------------
All new fields are optional.  Consumers that do not inspect lifecycle data
continue to work unchanged.  The lifecycle state is placed under the
``lifecycle_state`` key in result dicts, so code that reads only
``success`` or ``response`` is unaffected.

Usage::

    from core.schemas.execution_lifecycle import (
        ExecutionLifecycleState,
        LifecycleTransition,
        is_terminal,
        lifecycle_summary,
        advance_lifecycle,
    )

    state = ExecutionLifecycleState.PLANNED
    assert not is_terminal(state)

    state = advance_lifecycle(state, success=None)  # → DISPATCHING
    transition = LifecycleTransition.make(
        from_state=ExecutionLifecycleState.PLANNED,
        to_state=state,
        reason="starting dispatch",
    )
    print(lifecycle_summary(state, [transition]))
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set


__all__ = [
    "ExecutionLifecycleState",
    "LifecycleTransition",
    "initial_state_for_step_type",
    "terminal_states",
    "is_terminal",
    "lifecycle_summary",
    "advance_lifecycle",
    "lifecycle_trail_to_dict",
]


# ---------------------------------------------------------------------------
# ExecutionLifecycleState
# ---------------------------------------------------------------------------


class ExecutionLifecycleState(str, Enum):
    """Canonical execution lifecycle states.

    Values are stable lowercase strings suitable for serialisation,
    logging, and API responses.  All execution flow types — local
    manifestation, remote command, remote agent, and multi-device
    orchestration — use this single vocabulary.

    State machine overview
    ----------------------
    The typical happy-path progressions are::

        # Local execution
        CREATED → PLANNED → DISPATCHING → RUNNING → SUCCEEDED

        # Remote command dispatch
        CREATED → PLANNED → QUEUED → SELECTED → DISPATCHING
                → WAITING_REMOTE → SUCCEEDED | FAILED | TIMED_OUT

        # Remote agent dispatch
        CREATED → PLANNED → QUEUED → SELECTED → DISPATCHING
                → WAITING_REMOTE → SUCCEEDED | FAILED | TIMED_OUT

        # Multi-device orchestration
        CREATED → PLANNED → QUEUED → DISPATCHING
                → RUNNING (parallel steps)
                → PARTIALLY_SUCCEEDED | SUCCEEDED | FAILED | DEGRADED

    Any state can transition to CANCELLED.
    DEGRADED represents a terminal-ish state where execution completed
    with partial capability loss but is still operational.

    Attributes
    ----------
    CREATED:
        The execution record has been initialised but planning has not
        yet run.  This is the entry state for all flows.

    PLANNED:
        The :class:`~core.schemas.execution_plan.ExecutionPlan` has been
        constructed.  Execution intent is now explicit; dispatch has not
        started.

    QUEUED:
        The task has been placed in a dispatch queue or is waiting for a
        substrate slot (e.g. waiting for device pool selection).

    SELECTED:
        A specific execution target (device/executor) has been selected
        and the substrate is about to dispatch.

    DISPATCHING:
        The substrate is actively sending the command or agent envelope
        to the target.  For local execution this collapses with RUNNING.

    RUNNING:
        Execution is underway.  For local steps this is the main
        execution window.  For remote steps this state is entered once
        the remote side acknowledges receipt.

    WAITING_REMOTE:
        The substrate has dispatched to a remote device/agent and is
        waiting for the result.  No further local progress is possible
        until the remote responds.

    PARTIALLY_SUCCEEDED:
        One or more steps succeeded but at least one step failed.
        Meaningful for multi-step plans (e.g. orchestration fan-outs).
        Not a final-terminal state — a plan-level aggregator may promote
        this to SUCCEEDED, FAILED, or DEGRADED.

    SUCCEEDED:
        Execution completed successfully.  Terminal.

    FAILED:
        Execution completed with an unrecoverable error.  Terminal.

    CANCELLED:
        Execution was cancelled before completion.  Terminal.

    TIMED_OUT:
        Execution did not complete within the permitted time window.
        Terminal.

    DEGRADED:
        Execution completed but with reduced capability or partial loss.
        The system is still operational.  Terminal.
    """

    CREATED = "created"
    PLANNED = "planned"
    QUEUED = "queued"
    SELECTED = "selected"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    WAITING_REMOTE = "waiting_remote"
    PARTIALLY_SUCCEEDED = "partially_succeeded"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    DEGRADED = "degraded"


# ---------------------------------------------------------------------------
# Terminal states
# ---------------------------------------------------------------------------

_TERMINAL: Set[ExecutionLifecycleState] = {
    ExecutionLifecycleState.SUCCEEDED,
    ExecutionLifecycleState.FAILED,
    ExecutionLifecycleState.CANCELLED,
    ExecutionLifecycleState.TIMED_OUT,
    ExecutionLifecycleState.DEGRADED,
}


def terminal_states() -> Set[ExecutionLifecycleState]:
    """Return the set of terminal lifecycle states.

    Terminal states are those from which no further progress is expected
    under normal operation.  :attr:`ExecutionLifecycleState.PARTIALLY_SUCCEEDED`
    is *not* terminal because an aggregation step may still promote it.

    Returns
    -------
    frozenset-like set
        The stable set of terminal :class:`ExecutionLifecycleState` values.
    """
    return set(_TERMINAL)


def is_terminal(state: ExecutionLifecycleState) -> bool:
    """Return ``True`` if *state* is a terminal lifecycle state.

    Parameters
    ----------
    state:
        The lifecycle state to test.

    Returns
    -------
    bool
    """
    return state in _TERMINAL


# ---------------------------------------------------------------------------
# Initial state mapping
# ---------------------------------------------------------------------------

def initial_state_for_step_type(step_type_value: str) -> ExecutionLifecycleState:
    """Return the initial lifecycle state for a given step type value.

    All step types start at :attr:`ExecutionLifecycleState.CREATED`.
    Remote and orchestration steps then typically advance through QUEUED
    before reaching DISPATCHING, while local steps go directly from
    PLANNED to DISPATCHING.

    Parameters
    ----------
    step_type_value:
        The string value of an
        :class:`~core.schemas.execution_plan.ExecutionStepType`
        (e.g. ``"local_manifestation"``, ``"remote_command"``).

    Returns
    -------
    ExecutionLifecycleState
        Always :attr:`ExecutionLifecycleState.CREATED`.
    """
    return ExecutionLifecycleState.CREATED


# ---------------------------------------------------------------------------
# Lifecycle progression helpers
# ---------------------------------------------------------------------------

# Canonical happy-path next states for each (current_state, is_remote) pair.
# ``is_remote=True`` covers remote_command, remote_agent, and orchestration.
_NEXT_STATE: Dict[tuple, ExecutionLifecycleState] = {
    # Local path
    (ExecutionLifecycleState.CREATED, False): ExecutionLifecycleState.PLANNED,
    (ExecutionLifecycleState.PLANNED, False): ExecutionLifecycleState.DISPATCHING,
    (ExecutionLifecycleState.DISPATCHING, False): ExecutionLifecycleState.RUNNING,
    # Remote / orchestration path
    (ExecutionLifecycleState.CREATED, True): ExecutionLifecycleState.PLANNED,
    (ExecutionLifecycleState.PLANNED, True): ExecutionLifecycleState.QUEUED,
    (ExecutionLifecycleState.QUEUED, True): ExecutionLifecycleState.SELECTED,
    (ExecutionLifecycleState.SELECTED, True): ExecutionLifecycleState.DISPATCHING,
    (ExecutionLifecycleState.DISPATCHING, True): ExecutionLifecycleState.WAITING_REMOTE,
    (ExecutionLifecycleState.WAITING_REMOTE, True): ExecutionLifecycleState.RUNNING,
    # Shared
    (ExecutionLifecycleState.RUNNING, False): ExecutionLifecycleState.SUCCEEDED,
    (ExecutionLifecycleState.RUNNING, True): ExecutionLifecycleState.SUCCEEDED,
}


def advance_lifecycle(
    current: ExecutionLifecycleState,
    *,
    success: Optional[bool],
    is_remote: bool = False,
    timed_out: bool = False,
    cancelled: bool = False,
    degraded: bool = False,
    partially_succeeded: bool = False,
) -> ExecutionLifecycleState:
    """Return the next lifecycle state given the current state and outcome.

    This function encodes the canonical state-machine transitions.  It
    does **not** mutate any object; callers decide whether to apply the
    returned state.

    Terminal override rules (evaluated in priority order):
    1. ``cancelled=True`` → :attr:`~ExecutionLifecycleState.CANCELLED`
    2. ``timed_out=True`` → :attr:`~ExecutionLifecycleState.TIMED_OUT`
    3. ``success=False`` → :attr:`~ExecutionLifecycleState.FAILED`
    4. ``degraded=True`` → :attr:`~ExecutionLifecycleState.DEGRADED`
    5. ``partially_succeeded=True`` → :attr:`~ExecutionLifecycleState.PARTIALLY_SUCCEEDED`
    6. ``success=True`` → :attr:`~ExecutionLifecycleState.SUCCEEDED`
    7. No outcome provided → follow canonical next-state table.

    Parameters
    ----------
    current:
        Current lifecycle state.
    success:
        ``True`` for success, ``False`` for failure, ``None`` to follow
        the canonical happy-path progression (no outcome yet known).
    is_remote:
        ``True`` for remote command/agent/orchestration flows.
    timed_out:
        Set to ``True`` to force transition to TIMED_OUT.
    cancelled:
        Set to ``True`` to force transition to CANCELLED.
    degraded:
        Set to ``True`` to force transition to DEGRADED.
    partially_succeeded:
        Set to ``True`` to transition to PARTIALLY_SUCCEEDED (multi-step).

    Returns
    -------
    ExecutionLifecycleState
        The next state.  If the current state is already terminal and no
        override is provided, returns the current state unchanged.
    """
    # Already terminal — only override with explicit outcome flags.
    if current in _TERMINAL:
        if cancelled:
            return ExecutionLifecycleState.CANCELLED
        if timed_out:
            return ExecutionLifecycleState.TIMED_OUT
        if success is False:
            return ExecutionLifecycleState.FAILED
        return current

    # Explicit terminal outcomes
    if cancelled:
        return ExecutionLifecycleState.CANCELLED
    if timed_out:
        return ExecutionLifecycleState.TIMED_OUT
    if success is False:
        return ExecutionLifecycleState.FAILED
    if degraded:
        return ExecutionLifecycleState.DEGRADED
    if partially_succeeded:
        return ExecutionLifecycleState.PARTIALLY_SUCCEEDED
    if success is True:
        return ExecutionLifecycleState.SUCCEEDED

    # No outcome — follow canonical progression table.
    key = (current, bool(is_remote))
    return _NEXT_STATE.get(key, current)


# ---------------------------------------------------------------------------
# LifecycleTransition
# ---------------------------------------------------------------------------


@dataclass
class LifecycleTransition:
    """A timestamped record of a single lifecycle state change.

    Transitions are appended to a *trail* list on :class:`ExecutionStep`
    and :class:`ExecutionPlan` so that the full execution history is
    preserved for diagnostics and observability.

    Parameters
    ----------
    transition_id:
        Unique identifier for this transition (UUID hex).
    from_state:
        State before the transition.  ``None`` for the initial entry.
    to_state:
        State after the transition.
    reason:
        Human-readable description of why this transition occurred.
    timestamp:
        Wall-clock time when the transition was recorded (seconds since
        epoch).
    metadata:
        Optional extra diagnostic information.
    """

    transition_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    from_state: Optional[ExecutionLifecycleState] = None
    to_state: ExecutionLifecycleState = ExecutionLifecycleState.CREATED
    reason: str = ""
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def make(
        cls,
        to_state: ExecutionLifecycleState,
        *,
        from_state: Optional[ExecutionLifecycleState] = None,
        reason: str = "",
        **kwargs: Any,
    ) -> "LifecycleTransition":
        """Convenience factory for creating a transition record.

        Parameters
        ----------
        to_state:
            The state being transitioned *to*.
        from_state:
            The state being transitioned *from*.  ``None`` for the
            initial creation transition.
        reason:
            Short human-readable description.
        **kwargs:
            Extra metadata fields merged into ``metadata``.

        Returns
        -------
        LifecycleTransition
        """
        return cls(
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            metadata=dict(kwargs),
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        return {
            "transition_id": self.transition_id,
            "from_state": self.from_state.value if self.from_state else None,
            "to_state": self.to_state.value,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# lifecycle_summary
# ---------------------------------------------------------------------------


def lifecycle_summary(
    state: ExecutionLifecycleState,
    trail: Optional[List[LifecycleTransition]] = None,
    *,
    plan_id: Optional[str] = None,
    step_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Return a compact, JSON-safe lifecycle summary dict.

    Parameters
    ----------
    state:
        The current lifecycle state.
    trail:
        Optional list of :class:`LifecycleTransition` records.
    plan_id:
        Optional plan identifier to include in the summary.
    step_id:
        Optional step identifier to include in the summary.

    Returns
    -------
    dict
        Keys: ``lifecycle_state``, ``is_terminal``, ``transition_count``,
        ``last_reason``, ``plan_id``, ``step_id``,
        ``lifecycle_trail`` (list of transition dicts).
    """
    trail = trail or []
    last_reason = trail[-1].reason if trail else ""
    return {
        "lifecycle_state": state.value,
        "is_terminal": is_terminal(state),
        "transition_count": len(trail),
        "last_reason": last_reason,
        "plan_id": plan_id,
        "step_id": step_id,
        "lifecycle_trail": [t.to_dict() for t in trail],
    }


# ---------------------------------------------------------------------------
# lifecycle_trail_to_dict
# ---------------------------------------------------------------------------


def lifecycle_trail_to_dict(
    trail: Optional[List[LifecycleTransition]],
) -> List[Dict[str, Any]]:
    """Serialise a lifecycle trail to a list of JSON-safe dicts.

    Safe to call with ``None``; returns an empty list.

    Parameters
    ----------
    trail:
        List of :class:`LifecycleTransition` objects, or ``None``.

    Returns
    -------
    list of dict
    """
    if not trail:
        return []
    return [t.to_dict() for t in trail]
