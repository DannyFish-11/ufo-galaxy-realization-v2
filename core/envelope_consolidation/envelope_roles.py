#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.envelope_consolidation.envelope_roles
==========================================

PR-8 (V3) — Execution Envelope Consolidation

Defines the **formal role taxonomy** for the four canonical envelope types used
in the Galaxy runtime.  The roles answer the question:
*"Which envelope should I use at this layer of the stack?"*

The definitions here are **additive** — they do not replace or modify any of
the existing canonical models:

* :class:`~core.schemas.interaction_envelope.InteractionEnvelope`
    — defined in ``core/schemas/interaction_envelope.py``
* :class:`~core.schemas.task_envelope.TaskEnvelope`
    — defined in ``core/schemas/task_envelope.py``
* :class:`~core.unified.command_envelope.CommandEnvelope`
    — defined in ``core/unified/command_envelope.py``
* :class:`~core.unified.command_envelope.ResultEnvelope`
    — defined in ``core/unified/command_envelope.py``

Role taxonomy
-------------
Each role is represented by an :class:`EnvelopeRole` enum member.  The
companion :data:`ROLE_DESCRIPTIONS` dict maps each member to a human-readable
explanation and the Python path to the canonical class.

Usage guidance
--------------
+-------------------+-----------------------------------------------------------+
| Layer             | Use                                                       |
+===================+===========================================================+
| Interaction /     | :attr:`EnvelopeRole.INTERACTION` — output rendering,      |
| persona /         | persona state, multimodal context, UI-surface selection.  |
| rendering         |                                                           |
+-------------------+-----------------------------------------------------------+
| Orchestration /   | :attr:`EnvelopeRole.TASK` — routing decisions, lifecycle  |
| routing /         | tracking, capability checks, NATS publication, DAG nodes. |
| scheduling        |                                                           |
+-------------------+-----------------------------------------------------------+
| Executor /        | :attr:`EnvelopeRole.COMMAND` — executor-facing dispatch,  |
| dispatch          | idempotency key, verb (EXECUTE / CANCEL / INTERRUPT /     |
|                   | QUERY), per-executor trace correlation.                   |
+-------------------+-----------------------------------------------------------+
| Result /          | :attr:`EnvelopeRole.RESULT` — executor return value,      |
| observability     | elapsed time, error code, fallback metadata.              |
+-------------------+-----------------------------------------------------------+

Trace propagation contract
--------------------------
``trace_id`` must be propagated **unchanged** across all four envelope types
for a single user request:

    InteractionEnvelope.trace_id
        == TaskEnvelope.trace_id
        == CommandEnvelope.trace_id
        == ResultEnvelope.trace_id

See :mod:`core.envelope_consolidation.envelope_adapters` for helpers that
extract or propagate trace fields across envelope boundaries.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict


# ---------------------------------------------------------------------------
# EnvelopeRole
# ---------------------------------------------------------------------------


class EnvelopeRole(str, Enum):
    """Formal role label for each of the four canonical Galaxy envelope types.

    Values are lower-case strings suitable for use as JSON keys / log fields.
    """

    INTERACTION = "interaction"
    """Interaction / rendering / perception-output context.

    Canonical class : ``core.schemas.interaction_envelope.InteractionEnvelope``

    Built once per user request by ``InteractionBuilder`` after the multimodal
    bus, scene interpreter, and persona engine have processed the input.
    Carries the selected interaction mode, persona state, multimodal context
    snapshot, and per-channel rendering flags (``OutputPlan``).

    Consumers: UI layer (Windows / Android / Dashboard), avatar engine,
    voice synthesis, overlay renderer.
    """

    TASK = "task"
    """Internal task routing / orchestration contract.

    Canonical class : ``core.schemas.task_envelope.TaskEnvelope``

    The single, authoritative internal message format used across all routing
    paths: gateway command dispatch, device-to-device relay, node execution,
    MCP tool calls, and skill invocations.  Carries lifecycle status, priority,
    required capabilities, and arbitrary metadata.

    Consumers: ``CommandRouter``, ``TaskOrchestrator``, ``TaskGraph``,
    ``MultiDeviceOrchestrator``, NATS ``NATSTopics`` publisher.
    """

    COMMAND = "command"
    """Executor-facing command contract.

    Canonical class : ``core.unified.command_envelope.CommandEnvelope``

    Wraps a concrete execution request destined for a single executor
    (Windows arbiter, remote device, MCP adapter).  Adds idempotency key,
    command verb (EXECUTE / CANCEL / INTERRUPT / QUERY), and cancel metadata.
    Constructed from a ``TaskEnvelope`` via
    ``CommandEnvelope.from_task_envelope()``.

    Consumers: ``WindowsExecutionArbiter``, cross-device dispatcher,
    ``GlobalArbiter``.
    """

    RESULT = "result"
    """Executor return contract.

    Canonical class : ``core.unified.command_envelope.ResultEnvelope``

    Carries the outcome of a single executor attempt: success flag, output
    data, elapsed time, error code, and fallback metadata.  Correlated back
    to the originating ``CommandEnvelope`` via ``task_id`` + ``trace_id``.

    Consumers: orchestration callbacks, ``RuntimeProjection``, Status Board,
    Manifest stage, execution observability layer (PR-7).
    """


