"""galaxy_gateway/protocol/ingress_classifier.py
================================================
Canonical Ingress Message Classifier — PR-5 / Ingress Normalization.

Defines :class:`IngressMessageClass`: the **stable semantic categories** used
to classify a :class:`~galaxy_gateway.protocol.normalized_ingress_event.NormalizedIngressEvent`
before it enters runtime dispatch.

Design goal
-----------
Instead of branching on raw ``type`` strings or ``MessageType`` enum values,
handlers and routers should branch on a small, stable set of semantic classes:

* ``presence``  — device lifecycle: register, heartbeat, disconnect.
* ``control``   — dispatch of new work: command, task_submit, task_cancel, goal.
* ``execution`` — results of executed work: task_result, command_result, parallel_result.
* ``transport`` — overlay / routing events: wake, session_migrate, capability_report.
* ``unknown``   — any kind that does not map to a known class.

Usage::

    from galaxy_gateway.protocol.ingress_classifier import (
        IngressMessageClass,
        classify_ingress_kind,
    )
    from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind

    msg_class = classify_ingress_kind(event.kind)
    if msg_class == IngressMessageClass.PRESENCE:
        ...
"""

from __future__ import annotations

from typing import Dict

from .normalized_ingress_event import IngressEventKind

# ---------------------------------------------------------------------------
# PR-5 authority sentinel
# ---------------------------------------------------------------------------

INGRESS_CLASSIFIER_AUTHORITY = (
    "INGRESS_CLASSIFIER::STABLE_SEMANTIC_CLASSES_AIP_V3_CANONICAL"
)
"""Sentinel declared by the ingress classifier module.

Importing and asserting the presence of this sentinel confirms that the
classifier (and therefore stable semantic dispatch) is in use at the
ingress normalization boundary.
"""


# ---------------------------------------------------------------------------
# IngressMessageClass — stable semantic categories
# ---------------------------------------------------------------------------


class IngressMessageClass:
    """Stable semantic categories for classified ingress events.

    These categories represent the *intent* of a normalized ingress event and
    are deliberately coarser than the fine-grained :class:`IngressEventKind`
    vocabulary.  Runtime dispatch that branches on ``IngressMessageClass``
    instead of raw ``type`` strings is more robust to future protocol evolution.

    Categories
    ----------
    PRESENCE:
        Device lifecycle events — registration, heartbeat, disconnection.
        These events carry no task payload; they signal device state.

    CONTROL:
        Dispatch of new work — commands, task submissions, goal execution,
        parallel subtask fan-out, and cancellations.

    EXECUTION:
        Results of previously dispatched work — task results, command results,
        parallel sub-task completions.

    TRANSPORT:
        Overlay and routing events — wake events, session migrations,
        capability reports.  These are not task-bearing but have routing
        semantics.

    UNKNOWN:
        Events whose ``kind`` is not recognised or is ``IngressEventKind.UNKNOWN``.
    """

    PRESENCE: str = "presence"
    CONTROL: str = "control"
    EXECUTION: str = "execution"
    TRANSPORT: str = "transport"
    UNKNOWN: str = "unknown"

    _ALL = frozenset({PRESENCE, CONTROL, EXECUTION, TRANSPORT, UNKNOWN})


# ---------------------------------------------------------------------------
# Classification table
# ---------------------------------------------------------------------------

_KIND_TO_CLASS: Dict[str, str] = {
    # Presence
    IngressEventKind.DEVICE_REGISTER:   IngressMessageClass.PRESENCE,
    IngressEventKind.DEVICE_HEARTBEAT:  IngressMessageClass.PRESENCE,
    IngressEventKind.DEVICE_STATUS:     IngressMessageClass.PRESENCE,
    IngressEventKind.DEVICE_DISCONNECT: IngressMessageClass.PRESENCE,

    # Control / dispatch
    IngressEventKind.COMMAND:           IngressMessageClass.CONTROL,
    IngressEventKind.TASK_SUBMIT:       IngressMessageClass.CONTROL,
    IngressEventKind.TASK_CANCEL:       IngressMessageClass.CONTROL,
    IngressEventKind.GOAL_EXECUTION:    IngressMessageClass.CONTROL,
    IngressEventKind.PARALLEL_SUBTASK:  IngressMessageClass.CONTROL,

    # Execution / results
    IngressEventKind.TASK_RESULT:       IngressMessageClass.EXECUTION,
    IngressEventKind.COMMAND_RESULT:    IngressMessageClass.EXECUTION,
    IngressEventKind.PARALLEL_RESULT:   IngressMessageClass.EXECUTION,

    # Transport / overlay
    IngressEventKind.WAKE_EVENT:        IngressMessageClass.TRANSPORT,
    IngressEventKind.CAPABILITY_REPORT: IngressMessageClass.TRANSPORT,
    IngressEventKind.AGENT_STATUS:      IngressMessageClass.PRESENCE,
    IngressEventKind.DELEGATED_EXECUTION_SIGNAL: IngressMessageClass.EXECUTION,
    IngressEventKind.FILE_TRANSFER:     IngressMessageClass.CONTROL,
    IngressEventKind.PEER_ANNOUNCE:     IngressMessageClass.TRANSPORT,
    IngressEventKind.PEER_EXCHANGE:     IngressMessageClass.TRANSPORT,
    IngressEventKind.MESH_TOPOLOGY:     IngressMessageClass.TRANSPORT,

    # Android business result messages — PR-03-V2
    # goal_execution_result is the Android uplink result for goal_execution tasks.
    IngressEventKind.GOAL_EXECUTION_RESULT:      IngressMessageClass.EXECUTION,
    # goal_result is the Android error-path alias for goal_execution_result;
    # it carries the same class of user-visible business result.
    IngressEventKind.GOAL_RESULT:                IngressMessageClass.EXECUTION,
    # Handoff protocol uplink result types (PR-02-V2 / PR-03-V2).
    # All three status variants plus the unified envelope result share the
    # EXECUTION class: they carry terminal Android task execution outcomes.
    IngressEventKind.HANDOFF_ACK:                IngressMessageClass.EXECUTION,
    IngressEventKind.HANDOFF_RESULT:             IngressMessageClass.EXECUTION,
    IngressEventKind.HANDOFF_FAILURE:            IngressMessageClass.EXECUTION,
    IngressEventKind.HANDOFF_ENVELOPE_V2_RESULT: IngressMessageClass.EXECUTION,
}


def classify_ingress_kind(kind: str) -> str:
    """Return the :class:`IngressMessageClass` for a given ``IngressEventKind``.

    Parameters
    ----------
    kind:
        A canonical :class:`IngressEventKind` string (e.g. ``"device_register"``).

    Returns
    -------
    str
        One of the :class:`IngressMessageClass` constants.  Falls back to
        :attr:`IngressMessageClass.UNKNOWN` for unrecognised kinds.

    Examples
    --------
    >>> classify_ingress_kind("device_register")
    'presence'
    >>> classify_ingress_kind("task_submit")
    'control'
    >>> classify_ingress_kind("task_result")
    'execution'
    >>> classify_ingress_kind("wake_event")
    'transport'
    >>> classify_ingress_kind("unknown")
    'unknown'
    """
    return _KIND_TO_CLASS.get(kind, IngressMessageClass.UNKNOWN)
