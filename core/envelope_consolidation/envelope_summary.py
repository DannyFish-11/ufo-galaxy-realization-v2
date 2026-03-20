#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.envelope_consolidation.envelope_summary
============================================

PR-8 (V3) — Execution Envelope Consolidation

Provides **stable, serialisable summary helpers** that downstream layers
(RuntimeProjection, Status Board v2, Manifest stage, observability endpoints)
can consume without depending on the full internal envelope types.

Public API
----------

:class:`EnvelopeSummary`
    A compact, serialisable representation of any Galaxy envelope.  Contains
    the role, the shared correlation fields, a human-readable label, and any
    role-specific metadata extracted from the source envelope.

:func:`summarise_envelope`
    Build an :class:`EnvelopeSummary` from *any* Galaxy envelope object or
    plain dict, inferring the role automatically.

:func:`envelope_role_catalog`
    Return the full role catalog as a list of dicts, suitable for a read-only
    API response or documentation generator.

:func:`summarise_result_for_projection`
    Convenience wrapper that extracts a projection-friendly summary from a
    :class:`~core.unified.command_envelope.ResultEnvelope`.

Design
------
All functions are pure (no I/O, no side effects).  The
:class:`EnvelopeSummary` dataclass has a ``to_dict()`` method for JSON
serialisation and a ``from_dict()`` classmethod for reconstruction.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .envelope_roles import EnvelopeRole, ROLE_DESCRIPTIONS
from .envelope_adapters import (
    extract_trace_fields,
    task_to_command_summary,
    result_to_observation,
    interaction_trace_fields,
    _get,
)


# ---------------------------------------------------------------------------
# EnvelopeSummary
# ---------------------------------------------------------------------------


@dataclass
class EnvelopeSummary:
    """Compact, stable summary of any Galaxy envelope.

    Attributes
    ----------
    role:
        The :class:`~core.envelope_consolidation.envelope_roles.EnvelopeRole`
        of the source envelope.
    trace_id:
        Top-level distributed trace identifier.  Always non-empty.
    task_id:
        Optional task identifier.
    runtime_session_id:
        Optional session identifier (unified across CommandEnvelope and
        TaskEnvelope).
    label:
        Human-readable envelope label (e.g. ``"Task Envelope"``).
    metadata:
        Role-specific metadata extracted from the source envelope.
    captured_at:
        Unix epoch timestamp when this summary was created.
    """

    role: EnvelopeRole
    trace_id: str
    task_id: Optional[str]
    runtime_session_id: Optional[str]
    label: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    captured_at: float = field(default_factory=time.time)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        result: Dict[str, Any] = {
            "role": self.role.value,
            "label": self.label,
            "trace_id": self.trace_id,
            "captured_at": self.captured_at,
        }
        if self.task_id is not None:
            result["task_id"] = self.task_id
        if self.runtime_session_id is not None:
            result["runtime_session_id"] = self.runtime_session_id
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EnvelopeSummary":
        """Reconstruct an :class:`EnvelopeSummary` from a plain dict.

        Tolerates missing or ``None`` fields.
        """
        role_str = data.get("role") or "task"
        try:
            role = EnvelopeRole(role_str)
        except ValueError:
            role = EnvelopeRole.TASK
        return cls(
            role=role,
            trace_id=data.get("trace_id") or f"trace_{uuid.uuid4().hex[:12]}",
            task_id=data.get("task_id") or None,
            runtime_session_id=data.get("runtime_session_id") or None,
            label=data.get("label") or ROLE_DESCRIPTIONS[role]["label"],
            metadata=dict(data.get("metadata") or {}),
            captured_at=float(data.get("captured_at") or time.time()),
        )

    # ------------------------------------------------------------------
    # Projection helper
    # ------------------------------------------------------------------

    def projection_summary(self) -> Dict[str, Any]:
        """Return a compact summary suitable for Status Board / Manifest.

        Only includes non-empty / non-default fields.
        """
        summary: Dict[str, Any] = {
            "role": self.role.value,
            "trace_id": self.trace_id,
        }
        if self.task_id:
            summary["task_id"] = self.task_id
        if self.runtime_session_id:
            summary["runtime_session_id"] = self.runtime_session_id
        if self.metadata:
            for k, v in self.metadata.items():
                if v is not None:
                    summary[k] = v
        return summary


# ---------------------------------------------------------------------------
# Role-inference helpers
# ---------------------------------------------------------------------------

_SENTINEL = object()


def _infer_role(envelope: Any) -> EnvelopeRole:
    """Infer the envelope role by inspecting discriminating attributes.

    Heuristic (in priority order):

    1. ``interaction_id`` present → INTERACTION
    2. ``lifecycle_status`` present **and** ``targets`` present → TASK
    3. ``verb`` or ``idempotency_key`` present → COMMAND
    4. ``success`` present **and** ``elapsed_ms`` present → RESULT
    5. Fallback → TASK
    """
    if _get(envelope, "interaction_id") is not None:
        return EnvelopeRole.INTERACTION
    if _get(envelope, "lifecycle_status") is not None and _get(envelope, "targets") is not None:
        return EnvelopeRole.TASK
    if _get(envelope, "verb") is not None or _get(envelope, "idempotency_key") is not None:
        return EnvelopeRole.COMMAND
    # success is a bool — check for explicit presence
    success = _get(envelope, "success", _SENTINEL)
    elapsed_ms = _get(envelope, "elapsed_ms", _SENTINEL)
    if success is not _SENTINEL and elapsed_ms is not _SENTINEL:
        return EnvelopeRole.RESULT
    return EnvelopeRole.TASK


