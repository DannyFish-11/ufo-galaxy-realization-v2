#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.envelope_consolidation.envelope_adapters
=============================================

PR-8 (V3) — Execution Envelope Consolidation

Provides **additive adapters and trace-propagation helpers** that bridge the
four canonical Galaxy envelope types without modifying any of them:

* :func:`extract_trace_fields`
    Extract the shared correlation fields (``trace_id``, ``task_id``,
    ``runtime_session_id``, ``session_id``) from *any* envelope object or
    plain dict.

* :func:`propagate_trace`
    Copy trace fields from one envelope to a target dict / builder kwargs dict
    so that downstream envelopes stay correlated.

* :func:`task_to_command_summary`
    Derive a command-oriented execution summary dict from a
    :class:`~core.schemas.task_envelope.TaskEnvelope` **without** mutating
    the original object and without constructing a full
    :class:`~core.unified.command_envelope.CommandEnvelope`.

* :func:`result_to_observation`
    Convert a :class:`~core.unified.command_envelope.ResultEnvelope` into a
    compact dict compatible with
    :class:`~core.execution_observability.event_schema.ExecutionEvent`.

* :func:`interaction_trace_fields`
    Extract the trace subset from an
    :class:`~core.schemas.interaction_envelope.InteractionEnvelope` so it
    can be correlated with orchestration events.

Design
------
All functions accept objects *or* plain dicts (duck-typing with
``getattr`` / ``dict.get``).  No new top-level envelope type is introduced.
All adapters are pure functions — no I/O, no side effects.

Relationship to PR-7 (execution_observability)
----------------------------------------------
:func:`result_to_observation` produces a dict that can be passed directly to
:meth:`~core.execution_observability.event_schema.ExecutionEvent.from_dict`
(the PR-7 unified event schema).
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Attribute-or-dict accessor with a default."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_trace_fields(envelope: Any) -> Dict[str, Optional[str]]:
    """Extract shared correlation fields from *any* Galaxy envelope.

    Works with:

    * :class:`~core.schemas.interaction_envelope.InteractionEnvelope`
      (dataclass)
    * :class:`~core.schemas.task_envelope.TaskEnvelope` (Pydantic model)
    * :class:`~core.unified.command_envelope.CommandEnvelope` (dataclass)
    * :class:`~core.unified.command_envelope.ResultEnvelope` (dataclass)
    * Plain ``dict`` representations of any of the above.

    Returns a normalised dict with the following keys.  Missing fields are
    returned as ``None``; ``trace_id`` is *never* ``None`` (a new UUID is
    generated if the envelope has no trace).

    +------------------------+----------------------------------------------------+
    | Key                    | Source                                             |
    +========================+====================================================+
    | ``trace_id``           | ``envelope.trace_id``                              |
    +------------------------+----------------------------------------------------+
    | ``task_id``            | ``envelope.task_id``                               |
    +------------------------+----------------------------------------------------+
    | ``runtime_session_id`` | ``envelope.runtime_session_id``                    |
    +------------------------+----------------------------------------------------+
    | ``session_id``         | ``envelope.session_id``                            |
    +------------------------+----------------------------------------------------+
    | ``interaction_id``     | ``envelope.interaction_id`` (InteractionEnvelope)  |
    +------------------------+----------------------------------------------------+
    """
    import uuid

    trace_id = _get(envelope, "trace_id") or None
    if not trace_id:
        trace_id = f"trace_{uuid.uuid4().hex[:12]}"

    return {
        "trace_id": trace_id,
        "task_id": _get(envelope, "task_id") or None,
        "runtime_session_id": _get(envelope, "runtime_session_id") or None,
        "session_id": _get(envelope, "session_id") or None,
        "interaction_id": _get(envelope, "interaction_id") or None,
    }


def propagate_trace(source: Any, target: Dict[str, Any]) -> Dict[str, Any]:
    """Copy trace fields from *source* envelope into *target* dict (in-place).

    Useful when constructing a downstream envelope from an upstream one.
    Only fields that are present and non-empty in *source* are written;
    existing values in *target* are **not** overwritten.

    Args:
        source: Any envelope object or plain dict with trace fields.
        target: Mutable dict that will receive the extracted fields.

    Returns:
        The same *target* dict (mutated in-place) for convenience.

    Example::

        kwargs: Dict[str, Any] = {"device_id": "win_pc_01", "payload": {...}}
        propagate_trace(task_envelope, kwargs)
        cmd = CommandEnvelope(**kwargs)
    """
    fields = extract_trace_fields(source)
    for key, value in fields.items():
        if value is not None and key not in target:
            target[key] = value
    return target


