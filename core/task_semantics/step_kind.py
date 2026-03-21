#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.task_semantics.step_kind
==============================

PR-15 (V4) — Task Semantics & Step Classes

Defines the stable, serialisable :class:`StepKind` enumeration and its
associated helper utilities.

:class:`StepKind` answers: **what kind of step is this?**

It is intentionally kept minimal — classification describes *what role a step
plays in a task*, not how it is implemented.  All values are lowercase string
literals so that they round-trip cleanly through JSON and log streams.

Step kind overview
------------------
perceive
    Gather data from the environment (screenshot, sensor read, API poll, etc.).
    Typically read-only and side-effect-free.
analyze
    Process or reason over gathered data.  No I/O side effects, but may be
    CPU-intensive and may read cached/persisted state.
decide
    Choose among alternatives; policy decision; plan selection.  No direct
    system effects, but triggers subsequent steps.
execute
    Perform a concrete system action (click, type, file-write, API call with
    side effects, shell command, etc.).  Side-effectful by definition.
confirm
    Await or record explicit user/system confirmation before proceeding.
    Acts as a gate step; typically blocks progress until approval is given.
notify
    Deliver a notification to a user or system (push, log alert, webhook).
    Usually fire-and-forget; may be side-effectful in terms of network I/O.
rollback
    Undo or compensate for a previously executed step.  Side-effectful.
observe_remote
    Observe the state of a remote device without performing any action.
    Similar to ``perceive`` but explicitly cross-device.
unknown
    Catch-all for steps whose kind cannot be inferred.  Consumers should
    treat ``unknown`` conservatively (e.g. assume side-effectful).
"""

from __future__ import annotations

import enum
from typing import Dict, FrozenSet, List

__all__ = [
    "StepKind",
    "STEP_KIND_ORDER",
    "SIDE_EFFECTFUL_KINDS",
    "READONLY_KINDS",
    "step_kind_description",
    "is_side_effectful_kind",
    "is_readonly_kind",
    "coerce_step_kind",
]


# ---------------------------------------------------------------------------
# StepKind enum
# ---------------------------------------------------------------------------


class StepKind(str, enum.Enum):
    """Semantic step classification.

    All values are stable lowercase strings suitable for JSON serialisation.
    """

    PERCEIVE = "perceive"
    ANALYZE = "analyze"
    DECIDE = "decide"
    EXECUTE = "execute"
    CONFIRM = "confirm"
    NOTIFY = "notify"
    ROLLBACK = "rollback"
    OBSERVE_REMOTE = "observe_remote"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Canonical ordering (most read-only → most side-effectful)
# ---------------------------------------------------------------------------

STEP_KIND_ORDER: List[StepKind] = [
    StepKind.PERCEIVE,
    StepKind.OBSERVE_REMOTE,
    StepKind.ANALYZE,
    StepKind.DECIDE,
    StepKind.CONFIRM,
    StepKind.NOTIFY,
    StepKind.EXECUTE,
    StepKind.ROLLBACK,
    StepKind.UNKNOWN,
]
"""Canonical ordering from least to most side-effectful.

Consumers that need to compare or bound step kinds can use the index in
this list as a severity/impact level.
"""

# ---------------------------------------------------------------------------
# Semantic groupings
# ---------------------------------------------------------------------------

SIDE_EFFECTFUL_KINDS: FrozenSet[StepKind] = frozenset(
    {
        StepKind.EXECUTE,
        StepKind.ROLLBACK,
        StepKind.NOTIFY,
        StepKind.UNKNOWN,  # conservative default
    }
)
"""Step kinds that are considered side-effectful by default.

``StepKind.UNKNOWN`` is included conservatively.
"""

READONLY_KINDS: FrozenSet[StepKind] = frozenset(
    {
        StepKind.PERCEIVE,
        StepKind.OBSERVE_REMOTE,
        StepKind.ANALYZE,
        StepKind.DECIDE,
    }
)
"""Step kinds that are read-only (no direct system side effects)."""

# ---------------------------------------------------------------------------
# Human-readable descriptions
# ---------------------------------------------------------------------------

_KIND_DESCRIPTIONS: Dict[str, str] = {
    StepKind.PERCEIVE.value: (
        "Gather environmental data (screenshot, sensor read, API poll). "
        "Read-only, no system side effects."
    ),
    StepKind.ANALYZE.value: (
        "Process or reason over gathered data. No I/O side effects."
    ),
    StepKind.DECIDE.value: (
        "Choose among alternatives or select an execution plan. No direct "
        "system effects."
    ),
    StepKind.EXECUTE.value: (
        "Perform a concrete system action (click, type, file-write, API call "
        "with side effects, shell command). Side-effectful."
    ),
    StepKind.CONFIRM.value: (
        "Await or record explicit user/system confirmation before proceeding. "
        "Gate step."
    ),
    StepKind.NOTIFY.value: (
        "Deliver a notification (push, log alert, webhook). May be "
        "side-effectful in terms of network I/O."
    ),
    StepKind.ROLLBACK.value: (
        "Undo or compensate for a previously executed step. Side-effectful."
    ),
    StepKind.OBSERVE_REMOTE.value: (
        "Observe the state of a remote device without performing any action. "
        "Cross-device read-only."
    ),
    StepKind.UNKNOWN.value: (
        "Step kind could not be inferred. Treated conservatively as "
        "side-effectful."
    ),
}


def step_kind_description(kind: StepKind) -> str:
    """Return a human-readable description for the given :class:`StepKind`.

    Args:
        kind: A :class:`StepKind` value.

    Returns:
        A descriptive string.  Falls back to the kind's ``.value`` if no
        description is registered (should not happen in practice).
    """
    if isinstance(kind, StepKind):
        return _KIND_DESCRIPTIONS.get(kind.value, kind.value)
    return str(kind)


# ---------------------------------------------------------------------------
# Predicate helpers
# ---------------------------------------------------------------------------


def is_side_effectful_kind(kind: StepKind) -> bool:
    """Return ``True`` if *kind* is in :data:`SIDE_EFFECTFUL_KINDS`.

    Args:
        kind: A :class:`StepKind` value.
    """
    if not isinstance(kind, StepKind):
        return True  # conservative default for unknown inputs
    return kind in SIDE_EFFECTFUL_KINDS


def is_readonly_kind(kind: StepKind) -> bool:
    """Return ``True`` if *kind* is in :data:`READONLY_KINDS`.

    Args:
        kind: A :class:`StepKind` value.
    """
    if not isinstance(kind, StepKind):
        return False  # conservative default
    return kind in READONLY_KINDS


# ---------------------------------------------------------------------------
# Coercion helper
# ---------------------------------------------------------------------------


def coerce_step_kind(value: object) -> StepKind:
    """Coerce an arbitrary value to a :class:`StepKind`.

    Accepts:
    - :class:`StepKind` instances (returned as-is)
    - strings matching any :class:`StepKind` value (case-insensitive)
    - ``None`` or unrecognised values → :attr:`StepKind.UNKNOWN`

    Args:
        value: The value to coerce.

    Returns:
        The matching :class:`StepKind`, or :attr:`StepKind.UNKNOWN`.
    """
    if isinstance(value, StepKind):
        return value
    if isinstance(value, str):
        normalised = value.strip().lower()
        try:
            return StepKind(normalised)
        except ValueError:
            pass
    return StepKind.UNKNOWN