# ---------------------------------------------------------------------------
# Role metadata registry
# ---------------------------------------------------------------------------

#: Human-readable descriptions and canonical class paths for each role.
#: Intended for tooling, documentation generators, and the
#: :func:`~core.envelope_consolidation.envelope_summary.envelope_role_catalog`
#: helper.
ROLE_DESCRIPTIONS: Dict[EnvelopeRole, Dict[str, Any]] = {
    EnvelopeRole.INTERACTION: {
        "label": "Interaction Envelope",
        "canonical_class": "core.schemas.interaction_envelope.InteractionEnvelope",
        "module": "core.schemas.interaction_envelope",
        "class_name": "InteractionEnvelope",
        "layer": "interaction/rendering/persona",
        "trace_field": "trace_id",
        "key_fields": ["interaction_id", "trace_id", "session_id", "mode",
                       "relationship_mode", "output_plan"],
        "summary": (
            "Governs interaction mode selection, persona state snapshot, "
            "multimodal context, and per-channel rendering flags (OutputPlan). "
            "Built once per user request; consumed by UI/voice/avatar layers."
        ),
    },
    EnvelopeRole.TASK: {
        "label": "Task Envelope",
        "canonical_class": "core.schemas.task_envelope.TaskEnvelope",
        "module": "core.schemas.task_envelope",
        "class_name": "TaskEnvelope",
        "layer": "orchestration/routing/scheduling",
        "trace_field": "trace_id",
        "key_fields": ["task_id", "trace_id", "session_id", "source", "targets",
                       "tool_name", "priority", "lifecycle_status",
                       "required_capabilities"],
        "summary": (
            "Canonical internal task representation.  Used across all routing "
            "paths (gateway, relay, MCP, skill).  Carries lifecycle state "
            "machine (created→running→done|failed) and capability requirements."
        ),
    },
    EnvelopeRole.COMMAND: {
        "label": "Command Envelope",
        "canonical_class": "core.unified.command_envelope.CommandEnvelope",
        "module": "core.unified.command_envelope",
        "class_name": "CommandEnvelope",
        "layer": "executor/dispatch",
        "trace_field": "trace_id",
        "key_fields": ["task_id", "trace_id", "runtime_session_id", "device_id",
                       "verb", "idempotency_key", "payload"],
        "summary": (
            "Executor-facing command contract.  Adds idempotency key and "
            "command verb (EXECUTE/CANCEL/INTERRUPT/QUERY) to the task context. "
            "Constructed from TaskEnvelope via CommandEnvelope.from_task_envelope()."
        ),
    },
    EnvelopeRole.RESULT: {
        "label": "Result Envelope",
        "canonical_class": "core.unified.command_envelope.ResultEnvelope",
        "module": "core.unified.command_envelope",
        "class_name": "ResultEnvelope",
        "layer": "result/observability",
        "trace_field": "trace_id",
        "key_fields": ["task_id", "trace_id", "success", "elapsed_ms",
                       "error_code", "result"],
        "summary": (
            "Executor return contract.  Correlated back to CommandEnvelope via "
            "task_id+trace_id.  Carries success flag, output data, elapsed time, "
            "and structured error code."
        ),
    },
}


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def role_for_class(class_name: str) -> EnvelopeRole:
    """Return the :class:`EnvelopeRole` for a given canonical class name.

    Accepts both short names (``"InteractionEnvelope"``) and fully qualified
    module paths (``"core.schemas.interaction_envelope.InteractionEnvelope"``).
    Raises :class:`KeyError` if no matching role is found.

    >>> role_for_class("TaskEnvelope")
    <EnvelopeRole.TASK: 'task'>
    >>> role_for_class("core.unified.command_envelope.CommandEnvelope")
    <EnvelopeRole.COMMAND: 'command'>
    """
    for role, meta in ROLE_DESCRIPTIONS.items():
        if class_name in (meta["class_name"], meta["canonical_class"]):
            return role
    raise KeyError(f"No envelope role registered for class: {class_name!r}")


def layer_for_role(role: EnvelopeRole) -> str:
    """Return the layer string for a role.

    >>> layer_for_role(EnvelopeRole.INTERACTION)
    'interaction/rendering/persona'
    """
    return ROLE_DESCRIPTIONS[role]["layer"]


__all__ = [
    "EnvelopeRole",
    "ROLE_DESCRIPTIONS",
    "role_for_class",
    "layer_for_role",
]