def task_to_command_summary(task_envelope: Any) -> Dict[str, Any]:
    """Derive a command-oriented execution summary from a *task_envelope*.

    This is a **lightweight adapter** — it extracts the fields that are
    relevant for executor dispatch and returns them as a plain dict.  It does
    **not** construct a :class:`~core.unified.command_envelope.CommandEnvelope`
    (use ``CommandEnvelope.from_task_envelope()`` when a full envelope is
    needed).

    Returned dict keys:

    +---------------------------+-----------------------------------------------+
    | Key                       | Description                                   |
    +===========================+===============================================+
    | ``trace_id``              | Propagated trace identifier.                  |
    +---------------------------+-----------------------------------------------+
    | ``task_id``               | Task identifier.                              |
    +---------------------------+-----------------------------------------------+
    | ``runtime_session_id``    | Session scope (from ``session_id`` on task).  |
    +---------------------------+-----------------------------------------------+
    | ``device_id``             | First target device, or ``""`` if none.       |
    +---------------------------+-----------------------------------------------+
    | ``tool_name``             | Tool / command name.                          |
    +---------------------------+-----------------------------------------------+
    | ``args``                  | Tool arguments dict.                          |
    +---------------------------+-----------------------------------------------+
    | ``priority``              | Execution priority.                           |
    +---------------------------+-----------------------------------------------+
    | ``timeout``               | Timeout in seconds.                           |
    +---------------------------+-----------------------------------------------+
    | ``lifecycle_status``      | Current lifecycle state (if available).       |
    +---------------------------+-----------------------------------------------+
    | ``source``                | Originating component.                        |
    +---------------------------+-----------------------------------------------+
    | ``envelope_role``         | Always ``"task"`` (informational).            |
    +---------------------------+-----------------------------------------------+
    """
    te = task_envelope

    # Resolve device_id: first element of targets list, or direct attribute.
    targets = _get(te, "targets") or []
    if isinstance(targets, list) and targets:
        device_id = str(targets[0])
    else:
        device_id = str(_get(te, "device_id") or "")

    trace_fields = extract_trace_fields(te)

    return {
        "trace_id": trace_fields["trace_id"],
        "task_id": trace_fields["task_id"] or "",
        "runtime_session_id": trace_fields["session_id"] or trace_fields["runtime_session_id"] or "",
        "device_id": device_id,
        "tool_name": str(_get(te, "tool_name") or ""),
        "args": dict(_get(te, "args") or {}),
        "priority": int(_get(te, "priority") or 5),
        "timeout": float(_get(te, "timeout") or 30.0),
        "lifecycle_status": str(_get(te, "lifecycle_status") or "created"),
        "source": str(_get(te, "source") or ""),
        "envelope_role": "task",
    }


def result_to_observation(result_envelope: Any) -> Dict[str, Any]:
    """Convert a *result_envelope* to an observation dict for PR-7 consumers.

    The returned dict is compatible with
    :meth:`~core.execution_observability.event_schema.ExecutionEvent.from_dict`
    so it can be passed directly to the PR-7 unified event schema.

    Returned dict keys include all
    :class:`~core.execution_observability.event_schema.ExecutionEvent` fields
    that can be derived from a ``ResultEnvelope``:

    * ``trace`` — trace sub-dict with ``trace_id``, ``task_id``,
      ``runtime_session_id``
    * ``executor_level`` — always ``"unknown"`` (result envelopes do not carry
      executor-level metadata; set explicitly if known)
    * ``message`` — error string if failed, else ``"success"``
    * ``metadata`` — elapsed_ms, success, device_id, error_code
    """
    re = result_envelope
    trace_fields = extract_trace_fields(re)

    success: bool = bool(_get(re, "success", True))
    error: Optional[str] = _get(re, "error") or None
    error_code: Optional[str] = _get(re, "error_code") or None
    elapsed_ms: float = float(_get(re, "elapsed_ms") or 0.0)
    device_id: str = str(_get(re, "device_id") or "")

    return {
        "trace": {
            "trace_id": trace_fields["trace_id"],
            "task_id": trace_fields["task_id"],
            "runtime_session_id": trace_fields["runtime_session_id"] or "",
        },
        "executor_level": "unknown",
        "message": error if (not success and error) else "success",
        "metadata": {
            "elapsed_ms": elapsed_ms,
            "success": success,
            "device_id": device_id,
            "error_code": error_code,
        },
    }


def interaction_trace_fields(interaction_envelope: Any) -> Dict[str, Optional[str]]:
    """Extract the trace subset from an *interaction_envelope*.

    Returns a dict with ``trace_id``, ``session_id``, and ``interaction_id``
    so that orchestration events can be correlated with the interaction context
    that triggered them.

    Example::

        ix_fields = interaction_trace_fields(ix_envelope)
        task = TaskEnvelope(
            trace_id=ix_fields["trace_id"],
            session_id=ix_fields["session_id"],
            ...
        )
    """
    ie = interaction_envelope
    import uuid

    trace_id = _get(ie, "trace_id") or None
    if not trace_id:
        trace_id = f"trace_{uuid.uuid4().hex[:12]}"

    session_id = _get(ie, "session_id") or None
    interaction_id = _get(ie, "interaction_id") or None

    return {
        "trace_id": trace_id,
        "session_id": session_id,
        "interaction_id": interaction_id,
    }


__all__ = [
    "extract_trace_fields",
    "propagate_trace",
    "task_to_command_summary",
    "result_to_observation",
    "interaction_trace_fields",
]