# ---------------------------------------------------------------------------
# summarise_envelope
# ---------------------------------------------------------------------------


def summarise_envelope(envelope: Any, role: Optional[EnvelopeRole] = None) -> EnvelopeSummary:
    """Build an :class:`EnvelopeSummary` from *any* Galaxy envelope.

    Args:
        envelope: Any envelope object or plain dict.  The role is inferred
                  automatically unless *role* is supplied.
        role:     Optional explicit :class:`EnvelopeRole` override.

    Returns:
        An :class:`EnvelopeSummary` with shared correlation fields and
        role-specific metadata extracted from *envelope*.
    """
    if role is None:
        role = _infer_role(envelope)

    trace_fields = extract_trace_fields(envelope)
    trace_id = trace_fields["trace_id"]
    task_id = trace_fields["task_id"]
    session_id = trace_fields["session_id"] or trace_fields["runtime_session_id"]
    label = ROLE_DESCRIPTIONS[role]["label"]

    # Build role-specific metadata
    metadata: Dict[str, Any] = {}

    if role == EnvelopeRole.INTERACTION:
        ix_fields = interaction_trace_fields(envelope)
        metadata["interaction_id"] = ix_fields.get("interaction_id")
        metadata["mode"] = _get(envelope, "mode") or None
        metadata["relationship_mode"] = _get(envelope, "relationship_mode") or None
        ui_surface = None
        output_plan = _get(envelope, "output_plan")
        if output_plan is not None:
            if isinstance(output_plan, dict):
                ui_surface = output_plan.get("ui_surface")
            else:
                ui_surface = getattr(output_plan, "ui_surface", None)
        metadata["ui_surface"] = ui_surface

    elif role == EnvelopeRole.TASK:
        cmd_summary = task_to_command_summary(envelope)
        metadata["tool_name"] = cmd_summary.get("tool_name")
        metadata["priority"] = cmd_summary.get("priority")
        metadata["lifecycle_status"] = cmd_summary.get("lifecycle_status")
        metadata["device_id"] = cmd_summary.get("device_id") or None
        metadata["source"] = cmd_summary.get("source") or None

    elif role == EnvelopeRole.COMMAND:
        verb = _get(envelope, "verb")
        if hasattr(verb, "value"):
            verb = verb.value
        metadata["verb"] = verb or "execute"
        metadata["device_id"] = _get(envelope, "device_id") or None
        metadata["idempotency_key"] = _get(envelope, "idempotency_key") or None

    elif role == EnvelopeRole.RESULT:
        obs = result_to_observation(envelope)
        obs_meta = obs.get("metadata") or {}
        metadata["success"] = obs_meta.get("success")
        metadata["elapsed_ms"] = obs_meta.get("elapsed_ms")
        metadata["error_code"] = obs_meta.get("error_code")
        metadata["device_id"] = obs_meta.get("device_id") or None

    return EnvelopeSummary(
        role=role,
        trace_id=trace_id,
        task_id=task_id,
        runtime_session_id=session_id,
        label=label,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# envelope_role_catalog
# ---------------------------------------------------------------------------


def envelope_role_catalog() -> List[Dict[str, Any]]:
    """Return the full role catalog as a list of serialisable dicts.

    Each dict contains:
    * ``role``            — role value string
    * ``label``           — human-readable label
    * ``canonical_class`` — fully-qualified Python class path
    * ``layer``           — architectural layer
    * ``key_fields``      — list of important field names
    * ``summary``         — one-paragraph description
    * ``trace_field``     — name of the trace propagation field
    """
    return [
        {
            "role": role.value,
            "label": meta["label"],
            "canonical_class": meta["canonical_class"],
            "layer": meta["layer"],
            "key_fields": meta["key_fields"],
            "summary": meta["summary"],
            "trace_field": meta["trace_field"],
        }
        for role, meta in ROLE_DESCRIPTIONS.items()
    ]


# ---------------------------------------------------------------------------
# summarise_result_for_projection
# ---------------------------------------------------------------------------


def summarise_result_for_projection(result_envelope: Any) -> Dict[str, Any]:
    """Convenience wrapper: extract a projection-friendly summary from a result.

    Combines :func:`summarise_envelope` with
    :meth:`EnvelopeSummary.projection_summary` for a single-call path that
    Status Board v2 and Manifest stage consumers can use.

    Returns a flat dict suitable for JSON serialisation.
    """
    summary = summarise_envelope(result_envelope, role=EnvelopeRole.RESULT)
    return summary.projection_summary()


__all__ = [
    "EnvelopeSummary",
    "summarise_envelope",
    "envelope_role_catalog",
    "summarise_result_for_projection",
]
